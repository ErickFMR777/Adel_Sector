"""
parser.py — Estructuración de las tablas HTML de resultados de SECOP I.

Responsabilidades:
  1. Recibir HTML crudo (una o varias páginas) desde ``scraper.py``.
  2. Localizar la tabla de resultados con BeautifulSoup.
  3. Mapear las columnas al esquema canónico de ``config``.
  4. Derivar campos compuestos:
       • ``id_proceso``  ← ``javascript: consultaProceso('26-11-14696064')``
       • ``url_detalle`` ← ``detalleProceso.do?numConstancia=<id_proceso>``
       • ``departamento`` / ``municipio`` ← ``"Santander : Girón"``
       • ``fecha_apertura`` ← ``"Fecha de Celebración ... 31-03-2026"``
  5. Consolidar múltiples páginas en un único DataFrame.

Estructura real de la tabla (9 columnas, verificada en producción):

    0 ∇ (ordinal)  1 Número de Proceso  2 Tipo de Proceso  3 Estado
    4 Entidad      5 Objeto             6 Departamento y Municipio de Ejecución
    7 Cuantía      8 Fecha(dd-mm-aaaa)

Principios de diseño:
  • Tolerancia a cambios menores del DOM: si la tabla no encaja con el
    esquema conocido se cae a un parseo genérico por encabezados.
  • **Nunca convierte tipos** — eso le corresponde a ``cleaning.py``.
    Aquí ``cuantia`` sigue siendo ``'$255.000.000,00'`` y las fechas,
    texto ``'31-03-2026'``.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup, Tag

from config import (
    COLUMNAS_RESULTADO,
    COLUMNAS_TABLA_SECOP1,
    PATRON_ID_PROCESO,
    SECOP_DETALLE_URL,
    SEL_TABLA_RESULTADOS,
)
from exceptions import SecopEmptyTableError, SecopParsingError

logger = logging.getLogger(__name__)

_RE_ID_PROCESO = re.compile(PATRON_ID_PROCESO)
_RE_FECHA = re.compile(r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})")

# Encabezados que identifican inequívocamente la tabla de resultados.
_ENCABEZADOS_CLAVE = ("número de proceso", "numero de proceso")


# ════════════════════════════════════════════════════════════
# 1. LOCALIZAR LA TABLA
# ════════════════════════════════════════════════════════════


def _encontrar_tabla(soup: BeautifulSoup) -> Optional[Tag]:
    """Localiza la tabla principal de resultados en el DOM.

    Estrategia (de mayor a menor especificidad):
      1. Tabla cuyo encabezado contiene "Número de Proceso".
      2. Clase CSS histórica del portal (``tbl_resulados``, sic).
      3. Tabla con mayor número de filas (heurística).
      4. Primera tabla del documento (último recurso).

    En producción la tabla **no tiene clase CSS**, así que lo habitual es
    que gane la estrategia 1.
    """
    tablas = soup.find_all("table")

    # Estrategia 1: por encabezado real
    for tabla in tablas:
        primera = tabla.find("tr")
        if not primera:
            continue
        texto = primera.get_text(" ", strip=True).lower()
        if any(clave in texto for clave in _ENCABEZADOS_CLAVE):
            logger.debug("Tabla localizada por encabezado 'Número de Proceso'.")
            return tabla

    # Estrategia 2: clase CSS histórica
    clase_css = SEL_TABLA_RESULTADOS.replace("table.", "")
    tabla = soup.find("table", class_=clase_css)
    if tabla:
        logger.debug("Tabla localizada por clase CSS '%s'.", clase_css)
        return tabla

    # Estrategia 3: la tabla con más filas
    if tablas:
        mayor = max(tablas, key=lambda t: len(t.find_all("tr")))
        if len(mayor.find_all("tr")) > 1:
            logger.debug("Tabla localizada por heurística (mayor número de filas).")
            return mayor

    # Estrategia 4: la primera
    return tablas[0] if tablas else None


def _es_tabla_secop1(tabla: Tag) -> bool:
    """Indica si la tabla tiene el esquema conocido de SECOP I."""
    primera = tabla.find("tr")
    if not primera:
        return False
    texto = primera.get_text(" ", strip=True).lower()
    return any(clave in texto for clave in _ENCABEZADOS_CLAVE)


# ════════════════════════════════════════════════════════════
# 2. EXTRACCIÓN DE CAMPOS DERIVADOS
# ════════════════════════════════════════════════════════════


def _extraer_id_proceso(celda: Tag) -> Optional[str]:
    """Extrae el identificador interno del proceso de una celda.

    El enlace no es un ``href`` normal sino
    ``javascript: consultaProceso('26-11-14696064')``.

    Returns:
        El ID (``'26-11-14696064'``) o ``None``.
    """
    for enlace in celda.find_all("a"):
        for atributo in ("href", "onclick"):
            valor = enlace.get(atributo) or ""
            coincidencia = _RE_ID_PROCESO.search(valor)
            if coincidencia:
                return coincidencia.group(1).strip()
    return None


def _partir_ubicacion(texto: str) -> tuple[str, str]:
    """Separa ``"Santander : San José de Miranda"`` en depto y municipio.

    Returns:
        Tupla ``(departamento, municipio)``. Si no hay separador, todo el
        texto se considera departamento.
    """
    if not texto:
        return "", ""
    if ":" in texto:
        departamento, _, municipio = texto.partition(":")
        return departamento.strip(), municipio.strip()
    return texto.strip(), ""


def _partir_fecha(texto: str) -> tuple[str, str]:
    """Separa la etiqueta de la fecha en la última columna.

    El portal escribe, por ejemplo,
    ``"Fecha de Celebración del Primer Contrato 31-03-2026"``; la
    etiqueta cambia según el estado del proceso.

    Returns:
        Tupla ``(etiqueta, fecha)`` con la fecha en texto (``dd-mm-yyyy``).
    """
    if not texto:
        return "", ""
    coincidencia = _RE_FECHA.search(texto)
    if not coincidencia:
        return texto.strip(), ""
    fecha = coincidencia.group(1)
    etiqueta = texto.replace(fecha, "").strip(" .-:")
    return etiqueta, fecha


def _url_detalle(id_proceso: Optional[str]) -> Optional[str]:
    """Construye la URL de la ficha de detalle a partir del ID."""
    if not id_proceso:
        return None
    return f"{SECOP_DETALLE_URL}?numConstancia={id_proceso}"


# ════════════════════════════════════════════════════════════
# 3. PARSEO DE UNA PÁGINA
# ════════════════════════════════════════════════════════════


def _parsear_filas_secop1(tabla: Tag) -> list[dict]:
    """Convierte las filas de la tabla de SECOP I en diccionarios."""
    registros: list[dict] = []
    contenedor = tabla.find("tbody") or tabla

    for fila in contenedor.find_all("tr"):
        if fila.find("th") is not None:
            continue  # fila de encabezado

        celdas = fila.find_all("td")
        if len(celdas) < len(COLUMNAS_TABLA_SECOP1):
            continue  # separador o pie de paginación

        crudo = {
            nombre: celdas[indice].get_text(" ", strip=True)
            for indice, nombre in COLUMNAS_TABLA_SECOP1.items()
        }

        # En las filas de datos la primera columna es el ordinal (1, 2, 3...);
        # en el encabezado es el símbolo de ordenación "∇". Sirve para
        # descartar el encabezado aunque esté maquetado con <td>.
        if not crudo.get("orden", "").strip().isdigit():
            continue

        # Descartar filas sin número de proceso (decorativas)
        if not crudo.get("numero_proceso"):
            continue

        id_proceso = _extraer_id_proceso(celdas[1])
        departamento, municipio = _partir_ubicacion(crudo.pop("ubicacion_ejecucion", ""))
        etiqueta, fecha = _partir_fecha(crudo.pop("fecha_texto", ""))
        crudo.pop("orden", None)

        crudo.update(
            {
                "id_proceso": id_proceso,
                "departamento": departamento,
                "municipio": municipio,
                "fecha_etiqueta": etiqueta,
                "fecha_apertura": fecha,
                "url_detalle": _url_detalle(id_proceso),
            }
        )
        registros.append(crudo)

    return registros


def _parsear_filas_generico(tabla: Tag) -> pd.DataFrame:
    """Parseo de respaldo para tablas con un esquema desconocido.

    Usa los ``<th>`` como nombres de columna (normalizados) y, si no los
    hay, nombres genéricos ``col_0``, ``col_1``, ...
    """
    encabezados: list[str] = []
    thead = tabla.find("thead") or tabla
    ths = thead.find_all("th")
    if ths:
        for th in ths:
            limpio = re.sub(r"[^a-záéíóúñü0-9]+", "_", th.get_text(strip=True).lower())
            encabezados.append(re.sub(r"_+", "_", limpio).strip("_"))

    filas: list[list[str]] = []
    contenedor = tabla.find("tbody") or tabla
    for fila in contenedor.find_all("tr"):
        celdas = fila.find_all("td")
        if not celdas:
            continue
        valores = [td.get_text(" ", strip=True) for td in celdas]
        if all(v == "" for v in valores):
            continue
        filas.append(valores)

    if not filas:
        raise SecopParsingError(
            "Tabla encontrada pero sin filas de datos.",
            context={"encabezados": encabezados},
        )

    ancho = len(filas[0])
    if len(encabezados) == ancho:
        columnas = encabezados
    else:
        columnas = [f"col_{i}" for i in range(ancho)]
        logger.warning(
            "Esquema desconocido (%d columnas); se usan nombres genéricos.", ancho
        )

    normalizadas = [
        (fila + [""] * (ancho - len(fila)))[:ancho] for fila in filas
    ]
    return pd.DataFrame(normalizadas, columns=columnas)


def parsear_pagina(html: str) -> pd.DataFrame:
    """Convierte el HTML de una página de resultados en un DataFrame.

    Args:
        html: HTML crudo de una página.

    Returns:
        DataFrame sin tipar, con el esquema de ``COLUMNAS_RESULTADO`` si
        la tabla es la de SECOP I.

    Raises:
        SecopParsingError: Si no se encuentra tabla o no hay filas.
    """
    soup = BeautifulSoup(html, "html.parser")
    tabla = _encontrar_tabla(soup)

    if tabla is None:
        raise SecopParsingError(
            "No se encontró tabla de resultados en el HTML.",
            context={"html_length": len(html)},
        )

    if not _es_tabla_secop1(tabla):
        logger.debug("La tabla no tiene el esquema de SECOP I; parseo genérico.")
        return _parsear_filas_generico(tabla)

    registros = _parsear_filas_secop1(tabla)
    if not registros:
        raise SecopParsingError(
            "Tabla de SECOP I encontrada pero sin filas de datos.",
            context={"html_length": len(html)},
        )

    df = pd.DataFrame(registros)

    # Ordenar según el esquema canónico, conservando cualquier extra.
    presentes = [c for c in COLUMNAS_RESULTADO if c in df.columns]
    extras = [c for c in df.columns if c not in COLUMNAS_RESULTADO]
    df = df[presentes + extras]

    logger.info("Página parseada: %d filas × %d columnas.", len(df), len(df.columns))
    return df


# ════════════════════════════════════════════════════════════
# 4. PARSEO DE MÚLTIPLES PÁGINAS
# ════════════════════════════════════════════════════════════


def parsear_todas_paginas(paginas_html: list[str]) -> pd.DataFrame:
    """Parsea varias páginas y las consolida en un único DataFrame.

    Si una página falla, se registra y se omite sin detener el pipeline.

    Args:
        paginas_html: Lista de HTML, uno por página.

    Returns:
        DataFrame consolidado con todas las filas.

    Raises:
        SecopEmptyTableError: Si ninguna página produjo datos.
    """
    if not paginas_html:
        raise SecopEmptyTableError("No se recibieron páginas HTML para parsear.")

    dataframes: list[pd.DataFrame] = []
    errores = 0

    for indice, html in enumerate(paginas_html, start=1):
        try:
            dataframes.append(parsear_pagina(html))
        except SecopParsingError as exc:
            errores += 1
            logger.warning("Página %d: error de parsing — %s", indice, exc)

    if not dataframes:
        raise SecopEmptyTableError(
            f"Ninguna de las {len(paginas_html)} páginas produjo datos "
            f"({errores} errores de parsing).",
        )

    consolidado = pd.concat(dataframes, ignore_index=True)

    antes = len(consolidado)
    consolidado = consolidado.drop_duplicates().reset_index(drop=True)
    if antes != len(consolidado):
        logger.info("Duplicados eliminados: %d → %d filas.", antes, len(consolidado))

    logger.info(
        "Parsing completado: %d filas de %d páginas (%d errores).",
        len(consolidado), len(paginas_html), errores,
    )
    return consolidado
