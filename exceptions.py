"""
exceptions.py — Excepciones personalizadas para el pipeline SECOP I.

Jerarquía:
  SecopError (base)
  ├── SecopTimeoutError      → Timeout de Selenium / carga de página.
  ├── SecopRecaptchaError    → reCAPTCHA detectado en el portal.
  ├── SecopBlockedError      → El WAF del portal bloqueó la IP (403).
  ├── SecopIframeError       → No se pudo acceder al iframe de resultados.
  ├── SecopEmptyTableError   → La consulta no retornó registros.
  ├── SecopFormError         → Error al interactuar con el formulario.
  ├── SecopPaginationError   → Error durante la navegación de páginas.
  ├── SecopParsingError      → Error al parsear el HTML de resultados.
  └── SecopExportError       → Error al exportar el DataFrame.

Cada excepción lleva un mensaje descriptivo y, opcionalmente, el
contexto (URL, parámetros de búsqueda, HTML parcial) para facilitar
la depuración en los logs.
"""

from __future__ import annotations

from typing import Any, Optional


class SecopError(Exception):
    """Excepción base para todos los errores del pipeline SECOP.

    Args:
        message: Descripción legible del error.
        context: Diccionario opcional con datos de depuración
                 (URL actual, parámetros de búsqueda, fragmento HTML, etc.).
    """

    def __init__(self, message: str, context: Optional[dict[str, Any]] = None) -> None:
        self.context = context or {}
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        if self.context:
            ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{base} [{ctx}]"
        return base


class SecopTimeoutError(SecopError):
    """El elemento esperado no apareció dentro del timeout configurado.

    Se lanza cuando ``WebDriverWait`` agota el tiempo.  El ``context``
    debería incluir el selector que se intentó localizar.
    """


class SecopRecaptchaError(SecopError):
    """El portal presentó un desafío reCAPTCHA.

    Indica que se debe pausar y permitir resolución manual o integrar
    un servicio externo de resolución de CAPTCHA.
    """


class SecopBlockedError(SecopError):
    """El WAF de contratos.gov.co bloqueó la petición (HTTP 403).

    El portal está detrás de Zenedge/Imperva, que corta el tráfico ante
    ráfagas de peticiones y devuelve una página
    *"Access to the website is blocked"*.

    No es un error de programación: indica que hay que bajar el ritmo
    (``SECOP_DELAY``) o esperar a que expire el bloqueo de IP.
    """


class SecopIframeError(SecopError):
    """No fue posible cambiar al iframe que contiene los resultados.

    Puede ocurrir cuando el portal cambia la estructura de frames o
    cuando un reCAPTCHA bloquea la carga del iframe.
    """


class SecopEmptyTableError(SecopError):
    """La consulta se ejecutó correctamente pero no devolvió registros.

    No es necesariamente un *error* operativo; puede deberse a filtros
    muy restrictivos.  Se maneja de forma distinta a otros errores.
    """


class SecopFormError(SecopError):
    """Error al rellenar o enviar el formulario de búsqueda.

    Incluye en ``context`` el campo y el valor que se intentaba ingresar.
    """


class SecopPaginationError(SecopError):
    """Error durante la navegación entre páginas de resultados.

    Se lanza cuando no se puede localizar el control de paginación o
    cuando la página siguiente no carga dentro del timeout.
    """


class SecopParsingError(SecopError):
    """Error al extraer datos del HTML de la tabla de resultados.

    Puede deberse a un cambio en la estructura del DOM del portal.
    """


class SecopExportError(SecopError):
    """Error al guardar el DataFrame en disco (CSV, Parquet, etc.)."""
