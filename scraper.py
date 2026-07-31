"""
scraper.py — Extracción de la tabla de resultados de SECOP I (contratos.gov.co).

Ofrece **dos transportes** para el mismo objetivo, con el mismo contrato
de salida (lista de HTML crudo por página):

  1. **HTTP directo** (vía preferente, ``ejecutar_scraping_http``).
     El portal renderiza la tabla dentro de un ``<iframe>`` que apunta a
     ``resultadosConsulta.do`` con todos los filtros en la query string.
     Ese endpoint acepta GET y **no exige token de reCAPTCHA**, así que
     no hace falta navegador. Es un orden de magnitud más rápido y
     estable que Selenium.

  2. **Selenium** (respaldo, ``ejecutar_scraping_selenium``).
     Rellena el formulario en un Chrome real. Útil si el WAF empieza a
     exigir ejecución de JavaScript. Tras enviar el formulario reutiliza
     el mismo endpoint del iframe para paginar.

Notas sobre el portal (verificadas en producción):
  • **No existe campo de búsqueda por texto libre.** ``palabra_clave`` se
    aplica como filtro local sobre la columna *Objeto* ya descargada.
  • ``estado`` es un **ID numérico** (4 = Celebrado), no el texto visible.
  • La paginación se controla con el parámetro ``paginaObjetivo``.
  • El sitio está tras un WAF (Zenedge) que responde 403 ante ráfagas:
    ver ``SECOP_DELAY`` y ``SecopBlockedError``.

Principios de diseño:
  • Este módulo devuelve **HTML crudo** y nunca lo interpreta; eso le
    corresponde a ``parser.py``.
  • Los errores se convierten en excepciones tipadas (``exceptions.py``).
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

from config import (
    CAMPO_TOTAL_RESULTADOS,
    CHROME_ARGUMENTS,
    CHROME_HEADLESS,
    CHROME_PREFS,
    CHROME_USER_AGENT,
    DEFAULT_TIMEOUT,
    HTTP_DELAY,
    HTTP_DELAY_BLOQUEO,
    HTTP_HEADERS,
    HTTP_MAX_BLOQUEOS,
    HTTP_TIMEOUT,
    MARCADORES_BLOQUEO,
    MAX_RETRIES,
    PAGE_LOAD_WAIT,
    PARAM_ACTION,
    PARAM_CUANTIA,
    PARAM_DEPARTAMENTO,
    PARAM_DESDE_FORMULARIO,
    PARAM_ENTIDAD,
    PARAM_ESTADO,
    PARAM_FECHA_FINAL,
    PARAM_FECHA_INICIAL,
    PARAM_FIND_ENTIDAD,
    PARAM_MODALIDAD,
    PARAM_MUNICIPIO,
    PARAM_NUMERO_PROCESO,
    PARAM_OBJETO,
    PARAM_PAGINA,
    PARAM_RECAPTCHA,
    PARAM_REGISTROS_PAGINA,
    REGISTROS_POR_PAGINA,
    RETRY_BACKOFF,
    SECOP_CONSULTA_URL,
    SECOP_RESULTADOS_DATA_URL,
    SEL_BTN_BUSCAR,
    SEL_BTN_BUSCAR_LINK,
    SEL_CUANTIA,
    SEL_DEPARTAMENTO,
    SEL_ENTIDAD,
    SEL_ESTADO,
    SEL_FECHA_FIN,
    SEL_FECHA_INICIO,
    SEL_MODALIDAD,
    SEL_MUNICIPIO,
    SEL_NUMERO_PROCESO,
    SEL_OBJETO,
    SearchParams,
    detectar_binario_chrome,
)
from exceptions import (
    SecopBlockedError,
    SecopEmptyTableError,
    SecopFormError,
    SecopIframeError,
    SecopRecaptchaError,
    SecopTimeoutError,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# 1. SESIÓN HTTP
# ════════════════════════════════════════════════════════════


def crear_sesion() -> requests.Session:
    """Crea una sesión HTTP con cabeceras de navegador real.

    El WAF del portal rechaza clientes sin ``User-Agent`` creíble o sin
    el juego habitual de cabeceras ``Accept*`` / ``sec-ch-ua``.

    Returns:
        Sesión de ``requests`` lista para usar.
    """
    sesion = requests.Session()
    sesion.headers.update(HTTP_HEADERS)
    return sesion


def calentar_sesion(sesion: requests.Session) -> None:
    """Visita el formulario para obtener las cookies de sesión.

    ``resultadosConsulta.do`` exige un ``JSESSIONID`` válido; sin la
    visita previa a ``inicioConsulta.do`` el portal responde con una
    página vacía o un redirect.

    Raises:
        SecopBlockedError: Si el WAF bloquea ya en el calentamiento.
    """
    logger.debug("Calentando sesión en %s", SECOP_CONSULTA_URL)
    respuesta = _get(sesion, SECOP_CONSULTA_URL, referer=None)
    logger.debug(
        "Sesión iniciada (cookies: %s).", ", ".join(sesion.cookies.keys()) or "ninguna"
    )
    del respuesta


# ════════════════════════════════════════════════════════════
# 2. DETECCIÓN DEL BLOQUEO DEL WAF
# ════════════════════════════════════════════════════════════


def _es_bloqueo_waf(respuesta: requests.Response) -> bool:
    """Detecta la página de bloqueo del WAF (Zenedge).

    Se identifica por el 403 combinado con los marcadores textuales de
    la página *"Access to the website is blocked"*.
    """
    if respuesta.status_code not in (403, 406, 429):
        return False

    cuerpo = respuesta.text[:4000].lower()
    return any(marcador in cuerpo for marcador in MARCADORES_BLOQUEO)


def _get(
    sesion: requests.Session,
    url: str,
    params: Optional[dict] = None,
    referer: Optional[str] = SECOP_CONSULTA_URL,
) -> requests.Response:
    """GET con reintentos, backoff y manejo del bloqueo del WAF.

    Args:
        sesion:  Sesión activa.
        url:     URL destino.
        params:  Query string.
        referer: Cabecera ``Referer`` (el portal la revisa).

    Returns:
        La respuesta HTTP, ya con ``encoding='utf-8'``.

    Raises:
        SecopBlockedError: Si el WAF bloquea de forma persistente.
        SecopTimeoutError: Si se agotan los reintentos por timeout/red.
    """
    cabeceras = {"Referer": referer} if referer else {}
    bloqueos = 0
    ultimo_error: Optional[Exception] = None

    for intento in range(1, MAX_RETRIES + 1):
        try:
            respuesta = sesion.get(
                url,
                params=params,
                headers=cabeceras,
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            ultimo_error = exc
            espera = RETRY_BACKOFF**intento
            logger.warning(
                "Error de red en %s (intento %d/%d): %s. Reintentando en %.1f s.",
                url, intento, MAX_RETRIES, exc, espera,
            )
            time.sleep(espera)
            continue

        if _es_bloqueo_waf(respuesta):
            bloqueos += 1
            if bloqueos > HTTP_MAX_BLOQUEOS:
                raise SecopBlockedError(
                    "El WAF de contratos.gov.co bloqueó la IP de forma "
                    "persistente. Espera unos minutos o sube SECOP_DELAY.",
                    context={"url": url, "status": respuesta.status_code},
                )
            logger.warning(
                "WAF bloqueó la petición (403). Esperando %.0f s antes de "
                "reintentar (bloqueo %d/%d).",
                HTTP_DELAY_BLOQUEO, bloqueos, HTTP_MAX_BLOQUEOS,
            )
            time.sleep(HTTP_DELAY_BLOQUEO)
            continue

        respuesta.encoding = "utf-8"
        return respuesta

    raise SecopTimeoutError(
        f"No se pudo completar la petición tras {MAX_RETRIES} intentos.",
        context={"url": url, "error": str(ultimo_error)},
    )


# ════════════════════════════════════════════════════════════
# 3. CONSTRUCCIÓN DE LOS PARÁMETROS DE CONSULTA
# ════════════════════════════════════════════════════════════


def construir_parametros(params: SearchParams, pagina: int = 1) -> dict[str, str]:
    """Traduce un ``SearchParams`` a la query string del portal.

    El endpoint exige que **todos** los campos estén presentes, aunque
    vayan vacíos: si falta alguno el servidor ignora la consulta y
    devuelve el listado completo.

    Los códigos (modalidad, departamento, estado, cuantía) ya vienen
    resueltos por ``SearchParams.normalizada()``.

    Args:
        params:  Filtros de búsqueda (ya normalizados).
        pagina:  Número de página (1-indexado).

    Returns:
        Diccionario listo para pasar como ``params`` de ``requests``.
    """
    return {
        PARAM_ACTION: "validate_captcha",
        PARAM_CUANTIA: params.cuantia or "0",
        PARAM_DEPARTAMENTO: params.departamento or "",
        PARAM_DESDE_FORMULARIO: "true",
        PARAM_ENTIDAD: "",
        PARAM_ESTADO: params.estado or "",
        PARAM_FECHA_FINAL: params.fecha_fin or "",
        PARAM_FECHA_INICIAL: params.fecha_inicio or "",
        PARAM_FIND_ENTIDAD: params.entidad or "",
        PARAM_RECAPTCHA: "",
        PARAM_MUNICIPIO: params.municipio or "0",
        PARAM_NUMERO_PROCESO: params.numero_proceso or "",
        PARAM_OBJETO: params.objeto or "",
        PARAM_PAGINA: str(pagina),
        PARAM_REGISTROS_PAGINA: str(REGISTROS_POR_PAGINA),
        PARAM_MODALIDAD: params.modalidad or "",
    }


# ════════════════════════════════════════════════════════════
# 4. LECTURA DEL TOTAL DE RESULTADOS
# ════════════════════════════════════════════════════════════

_PATRON_TOTAL_INPUT = re.compile(
    rf"name=['\"]{CAMPO_TOTAL_RESULTADOS}['\"]\s+value=['\"](\d+)['\"]",
    re.IGNORECASE,
)
_PATRON_TOTAL_TEXTO = re.compile(r"([\d.,]+)\s*registros\s+encontrados", re.IGNORECASE)


def extraer_total_resultados(html: str) -> Optional[int]:
    """Lee el número total de procesos que coinciden con la consulta.

    Busca primero el input oculto ``totalResultados`` y, como respaldo,
    el texto *"N registros encontrados"*.

    Returns:
        Total de registros, o ``None`` si no se pudo determinar.
    """
    coincidencia = _PATRON_TOTAL_INPUT.search(html)
    if coincidencia:
        return int(coincidencia.group(1))

    coincidencia = _PATRON_TOTAL_TEXTO.search(html)
    if coincidencia:
        crudo = coincidencia.group(1).replace(".", "").replace(",", "")
        if crudo.isdigit():
            return int(crudo)

    return None


# ════════════════════════════════════════════════════════════
# 5. SCRAPING VÍA HTTP (VÍA PREFERENTE)
# ════════════════════════════════════════════════════════════


def descargar_pagina(
    sesion: requests.Session,
    params: SearchParams,
    pagina: int,
) -> str:
    """Descarga el HTML de una página de resultados.

    Args:
        sesion: Sesión ya calentada.
        params: Filtros normalizados.
        pagina: Número de página (1-indexado).

    Returns:
        HTML crudo de la tabla de resultados.
    """
    respuesta = _get(
        sesion,
        SECOP_RESULTADOS_DATA_URL,
        params=construir_parametros(params, pagina),
    )
    return respuesta.text


def ejecutar_scraping_http(
    params: SearchParams,
    sesion: Optional[requests.Session] = None,
) -> list[str]:
    """Recorre todas las páginas de resultados usando HTTP directo.

    Flujo:
      1. Calentar la sesión (cookies).
      2. Descargar la página 1 y leer ``totalResultados``.
      3. Calcular cuántas páginas hay y descargarlas con pausas.

    Args:
        params: Filtros de búsqueda (se normalizan internamente).
        sesion: Sesión reutilizable (opcional).

    Returns:
        Lista de HTML, uno por página de resultados.

    Raises:
        SecopEmptyTableError: Si la consulta no devuelve registros.
        SecopBlockedError:    Si el WAF bloquea de forma persistente.
    """
    params = params.normalizada()
    sesion_propia = sesion is None
    sesion = sesion or crear_sesion()

    try:
        calentar_sesion(sesion)

        logger.info("[HTTP] Descargando página 1...")
        primera = descargar_pagina(sesion, params, 1)

        total = extraer_total_resultados(primera)
        if total == 0:
            raise SecopEmptyTableError(
                "La consulta no devolvió registros.",
                context={"filtros": str(params)},
            )

        if total is None:
            logger.warning(
                "No se pudo leer el total de resultados; se asume una sola página."
            )
            return [primera]

        paginas_totales = max(1, math.ceil(total / REGISTROS_POR_PAGINA))
        paginas_a_bajar = min(paginas_totales, params.max_pages)

        logger.info(
            "[HTTP] %d registros encontrados → %d páginas (se descargarán %d).",
            total, paginas_totales, paginas_a_bajar,
        )

        paginas_html = [primera]

        for numero in range(2, paginas_a_bajar + 1):
            time.sleep(HTTP_DELAY)
            logger.info("[HTTP] Descargando página %d/%d...", numero, paginas_a_bajar)
            paginas_html.append(descargar_pagina(sesion, params, numero))

        logger.info("[HTTP] Descarga completada: %d páginas.", len(paginas_html))
        return paginas_html

    finally:
        if sesion_propia:
            sesion.close()


# ════════════════════════════════════════════════════════════
# 6. RUTA SELENIUM (RESPALDO)
# ════════════════════════════════════════════════════════════


def crear_driver():
    """Crea una instancia configurada de Chrome WebDriver.

    A diferencia de la versión anterior, el binario de Chrome se
    **detecta según el sistema operativo** en vez de fijar una ruta de
    Linux, de modo que funciona igual en Windows, macOS y Linux.
    Se puede forzar con la variable de entorno ``CHROME_BINARY``.

    Returns:
        Instancia activa de ``webdriver.Chrome``.

    Raises:
        SecopFormError: Si Chrome o ChromeDriver no están disponibles.
    """
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service

    options = ChromeOptions()

    for arg in CHROME_ARGUMENTS:
        options.add_argument(arg)

    options.add_argument(f"--user-agent={CHROME_USER_AGENT}")

    if CHROME_HEADLESS:
        options.add_argument("--headless=new")
        logger.info("Modo headless activado.")

    options.add_experimental_option("prefs", CHROME_PREFS)

    binario = detectar_binario_chrome()
    if binario:
        options.binary_location = binario
        logger.debug("Binario de Chrome: %s", binario)
    else:
        logger.warning(
            "No se encontró Chrome en las rutas habituales; se deja que "
            "Selenium lo detecte. Define CHROME_BINARY si falla."
        )

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        try:
            # Selenium 4.6+ resuelve el driver solo (Selenium Manager).
            driver = webdriver.Chrome(options=options)
        except WebDriverException:
            from webdriver_manager.chrome import ChromeDriverManager

            servicio = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=servicio, options=options)
    except Exception as exc:
        raise SecopFormError(
            "No se pudo inicializar Chrome WebDriver.",
            context={"error": str(exc), "binario": binario},
        ) from exc

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": "Object.defineProperty(navigator, 'webdriver', "
                      "{get: () => undefined})"
        },
    )

    logger.info("WebDriver de Chrome inicializado correctamente.")
    return driver


def cerrar_driver(driver) -> None:
    """Cierra el WebDriver de forma segura."""
    if driver is None:
        return
    try:
        driver.quit()
        logger.info("WebDriver cerrado correctamente.")
    except Exception as exc:  # noqa: BLE001 - nunca debe romper el finally
        logger.warning("Error al cerrar el WebDriver: %s", exc)


def _hay_reto_recaptcha(driver) -> bool:
    """Detecta un reto de reCAPTCHA **visible**.

    El portal usa reCAPTCHA **v3**, que es invisible y siempre inyecta un
    iframe y el distintivo ``.grecaptcha-badge``. La versión anterior de
    esta función buscaba cualquier iframe de recaptcha, así que daba
    positivo *siempre*, esperaba 120 s y abortaba el scraping.

    Aquí solo se considera reto real un widget interactivo visible
    (``api2/bframe``, el checkbox de v2 o el texto "No soy un robot").
    """
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    selectores = [
        (By.CSS_SELECTOR, "iframe[src*='api2/bframe']"),
        (By.CSS_SELECTOR, "div.g-recaptcha > div"),
        (By.XPATH, "//*[contains(text(), 'No soy un robot')]"),
    ]

    for by, selector in selectores:
        try:
            for elemento in driver.find_elements(by, selector):
                if elemento.is_displayed():
                    return True
        except WebDriverException:
            continue

    return False


def manejar_recaptcha(driver, timeout: int = 0) -> None:
    """Pausa la ejecución si aparece un reto de reCAPTCHA visible.

    Args:
        driver:  WebDriver activo.
        timeout: Segundos de espera para resolución manual. Con ``0``
                 (por defecto) falla de inmediato en vez de bloquear.

    Raises:
        SecopRecaptchaError: Si el reto persiste tras el timeout.
    """
    if not _hay_reto_recaptcha(driver):
        return

    if timeout <= 0:
        raise SecopRecaptchaError(
            "reCAPTCHA interactivo detectado.",
            context={"url": driver.current_url},
        )

    logger.warning(
        "reCAPTCHA detectado. Esperando resolución manual (%d s)...", timeout
    )
    inicio = time.monotonic()
    while time.monotonic() - inicio < timeout:
        time.sleep(2)
        if not _hay_reto_recaptcha(driver):
            logger.info("reCAPTCHA resuelto.")
            return

    raise SecopRecaptchaError(
        f"reCAPTCHA no resuelto tras {timeout} segundos.",
        context={"url": driver.current_url},
    )


def _rellenar_campo(driver, css: str, valor: Optional[str]) -> None:
    """Escribe en un campo de texto si el valor no es ``None``."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    if not valor:
        return

    try:
        elemento = driver.find_element(By.CSS_SELECTOR, css)
        elemento.clear()
        elemento.send_keys(valor)
        logger.debug("Campo '%s' → '%s'", css, valor)
    except WebDriverException as exc:
        logger.warning("No se pudo rellenar '%s': %s", css, exc)


def _seleccionar_por_valor(driver, css: str, valor: Optional[str]) -> None:
    """Selecciona una opción de un ``<select>`` por su atributo ``value``."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    if not valor:
        return

    try:
        select = Select(driver.find_element(By.CSS_SELECTOR, css))
        select.select_by_value(str(valor))
        logger.debug("Dropdown '%s' → value='%s'", css, valor)
    except WebDriverException as exc:
        logger.warning(
            "No se pudo seleccionar value=%r en '%s': %s", valor, css, exc
        )


def _esperar_opciones(driver, css: str, timeout: int = 15) -> bool:
    """Espera a que un ``<select>`` cargue sus opciones por AJAX/JS."""
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: len(Select(d.find_element(By.CSS_SELECTOR, css)).options) > 1
        )
        return True
    except (TimeoutException, WebDriverException):
        logger.warning("El dropdown '%s' no cargó opciones en %d s.", css, timeout)
        return False


def rellenar_formulario(driver, params: SearchParams) -> None:
    """Rellena el formulario de búsqueda de SECOP I.

    ``params`` debe venir ya normalizado (códigos resueltos).

    Raises:
        SecopFormError:      Si el formulario no carga.
        SecopRecaptchaError: Si aparece un reto de reCAPTCHA visible.
    """
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    logger.info("Navegando a %s", SECOP_CONSULTA_URL)
    driver.get(SECOP_CONSULTA_URL)

    try:
        WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SEL_FECHA_INICIO))
        )
    except TimeoutException as exc:
        raise SecopFormError(
            "El formulario de consulta no cargó.",
            context={"url": driver.current_url},
        ) from exc

    manejar_recaptcha(driver)

    # Los dropdowns de modalidad y departamento se llenan por JavaScript.
    _esperar_opciones(driver, SEL_MODALIDAD)
    _esperar_opciones(driver, SEL_DEPARTAMENTO)

    _rellenar_campo(driver, SEL_NUMERO_PROCESO, params.numero_proceso)
    _rellenar_campo(driver, SEL_ENTIDAD, params.entidad)
    _rellenar_campo(driver, SEL_FECHA_INICIO, params.fecha_inicio)
    _rellenar_campo(driver, SEL_FECHA_FIN, params.fecha_fin)

    _seleccionar_por_valor(driver, SEL_OBJETO, params.objeto)
    _seleccionar_por_valor(driver, SEL_MODALIDAD, params.modalidad)
    _seleccionar_por_valor(driver, SEL_DEPARTAMENTO, params.departamento)
    _seleccionar_por_valor(driver, SEL_CUANTIA, params.cuantia)

    if params.municipio:
        time.sleep(2.0)  # el municipio carga por AJAX tras elegir departamento
        _seleccionar_por_valor(driver, SEL_MUNICIPIO, params.municipio)

    if params.estado:
        _esperar_opciones(driver, SEL_ESTADO)
        _seleccionar_por_valor(driver, SEL_ESTADO, params.estado)

    logger.info(
        "Formulario rellenado: modalidad=%r, departamento=%r, estado=%r, "
        "fechas=%s→%s",
        params.modalidad, params.departamento, params.estado,
        params.fecha_inicio, params.fecha_fin,
    )


def enviar_formulario(driver) -> None:
    """Hace clic en *Buscar* y espera la página de resultados."""
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    for by, selector in (
        (By.CSS_SELECTOR, SEL_BTN_BUSCAR),
        (By.CSS_SELECTOR, SEL_BTN_BUSCAR_LINK),
    ):
        try:
            boton = driver.find_element(by, selector)
            driver.execute_script("arguments[0].click();", boton)
            logger.info("Formulario enviado.")
            break
        except WebDriverException:
            continue
    else:
        # El botón es un <a href="javascript:enviarParametros()">.
        try:
            driver.execute_script("enviarParametros();")
            logger.info("Formulario enviado vía enviarParametros().")
        except WebDriverException as exc:
            raise SecopFormError(
                "No se encontró forma de enviar el formulario.",
                context={"url": driver.current_url},
            ) from exc

    time.sleep(PAGE_LOAD_WAIT)
    manejar_recaptcha(driver)


def _url_iframe_resultados(driver) -> str:
    """Obtiene la URL del iframe que contiene la tabla de resultados.

    Es la misma que usa la ruta HTTP, con todos los filtros ya resueltos
    por el portal, así que sirve para paginar sin volver al formulario.

    Raises:
        SecopIframeError: Si no se encuentra el iframe.
    """
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By

    try:
        for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
            src = iframe.get_attribute("src") or ""
            if "resultadosConsulta.do" in src:
                return src
    except WebDriverException as exc:
        raise SecopIframeError(
            "Error buscando el iframe de resultados.",
            context={"url": driver.current_url},
        ) from exc

    raise SecopIframeError(
        "No se encontró el iframe de resultados.",
        context={"url": driver.current_url},
    )


def ejecutar_scraping_selenium(
    params: SearchParams,
    driver=None,
    cerrar_al_final: bool = True,
) -> list[str]:
    """Recorre los resultados usando un navegador real.

    Se usa como respaldo cuando la ruta HTTP falla. Tras enviar el
    formulario reutiliza el endpoint del iframe para paginar, que es más
    fiable que pelearse con los controles de paginación.

    Args:
        params:          Filtros de búsqueda.
        driver:          WebDriver existente (opcional).
        cerrar_al_final: Si cerrar el driver al terminar.

    Returns:
        Lista de HTML, uno por página de resultados.
    """
    params = params.normalizada()
    driver_propio = driver is None
    if driver_propio:
        driver = crear_driver()

    try:
        rellenar_formulario(driver, params)
        enviar_formulario(driver)

        url_base = _url_iframe_resultados(driver)
        logger.debug("URL del iframe de resultados: %s", url_base)

        driver.get(url_base)
        time.sleep(PAGE_LOAD_WAIT)
        primera = driver.page_source

        total = extraer_total_resultados(primera)
        if total == 0:
            raise SecopEmptyTableError(
                "La consulta no devolvió registros.",
                context={"filtros": str(params)},
            )

        if total is None:
            return [primera]

        paginas_totales = max(1, math.ceil(total / REGISTROS_POR_PAGINA))
        paginas_a_bajar = min(paginas_totales, params.max_pages)
        logger.info(
            "[Selenium] %d registros → %d páginas (se descargarán %d).",
            total, paginas_totales, paginas_a_bajar,
        )

        paginas_html = [primera]
        partes = urlparse(url_base)
        consulta = {k: v[0] for k, v in parse_qs(partes.query).items()}

        for numero in range(2, paginas_a_bajar + 1):
            consulta[PARAM_PAGINA] = str(numero)
            url_pagina = (
                f"{partes.scheme}://{partes.netloc}{partes.path}?"
                + "&".join(f"{k}={v}" for k, v in consulta.items())
            )
            time.sleep(HTTP_DELAY)
            logger.info(
                "[Selenium] Descargando página %d/%d...", numero, paginas_a_bajar
            )
            driver.get(url_pagina)
            paginas_html.append(driver.page_source)

        return paginas_html

    finally:
        if driver_propio and cerrar_al_final:
            cerrar_driver(driver)


# ════════════════════════════════════════════════════════════
# 7. API PÚBLICA
# ════════════════════════════════════════════════════════════


def ejecutar_scraping(
    params: SearchParams,
    driver=None,
    cerrar_al_final: bool = True,
    usar_selenium: bool = False,
) -> tuple[list[str], list[str]]:
    """Extrae todas las páginas de resultados de SECOP I.

    Intenta primero la ruta HTTP (rápida y sin navegador). Si falla por
    algo distinto de "sin resultados", reintenta con Selenium.

    Args:
        params:          Filtros de búsqueda.
        driver:          WebDriver a reutilizar en la ruta Selenium.
        cerrar_al_final: Si cerrar el driver al terminar.
        usar_selenium:   Forzar la ruta Selenium desde el principio.

    Returns:
        Tupla ``(paginas_html, urls_detalle)``. La segunda lista se deja
        vacía: las URLs de detalle las reconstruye ``parser.py`` a partir
        del ``id_proceso`` de cada fila.

    Raises:
        SecopEmptyTableError: Si la consulta no devuelve registros.
    """
    if not usar_selenium:
        try:
            return ejecutar_scraping_http(params), []
        except SecopEmptyTableError:
            raise
        except Exception as exc:  # noqa: BLE001 - se degrada a Selenium
            logger.warning(
                "[HTTP] Falló la ruta sin navegador (%s). Probando con Selenium...",
                exc,
            )

    return ejecutar_scraping_selenium(params, driver, cerrar_al_final), []
