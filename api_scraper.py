"""
api_scraper.py — Extracción de SECOP II vía la API de Datos Abiertos.

Consulta la API Socrata de datos.gov.co, que expone los contratos de
SECOP II sin CAPTCHA ni WAF. Es la fuente recomendada para datos de
contratos ya celebrados: más completa y más rápida que raspar SECOP I.

Datasets:
  • Contratos SECOP II: ``jbjy-vk9h``
  • Procesos  SECOP II: ``p6dx-8zbt``

Equivalencias SECOP I → SECOP II (los nombres difieren entre portales):
  • Estado "Celebrado" → ``estado_contrato`` IN (Cerrado, terminado,
    En ejecución, Modificado, Prorrogado, cedido)
  • "Contratación Mínima Cuantía" → "Mínima cuantía"
  • Departamento código ``668000`` → ``departamento = 'Santander'``

Detalles de implementación relevantes:
  • **Paginación estable**: Socrata no garantiza un orden consistente
    entre peticiones si la clave de orden tiene empates, lo que provoca
    filas duplicadas y filas perdidas al paginar por ``$offset``. Se
    ordena por ``:id`` (identificador interno único) para evitarlo.
  • **Sin tope artificial**: por defecto se descargan *todos* los
    registros que coincidan con el filtro.
  • Se admite un ``SOCRATA_APP_TOKEN`` para evitar el throttling.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Optional

import pandas as pd

from catalogos import (
    DEPARTAMENTOS,
    ESTADOS,
    MODALIDADES,
    TIPOS_CONTRATO,
    buscar_opcion,
)
from config import (
    CSV_ENCODING,
    CSV_SEPARATOR,
    ESTADO_SECOP1,
    MAX_RETRIES,
    OUTPUT_DIR,
    RETRY_BACKOFF,
    SOCRATA_APP_TOKEN,
    SOCRATA_BASE_URL,
    SOCRATA_DATASET_CONTRATOS,
    SOCRATA_DATASET_PROCESOS,
    SOCRATA_PAGE_SIZE,
    SOCRATA_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Alias mantenidos por compatibilidad con importaciones existentes.
BASE_URL = SOCRATA_BASE_URL
DATASET_CONTRATOS = SOCRATA_DATASET_CONTRATOS
DATASET_PROCESOS = SOCRATA_DATASET_PROCESOS
API_PAGE_SIZE = SOCRATA_PAGE_SIZE


# ────────────────────────────────────────────────────────────
# MAPEOS SECOP I → SECOP II
# ────────────────────────────────────────────────────────────
#
# Las equivalencias de departamento, modalidad y tipo de contrato viven
# en ``catalogos.py``, que es la única fuente de verdad. Aquí solo queda
# la expansión de estados, que no es una correspondencia uno a uno.

# "Celebrado" en SECOP I equivale a contratos ya formalizados en SECOP II.
ESTADO_CELEBRADO_EQUIVALENTES = [
    "Cerrado",
    "terminado",
    "En ejecución",
    "Modificado",
    "Prorrogado",
    "cedido",
]

# Columnas a solicitar a la API.
COLUMNAS_API = [
    "nombre_entidad",
    "nit_entidad",
    "departamento",
    "ciudad",
    "modalidad_de_contratacion",
    "estado_contrato",
    "tipo_de_contrato",
    "objeto_del_contrato",
    "valor_del_contrato",
    "valor_pagado",
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
    "fecha_de_firma",
    "documento_proveedor",
    "proveedor_adjudicado",
    "proceso_de_compra",
    "id_contrato",
    "urlproceso",
]


# ────────────────────────────────────────────────────────────
# CONSTRUCCIÓN DEL FILTRO SoQL
# ────────────────────────────────────────────────────────────


def _escapar(valor: str) -> str:
    """Escapa comillas simples para incrustar un literal en SoQL."""
    return str(valor).replace("'", "''")


def _fecha_iso(fecha: str, fin_del_dia: bool = False) -> Optional[str]:
    """Convierte ``dd/MM/yyyy`` (o ``dd-MM-yyyy``) a ISO 8601.

    Returns:
        Cadena ``yyyy-MM-ddTHH:mm:ss`` o ``None`` si el formato no encaja.
    """
    if not fecha:
        return None
    partes = str(fecha).replace("-", "/").split("/")
    if len(partes) != 3:
        logger.warning("Formato de fecha no reconocido: %r (se ignora).", fecha)
        return None
    dia, mes, anio = (p.strip() for p in partes)
    if len(anio) != 4:
        logger.warning("Formato de fecha no reconocido: %r (se ignora).", fecha)
        return None
    hora = "23:59:59" if fin_del_dia else "00:00:00"
    return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}T{hora}"



def _traducir(catalogo, valor: str, concepto: str) -> Optional[str]:
    """Resuelve un filtro al valor exacto que usa la API de SECOP II.

    Acepta el código de SECOP I, el nombre de cualquiera de los dos
    portales o la etiqueta del catálogo, tolerando tildes y mayúsculas.

    Returns:
        El valor para la API, o ``None`` si el concepto no existe en
        SECOP II (en cuyo caso el filtro debe omitirse en vez de enviar
        un literal que no casaría con nada).
    """
    opcion = buscar_opcion(catalogo, valor)

    if opcion is None:
        logger.warning(
            "No se reconoce %s=%r; se envía tal cual y puede no devolver "
            "registros.", concepto, valor,
        )
        return str(valor).strip()

    if not opcion.existe_en_api:
        logger.warning(
            "%s %r solo existe en SECOP I; se omite ese filtro en la "
            "consulta a la API.", concepto.capitalize(), opcion.etiqueta,
        )
        return None

    return opcion.api_valores[0]


def _traducir_modalidad(modalidad: str) -> Optional[str]:
    """Traduce una modalidad al texto exacto que usa SECOP II."""
    return _traducir(MODALIDADES, modalidad, "modalidad")


def _traducir_departamento(departamento: str) -> Optional[str]:
    """Traduce un departamento al texto exacto que usa SECOP II.

    Cuidado: los nombres **no coinciden** entre portales. El caso más
    llamativo es Bogotá, que en SECOP I es "Bogotá D.C." (código 1100) y
    en la API "Distrito Capital de Bogotá"; usar el primero devolvía cero
    registros del departamento con más contratación del país.
    """
    return _traducir(DEPARTAMENTOS, departamento, "departamento")


def _traducir_tipo_contrato(tipo: str) -> Optional[str]:
    """Traduce un tipo de contrato al valor exacto de SECOP II."""
    return _traducir(TIPOS_CONTRATO, tipo, "tipo de contrato")


def _traducir_estado(estado: str) -> list[str]:
    """Traduce un estado a los valores equivalentes de ``estado_contrato``.

    Acepta el ID de SECOP I (``'4'``), la etiqueta del catálogo o el
    valor de la API. "Celebrado" no tiene un equivalente único: en
    SECOP II se corresponde con todo el grupo de contratos ya
    formalizados, así que se expande a varios valores.

    Returns:
        Lista de valores a incluir; vacía si el estado solo existe en
        SECOP I (entonces el filtro se omite en la API).
    """
    opcion = buscar_opcion(ESTADOS, estado)

    if opcion is None:
        texto = ESTADO_SECOP1.get(str(estado), str(estado))
        if texto.lower() == "celebrado":
            return list(ESTADO_CELEBRADO_EQUIVALENTES)
        return [texto]

    if not opcion.existe_en_api:
        logger.warning(
            "El estado %r solo existe en SECOP I; se omite ese filtro en "
            "la consulta a la API.", opcion.etiqueta,
        )
        return []

    return list(opcion.api_valores)


def _construir_where(
    departamento: Optional[str] = None,
    modalidad: Optional[str | Iterable[str]] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str | Iterable[str]] = None,
    campo_fecha: str = "fecha_de_inicio_del_contrato",
) -> str:
    """Construye la cláusula ``$where`` para la API Socrata.

    Args:
        departamento:  Código SECOP I (``'668000'``) o nombre.
        modalidad:     Código, nombre, o lista de cualquiera de los dos.
        estado:        ID o texto; ``'Celebrado'`` se expande.
        palabra_clave: Texto a buscar en ``objeto_del_contrato``.
        fecha_inicio:  Fecha desde (``dd/MM/yyyy``).
        fecha_fin:     Fecha hasta (``dd/MM/yyyy``).
        campo_fecha:   Columna de fecha sobre la que aplicar el rango.

    Returns:
        Cadena SoQL lista para ``$where`` (vacía si no hay filtros).
    """
    condiciones: list[str] = []

    def _condicion(campo: str, valor, traductor) -> None:
        """Añade una condición ``campo = valor`` o ``campo in (...)``.

        Los valores sin equivalente en SECOP II se descartan: filtrar por
        un literal inexistente devolvería cero registros en silencio.
        """
        if not valor:
            return

        if isinstance(valor, (list, tuple, set)):
            traducidos = [t for t in (traductor(v) for v in valor) if t]
            if not traducidos:
                return
            if len(traducidos) == 1:
                condiciones.append(f"{campo}='{_escapar(traducidos[0])}'")
            else:
                unidos = ",".join(f"'{_escapar(t)}'" for t in traducidos)
                condiciones.append(f"{campo} in({unidos})")
            return

        traducido = traductor(valor)
        if traducido:
            condiciones.append(f"{campo}='{_escapar(traducido)}'")

    _condicion("departamento", departamento, _traducir_departamento)
    _condicion("modalidad_de_contratacion", modalidad, _traducir_modalidad)
    _condicion("tipo_de_contrato", tipo_contrato, _traducir_tipo_contrato)

    if estado:
        equivalentes = _traducir_estado(estado)
        if len(equivalentes) == 1:
            condiciones.append(f"estado_contrato='{_escapar(equivalentes[0])}'")
        elif equivalentes:
            unidos = ",".join(f"'{_escapar(e)}'" for e in equivalentes)
            condiciones.append(f"estado_contrato in({unidos})")

    if palabra_clave:
        # AND lógico: todas las palabras deben aparecer en el objeto.
        for palabra in str(palabra_clave).split():
            escapada = _escapar(palabra)
            condiciones.append(
                f"upper(objeto_del_contrato) like upper('%{escapada}%')"
            )

    iso_inicio = _fecha_iso(fecha_inicio) if fecha_inicio else None
    if iso_inicio:
        condiciones.append(f"{campo_fecha} >= '{iso_inicio}'")

    iso_fin = _fecha_iso(fecha_fin, fin_del_dia=True) if fecha_fin else None
    if iso_fin:
        condiciones.append(f"{campo_fecha} <= '{iso_fin}'")

    return " AND ".join(condiciones)


# ────────────────────────────────────────────────────────────
# TRANSPORTE HTTP
# ────────────────────────────────────────────────────────────


def _fetch(
    dataset: str,
    params: dict[str, str],
    timeout: int = SOCRATA_TIMEOUT,
) -> list[dict[str, Any]]:
    """Ejecuta una consulta a Socrata con reintentos y backoff.

    Args:
        dataset: Identificador del dataset (``jbjy-vk9h``).
        params:  Parámetros ``$select`` / ``$where`` / ``$limit`` / ...
        timeout: Segundos de espera por intento.

    Returns:
        Lista de registros.

    Raises:
        RuntimeError: Si se agotan los reintentos.
    """
    url = f"{SOCRATA_BASE_URL}/{dataset}.json?{urllib.parse.urlencode(params)}"
    logger.debug("API request: %s", url)

    ultimo_error: Optional[Exception] = None

    for intento in range(1, MAX_RETRIES + 1):
        peticion = urllib.request.Request(url)
        peticion.add_header("Accept", "application/json")
        if SOCRATA_APP_TOKEN:
            peticion.add_header("X-App-Token", SOCRATA_APP_TOKEN)

        try:
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            ultimo_error = exc
            espera = RETRY_BACKOFF**intento
            logger.warning(
                "Error consultando la API (intento %d/%d): %s. "
                "Reintentando en %.1f s.",
                intento, MAX_RETRIES, exc, espera,
            )
            if intento < MAX_RETRIES:
                time.sleep(espera)

    raise RuntimeError(
        f"La API de datos.gov.co no respondió tras {MAX_RETRIES} intentos: "
        f"{ultimo_error}"
    )


def _fetch_page(
    dataset: str,
    where: str,
    select: str,
    limit: int = SOCRATA_PAGE_SIZE,
    offset: int = 0,
    order: str = ":id",
) -> list[dict[str, Any]]:
    """Descarga una página de resultados.

    ``order`` usa ``:id`` por defecto: es el único campo con unicidad
    garantizada, lo que hace que la paginación por ``$offset`` sea
    consistente entre peticiones.
    """
    params: dict[str, str] = {"$limit": str(limit), "$offset": str(offset)}
    if where:
        params["$where"] = where
    if select:
        params["$select"] = select
    if order:
        params["$order"] = order
    return _fetch(dataset, params)


# ────────────────────────────────────────────────────────────
# CONSULTAS
# ────────────────────────────────────────────────────────────


def contar_registros(
    departamento: Optional[str] = None,
    modalidad: Optional[str | Iterable[str]] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str | Iterable[str]] = None,
    dataset: str = SOCRATA_DATASET_CONTRATOS,
) -> int:
    """Cuenta los registros que coinciden con los filtros.

    Acepta **los mismos filtros** que ``consultar_contratos``, incluidas
    las fechas. (La versión anterior las omitía, así que el total no
    correspondía con la consulta real y truncaba la descarga.)

    Returns:
        Número total de registros coincidentes.
    """
    where = _construir_where(
        departamento, modalidad, estado, palabra_clave,
        fecha_inicio, fecha_fin, tipo_contrato,
    )
    datos = _fetch_page(
        dataset,
        where=where,
        select="count(*) as total",
        limit=1,
        order="",
    )
    return int(datos[0]["total"]) if datos else 0


def consultar_contratos(
    departamento: Optional[str] = None,
    modalidad: Optional[str | Iterable[str]] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str | Iterable[str]] = None,
    max_registros: Optional[int] = None,
    dataset: str = SOCRATA_DATASET_CONTRATOS,
) -> pd.DataFrame:
    """Descarga contratos de SECOP II con paginación automática.

    Args:
        departamento:  Código SECOP I (``'668000'``) o nombre.
        modalidad:     Código, nombre, o lista.
        estado:        ID o texto; ``'Celebrado'`` se expande.
        palabra_clave: Filtro por texto en el objeto del contrato.
        fecha_inicio:  Fecha desde (``dd/MM/yyyy``).
        fecha_fin:     Fecha hasta (``dd/MM/yyyy``).
        max_registros: Tope de registros. ``None`` = **todos**.
        dataset:       Dataset a consultar.

    Returns:
        DataFrame con los contratos encontrados.
    """
    where = _construir_where(
        departamento, modalidad, estado, palabra_clave,
        fecha_inicio, fecha_fin, tipo_contrato,
    )
    select = ",".join(COLUMNAS_API)

    total = contar_registros(
        departamento, modalidad, estado, palabra_clave,
        fecha_inicio, fecha_fin, tipo_contrato, dataset,
    )
    logger.info("Total de registros que coinciden: %d", total)

    if total == 0:
        logger.warning("La consulta no retornó registros.")
        return pd.DataFrame(columns=COLUMNAS_API)

    objetivo = total if max_registros is None else min(total, max_registros)
    if objetivo < total:
        logger.info("Se descargarán %d de %d registros (tope solicitado).",
                    objetivo, total)
    else:
        logger.info("Se descargarán los %d registros.", objetivo)

    registros: list[dict[str, Any]] = []
    offset = 0

    while offset < objetivo:
        tamano = min(SOCRATA_PAGE_SIZE, objetivo - offset)
        pagina = _fetch_page(
            dataset, where=where, select=select, limit=tamano, offset=offset
        )

        if not pagina:
            logger.info("La API dejó de devolver registros en offset %d.", offset)
            break

        registros.extend(pagina)
        offset += len(pagina)
        logger.info(
            "  Página obtenida: %d registros (acumulado: %d / %d)",
            len(pagina), len(registros), objetivo,
        )

        if len(pagina) < tamano:
            break  # última página

    df = pd.DataFrame(registros)

    # Garantizar que todas las columnas pedidas existen, aunque la API
    # las omita cuando vienen vacías en todos los registros.
    for columna in COLUMNAS_API:
        if columna not in df.columns:
            df[columna] = pd.NA

    logger.info("Consulta API completada: %d registros obtenidos.", len(df))
    return df[COLUMNAS_API]


def consultar_desde_params(
    params,
    max_registros: Optional[int] = None,
    tipo_contrato: Optional[str] = None,
) -> pd.DataFrame:
    """Consulta usando un ``SearchParams`` de ``config.py``.

    Args:
        params:        Instancia de ``SearchParams``.
        max_registros: Tope opcional. ``None`` = todos los coincidentes.

    Returns:
        DataFrame con los contratos.
    """
    return consultar_contratos(
        departamento=params.departamento,
        modalidad=params.modalidad,
        estado=params.estado,
        palabra_clave=params.palabra_clave,
        fecha_inicio=params.fecha_inicio,
        fecha_fin=params.fecha_fin,
        tipo_contrato=tipo_contrato,
        max_registros=max_registros,
    )


# ────────────────────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from config import SEARCH_SANTANDER_MINIMA_CELEBRADO, setup_logging
    from cleaning import limpiar_dataframe

    setup_logging()

    logger.info("=" * 70)
    logger.info("CONSULTA API — Santander / Mínima Cuantía / Celebrado")
    logger.info("=" * 70)

    df = consultar_desde_params(SEARCH_SANTANDER_MINIMA_CELEBRADO)

    if df.empty:
        logger.warning("No se obtuvieron registros.")
        print("Sin resultados.")
    else:
        df_limpio = limpiar_dataframe(df)

        ruta = OUTPUT_DIR / "secop_santander_minima_celebrado.csv"
        df_limpio.to_csv(
            ruta, index=False, sep=CSV_SEPARATOR, encoding=CSV_ENCODING
        )
        logger.info("Archivo exportado: %s", ruta)

        print("\n" + "=" * 70)
        print("RESULTADOS — Santander / Mínima Cuantía / Celebrado")
        print("=" * 70)
        print(f"Total registros: {len(df_limpio)}")
        print(f"Archivo: {ruta}")
        print("\nVista previa (primeros 10):")
        columnas = [
            c for c in (
                "nombre_entidad", "ciudad", "estado_contrato",
                "tipo_de_contrato", "valor_del_contrato",
            ) if c in df_limpio.columns
        ]
        print(df_limpio[columnas].head(10).to_string(index=False))
