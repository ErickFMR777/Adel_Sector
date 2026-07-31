"""
config.py — Constantes de configuración centralizadas para el pipeline SECOP.

Contiene:
  • URLs y endpoints reales de SECOP I (contratos.gov.co).
  • Nombres de los parámetros del formulario de consulta (verificados
    contra el DOM en producción).
  • Códigos oficiales de modalidad / departamento / estado, extraídos de
    los JS del propio portal (``tProceso.js``, ``deptos.js``,
    ``ServletComboEstado.select``).
  • Selectores CSS / XPath para la ruta Selenium (fallback).
  • Nombres canónicos de las columnas del DataFrame de salida.
  • Parámetros de reintentos, timeouts, cortesía con el WAF y rutas.
  • Configuración de logging estructurado.

Se importa desde todos los demás módulos para evitar valores mágicos y
facilitar el mantenimiento cuando el portal cambie.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ────────────────────────────────────────────────────────────
# 1. RUTAS Y DIRECTORIOS
# ────────────────────────────────────────────────────────────

BASE_DIR: Path = Path(__file__).resolve().parent
OUTPUT_DIR: Path = BASE_DIR / "output"
LOG_DIR: Path = BASE_DIR / "logs"


def _asegurar_directorio(ruta: Path) -> bool:
    """Crea un directorio si se puede escribir en él.

    En despliegues con el sistema de archivos de solo lectura (algunos
    PaaS y contenedores endurecidos) esto falla. Como se ejecuta al
    importar el módulo, una excepción aquí tumbaría la aplicación entera
    antes de arrancar, así que el fallo se degrada a un aviso.

    Returns:
        ``True`` si el directorio existe y es utilizable.
    """
    try:
        ruta.mkdir(exist_ok=True, parents=True)
        return True
    except OSError:
        return False


ESCRITURA_DISPONIBLE: bool = _asegurar_directorio(OUTPUT_DIR)
_LOGS_DISPONIBLES: bool = _asegurar_directorio(LOG_DIR)


# ────────────────────────────────────────────────────────────
# 2. CONSOLA UTF-8 (Windows)
# ────────────────────────────────────────────────────────────


def configurar_consola_utf8() -> None:
    """Fuerza la salida estándar a UTF-8.

    En Windows la consola usa cp1252 por defecto, lo que hace que
    cualquier ``print`` con acentos, emoji o caracteres de caja
    (``─``, ``═``) lance ``UnicodeEncodeError`` y aborte el pipeline.
    Se invoca desde los puntos de entrada antes de imprimir nada.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - stream exótico
                pass


# ────────────────────────────────────────────────────────────
# 3. URLs Y ENDPOINTS DE SECOP I
# ────────────────────────────────────────────────────────────

SECOP_BASE_URL: str = "https://www.contratos.gov.co"

# Formulario de consulta (GET). Sirve además para "calentar" la sesión y
# obtener las cookies que exige el WAF.
SECOP_CONSULTA_URL: str = f"{SECOP_BASE_URL}/consultas/inicioConsulta.do"

# Página contenedora que devuelve el POST del formulario. Solo trae un
# cascarón con "cargando..." y un <iframe> hacia el endpoint real.
SECOP_RESULTADO_URL: str = f"{SECOP_BASE_URL}/consultas/resultadoListadoProcesos.jsp"

# ENDPOINT REAL de la tabla de resultados: es lo que carga el iframe.
# Acepta GET con todos los filtros en la query string y NO exige token
# de reCAPTCHA. Es la vía preferente del scraper (sin navegador).
SECOP_RESULTADOS_DATA_URL: str = f"{SECOP_BASE_URL}/consultas/resultadosConsulta.do"

# Ficha de detalle de un proceso: ?numConstancia=<id_proceso>
SECOP_DETALLE_URL: str = f"{SECOP_BASE_URL}/consultas/detalleProceso.do"

# Combo de estados, depende de la modalidad: ?valor=<cod_modalidad>&cont=0
SECOP_ESTADOS_URL: str = f"{SECOP_BASE_URL}/consultas/ServletComboEstado.select"


# ────────────────────────────────────────────────────────────
# 4. PARÁMETROS DEL FORMULARIO DE CONSULTA (nombres reales)
# ────────────────────────────────────────────────────────────

# Nombres de los campos tal como los espera el servidor. Verificados
# contra <form name="parametros"> de inicioConsulta.do.
PARAM_NUMERO_PROCESO: str = "numeroProceso"
PARAM_ENTIDAD: str = "entidad"           # hidden, código interno de la entidad
PARAM_FIND_ENTIDAD: str = "findEntidad"  # visible, texto del autocompletar
PARAM_FECHA_INICIAL: str = "fechaInicial"
PARAM_FECHA_FINAL: str = "fechaFinal"
PARAM_OBJETO: str = "objeto"             # código UNSPSC (segmento)
PARAM_MODALIDAD: str = "tipoProceso"
PARAM_ESTADO: str = "estado"             # ID numérico (ver ESTADO_SECOP1)
PARAM_DEPARTAMENTO: str = "departamento"
PARAM_MUNICIPIO: str = "municipio"
PARAM_CUANTIA: str = "cuantia"           # rango de cuantía (ver CUANTIA_SECOP1)
PARAM_REGISTROS_PAGINA: str = "registrosXPagina"
PARAM_PAGINA: str = "paginaObjetivo"

# Campos fijos que el portal siempre envía.
PARAM_DESDE_FORMULARIO: str = "desdeFomulario"   # (sic) typo del portal
PARAM_ACTION: str = "action"
PARAM_RECAPTCHA: str = "g-recaptcha-response"

# Máximo de registros por página que acepta el select del portal.
REGISTROS_POR_PAGINA: int = 100

# Input oculto de la página de resultados con el total de coincidencias.
CAMPO_TOTAL_RESULTADOS: str = "totalResultados"


# ────────────────────────────────────────────────────────────
# 5. CÓDIGOS OFICIALES DE SECOP I
#    Extraídos de los JS del portal — son los valores que el
#    servidor espera en la query string.
# ────────────────────────────────────────────────────────────

# Modalidad de contratación (de /entidades/comun/js/tProceso.js)
MODALIDAD_SECOP1: dict[str, str] = {
    "1": "Licitación Pública",
    "11": "Selección Abreviada de Menor Cuantía (Ley 1150 de 2007)",
    "9": "Subasta",
    "13": "Contratación Mínima Cuantía",
    "17": "Selección Abreviada servicios de Salud",
    "10": "Concurso de Méritos con Lista Corta",
    "14": "Concurso de Méritos con Lista Multiusos",
    "15": "Concurso de Méritos Abierto",
    "16": "Lista Multiusos",
    "12": "Contratación Directa (Ley 1150 de 2007)",
    "4": "Régimen Especial",
    "2": "Contratación Directa Menor Cuantía",
    "3": "Otras Formas de Contratación Directa",
    "5": "Invitación ofertas cooperativas o asociaciones de entidades territoriales",
    "18": "Selección Abreviada del literal h del numeral 2 del artículo 2 de la Ley 1150 de 2007",
    "19": "Asociación Público Privada",
    "20": "Iniciativa Privada sin recursos públicos",
    "21": "Licitación obra pública",
    "22": "Contratos y convenios con más de dos partes",
    "23": "Concurso de diseño Arquitectónico",
}

# Departamento de ejecución (de /entidades/comun/js/deptos.js)
DEPARTAMENTO_SECOP1: dict[str, str] = {
    "91000": "Amazonas",
    "5000": "Antioquia",
    "81000": "Arauca",
    "8000": "Atlántico",
    "1100": "Bogotá D.C.",
    "1300": "Bolívar",
    "15000": "Boyacá",
    "17000": "Caldas",
    "1800": "Caquetá",
    "85000": "Casanare",
    "19000": "Cauca",
    "20000": "Cesar",
    "27000": "Chocó",
    "00002": "Colombia",
    "23000": "Córdoba",
    "25000": "Cundinamarca",
    "94000": "Guainía",
    "95000": "Guaviare",
    "41000": "Huila",
    "44000": "La Guajira",
    "47000": "Magdalena",
    "50000": "Meta",
    "52000": "Nariño",
    "54000": "Norte De Santander",
    "00000": "Otros Paises",
    "86000": "Putumayo",
    "63000": "Quindío",
    "66000": "Risaralda",
    "88000": "San Andrés, Providencia y Santa Catalina",
    "668000": "Santander",
    "70000": "Sucre",
    "73000": "Tolima",
    "76000": "Valle del Cauca",
    "97000": "Vaupés",
    "99000": "Vichada",
}

# Estado del proceso (de ServletComboEstado.select). El formulario espera
# el ID numérico, NO el texto visible. No todas las modalidades exponen
# todos los estados.
ESTADO_SECOP1: dict[str, str] = {
    "1": "Borrador",
    "2": "Convocado",
    "3": "Adjudicado",
    "4": "Celebrado",
    "5": "Liquidado",
    "6": "Descartado",
    "7": "Terminado Anormalmente después de Convocado",
    "8": "Terminado sin Liquidar",
}

# Rango de cuantía (select#cuantia del formulario)
CUANTIA_SECOP1: dict[str, str] = {
    "0": "Cualquier Valor",
    "1": "$0 - $100.000.000",
    "2": "$100.000.001 - $300.000.000",
    "3": "$300.000.001 - $500.000.000",
    "4": "$500.000.001 - $1.000.000.000",
    "5": "Más de $1.000.000.000",
}


def resolver_codigo(mapa: dict[str, str], valor: Optional[str]) -> Optional[str]:
    """Traduce un texto legible al código que espera el portal.

    Acepta indistintamente el código (``'13'``) o el nombre visible
    (``'Contratación Mínima Cuantía'``, ``'mínima'``). La comparación por
    nombre es *case-insensitive* y por subcadena, de modo que
    ``'minima cuantia'`` también resuelve.

    Args:
        mapa:  Uno de ``MODALIDAD_SECOP1`` / ``DEPARTAMENTO_SECOP1`` / ...
        valor: Código o nombre a resolver (``None`` = omitir el filtro).

    Returns:
        El código correspondiente, o ``None`` si ``valor`` era ``None``.
        Si no se logra resolver, devuelve ``valor`` sin tocar para que el
        portal decida (y el llamador registre la advertencia).
    """
    if valor is None:
        return None

    valor = str(valor).strip()
    if not valor:
        return None

    # Ya es un código válido
    if valor in mapa:
        return valor

    def _norm(s: str) -> str:
        tabla = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
        return " ".join(s.translate(tabla).lower().split())

    objetivo = _norm(valor)

    # Coincidencia exacta por nombre
    for codigo, nombre in mapa.items():
        if _norm(nombre) == objetivo:
            return codigo

    # Coincidencia parcial por nombre
    for codigo, nombre in mapa.items():
        if objetivo in _norm(nombre):
            return codigo

    return valor


# ────────────────────────────────────────────────────────────
# 6. SELECTORES DEL FORMULARIO (ruta Selenium — fallback)
#    IDs verificados contra el DOM real de inicioConsulta.do.
# ────────────────────────────────────────────────────────────

# --- Campos de texto ---
SEL_NUMERO_PROCESO: str = "input#numeroProceso"
SEL_ENTIDAD: str = "input#findEntidad"          # autocompletar visible
SEL_ENTIDAD_HIDDEN: str = "input#entidad"       # código interno

# --- Campos de fecha (formato dd/MM/yyyy) ---
SEL_FECHA_INICIO: str = "input#fechaInicial"
SEL_FECHA_FIN: str = "input#fechaFinal"

# --- Selects (dropdowns) ---
SEL_OBJETO: str = "select#objeto"               # Producto o Servicio (UNSPSC)
SEL_MODALIDAD: str = "select#tipoProceso"       # se llena por JS
SEL_DEPARTAMENTO: str = "select#selDepartamento"  # se llena por JS
SEL_MUNICIPIO: str = "select#selMunicipio"      # carga AJAX tras depto
SEL_ESTADO: str = "select#estado"               # carga AJAX tras modalidad
SEL_CUANTIA: str = "select#cuantia"
SEL_REGISTROS_PAGINA: str = "select[name='registrosXPagina']"

# --- Botón buscar: <a href="javascript:enviarParametros()"><img ...></a> ---
SEL_BTN_BUSCAR: str = "img#ctl00_ContentPlaceHolder1_imgBuscar"
SEL_BTN_BUSCAR_LINK: str = "a#ctl00_ContentPlaceHolder1_btnBuscar"


# ────────────────────────────────────────────────────────────
# 7. SELECTORES DE RESULTADOS E IFRAME
# ────────────────────────────────────────────────────────────

# La página contenedora incrusta los resultados en este iframe.
IFRAME_NAME: str = "detalle"
IFRAME_XPATH: str = "//iframe[@name='detalle']"

# La tabla de resultados NO tiene clase CSS en producción: se localiza
# por heurística (la tabla con más filas). Se conservan los selectores
# históricos como primer intento.
SEL_TABLA_RESULTADOS: str = "table.tbl_resulados"   # typo original del portal
SEL_TABLA_RESULTADOS_FALLBACK: str = "table"

# Enlace de detalle: es un javascript:consultaProceso('<id>'), no un href.
PATRON_ID_PROCESO: str = r"consultaProceso\(\s*['\"]([^'\"]+)['\"]\s*\)"


# ────────────────────────────────────────────────────────────
# 8. ESQUEMA CANÓNICO — TABLA DE RESULTADOS SECOP I
#    Orden real de las 9 columnas de resultadosConsulta.do:
#      0 ∇ (ordinal) | 1 Número de Proceso | 2 Tipo de Proceso |
#      3 Estado | 4 Entidad | 5 Objeto |
#      6 Departamento y Municipio de Ejecución | 7 Cuantía |
#      8 Fecha(dd-mm-aaaa)
# ────────────────────────────────────────────────────────────

# Mapeo posicional índice de columna → nombre canónico.
COLUMNAS_TABLA_SECOP1: dict[int, str] = {
    0: "orden",
    1: "numero_proceso",
    2: "modalidad",
    3: "estado",
    4: "entidad",
    5: "objeto_contrato",
    6: "ubicacion_ejecucion",
    7: "cuantia",
    8: "fecha_texto",
}

# Esquema final que produce parser.py para la ruta SECOP I.
COLUMNAS_RESULTADO: list[str] = [
    "numero_proceso",
    "id_proceso",
    "entidad",
    "objeto_contrato",
    "modalidad",
    "estado",
    "departamento",
    "municipio",
    "cuantia",
    "fecha_apertura",
    "fecha_etiqueta",
    "url_detalle",
]

# Columnas numéricas que requieren conversión monetaria.
# Incluye tanto el esquema SECOP I como el de la API SECOP II.
COLUMNAS_MONETARIAS: list[str] = [
    # SECOP I
    "cuantia",
    "valor_estimado",
    "valor_adjudicado",
    "valor_contrato",
    # API SECOP II
    "valor_del_contrato",
    "valor_pagado",
    "valor_facturado",
    "valor_pendiente_de",
    "valor_amortizado",
    "saldo_cdp",
    "saldo_vigencia",
]

# Columnas de fecha que requieren parseo.
COLUMNAS_FECHA: list[str] = [
    # SECOP I
    "fecha_apertura",
    "fecha_cierre",
    "fecha_adjudicacion",
    "fecha_contrato",
    # API SECOP II
    "fecha_de_inicio_del_contrato",
    "fecha_de_fin_del_contrato",
    "fecha_de_firma",
]


# ────────────────────────────────────────────────────────────
# 9. COLUMNAS DEL DETALLE INDIVIDUAL DE PROCESO
# ────────────────────────────────────────────────────────────

COLUMNAS_DETALLE: list[str] = [
    "numero_proceso",
    "id_proceso",
    "entidad",
    "objeto_contrato",
    "modalidad",
    "estado",
    "fecha_apertura",
    "fecha_cierre",
    "fecha_adjudicacion",
    "valor_estimado",
    "valor_adjudicado",
    "valor_contrato",
    "numero_contrato",
    "tipo_contrato",
    "estado_contrato",
    "proveedor",
    "nit_proveedor",
    "departamento",
    "municipio",
    "url_detalle",
]


# ────────────────────────────────────────────────────────────
# 10. TIMEOUTS, REINTENTOS Y CORTESÍA CON EL WAF
# ────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT: int = 30        # WebDriverWait (Selenium)
HTTP_TIMEOUT: int = 90           # requests: el portal puede tardar
PAGE_LOAD_WAIT: float = 3.0      # espera tras clic de paginación
MAX_RETRIES: int = 3             # reintentos por operación
RETRY_BACKOFF: float = 2.0       # factor de backoff exponencial
MAX_PAGES: int = 200             # límite de seguridad de paginación
RECAPTCHA_WAIT: int = 120        # espera para resolución manual

# contratos.gov.co está detrás de un WAF (Zenedge) que responde 403
# "Access to the website is blocked" ante ráfagas de peticiones. Estos
# valores mantienen el ritmo por debajo del umbral observado.
HTTP_DELAY: float = float(os.getenv("SECOP_DELAY", "2.5"))   # s entre páginas
HTTP_DELAY_BLOQUEO: float = 90.0     # espera tras detectar un bloqueo
HTTP_MAX_BLOQUEOS: int = 2           # bloqueos tolerados antes de abortar

# Marcadores de la página de bloqueo del WAF.
MARCADORES_BLOQUEO: tuple[str, ...] = (
    "access to the website is blocked",
    "your ip address",
    "__zenedge",
)


# ────────────────────────────────────────────────────────────
# 11. CABECERAS HTTP
#     Un User-Agent de navegador real y el juego completo de
#     cabeceras reduce mucho la probabilidad de 403.
# ────────────────────────────────────────────────────────────

HTTP_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

HTTP_HEADERS: dict[str, str] = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="140", "Google Chrome";v="140", "Not=A?Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


# ────────────────────────────────────────────────────────────
# 12. CHROME DRIVER OPTIONS (ruta Selenium — fallback)
# ────────────────────────────────────────────────────────────

CHROME_HEADLESS: bool = os.getenv("SECOP_HEADLESS", "0") == "1"

# Rutas habituales del binario de Chrome por sistema operativo.
_CANDIDATOS_CHROME: dict[str, tuple[str, ...]] = {
    "win32": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
        ),
    ),
    "darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "linux": (
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ),
}


def detectar_binario_chrome() -> Optional[str]:
    """Localiza el ejecutable de Chrome en el sistema actual.

    Antes se fijaba ``/usr/bin/google-chrome-stable`` a fuego, lo que
    hacía imposible usar Selenium fuera de Linux. Ahora se resuelve así:

      1. Variable de entorno ``CHROME_BINARY`` (override explícito).
      2. Rutas habituales del sistema operativo en curso.
      3. ``PATH`` (``chrome`` / ``chromium`` / ...).

    Returns:
        Ruta absoluta al binario, o ``None`` para que Selenium use su
        propia detección automática.
    """
    override = os.getenv("CHROME_BINARY")
    if override and Path(override).exists():
        return override

    plataforma = "linux"
    if sys.platform.startswith("win"):
        plataforma = "win32"
    elif sys.platform == "darwin":
        plataforma = "darwin"

    for ruta in _CANDIDATOS_CHROME.get(plataforma, ()):
        if ruta and Path(ruta).exists():
            return ruta

    for nombre in ("google-chrome-stable", "google-chrome", "chromium", "chrome"):
        encontrado = shutil.which(nombre)
        if encontrado:
            return encontrado

    return None


CHROME_ARGUMENTS: list[str] = [
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--window-size=1920,1080",
    "--lang=es-CO",
]

CHROME_USER_AGENT: str = HTTP_USER_AGENT

# Nota: no se desactivan las imágenes porque el portal usa un <img> como
# botón de búsqueda y necesita renderizarse para poder hacerle clic.
CHROME_PREFS: dict = {
    "intl.accept_languages": "es-CO,es",
}


# ────────────────────────────────────────────────────────────
# 13. API DE DATOS ABIERTOS (SECOP II)
# ────────────────────────────────────────────────────────────

SOCRATA_BASE_URL: str = "https://www.datos.gov.co/resource"
SOCRATA_DATASET_CONTRATOS: str = "jbjy-vk9h"   # SECOP II — Contratos
SOCRATA_DATASET_PROCESOS: str = "p6dx-8zbt"    # SECOP II — Procesos

# Un app token evita el throttling agresivo de Socrata para anónimos.
SOCRATA_APP_TOKEN: Optional[str] = os.getenv("SOCRATA_APP_TOKEN") or None

# Socrata admite $limit hasta 50 000, pero páginas grandes agotan el
# timeout con frecuencia. 20 000 es un compromiso estable.
SOCRATA_PAGE_SIZE: int = int(os.getenv("SOCRATA_PAGE_SIZE", "20000"))
SOCRATA_TIMEOUT: int = 180


# ────────────────────────────────────────────────────────────
# 13b. FUENTES PARA LA EXPORTACIÓN A PDF
#      fpdf2 necesita una TrueType con soporte Unicode: sus fuentes
#      internas solo cubren Latin-1 y los informes llevan comillas
#      tipográficas y rayas largas.
# ────────────────────────────────────────────────────────────

_FUENTES_PDF: list[tuple[str, str]] = [
    # Linux (Debian/Ubuntu: contenedores y Streamlit Community Cloud)
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf",
     "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    # Windows
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\verdana.ttf", r"C:\Windows\Fonts\verdanab.ttf"),
    # macOS
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]


def resolver_fuente_pdf() -> Optional[tuple[str, str]]:
    """Localiza una fuente TrueType Unicode disponible en el sistema.

    Se puede forzar con la variable de entorno ``PDF_FONT_DIR``, que debe
    contener ``DejaVuSans.ttf`` y ``DejaVuSans-Bold.ttf``.

    Returns:
        Tupla ``(ruta_regular, ruta_negrita)``, o ``None`` si no hay
        ninguna fuente utilizable (entonces se deshabilita el PDF en vez
        de dejar que reviente la exportación).
    """
    candidatas = list(_FUENTES_PDF)

    dir_env = os.getenv("PDF_FONT_DIR")
    if dir_env:
        candidatas.insert(0, (
            str(Path(dir_env) / "DejaVuSans.ttf"),
            str(Path(dir_env) / "DejaVuSans-Bold.ttf"),
        ))

    for regular, negrita in candidatas:
        if Path(regular).exists():
            return regular, (negrita if Path(negrita).exists() else regular)

    return None


# ────────────────────────────────────────────────────────────
# 14. EXPORTACIÓN
# ────────────────────────────────────────────────────────────

CSV_SEPARATOR: str = ","
CSV_ENCODING: str = "utf-8-sig"      # BOM para Excel en español
PARQUET_ENGINE: str = "pyarrow"


# ────────────────────────────────────────────────────────────
# 15. DATACLASS DE PARÁMETROS DE BÚSQUEDA
# ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchParams:
    """Parámetros de búsqueda del formulario de SECOP I.

    Todos los campos son opcionales. Si un campo es ``None`` el scraper
    no aplica ese filtro.

    Los campos ``modalidad``, ``departamento``, ``estado`` y ``cuantia``
    aceptan tanto el código del portal como el nombre legible: se
    normalizan con ``resolver_codigo`` contra los mapas de esta sección.

    Attributes:
        palabra_clave:  Texto libre. **SECOP I no tiene búsqueda por
                        texto libre**, así que se aplica como filtro
                        local sobre la columna *Objeto* ya descargada.
                        En la API sí viaja al servidor.
        numero_proceso: Número específico de un proceso.
        entidad:        Nombre (parcial) de la entidad compradora.
        fecha_inicio:   Fecha desde (``dd/MM/yyyy``).
        fecha_fin:      Fecha hasta  (``dd/MM/yyyy``).
        objeto:         Código UNSPSC del dropdown *Producto o Servicio*.
        modalidad:      Código o nombre de la modalidad.
        departamento:   Código o nombre del departamento.
        municipio:      Código del municipio (``'0'`` = todos).
        estado:         ID o nombre del estado del proceso.
        cuantia:        Código del rango de cuantía.
        max_pages:      Límite de páginas a recorrer.
    """

    palabra_clave: Optional[str] = None
    numero_proceso: Optional[str] = None
    entidad: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    objeto: Optional[str] = None
    modalidad: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    estado: Optional[str] = None
    cuantia: Optional[str] = None
    max_pages: int = MAX_PAGES

    def normalizada(self) -> "SearchParams":
        """Devuelve una copia con los códigos del portal ya resueltos."""
        from dataclasses import replace

        return replace(
            self,
            modalidad=resolver_codigo(MODALIDAD_SECOP1, self.modalidad),
            departamento=resolver_codigo(DEPARTAMENTO_SECOP1, self.departamento),
            estado=resolver_codigo(ESTADO_SECOP1, self.estado),
            cuantia=resolver_codigo(CUANTIA_SECOP1, self.cuantia),
        )


# ────────────────────────────────────────────────────────────
# 15b. CONFIGURACIONES PREDETERMINADAS
# ────────────────────────────────────────────────────────────

VALOR_DEPTO_SANTANDER: str = "668000"
VALOR_MODALIDAD_MINIMA_CUANTIA: str = "13"
VALOR_ESTADO_CELEBRADO: str = "4"

# Mantenido por compatibilidad con código que lo importaba por nombre.
TEXTO_ESTADO_CELEBRADO: str = "Celebrado"

SEARCH_SANTANDER_MINIMA_CELEBRADO = SearchParams(
    departamento=VALOR_DEPTO_SANTANDER,
    modalidad=VALOR_MODALIDAD_MINIMA_CUANTIA,
    estado=VALOR_ESTADO_CELEBRADO,
)


# ────────────────────────────────────────────────────────────
# 16. CONFIGURACIÓN DE LOGGING ESTRUCTURADO
# ────────────────────────────────────────────────────────────

LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(funcName)-25s | %(message)s"
)
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL: int = logging.DEBUG if os.getenv("SECOP_DEBUG", "0") == "1" else logging.INFO
LOG_FILE: Path = LOG_DIR / "secop_pipeline.log"


def setup_logging() -> None:
    """Configura logging con salida a consola **y** a archivo rotativo.

    Se invoca una sola vez desde el punto de entrada. Usa
    ``RotatingFileHandler`` para evitar archivos de log gigantes.
    """
    from logging.handlers import RotatingFileHandler

    configurar_consola_utf8()

    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # Evitar handlers duplicados en re-imports
    if root_logger.handlers:
        return

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # El log a disco es opcional: en despliegues de solo lectura basta
    # con la salida por consola, que el PaaS ya recoge.
    if _LOGS_DISPONIBLES:
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError:
            root_logger.warning(
                "No se pudo abrir %s; se registrará solo por consola.", LOG_FILE
            )

    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
