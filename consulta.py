"""
consulta.py — Consultas en vivo contra los dos portales de SECOP.

Este módulo es el que usa el dashboard para traer contratos **en el
momento de la búsqueda**, en lugar de leer un CSV ya descargado. Ejecuta
el pipeline completo (scraping → parsing → limpieza) y devuelve siempre
el mismo esquema, venga de donde venga el dato.

Diferencias entre fuentes que conviene tener presentes:

  • **SECOP II (API de datos.gov.co)** — rápida (segundos), sin WAF, con
    filtros aplicados en el servidor (incluido el texto libre). Publica
    con unos días de rezago respecto al portal.

  • **SECOP I (contratos.gov.co)** — es el portal en vivo, así que trae
    procesos más recientes, pero va paginado de 100 en 100 con pausas
    para no despertar al WAF. Por eso las consultas se acotan con
    ``max_paginas``: pedir un departamento entero son decenas de páginas
    y varios minutos.

Las dos rutas se normalizan al esquema de la API, que es contra el que
está escrito ``app.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

import pandas as pd

from catalogos import DEPARTAMENTOS, ESTADOS, MODALIDADES, buscar_opcion
from config import SearchParams

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# ESQUEMA UNIFICADO
# ────────────────────────────────────────────────────────────

# Columnas que el dashboard espera. Es el esquema de la API de SECOP II.
ESQUEMA_DASHBOARD: list[str] = [
    "nombre_entidad",
    "objeto_del_contrato",
    "valor_del_contrato",
    "valor_pagado",
    "modalidad_de_contratacion",
    "ciudad",
    "departamento",
    "estado_contrato",
    "tipo_de_contrato",
    "proveedor_adjudicado",
    "proceso_de_compra",
    "urlproceso",
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
]

# Traducción del esquema de SECOP I al del dashboard.
EQUIVALENCIAS_SECOP1: dict[str, str] = {
    "entidad": "nombre_entidad",
    "objeto_contrato": "objeto_del_contrato",
    "cuantia": "valor_del_contrato",
    "modalidad": "modalidad_de_contratacion",
    "municipio": "ciudad",
    "estado": "estado_contrato",
    "tipo_contrato": "tipo_de_contrato",
    "numero_proceso": "proceso_de_compra",
    "proveedor": "proveedor_adjudicado",
    "url_detalle": "urlproceso",
    "fecha_apertura": "fecha_de_inicio_del_contrato",
    "fecha_cierre": "fecha_de_fin_del_contrato",
    "valor_contrato": "valor_del_contrato",
}


def normalizar_esquema(df: pd.DataFrame, fuente: str = "") -> pd.DataFrame:
    """Lleva un DataFrame de cualquier ruta al esquema del dashboard.

    Args:
        df:     DataFrame de SECOP I o de la API.
        fuente: Etiqueta a guardar en la columna ``fuente``.

    Returns:
        DataFrame con todas las columnas de ``ESQUEMA_DASHBOARD``.
    """
    df = df.copy()

    renombres = {
        origen: destino
        for origen, destino in EQUIVALENCIAS_SECOP1.items()
        if origen in df.columns and destino not in df.columns
    }
    if renombres:
        df = df.rename(columns=renombres)

    for columna in ESQUEMA_DASHBOARD:
        if columna not in df.columns:
            df[columna] = pd.NA

    if fuente:
        df["fuente"] = fuente

    return df


# ────────────────────────────────────────────────────────────
# CONSULTA A SECOP II (API)
# ────────────────────────────────────────────────────────────


def consultar_secop2(
    departamento: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str] = None,
    max_registros: Optional[int] = 20000,
) -> pd.DataFrame:
    """Consulta contratos en la API de Datos Abiertos (SECOP II).

    Todos los filtros, incluido el de texto libre, viajan al servidor.

    Returns:
        DataFrame normalizado al esquema del dashboard.
    """
    from api_scraper import consultar_contratos
    from cleaning import limpiar_dataframe

    df = consultar_contratos(
        departamento=departamento or None,
        modalidad=modalidad or None,
        estado=estado or None,
        palabra_clave=palabra_clave or None,
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        tipo_contrato=tipo_contrato or None,
        max_registros=max_registros,
    )

    if df.empty:
        return normalizar_esquema(df, "SECOP II")

    return normalizar_esquema(limpiar_dataframe(df), "SECOP II")


def contar_secop2(
    departamento: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str] = None,
) -> int:
    """Cuenta cuántos contratos coinciden, sin descargarlos.

    Sirve para avisar antes de lanzar una descarga enorme: una consulta
    nacional sin filtros son casi 6 millones de registros.
    """
    from api_scraper import contar_registros

    return contar_registros(
        departamento=departamento or None,
        modalidad=modalidad or None,
        estado=estado or None,
        palabra_clave=palabra_clave or None,
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        tipo_contrato=tipo_contrato or None,
    )


# ────────────────────────────────────────────────────────────
# CONSULTA A SECOP I (PORTAL)
# ────────────────────────────────────────────────────────────


def consultar_secop1(
    departamento: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    max_paginas: int = 3,
) -> pd.DataFrame:
    """Raspa la tabla de resultados de contratos.gov.co en vivo.

    Cada página son 100 procesos y lleva una pausa (``SECOP_DELAY``) para
    no disparar el WAF, así que ``max_paginas`` marca el compromiso entre
    exhaustividad y tiempo de respuesta.

    El filtro por ``palabra_clave`` se aplica en local: el formulario de
    SECOP I no admite búsqueda por texto libre.

    Los filtros se resuelven contra el catálogo para enviar el código
    exacto que espera el formulario; los conceptos que solo existen en
    SECOP II se omiten en lugar de enviarse como texto.

    Returns:
        DataFrame normalizado al esquema del dashboard.
    """
    from cleaning import filtrar_por_palabra_clave, limpiar_dataframe
    from parser import parsear_todas_paginas
    from scraper import ejecutar_scraping

    def _codigo(catalogo, valor):
        opcion = buscar_opcion(catalogo, valor)
        if opcion is None:
            return valor or None
        if opcion.codigo_secop1 is None:
            logger.info(
                "%r no existe en SECOP I; se omite ese filtro en el portal.",
                opcion.etiqueta,
            )
            return None
        return opcion.codigo_secop1

    params = SearchParams(
        departamento=_codigo(DEPARTAMENTOS, departamento),
        modalidad=_codigo(MODALIDADES, modalidad),
        estado=_codigo(ESTADOS, estado),
        fecha_inicio=fecha_inicio or None,
        fecha_fin=fecha_fin or None,
        max_pages=max_paginas,
    )

    paginas, _ = ejecutar_scraping(params)
    df = parsear_todas_paginas(paginas)
    df = filtrar_por_palabra_clave(df, palabra_clave)

    if df.empty:
        return normalizar_esquema(df, "SECOP I")

    return normalizar_esquema(limpiar_dataframe(df), "SECOP I")


# ────────────────────────────────────────────────────────────
# CONSULTA COMBINADA
# ────────────────────────────────────────────────────────────


def consultar_en_vivo(
    fuentes: Iterable[str] = ("SECOP II",),
    departamento: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    palabra_clave: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    tipo_contrato: Optional[str] = None,
    max_paginas_secop1: int = 3,
    max_registros_api: Optional[int] = 20000,
) -> tuple[pd.DataFrame, dict]:
    """Ejecuta la consulta contra las fuentes indicadas y combina el resultado.

    Si una fuente falla, se registra en el informe y se continúa con la
    otra: es preferible devolver resultados parciales a no devolver nada.

    Args:
        fuentes:            ``"SECOP I"``, ``"SECOP II"`` o ambas.
        departamento:       Código o nombre.
        modalidad:          Código o nombre.
        estado:             ID o nombre.
        palabra_clave:      Texto libre.
        fecha_inicio:       ``dd/MM/yyyy``.
        fecha_fin:          ``dd/MM/yyyy``.
        max_paginas_secop1: Páginas a traer de SECOP I (100 procesos c/u).
        max_registros_api:  Tope de registros de la API.

    Returns:
        Tupla ``(df, informe)``. El informe lleva el momento de la
        consulta, el conteo por fuente y los errores encontrados.
    """
    informe: dict = {
        "consultado_en": datetime.now(),
        "por_fuente": {},
        "errores": {},
        "avisos": [],
        "coincidencias_api": None,
        "truncado": False,
    }

    if tipo_contrato and "SECOP I" in fuentes:
        informe["avisos"].append(
            "El tipo de contrato solo se puede filtrar en SECOP II: la "
            "tabla de resultados de SECOP I no incluye ese dato."
        )

    partes: list[pd.DataFrame] = []

    for fuente in fuentes:
        try:
            if fuente == "SECOP II":
                # Se cuenta antes de descargar para poder avisar si el
                # resultado se va a truncar (una consulta nacional sin
                # filtros son casi 6 millones de contratos).
                total = contar_secop2(
                    departamento, modalidad, estado, palabra_clave,
                    fecha_inicio, fecha_fin, tipo_contrato,
                )
                informe["coincidencias_api"] = total
                if max_registros_api and total > max_registros_api:
                    informe["truncado"] = True
                    informe["avisos"].append(
                        f"La consulta coincide con {total:,} contratos en "
                        f"SECOP II y se descargaron los {max_registros_api:,} "
                        "más recientes. Acota por departamento, fechas o "
                        "modalidad para verlos todos."
                    )

                df_fuente = consultar_secop2(
                    departamento, modalidad, estado, palabra_clave,
                    fecha_inicio, fecha_fin, tipo_contrato, max_registros_api,
                )
            elif fuente == "SECOP I":
                df_fuente = consultar_secop1(
                    departamento, modalidad, estado, palabra_clave,
                    fecha_inicio, fecha_fin, max_paginas_secop1,
                )
            else:
                logger.warning("Fuente desconocida: %r", fuente)
                continue

            informe["por_fuente"][fuente] = len(df_fuente)
            if not df_fuente.empty:
                partes.append(df_fuente)

        except Exception as exc:  # noqa: BLE001 - se reporta y se sigue
            logger.warning("Fallo consultando %s: %s", fuente, exc)
            informe["errores"][fuente] = str(exc)
            informe["por_fuente"][fuente] = 0

    if not partes:
        return normalizar_esquema(pd.DataFrame()), informe

    df = pd.concat(partes, ignore_index=True)

    # Reordenar dejando primero el esquema conocido.
    columnas = [c for c in ESQUEMA_DASHBOARD if c in df.columns]
    extras = [c for c in df.columns if c not in columnas]
    df = df[columnas + extras]

    informe["total"] = len(df)
    return df, informe
