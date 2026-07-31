"""
cleaning.py — Limpieza y tipificación del DataFrame de resultados SECOP I.

Responsabilidades:
  1. Normalizar strings (strip, colapsar espacios, eliminar saltos de línea).
  2. Convertir columnas monetarias (formato colombiano) a ``float``.
  3. Parsear columnas de fecha a ``datetime``.
  4. Eliminar filas completamente vacías.
  5. Renombrar columnas según convención canónica.
  6. Validar el esquema final y generar reporte de calidad.

Principios:
  • Inmutabilidad: todas las funciones retornan un **nuevo** DataFrame.
  • Nunca pierde datos: valores no convertibles se mantienen como ``NaN``
    en vez de descartarse.
  • Logging detallado de cada transformación.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd

from config import (
    COLUMNAS_FECHA,
    COLUMNAS_MONETARIAS,
    COLUMNAS_RESULTADO,
)

logger = logging.getLogger(__name__)

# Dtypes que representan texto. pandas 3 dejó de usar ``object`` como
# dtype por defecto para strings (ahora es ``str``), así que filtrar solo
# por ``object`` deja de encontrar las columnas de texto.
_DTYPES_TEXTO = frozenset(
    {"object", "str", "string", "string[python]", "string[pyarrow]"}
)


def _columnas_texto(df: pd.DataFrame) -> list[str]:
    """Devuelve las columnas de texto, en pandas 2 y en pandas 3."""
    return [col for col in df.columns if str(df[col].dtype) in _DTYPES_TEXTO]


def _con_contenido(serie: pd.Series) -> pd.Series:
    """Máscara de celdas con contenido real.

    ``normalizar_strings`` corre antes que las conversiones y transforma
    los nulos en cadenas vacías, así que comprobar solo ``notna()`` haría
    que las celdas vacías se contabilizaran como errores de conversión.
    """
    if serie.isna().all():
        return serie.notna()
    return serie.notna() & (serie.astype(str).str.strip() != "")


# ════════════════════════════════════════════════════════════
# 1. NORMALIZACIÓN DE STRINGS
# ════════════════════════════════════════════════════════════


# Los datos de SECOP llegan con puntuación de Windows-1252 mal decodificada
# (bytes 0x80-0x9F sueltos). Quedan como caracteres de control invisibles
# que rompen la exportación a PDF ("missing glyph") y ensucian los
# informes, así que se traducen a su equivalente Unicode.
_CONTROLES_CP1252 = {
    "\x82": ",", "\x84": '"', "\x85": "...", "\x91": "'", "\x92": "'",
    "\x93": '"', "\x94": '"', "\x95": "-", "\x96": "-", "\x97": "-",
    "\x99": "™", "\xa0": " ",
}
_RE_CONTROLES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _normalizar_string(valor: object) -> str:
    """Normaliza un valor a string limpio.

    • Convierte a ``str``.
    • Traduce la puntuación cp1252 mal decodificada a Unicode.
    • Elimina caracteres de control residuales.
    • Elimina saltos de línea, tabuladores y retornos de carro.
    • Colapsa espacios múltiples.
    • Aplica ``strip()``.
    """
    if pd.isna(valor):
        return ""
    s = str(valor)
    for control, reemplazo in _CONTROLES_CP1252.items():
        if control in s:
            s = s.replace(control, reemplazo)
    s = _RE_CONTROLES.sub("", s)
    s = re.sub(r"[\n\r\t]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def normalizar_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica ``_normalizar_string`` a todas las columnas tipo ``object``.

    Returns:
        Nuevo DataFrame con strings normalizados.
    """
    df = df.copy()
    cols_str = _columnas_texto(df)
    for col in cols_str:
        df[col] = df[col].map(_normalizar_string)
    logger.info("Strings normalizados en %d columnas.", len(cols_str))
    return df


# ════════════════════════════════════════════════════════════
# 2. CONVERSIÓN DE VALORES MONETARIOS
# ════════════════════════════════════════════════════════════


# Porción numérica de una cadena monetaria: signo, dígitos y separadores.
_RE_NUMERO_MONETARIO = re.compile(r"-?\d[\d.,]*")


def _convertir_moneda_colombiana(valor: str) -> Optional[float]:
    """Convierte un string monetario a ``float``.

    El portal SECOP mezcla **dos convenciones** según la página, así que
    hay que deducir cuál es el separador decimal en vez de asumirlo:

      • Tabla de resultados (formato colombiano):
        ``$255.000.000,00`` → ``255000000.0``
      • Ficha de detalle (formato anglosajón):
        ``$9,062,000.00 Peso Colombiano`` → ``9062000.0``

    Reglas aplicadas:
      1. Se extrae solo la porción numérica (ignora ``$``, ``COP``, y
         cualquier texto que acompañe al número).
      2. Si aparecen ambos separadores, el **último** es el decimal.
      3. Si solo aparece uno y está repetido, es separador de miles.
      4. Si solo aparece una vez, es decimal cuando le siguen 1 o 2
         dígitos, y separador de miles cuando le siguen exactamente 3.

    Returns:
        El valor como ``float``, o ``None`` si no hay número.
    """
    if valor is None:
        return None

    coincidencia = _RE_NUMERO_MONETARIO.search(str(valor))
    if not coincidencia:
        return None

    s = coincidencia.group(0).rstrip(".,")
    if not s:
        return None

    negativo = s.startswith("-")
    s = s.lstrip("-")

    pos_punto = s.rfind(".")
    pos_coma = s.rfind(",")

    if pos_punto >= 0 and pos_coma >= 0:
        # Ambos presentes: el más a la derecha es el decimal.
        separador_decimal = "." if pos_punto > pos_coma else ","
    elif pos_punto >= 0 or pos_coma >= 0:
        separador = "." if pos_punto >= 0 else ","
        decimales = len(s.split(separador)[-1])
        repetido = s.count(separador) > 1
        # Repetido → miles. Una vez con 3 dígitos detrás → miles.
        separador_decimal = "" if (repetido or decimales == 3) else separador
    else:
        separador_decimal = ""

    if separador_decimal:
        entero, _, decimal = s.rpartition(separador_decimal)
        entero = re.sub(r"[.,]", "", entero)
        limpio = f"{entero or '0'}.{decimal}"
    else:
        limpio = re.sub(r"[.,]", "", s)

    try:
        numero = float(limpio)
    except ValueError:
        return None

    return -numero if negativo else numero


def convertir_columnas_monetarias(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas monetarias de string a ``float64``.

    Solo procesa columnas que existen en el DataFrame **y** están listadas
    en ``config.COLUMNAS_MONETARIAS``.

    Returns:
        Nuevo DataFrame con columnas monetarias convertidas.
    """
    df = df.copy()
    cols_presentes = [c for c in COLUMNAS_MONETARIAS if c in df.columns]

    for col in cols_presentes:
        # Solo se convierten los valores presentes: pasar los nulos por
        # astype(str) los volvería la cadena "nan" y se contarían como
        # errores de conversión que en realidad son celdas vacías.
        presentes = _con_contenido(df[col])
        df[col] = (
            df.loc[presentes, col].astype(str).map(_convertir_moneda_colombiana)
        )
        fallidos = int((presentes & df[col].isna()).sum())

        if fallidos > 0:
            logger.warning(
                "Columna '%s': %d valores no convertibles a float.", col, fallidos
            )
        logger.debug("Columna '%s' convertida a float64.", col)

    if cols_presentes:
        logger.info("Columnas monetarias convertidas: %s", cols_presentes)
    else:
        logger.debug("No se encontraron columnas monetarias para convertir.")

    return df


# ════════════════════════════════════════════════════════════
# 3. PARSEO DE COLUMNAS DE FECHA
# ════════════════════════════════════════════════════════════

# Formatos de fecha que usa el portal SECOP I
_FORMATOS_FECHA: list[str] = [
    "%d/%m/%Y",             # 31/01/2025            (SECOP I, formulario)
    "%d-%m-%Y",             # 31-01-2025            (SECOP I, tabla)
    "%Y-%m-%d",             # 2025-01-31
    "%d/%m/%Y %H:%M",       # 31/01/2025 14:30
    "%d/%m/%Y %H:%M:%S",    # 31/01/2025 14:30:00
    "%Y-%m-%dT%H:%M:%S.%f", # 2025-01-31T00:00:00.000  (API Socrata)
    "%Y-%m-%dT%H:%M:%S",    # ISO 8601
    "%Y-%m-%d %H:%M:%S",
]

# Una fecha que empieza por "yyyy-" es ISO: el año va primero y, por
# tanto, el día NUNCA va primero. Distinguirlo evita que 2026-03-10 se
# interprete como 3 de octubre en vez de 10 de marzo.
_RE_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


def _parsear_fecha(valor: str) -> Optional[pd.Timestamp]:
    """Intenta parsear un string a ``Timestamp`` probando múltiples formatos.

    El orden importa: los formatos con día primero (``dd/mm/yyyy``, que
    usa SECOP I) se prueban antes que los ISO (que usa la API). Para el
    intento final de inferencia automática se decide ``dayfirst`` según
    la forma de la cadena, porque aplicar ``dayfirst=True`` a una fecha
    ISO invierte día y mes silenciosamente.

    Returns:
        ``pd.Timestamp`` si se logra, ``None`` en caso contrario.
    """
    if not valor or valor.strip() == "":
        return None

    s = valor.strip()

    for fmt in _FORMATOS_FECHA:
        try:
            return pd.Timestamp(pd.to_datetime(s, format=fmt))
        except (ValueError, TypeError):
            continue

    # Último intento: inferencia automática, con dayfirst según el formato.
    try:
        return pd.Timestamp(pd.to_datetime(s, dayfirst=not _RE_ISO.match(s)))
    except (ValueError, TypeError):
        return None


def convertir_columnas_fecha(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas de fecha de string a ``datetime64``.

    Solo procesa columnas presentes en el DataFrame que coincidan con
    ``config.COLUMNAS_FECHA``.

    Returns:
        Nuevo DataFrame con columnas de fecha convertidas.
    """
    df = df.copy()
    cols_presentes = [c for c in COLUMNAS_FECHA if c in df.columns]

    for col in cols_presentes:
        # Igual que con los montos: los nulos se dejan fuera para que el
        # recuento de fallos refleje errores reales de formato.
        presentes = _con_contenido(df[col])
        df[col] = df.loc[presentes, col].astype(str).map(_parsear_fecha)
        fallidos = int((presentes & df[col].isna()).sum())

        if fallidos > 0:
            logger.warning(
                "Columna '%s': %d valores no parseables como fecha.", col, fallidos
            )
        logger.debug("Columna '%s' convertida a datetime.", col)

    if cols_presentes:
        logger.info("Columnas de fecha convertidas: %s", cols_presentes)

    return df


# ════════════════════════════════════════════════════════════
# 4. ELIMINACIÓN DE FILAS VACÍAS
# ════════════════════════════════════════════════════════════


def eliminar_filas_vacias(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina filas donde todas las columnas son vacías o NaN.

    También elimina filas donde todas las columnas de texto son strings
    vacíos (que ``dropna`` no detecta).

    Returns:
        Nuevo DataFrame sin filas vacías.
    """
    df = df.copy()
    antes = len(df)

    # Paso 1: dropna clásico
    df.dropna(how="all", inplace=True)

    # Paso 2: filas donde todos los strings son vacíos
    cols_str = _columnas_texto(df)
    if len(cols_str) > 0:
        mask_vacios = df[cols_str].apply(
            lambda row: all(str(v).strip() == "" for v in row), axis=1
        )
        df = df[~mask_vacios]

    df.reset_index(drop=True, inplace=True)
    eliminadas = antes - len(df)

    if eliminadas > 0:
        logger.info("Filas vacías eliminadas: %d", eliminadas)

    return df


# ════════════════════════════════════════════════════════════
# 5. RENOMBRAR COLUMNAS (MAPEO OPCIONAL)
# ════════════════════════════════════════════════════════════


def renombrar_columnas(
    df: pd.DataFrame, mapeo: Optional[dict[str, str]] = None
) -> pd.DataFrame:
    """Renombra columnas del DataFrame según un mapeo explícito.

    Si no se provee mapeo, intenta alinear con ``COLUMNAS_RESULTADO``
    por posición.

    Args:
        df:    DataFrame a renombrar.
        mapeo: ``{nombre_actual: nombre_nuevo}`` (opcional).

    Returns:
        Nuevo DataFrame con columnas renombradas.
    """
    df = df.copy()

    if mapeo:
        df.rename(columns=mapeo, inplace=True)
        logger.info("Columnas renombradas con mapeo explícito: %s", mapeo)
    elif list(df.columns) != COLUMNAS_RESULTADO:
        # Solo renombrar si las columnas son genéricas (col_0, col_1, ...)
        if all(str(c).startswith("col_") for c in df.columns):
            nuevas = COLUMNAS_RESULTADO[: len(df.columns)]
            df.columns = nuevas
            logger.info("Columnas renombradas por posición a: %s", nuevas)

    return df


# ════════════════════════════════════════════════════════════
# 6. REPORTE DE CALIDAD DE DATOS
# ════════════════════════════════════════════════════════════


def generar_reporte_calidad(df: pd.DataFrame) -> dict:
    """Genera un reporte resumido de la calidad del DataFrame.

    Returns:
        Diccionario con métricas por columna y globales.
    """
    reporte: dict = {
        "total_filas": len(df),
        "total_columnas": len(df.columns),
        "columnas": {},
    }

    cols_texto = set(_columnas_texto(df))

    for col in df.columns:
        info_col = {
            "dtype": str(df[col].dtype),
            "nulos": int(df[col].isna().sum()),
            "pct_nulos": round(df[col].isna().mean() * 100, 2),
            "unicos": int(df[col].nunique()),
        }

        # Para strings: contar vacíos
        if col in cols_texto:
            vacios = int((df[col].astype(str).str.strip() == "").sum())
            info_col["vacios"] = vacios

        reporte["columnas"][col] = info_col

    total_nulos = int(df.isna().sum().sum())
    total_celdas = len(df) * len(df.columns)
    reporte["pct_completitud"] = round(
        (1 - total_nulos / total_celdas) * 100, 2
    ) if total_celdas > 0 else 0.0

    logger.info(
        "Reporte de calidad: %d filas, completitud %.1f%%.",
        reporte["total_filas"],
        reporte["pct_completitud"],
    )
    return reporte


# ════════════════════════════════════════════════════════════
# 6b. FILTRO LOCAL POR PALABRA CLAVE
# ════════════════════════════════════════════════════════════

# Columnas donde buscar el texto libre, por orden de preferencia.
_COLUMNAS_OBJETO: tuple[str, ...] = ("objeto_contrato", "objeto_del_contrato")


def _sin_tildes(texto: str) -> str:
    """Normaliza a minúsculas y sin tildes para comparar."""
    tabla = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return texto.translate(tabla).lower()


def filtrar_por_palabra_clave(df: pd.DataFrame, texto: Optional[str]) -> pd.DataFrame:
    """Filtra por palabras clave sobre el objeto del contrato.

    **SECOP I no ofrece búsqueda por texto libre**: su formulario solo
    filtra por código UNSPSC, entidad, fechas, modalidad, estado y
    ubicación. Por eso el filtro por palabra clave se aplica en local,
    sobre los registros ya descargados.

    Todas las palabras deben aparecer (AND lógico), sin distinguir
    mayúsculas ni tildes.

    Args:
        df:    DataFrame ya parseado.
        texto: Palabras separadas por espacio (``None`` = no filtrar).

    Returns:
        Nuevo DataFrame filtrado.
    """
    if not texto or not texto.strip():
        return df

    columna = next((c for c in _COLUMNAS_OBJETO if c in df.columns), None)
    if columna is None:
        logger.warning(
            "No hay columna de objeto del contrato; se omite el filtro por "
            "palabra clave."
        )
        return df

    objetivo = df[columna].astype(str).map(_sin_tildes)
    mascara = pd.Series(True, index=df.index)
    for palabra in _sin_tildes(texto).split():
        mascara &= objetivo.str.contains(re.escape(palabra), na=False)

    filtrado = df[mascara].reset_index(drop=True)
    logger.info(
        "Filtro por palabra clave %r sobre '%s': %d → %d filas.",
        texto, columna, len(df), len(filtrado),
    )
    return filtrado


# ════════════════════════════════════════════════════════════
# 7. PIPELINE DE LIMPIEZA COMPLETO
# ════════════════════════════════════════════════════════════


def limpiar_dataframe(
    df: pd.DataFrame,
    mapeo_columnas: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    """Ejecuta el pipeline completo de limpieza sobre un DataFrame crudo.

    Orden de operaciones:
      1. Normalizar strings.
      2. Eliminar filas vacías.
      3. Renombrar columnas.
      4. Convertir columnas monetarias.
      5. Convertir columnas de fecha.

    Args:
        df:              DataFrame crudo del parser.
        mapeo_columnas:  Mapeo opcional ``{col_actual: col_nueva}``.

    Returns:
        DataFrame limpio y tipificado.
    """
    logger.info("Iniciando pipeline de limpieza (%d filas)...", len(df))

    df = normalizar_strings(df)
    df = eliminar_filas_vacias(df)
    df = renombrar_columnas(df, mapeo_columnas)
    df = convertir_columnas_monetarias(df)
    df = convertir_columnas_fecha(df)

    reporte = generar_reporte_calidad(df)
    logger.info(
        "Pipeline de limpieza completado: %d filas, completitud %.1f%%.",
        reporte["total_filas"],
        reporte["pct_completitud"],
    )

    return df
