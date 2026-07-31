"""
detail_scraper.py — Extracción de la ficha de detalle de procesos SECOP I.

La ficha (``detalleProceso.do?numConstancia=<id>``) contiene los datos
que no aparecen en la tabla de resultados: contratista, identificación,
cuantía definitiva, fechas de apertura y cierre, tipo de contrato, etc.

Responsabilidades:
  1. Descargar la ficha de un proceso (HTTP directo o, opcionalmente,
     reutilizando un WebDriver ya abierto).
  2. Convertir los pares etiqueta-valor del HTML en campos tipados.
  3. Extracción masiva con control de ritmo para no despertar al WAF.
  4. Mantener una base histórica incremental.

Las etiquetas del mapeo están tomadas del HTML real en producción: el
portal usa "Tipo de Proceso" (no "Modalidad de Contratación"),
"Cuantía a Contratar" para el presupuesto y "Cuantía Definitiva del
Contrato" para el valor final.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import pandas as pd
from bs4 import BeautifulSoup

from config import (
    COLUMNAS_DETALLE,
    HTTP_DELAY,
    MAX_RETRIES,
    RETRY_BACKOFF,
)

logger = logging.getLogger(__name__)

_RE_FECHA = re.compile(r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})")
_RE_NUMERO_PROCESO = re.compile(
    r"Detalle\s+del\s+Proceso\s+N[úu]mero:\s*(.+)", re.IGNORECASE
)


# ════════════════════════════════════════════════════════════
# 1. DATACLASS
# ════════════════════════════════════════════════════════════


@dataclass
class DetalleProceso:
    """Datos detallados de un proceso de contratación de SECOP I."""

    numero_proceso: str = ""
    id_proceso: str = ""
    entidad: str = ""
    objeto_contrato: str = ""
    modalidad: str = ""
    estado: str = ""
    fecha_apertura: str = ""
    fecha_cierre: str = ""
    fecha_adjudicacion: str = ""
    valor_estimado: str = ""
    valor_adjudicado: str = ""
    valor_contrato: str = ""
    numero_contrato: str = ""
    tipo_contrato: str = ""
    estado_contrato: str = ""
    proveedor: str = ""
    nit_proveedor: str = ""
    departamento: str = ""
    municipio: str = ""
    url_detalle: str = ""

    def to_dict(self) -> dict:
        """Convierte el dataclass a diccionario."""
        return asdict(self)


# ════════════════════════════════════════════════════════════
# 2. MAPEO DE ETIQUETAS DEL PORTAL → CAMPOS
# ════════════════════════════════════════════════════════════

# Claves ya normalizadas por ``_normalizar_etiqueta`` (minúsculas, sin
# signos, sin dobles espacios).
_MAPEO_ETIQUETAS: dict[str, str] = {
    # --- Información general del proceso ---
    "tipo de proceso": "modalidad",
    "modalidad de contratacion": "modalidad",
    "estado del proceso": "estado",
    "detalle y cantidad del objeto a contratar": "objeto_contrato",
    "objeto a contratar": "objeto_contrato",
    "cuantia a contratar": "valor_estimado",
    "presupuesto oficial": "valor_estimado",
    "fecha y hora de apertura del proceso": "fecha_apertura",
    "fecha de apertura del proceso": "fecha_apertura",
    "fecha y hora de cierre del proceso": "fecha_cierre",
    "fecha de cierre del proceso": "fecha_cierre",
    # --- Datos del contrato ---
    "numero del contrato": "numero_contrato",
    "objeto del contrato": "objeto_contrato",
    "estado del contrato": "estado_contrato",
    "tipo de contrato": "tipo_contrato",
    "cuantia definitiva del contrato": "valor_contrato",
    "valor total del contrato": "valor_contrato",
    "fecha de firma del contrato": "fecha_adjudicacion",
    "fecha de adjudicacion": "fecha_adjudicacion",
    "valor adjudicado": "valor_adjudicado",
    # --- Contratista ---
    "nombre o razon social del contratista": "proveedor",
    "nombre del contratista": "proveedor",
    "identificacion del contratista": "nit_proveedor",
    # --- Ubicación ---
    "departamento y municipio de ejecucion": "_ubicacion",
}


def _normalizar_etiqueta(texto: str) -> str:
    """Normaliza una etiqueta del portal para buscarla en el mapeo.

    Pasa a minúsculas, quita tildes, signos de puntuación y espacios
    redundantes, de modo que el mapeo no dependa de la acentuación ni de
    los dos puntos finales.
    """
    tabla = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    s = texto.translate(tabla).lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())


def _partir_ubicacion(texto: str) -> tuple[str, str]:
    """Separa ``"Santander : Albania"`` en departamento y municipio."""
    if not texto:
        return "", ""
    if ":" in texto:
        departamento, _, municipio = texto.partition(":")
        return departamento.strip(), municipio.strip()
    return texto.strip(), ""


def _solo_fecha(texto: str) -> str:
    """Extrae la fecha de cadenas como ``'24-03-2026 11:30 a.m.'``."""
    coincidencia = _RE_FECHA.search(texto or "")
    return coincidencia.group(1) if coincidencia else ""


def _id_desde_url(url: str) -> str:
    """Extrae el ``numConstancia`` de la URL de detalle."""
    try:
        return parse_qs(urlparse(url).query).get("numConstancia", [""])[0]
    except (ValueError, AttributeError):
        return ""


# ════════════════════════════════════════════════════════════
# 3. PARSEO DEL HTML DE DETALLE
# ════════════════════════════════════════════════════════════


def _parsear_detalle_html(html: str, url: str) -> DetalleProceso:
    """Extrae los campos de la ficha de detalle de un proceso.

    Recorre las filas ``<tr>`` con al menos dos celdas, interpretándolas
    como pares etiqueta-valor, y además rescata el número de proceso y
    la entidad del encabezado de la página.

    Args:
        html: HTML de la ficha de detalle.
        url:  URL de origen (se guarda en el resultado).

    Returns:
        ``DetalleProceso`` con los campos encontrados.
    """
    soup = BeautifulSoup(html, "html.parser")
    detalle = DetalleProceso(url_detalle=url, id_proceso=_id_desde_url(url))

    # --- Encabezado: número de proceso y entidad ---
    texto_pagina = soup.get_text("\n", strip=True)
    coincidencia = _RE_NUMERO_PROCESO.search(texto_pagina)
    if coincidencia:
        detalle.numero_proceso = coincidencia.group(1).strip()

    lineas = [ln for ln in texto_pagina.split("\n") if ln.strip()]
    for indice, linea in enumerate(lineas):
        if _RE_NUMERO_PROCESO.search(linea) and indice + 1 < len(lineas):
            detalle.entidad = lineas[indice + 1].strip()
            break

    # --- Pares etiqueta / valor ---
    encontrados: set[str] = set()

    for fila in soup.find_all("tr"):
        celdas = fila.find_all("td")
        if len(celdas) < 2:
            continue

        etiqueta = _normalizar_etiqueta(celdas[0].get_text(" ", strip=True))
        valor = celdas[1].get_text(" ", strip=True)
        if not etiqueta or not valor:
            continue

        campo = _MAPEO_ETIQUETAS.get(etiqueta)
        if not campo or campo in encontrados:
            continue

        if campo == "_ubicacion":
            detalle.departamento, detalle.municipio = _partir_ubicacion(valor)
            encontrados.add(campo)
            continue

        if campo in ("fecha_apertura", "fecha_cierre", "fecha_adjudicacion"):
            valor = _solo_fecha(valor)
            if not valor:
                continue

        setattr(detalle, campo, valor)
        encontrados.add(campo)

    logger.debug(
        "Detalle parseado para %r: %d campos.",
        detalle.numero_proceso or url, len(encontrados),
    )
    return detalle


# ════════════════════════════════════════════════════════════
# 4. DESCARGA DE UNA FICHA
# ════════════════════════════════════════════════════════════


def extraer_detalle_proceso(
    url: str,
    sesion=None,
    driver=None,
) -> Optional[DetalleProceso]:
    """Descarga y parsea la ficha de detalle de un proceso.

    Usa HTTP directo salvo que se pase un ``driver``, en cuyo caso
    navega con Selenium (útil si el WAF empieza a exigir JavaScript).

    Args:
        url:    URL absoluta de la ficha.
        sesion: Sesión HTTP reutilizable.
        driver: WebDriver a usar en lugar de HTTP.

    Returns:
        ``DetalleProceso``, o ``None`` si falla.
    """
    if driver is not None:
        from selenium.common.exceptions import WebDriverException

        for intento in range(1, MAX_RETRIES + 1):
            try:
                driver.get(url)
                return _parsear_detalle_html(driver.page_source, url)
            except WebDriverException as exc:
                logger.warning(
                    "Error en detalle %s (intento %d/%d): %s",
                    url, intento, MAX_RETRIES, exc,
                )
                if intento < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF**intento)
        return None

    from scraper import _get, crear_sesion

    sesion = sesion or crear_sesion()
    try:
        respuesta = _get(sesion, url)
        return _parsear_detalle_html(respuesta.text, url)
    except Exception as exc:  # noqa: BLE001 - un fallo no debe parar el lote
        logger.warning("No se pudo obtener el detalle %s: %s", url, exc)
        return None


# ════════════════════════════════════════════════════════════
# 5. EXTRACCIÓN MASIVA
# ════════════════════════════════════════════════════════════


def extraer_detalles_masivo(
    urls: list[str],
    delay: float = HTTP_DELAY,
    max_errores: int = 10,
    driver=None,
    sesion=None,
) -> pd.DataFrame:
    """Descarga las fichas de varios procesos, de forma secuencial.

    Args:
        urls:        URLs de detalle a procesar.
        delay:       Segundos entre peticiones (cortesía con el WAF).
        max_errores: Errores consecutivos tolerados antes de abortar.
        driver:      WebDriver opcional (fuerza la ruta Selenium).
        sesion:      Sesión HTTP reutilizable.

    Returns:
        DataFrame con los detalles extraídos correctamente.
    """
    from scraper import calentar_sesion, crear_sesion

    if driver is None and sesion is None:
        sesion = crear_sesion()
        calentar_sesion(sesion)

    resultados: list[dict] = []
    errores_consecutivos = 0
    total = len(urls)

    logger.info("Iniciando extracción masiva de detalles: %d procesos.", total)

    for indice, url in enumerate(urls, start=1):
        detalle = extraer_detalle_proceso(url, sesion=sesion, driver=driver)

        if detalle and (detalle.numero_proceso or detalle.objeto_contrato):
            resultados.append(detalle.to_dict())
            errores_consecutivos = 0
        else:
            errores_consecutivos += 1
            logger.warning(
                "Fallo en proceso %d/%d (errores consecutivos: %d).",
                indice, total, errores_consecutivos,
            )

        if errores_consecutivos >= max_errores:
            logger.error(
                "Abortando extracción masiva tras %d errores consecutivos.",
                max_errores,
            )
            break

        if indice < total:
            time.sleep(delay)

        if indice % 10 == 0:
            logger.info(
                "Progreso: %d/%d procesados (%d exitosos).",
                indice, total, len(resultados),
            )

    if not resultados:
        logger.warning("No se extrajo ningún detalle de %d URLs.", total)
        return pd.DataFrame(columns=COLUMNAS_DETALLE)

    df = pd.DataFrame(resultados)

    presentes = [c for c in COLUMNAS_DETALLE if c in df.columns]
    extras = [c for c in df.columns if c not in COLUMNAS_DETALLE]
    df = df[presentes + extras]

    logger.info(
        "Extracción masiva completada: %d/%d detalles extraídos.", len(df), total
    )
    return df


# ════════════════════════════════════════════════════════════
# 6. BASE HISTÓRICA INCREMENTAL
# ════════════════════════════════════════════════════════════


def actualizar_base_historica(
    nuevos: pd.DataFrame,
    ruta_historica: str,
    columna_clave: str = "numero_proceso",
) -> pd.DataFrame:
    """Combina nuevos registros con una base histórica existente.

    Deduplica por ``columna_clave`` conservando el registro más reciente.
    El formato (CSV o Parquet) se decide por la extensión del archivo.

    Args:
        nuevos:         DataFrame con registros nuevos.
        ruta_historica: Ruta del archivo histórico.
        columna_clave:  Columna identificadora única.

    Returns:
        DataFrame con la base histórica actualizada.
    """
    from pathlib import Path

    ruta = Path(ruta_historica)

    if ruta.exists():
        if ruta.suffix == ".parquet":
            historica = pd.read_parquet(ruta)
        else:
            historica = pd.read_csv(ruta, dtype=str)
        logger.info("Base histórica cargada: %d registros.", len(historica))
    else:
        historica = pd.DataFrame()
        logger.info("No existe base histórica, se creará nueva.")

    combinado = pd.concat([historica, nuevos], ignore_index=True)

    if columna_clave in combinado.columns:
        antes = len(combinado)
        combinado = combinado.drop_duplicates(
            subset=[columna_clave], keep="last"
        ).reset_index(drop=True)
        logger.info(
            "Deduplicación: %d → %d registros (clave: '%s').",
            antes, len(combinado), columna_clave,
        )

    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.suffix == ".parquet":
        combinado.to_parquet(ruta, index=False, engine="pyarrow")
    else:
        combinado.to_csv(ruta, index=False, encoding="utf-8-sig")

    logger.info(
        "Base histórica actualizada en '%s': %d registros.", ruta, len(combinado)
    )
    return combinado
