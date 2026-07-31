"""
main.py — Orquestador CLI del pipeline de scraping SECOP I.

Punto de entrada principal.  Ofrece dos modos de operación:

  1. **Búsqueda** (``--modo busqueda``, por defecto):
     Rellena el formulario → extrae tabla paginada → limpia → exporta CSV.

  2. **Detalle** (``--modo detalle``):
     Toma un CSV existente con ``url_detalle`` → ingresa a cada proceso →
     extrae datos enriquecidos → actualiza base histórica.

Uso:
  python main.py \\
      --palabra-clave "vigilancia" \\
      --fecha-inicio "01/01/2025" \\
      --fecha-fin "31/12/2025" \\
      --departamento "BOGOTÁ D.C." \\
      --salida output/resultados.csv

  python main.py \\
      --modo detalle \\
      --entrada output/resultados.csv \\
      --salida output/detalles.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (
    CSV_ENCODING,
    CSV_SEPARATOR,
    LOG_DIR,
    OUTPUT_DIR,
    SearchParams,
    setup_logging,
)
from exceptions import (
    SecopEmptyTableError,
    SecopError,
    SecopRecaptchaError,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# 1. ARGUMENTOS DE LÍNEA DE COMANDOS
# ════════════════════════════════════════════════════════════


def construir_parser_args() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI.

    Returns:
        Instancia de ``ArgumentParser`` configurada.
    """
    parser = argparse.ArgumentParser(
        description="Pipeline de scraping SECOP I — Búsqueda y extracción de contratos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Búsqueda básica por palabra clave
  python main.py --palabra-clave "vigilancia"

  # Búsqueda con filtros completos
  python main.py \\
      --palabra-clave "consultoría" \\
      --fecha-inicio "01/01/2025" \\
      --fecha-fin "30/06/2025" \\
      --departamento "ANTIOQUIA" \\
      --modalidad "Licitación pública"

  # Extracción de detalles desde CSV previo
  python main.py --modo detalle --entrada output/resultados.csv

  # Modo headless
  SECOP_HEADLESS=1 python main.py --palabra-clave "vigilancia"
        """,
    )

    # --- Modo de operación ---
    parser.add_argument(
        "--modo",
        choices=["busqueda", "detalle"],
        default="busqueda",
        help="Modo de operación (default: busqueda).",
    )
    parser.add_argument(
        "--fuente",
        choices=["auto", "secop1", "api"],
        default="auto",
        help=(
            "Origen de los datos: 'secop1' raspa contratos.gov.co, 'api' usa "
            "datos.gov.co (SECOP II), 'auto' intenta SECOP I y cae a la API "
            "(default: auto)."
        ),
    )
    parser.add_argument(
        "--selenium",
        action="store_true",
        help=(
            "Forzar el uso de Chrome para SECOP I. Por defecto se usa HTTP "
            "directo, que es más rápido y no requiere navegador."
        ),
    )

    # --- Parámetros de búsqueda ---
    grupo_busqueda = parser.add_argument_group("Parámetros de búsqueda")
    grupo_busqueda.add_argument(
        "--palabra-clave", "-k",
        type=str,
        default=None,
        help="Texto libre para el campo Objeto del contrato.",
    )
    grupo_busqueda.add_argument(
        "--numero-proceso",
        type=str,
        default=None,
        help="Número específico de un proceso.",
    )
    grupo_busqueda.add_argument(
        "--entidad",
        type=str,
        default=None,
        help="Nombre (parcial) de la entidad compradora.",
    )
    grupo_busqueda.add_argument(
        "--fecha-inicio", "-fi",
        type=str,
        default=None,
        help="Fecha apertura desde (dd/MM/yyyy).",
    )
    grupo_busqueda.add_argument(
        "--fecha-fin", "-ff",
        type=str,
        default=None,
        help="Fecha apertura hasta (dd/MM/yyyy).",
    )
    grupo_busqueda.add_argument(
        "--objeto",
        type=str,
        default=None,
        help="Producto o Servicio — value del <option> (ej. '80000000').",
    )
    grupo_busqueda.add_argument(
        "--modalidad", "-m",
        type=str,
        default=None,
        help="Modalidad de contratación — value del <option> (ej. '13' = Mínima Cuantía).",
    )
    grupo_busqueda.add_argument(
        "--departamento", "-d",
        type=str,
        default=None,
        help="Departamento — value del <option> (ej. '668000' = Santander).",
    )
    grupo_busqueda.add_argument(
        "--municipio",
        type=str,
        default=None,
        help="Municipio (texto visible del dropdown).",
    )
    grupo_busqueda.add_argument(
        "--estado",
        type=str,
        default=None,
        help="Estado del proceso — ID o nombre (ej. '4' o 'Celebrado').",
    )
    grupo_busqueda.add_argument(
        "--tipo-contrato",
        type=str,
        default=None,
        help=(
            "Tipo de contrato (solo API): 'Obra', 'Consultoría', "
            "'Prestación de servicios'..."
        ),
    )
    grupo_busqueda.add_argument(
        "--cuantia",
        type=str,
        default=None,
        help="Rango de cuantía — código del dropdown (ej. '1' = $0-$100M).",
    )
    grupo_busqueda.add_argument(
        "--max-registros",
        type=int,
        default=None,
        help=(
            "Tope de registros a traer desde la API (default: todos los "
            "que coincidan con el filtro)."
        ),
    )

    # --- Paginación ---
    parser.add_argument(
        "--max-paginas",
        type=int,
        default=200,
        help="Número máximo de páginas a recorrer (default: 200).",
    )

    # --- Entrada/Salida ---
    grupo_io = parser.add_argument_group("Entrada / Salida")
    grupo_io.add_argument(
        "--entrada", "-i",
        type=str,
        default=None,
        help="Archivo CSV de entrada (para modo detalle).",
    )
    grupo_io.add_argument(
        "--salida", "-o",
        type=str,
        default=None,
        help="Ruta del archivo de salida (CSV). Default: output/secop_<timestamp>.csv",
    )
    grupo_io.add_argument(
        "--historica",
        type=str,
        default=None,
        help="Ruta de la base histórica para actualización incremental.",
    )

    # --- Opciones avanzadas ---
    grupo_avanzado = parser.add_argument_group("Opciones avanzadas")
    grupo_avanzado.add_argument(
        "--delay-detalle",
        type=float,
        default=1.5,
        help="Segundos de espera entre cada detalle (rate limiting, default: 1.5).",
    )
    grupo_avanzado.add_argument(
        "--debug",
        action="store_true",
        help="Activar logging nivel DEBUG.",
    )

    return parser


# ════════════════════════════════════════════════════════════
# 2. CONSTRUIR SearchParams DESDE ARGUMENTOS
# ════════════════════════════════════════════════════════════


def args_a_search_params(args: argparse.Namespace) -> SearchParams:
    """Convierte los argumentos CLI a un ``SearchParams``.

    Returns:
        Instancia inmutable de ``SearchParams``.
    """
    return SearchParams(
        palabra_clave=args.palabra_clave,
        numero_proceso=args.numero_proceso,
        entidad=args.entidad,
        fecha_inicio=args.fecha_inicio,
        fecha_fin=args.fecha_fin,
        objeto=args.objeto,
        modalidad=args.modalidad,
        departamento=args.departamento,
        municipio=args.municipio,
        estado=args.estado,
        cuantia=args.cuantia,
        max_pages=args.max_paginas,
    )


# ════════════════════════════════════════════════════════════
# 3. GENERAR RUTA DE SALIDA
# ════════════════════════════════════════════════════════════


def generar_ruta_salida(ruta_arg: str | None, prefijo: str = "secop") -> Path:
    """Genera la ruta de salida con timestamp si no se especificó.

    Args:
        ruta_arg: Ruta proporcionada por el usuario (puede ser ``None``).
        prefijo:  Prefijo para el nombre de archivo generado.

    Returns:
        Ruta absoluta del archivo de salida.
    """
    if ruta_arg:
        ruta = Path(ruta_arg)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        return ruta

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{prefijo}_{timestamp}.csv"


# ════════════════════════════════════════════════════════════
# 4. MODO BÚSQUEDA
# ════════════════════════════════════════════════════════════


def ejecutar_modo_busqueda(args: argparse.Namespace) -> int:
    """Ejecuta el pipeline completo en modo búsqueda.

    Flujo:
      1. Según ``--fuente``, raspar SECOP I (HTTP directo o Selenium)
         y/o consultar la API de Datos Abiertos (SECOP II).
      2. En modo ``auto``, si SECOP I falla o no devuelve nada, se cae
         automáticamente a la API.
      3. Parsear / Limpiar / Exportar CSV.

    Returns:
        Código de salida (0 = éxito, 1 = error).
    """
    from cleaning import filtrar_por_palabra_clave, limpiar_dataframe

    params = args_a_search_params(args)
    ruta_salida = generar_ruta_salida(args.salida, prefijo="secop_busqueda")

    logger.info("=" * 70)
    logger.info("MODO BÚSQUEDA — Inicio del pipeline (fuente=%s)", args.fuente)
    logger.info("Parámetros: %s", params)
    logger.info("=" * 70)

    df_limpio = None
    error_secop1: Exception | None = None

    # ── Intento 1: SECOP I (contratos.gov.co) ──
    if args.fuente in ("auto", "secop1"):
        try:
            from scraper import ejecutar_scraping
            from parser import parsear_todas_paginas

            transporte = "Selenium" if args.selenium else "HTTP directo"
            logger.info("[SECOP I] Extrayendo vía %s...", transporte)

            paginas_html, _ = ejecutar_scraping(
                params=params,
                usar_selenium=args.selenium,
            )
            logger.info("[SECOP I] %d páginas descargadas.", len(paginas_html))

            df_crudo = parsear_todas_paginas(paginas_html)
            logger.info("[SECOP I] Parsing completado: %d filas.", len(df_crudo))

            # SECOP I no tiene búsqueda por texto libre: se filtra en local.
            df_crudo = filtrar_por_palabra_clave(df_crudo, args.palabra_clave)

            df_limpio = limpiar_dataframe(df_crudo)
            logger.info("[SECOP I] Limpieza completada: %d filas.", len(df_limpio))

        except Exception as exc:
            error_secop1 = exc
            logger.warning("[SECOP I] Falló la extracción: %s", exc)
            if args.fuente == "secop1":
                logger.exception("[SECOP I] Detalle del error.")
                print(f"\nError extrayendo de SECOP I: {exc}")
                return 1
            logger.info("[API] Cambiando a datos.gov.co (SECOP II)...")

    # ── Intento 2: API de Datos Abiertos (SECOP II) ──
    if (df_limpio is None or df_limpio.empty) and args.fuente in ("auto", "api"):
        try:
            from api_scraper import consultar_desde_params

            logger.info("[API] Consultando SECOP II vía datos.gov.co...")
            df_api = consultar_desde_params(
                params,
                max_registros=args.max_registros,
                tipo_contrato=args.tipo_contrato,
            )

            if df_api.empty:
                logger.warning("[API] La consulta no retornó registros.")
                print("\nSin resultados en la API.")
                return 0

            df_limpio = limpiar_dataframe(df_api)
            logger.info("[API] %d registros obtenidos y limpiados.", len(df_limpio))

        except Exception as exc_api:
            logger.exception("[API] Error en consulta API: %s", exc_api)
            print("\nError: no se pudieron obtener datos.")
            if error_secop1 is not None:
                print(f"  SECOP I: {error_secop1}")
            print(f"  API:     {exc_api}")
            return 1

    if df_limpio is None or df_limpio.empty:
        logger.warning("No se obtuvieron registros con los filtros dados.")
        print("\nSin resultados para los filtros indicados.")
        return 0

    # ── Exportación ──
    logger.info("Exportando resultados...")
    df_limpio.to_csv(
        ruta_salida,
        index=False,
        sep=CSV_SEPARATOR,
        encoding=CSV_ENCODING,
    )
    logger.info("Resultados exportados a: %s", ruta_salida)

    # --- Opcional: Actualizar base histórica ---
    if args.historica:
        from detail_scraper import actualizar_base_historica
        actualizar_base_historica(df_limpio, args.historica)

    # --- Resumen ---
    logger.info("=" * 70)
    logger.info("RESUMEN DE BÚSQUEDA")
    logger.info("  Filas totales:     %d", len(df_limpio))
    logger.info("  Columnas:          %s", list(df_limpio.columns))
    logger.info("  Archivo de salida: %s", ruta_salida)
    logger.info("=" * 70)

    # Vista previa
    print("\n" + "=" * 70)
    print("VISTA PREVIA DE RESULTADOS")
    print("=" * 70)
    print(df_limpio.head(10).to_string(index=False))
    print(f"\n[Total: {len(df_limpio)} registros → {ruta_salida}]")

    return 0


# ════════════════════════════════════════════════════════════
# 5. MODO DETALLE
# ════════════════════════════════════════════════════════════


def ejecutar_modo_detalle(args: argparse.Namespace) -> int:
    """Ejecuta el pipeline en modo extracción de detalles individuales.

    Flujo:
      1. Cargar CSV de entrada (debe contener columna ``url_detalle``).
      2. Crear WebDriver.
      3. Navegar a cada URL de detalle.
      4. Extraer datos enriquecidos.
      5. Limpiar y exportar.
      6. Actualizar base histórica.

    Returns:
        Código de salida (0 = éxito, 1 = error).
    """
    from detail_scraper import extraer_detalles_masivo, actualizar_base_historica
    from cleaning import limpiar_dataframe

    if not args.entrada:
        logger.error("Modo detalle requiere --entrada con un archivo CSV.")
        print("❌ Se requiere --entrada para modo detalle.")
        return 1

    ruta_entrada = Path(args.entrada)
    if not ruta_entrada.exists():
        logger.error("Archivo de entrada no encontrado: %s", ruta_entrada)
        print(f"❌ Archivo no encontrado: {ruta_entrada}")
        return 1

    ruta_salida = generar_ruta_salida(args.salida, prefijo="secop_detalles")

    logger.info("=" * 70)
    logger.info("MODO DETALLE — Inicio del pipeline")
    logger.info("Entrada: %s", ruta_entrada)
    logger.info("=" * 70)

    # Cargar CSV y extraer URLs
    df_entrada = pd.read_csv(ruta_entrada, dtype=str)

    if "url_detalle" not in df_entrada.columns:
        logger.error("El CSV de entrada no contiene la columna 'url_detalle'.")
        print("❌ El CSV de entrada no tiene columna 'url_detalle'.")
        return 1

    urls = df_entrada["url_detalle"].dropna().unique().tolist()
    logger.info("URLs de detalle encontradas: %d", len(urls))

    if not urls:
        logger.warning("No hay URLs de detalle para procesar.")
        print("⚠️  No hay URLs de detalle en el archivo.")
        return 0

    driver = None
    if args.selenium:
        from scraper import crear_driver
        driver = crear_driver()

    try:
        # --- Paso 1: Extracción masiva ---
        logger.info("[1/3] Extrayendo detalles de %d procesos...", len(urls))
        df_detalles = extraer_detalles_masivo(
            urls=urls,
            delay=args.delay_detalle,
            driver=driver,
        )
        logger.info("Extracción completada: %d detalles.", len(df_detalles))

        if df_detalles.empty:
            logger.warning("No se extrajo ningún detalle.")
            print("⚠️  No se pudieron extraer detalles.")
            return 0

        # --- Paso 2: Limpieza ---
        logger.info("[2/3] Limpiando detalles...")
        df_limpio = limpiar_dataframe(df_detalles)

        # --- Paso 3: Exportación ---
        logger.info("[3/3] Exportando detalles...")
        df_limpio.to_csv(
            ruta_salida,
            index=False,
            sep=CSV_SEPARATOR,
            encoding=CSV_ENCODING,
        )
        logger.info("Detalles exportados a: %s", ruta_salida)

        # Base histórica
        if args.historica:
            actualizar_base_historica(df_limpio, args.historica)

        # Resumen
        logger.info("=" * 70)
        logger.info("RESUMEN DE DETALLES")
        logger.info("  Procesos procesados: %d", len(urls))
        logger.info("  Detalles extraídos:  %d", len(df_limpio))
        logger.info("  Archivo de salida:   %s", ruta_salida)
        logger.info("=" * 70)

        print("\n" + "=" * 70)
        print("VISTA PREVIA DE DETALLES")
        print("=" * 70)
        print(df_limpio.head(5).to_string(index=False))
        print(f"\n[Total: {len(df_limpio)} detalles → {ruta_salida}]")

        return 0

    except SecopError as exc:
        logger.error("Error del pipeline: %s", exc)
        print(f"\n❌ Error: {exc}")
        return 1

    except Exception as exc:
        logger.exception("Error inesperado: %s", exc)
        print(f"\n❌ Error inesperado: {exc}")
        return 1

    finally:
        if driver is not None:
            from scraper import cerrar_driver
            cerrar_driver(driver)


# ════════════════════════════════════════════════════════════
# 6. PUNTO DE ENTRADA
# ════════════════════════════════════════════════════════════


def main() -> int:
    """Punto de entrada principal del pipeline.

    Returns:
        Código de salida del programa.
    """
    # Parsear argumentos
    parser = construir_parser_args()
    args = parser.parse_args()

    # Configurar logging
    if args.debug:
        import os
        os.environ["SECOP_DEBUG"] = "1"
    setup_logging()

    logger.info(
        "Pipeline SECOP I iniciado — modo=%s, versión=1.0.0",
        args.modo,
    )

    # Despachar al modo correspondiente
    if args.modo == "busqueda":
        return ejecutar_modo_busqueda(args)
    elif args.modo == "detalle":
        return ejecutar_modo_detalle(args)
    else:
        logger.error("Modo desconocido: %s", args.modo)
        return 1


if __name__ == "__main__":
    sys.exit(main())
