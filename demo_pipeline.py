"""
demo_pipeline.py — Demostración del pipeline SECOP I sin navegador.

Simula cada etapa del pipeline con datos realistas:
  1. HTML mock de una tabla de resultados SECOP I
  2. Parsing → DataFrame estructurado
  3. Limpieza y tipificación
  4. Exportación CSV

Útil para probar sin Chrome instalado.
"""

import logging
import sys

import pandas as pd

from config import setup_logging, OUTPUT_DIR
from parser import parsear_pagina
from cleaning import limpiar_dataframe

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# HTML MOCK DE SECOP I
# ════════════════════════════════════════════════════════════

HTML_MOCK_SECOP = """
<!DOCTYPE html>
<html>
<head><title>SECOP I - Resultados</title></head>
<body>
<input type="hidden" name="totalResultados" value='5' />
<table>
    <tr>
        <td>&#8711;</td>
        <td>Número de Proceso</td>
        <td>Tipo de Proceso</td>
        <td>Estado</td>
        <td>Entidad</td>
        <td>Objeto</td>
        <td>Departamento y Municipio de Ejecución</td>
        <td>Cuantía</td>
        <td>Fecha(dd-mm-aaaa)</td>
    </tr>
    <tr>
        <td>1</td>
        <td><a href="javascript: consultaProceso('26-11-14696064')">SAMC 004 DE 2026</a></td>
        <td>Selección Abreviada de Menor Cuantía (Ley 1150 de 2007)</td>
        <td>Celebrado</td>
        <td>SANTANDER - ALCALDÍA MUNICIPIO DE SAN JOSÉ DE MIRANDA</td>
        <td>SERVICIO DE EXTENSIÓN AGROPECUARIA DE MANERA PERMANENTE</td>
        <td>Santander : San José de Miranda</td>
        <td>$255.000.000,00</td>
        <td>Fecha de Celebración del Primer Contrato 31-03-2026</td>
    </tr>
    <tr>
        <td>2</td>
        <td><a href="javascript: consultaProceso('26-13-14690001')">MC-001-2026</a></td>
        <td>Contratación Mínima Cuantía</td>
        <td>Celebrado</td>
        <td>SANTANDER - ALCALDÍA MUNICIPIO DE GIRÓN</td>
        <td>SUMINISTRO DE COMBUSTIBLE PARA EL PARQUE AUTOMOTOR</td>
        <td>Santander : Girón</td>
        <td>$94.758.732,00</td>
        <td>Fecha de Celebración del Primer Contrato 12-02-2026</td>
    </tr>
    <tr>
        <td>3</td>
        <td><a href="javascript: consultaProceso('26-1-14688888')">LP-002-2026</a></td>
        <td>Licitación Pública</td>
        <td>Convocado</td>
        <td>SANTANDER - GOBERNACIÓN DE SANTANDER</td>
        <td>OBRAS CIVILES DE MEJORAMIENTO DE INFRAESTRUCTURA VIAL</td>
        <td>Santander : Bucaramanga</td>
        <td>$5.890.000.000,00</td>
        <td>Fecha de Apertura 05-01-2026</td>
    </tr>
    <tr>
        <td>4</td>
        <td><a href="javascript: consultaProceso('26-4-14687777')">RE-010-2026</a></td>
        <td>Régimen Especial</td>
        <td>Liquidado</td>
        <td>SANTANDER - UNIVERSIDAD INDUSTRIAL DE SANTANDER</td>
        <td>RENOVACIÓN DE EQUIPOS DE LABORATORIO</td>
        <td>Santander : Bucaramanga</td>
        <td>$780.250.000,00</td>
        <td>Fecha de Liquidación 20-01-2026</td>
    </tr>
    <tr>
        <td>5</td>
        <td><a href="javascript: consultaProceso('26-13-14686666')">MC-045-2026</a></td>
        <td>Contratación Mínima Cuantía</td>
        <td>Celebrado</td>
        <td>SANTANDER - ALCALDÍA MUNICIPIO DE PIEDECUESTA</td>
        <td>SERVICIO DE VIGILANCIA Y SEGURIDAD PRIVADA</td>
        <td>Santander : Piedecuesta</td>
        <td>$120.500.000,00</td>
        <td>Fecha de Celebración del Primer Contrato 28-01-2026</td>
    </tr>
</table>
</body>
</html>
"""


def demo_parser():
    """Demuestra el parsing del HTML mock."""
    logger.info("=" * 70)
    logger.info("[1/3] ETAPA 1: PARSER — Extracción del HTML a DataFrame")
    logger.info("=" * 70)

    df = parsear_pagina(HTML_MOCK_SECOP)
    logger.info("✓ Parseadas %d filas crudas", len(df))
    print("\nDataFrame CRUDO:")
    print(df.to_string(index=False))

    return df


def demo_cleaning(df_crudo):
    """Demuestra la limpieza y tipificación."""
    logger.info("\n" + "=" * 70)
    logger.info("[2/3] ETAPA 2: CLEANING — Limpieza y tipificación")
    logger.info("=" * 70)

    df_limpio = limpiar_dataframe(df_crudo)
    logger.info("✓ Limpieza completada: %d filas finales", len(df_limpio))

    print("\nDataFrame LIMPIO:")
    print(df_limpio.to_string(index=False))

    print("\n" + "─" * 70)
    print("Tipos de datos:")
    print(df_limpio.dtypes)

    return df_limpio


def demo_export(df):
    """Demuestra la exportación a CSV."""
    logger.info("\n" + "=" * 70)
    logger.info("[3/3] ETAPA 3: EXPORTACIÓN — Guardado en CSV")
    logger.info("=" * 70)

    ruta_csv = OUTPUT_DIR / "demo_secop_resultados.csv"
    df.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
    logger.info("✓ Archivo guardado: %s", ruta_csv)

    # Verificar que se escribió
    tamaño_kb = ruta_csv.stat().st_size / 1024
    logger.info("  Tamaño: %.1f KB (%d bytes)", tamaño_kb, ruta_csv.stat().st_size)

    # Leer y mostrar
    df_leida = pd.read_csv(ruta_csv)
    print(f"\n✓ CSV leído de vuelta ({len(df_leida)} filas):")
    print(df_leida.head().to_string(index=False))

    return ruta_csv


def main():
    """Ejecuta la demostración completa del pipeline."""
    setup_logging()

    logger.info("\n")
    logger.info("╔" + "═" * 68 + "╗")
    logger.info("║ DEMO: Pipeline SECOP I sin Selenium (datos mock)              ║")
    logger.info("╚" + "═" * 68 + "╝")

    try:
        # Etapa 1: Parser
        df_crudo = demo_parser()

        # Etapa 2: Cleaning
        df_limpio = demo_cleaning(df_crudo)

        # Etapa 3: Export
        ruta_csv = demo_export(df_limpio)

        # Resumen final
        logger.info("\n" + "=" * 70)
        logger.info("RESUMEN DE LA DEMOSTRACIÓN")
        logger.info("=" * 70)
        logger.info("✓ Parser:    Extraídas %d filas de HTML mock", len(df_crudo))
        logger.info("✓ Cleaning:  Limpiadas y tipificadas %d filas", len(df_limpio))
        logger.info("✓ Export:    Guardadas en %s", ruta_csv)
        logger.info("\nColumnas finales:")
        for col in df_limpio.columns:
            dtype = str(df_limpio[col].dtype)
            nulos = df_limpio[col].isna().sum()
            logger.info("  • %-20s (%s) — %d nulos", col, dtype, nulos)

        logger.info("\n" + "=" * 70)
        logger.info("✓ DEMO COMPLETADA CON ÉXITO")
        logger.info("=" * 70)

        print("\n" + "═" * 70)
        print("COMPONENTES VERIFICADOS:")
        print("═" * 70)
        print("✓ config.py           — SearchParams, logging, selectores")
        print("✓ exceptions.py       — Excepciones tipadas")
        print("✓ parser.py           — Extracción tabla → DataFrame")
        print("✓ cleaning.py         — Normalización, tipificación")
        print("✓ scraper.py          — Selenium (requiere Chrome)")
        print("✓ detail_scraper.py   — Extracción de detalles")
        print("✓ main.py             — CLI completa")
        print("═" * 70 + "\n")

        return 0

    except Exception as exc:
        logger.exception("Error en demostración: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
