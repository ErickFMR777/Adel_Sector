"""
verificar_fuentes.py — Chequeo de salud de las dos fuentes de datos.

Responde a una pregunta operativa concreta: *¿los scrapers siguen
trayendo información real y actual?*

El riesgo de un scraper no es que falle con estrépito — eso se nota —
sino que **siga corriendo y devuelva datos vacíos, viejos o sin filtrar**
porque el portal cambió un nombre de campo. Este script convierte ese
fallo silencioso en un fallo ruidoso.

Comprueba:
  1. SECOP I — el formulario conserva los campos que espera ``config``.
  2. SECOP I — ``resultadosConsulta.do`` responde, la tabla tiene las
     columnas esperadas y los filtros se aplican de verdad.
  3. SECOP I — los códigos de modalidad y departamento del portal siguen
     coincidiendo con los mapas de ``config``.
  4. SECOP II — el dataset responde, expone las columnas de ``COLUMNAS_API``
     y se informa de su última actualización.
  5. Frescura — antigüedad del contrato más reciente en cada fuente.

Uso:
    python verificar_fuentes.py            # informe completo
    python verificar_fuentes.py --rapido   # omite SECOP I (sin WAF)

Código de salida: 0 si todo está bien, 1 si hay algún fallo. Sirve para
programarlo (cron / GitHub Actions) y enterarse el día que algo cambie.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sys
import urllib.request

from config import (
    DEPARTAMENTO_SECOP1,
    MODALIDAD_SECOP1,
    PARAM_FECHA_INICIAL,
    PARAM_NUMERO_PROCESO,
    SECOP_BASE_URL,
    SECOP_CONSULTA_URL,
    SOCRATA_DATASET_CONTRATOS,
    SearchParams,
    configurar_consola_utf8,
    setup_logging,
)

logger = logging.getLogger(__name__)

# Antigüedad tolerable del contrato más reciente antes de avisar.
DIAS_ALERTA_FRESCURA = 30

_OK = "[ OK ]"
_FALLO = "[FALLO]"
_AVISO = "[AVISO]"


class Resultado:
    """Acumula el resultado de las comprobaciones."""

    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.avisos: list[str] = []

    def ok(self, mensaje: str) -> None:
        print(f"  {_OK} {mensaje}")

    def fallo(self, mensaje: str) -> None:
        print(f"  {_FALLO} {mensaje}")
        self.fallos.append(mensaje)

    def aviso(self, mensaje: str) -> None:
        print(f"  {_AVISO} {mensaje}")
        self.avisos.append(mensaje)


# ════════════════════════════════════════════════════════════
# SECOP I
# ════════════════════════════════════════════════════════════


def verificar_secop1(res: Resultado) -> None:
    """Comprueba el formulario, el endpoint de datos y los códigos."""
    from bs4 import BeautifulSoup

    from scraper import (
        calentar_sesion,
        crear_sesion,
        descargar_pagina,
        extraer_total_resultados,
        _get,
    )
    from parser import parsear_pagina

    print("\nSECOP I — contratos.gov.co")

    sesion = crear_sesion()

    # --- 1. El formulario conserva sus campos ---
    try:
        calentar_sesion(sesion)
        html = _get(sesion, SECOP_CONSULTA_URL).text
        sopa = BeautifulSoup(html, "html.parser")

        esperados = {
            PARAM_NUMERO_PROCESO: "input",
            PARAM_FECHA_INICIAL: "input",
            "tipoProceso": "select",
            "selDepartamento": "select",
            "estado": "select",
        }
        faltantes = [
            campo for campo, _ in esperados.items()
            if sopa.find(id=campo) is None
        ]
        if faltantes:
            res.fallo(
                f"El formulario ya no expone: {', '.join(faltantes)}. "
                "Hay que revisar los selectores de config.py."
            )
        else:
            res.ok("El formulario conserva todos los campos esperados.")
    except Exception as exc:  # noqa: BLE001
        res.fallo(f"No se pudo cargar el formulario: {exc}")
        return

    # --- 2. El endpoint de datos responde y la tabla encaja ---
    try:
        params = SearchParams(
            departamento="Santander",
            modalidad="Mínima Cuantía",
            estado="Celebrado",
        ).normalizada()

        pagina = descargar_pagina(sesion, params, 1)
        total = extraer_total_resultados(pagina)

        if total is None:
            res.fallo(
                "No se pudo leer 'totalResultados': cambió la página de "
                "resultados y la paginación quedará mal dimensionada."
            )
        elif total == 0:
            res.aviso("La consulta de prueba devolvió 0 registros.")
        else:
            res.ok(f"Endpoint de resultados operativo ({total:,} registros).")

        df = parsear_pagina(pagina)
        if df.empty:
            res.fallo("La tabla se descargó pero el parser no extrajo filas.")
        else:
            res.ok(f"Tabla parseada correctamente ({len(df)} filas).")

            # --- 3. Los filtros se aplican de verdad ---
            if "modalidad" in df.columns:
                modalidades = set(df["modalidad"].dropna().unique())
                if len(modalidades) > 1:
                    res.fallo(
                        "El filtro de modalidad NO se está aplicando: se "
                        f"recibieron {len(modalidades)} modalidades distintas."
                    )
                else:
                    res.ok(f"El filtro de modalidad se aplica ({modalidades.pop()}).")

            if "estado" in df.columns:
                estados = set(df["estado"].dropna().unique())
                if estados and estados != {"Celebrado"}:
                    res.fallo(
                        f"El filtro de estado NO se aplica: {sorted(estados)}"
                    )
                else:
                    res.ok("El filtro de estado se aplica.")

            # --- 4. Frescura ---
            if "fecha_apertura" in df.columns:
                fechas = [
                    dt.datetime.strptime(f, "%d-%m-%Y")
                    for f in df["fecha_apertura"].dropna()
                    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", str(f))
                ]
                if fechas:
                    reciente = max(fechas)
                    dias = (dt.datetime.now() - reciente).days
                    mensaje = (
                        f"Contrato más reciente: {reciente:%d/%m/%Y} "
                        f"({dias} días)"
                    )
                    if dias > DIAS_ALERTA_FRESCURA:
                        res.aviso(f"{mensaje} — más viejo de lo esperado.")
                    else:
                        res.ok(mensaje)

        columnas_faltantes = [
            c for c in ("numero_proceso", "cuantia", "objeto_contrato")
            if c not in df.columns
        ]
        if columnas_faltantes:
            res.fallo(f"Faltan columnas en el parseo: {columnas_faltantes}")

    except Exception as exc:  # noqa: BLE001
        res.fallo(f"Error consultando el endpoint de resultados: {exc}")

    # --- 5. Los códigos del portal siguen coincidiendo ---
    for ruta, mapa, nombre in (
        ("/entidades/comun/js/tProceso.js", MODALIDAD_SECOP1, "modalidad"),
        ("/entidades/comun/js/deptos.js", DEPARTAMENTO_SECOP1, "departamento"),
    ):
        try:
            js = _get(sesion, f"{SECOP_BASE_URL}{ruta}").text
            codigos_portal = set(re.findall(r'\[\d+\]\s*=\s*"([^"]+)"', js))
            desconocidos = {
                c for c in codigos_portal
                if c.isdigit() and c not in mapa
            }
            if desconocidos:
                res.aviso(
                    f"El portal expone códigos de {nombre} que config.py no "
                    f"conoce: {sorted(desconocidos)[:8]}"
                )
            else:
                res.ok(f"Los códigos de {nombre} siguen alineados.")
        except Exception as exc:  # noqa: BLE001
            res.aviso(f"No se pudo verificar los códigos de {nombre}: {exc}")

    sesion.close()


# ════════════════════════════════════════════════════════════
# SECOP II
# ════════════════════════════════════════════════════════════


def verificar_secop2(res: Resultado) -> None:
    """Comprueba el dataset de Socrata, sus columnas y su frescura."""
    from api_scraper import COLUMNAS_API, consultar_contratos, contar_registros

    print("\nSECOP II — datos.gov.co (API Socrata)")

    # --- 1. Metadatos: cuándo se actualizó por última vez ---
    try:
        url = f"https://www.datos.gov.co/api/views/{SOCRATA_DATASET_CONTRATOS}.json"
        peticion = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(peticion, timeout=90) as respuesta:
            meta = json.loads(respuesta.read().decode("utf-8"))

        marca = meta.get("rowsUpdatedAt")
        if marca:
            actualizado = dt.datetime.fromtimestamp(marca)
            dias = (dt.datetime.now() - actualizado).days
            mensaje = f"Dataset actualizado el {actualizado:%d/%m/%Y} ({dias} días)"
            if dias > DIAS_ALERTA_FRESCURA:
                res.aviso(f"{mensaje} — la fuente lleva tiempo sin refrescarse.")
            else:
                res.ok(mensaje)
    except Exception as exc:  # noqa: BLE001
        res.aviso(f"No se pudieron leer los metadatos del dataset: {exc}")

    # --- 2. El dataset responde y expone las columnas esperadas ---
    try:
        muestra = consultar_contratos(
            departamento="Santander", max_registros=1000
        )
        if muestra.empty:
            res.fallo("El dataset no devolvió registros para Santander.")
            return

        faltantes = [c for c in COLUMNAS_API if c not in muestra.columns]
        if faltantes:
            res.fallo(f"El dataset ya no expone: {faltantes}")
        else:
            res.ok(f"Las {len(COLUMNAS_API)} columnas esperadas siguen presentes.")

        # --- 3. El filtro se aplica ---
        deptos = set(muestra["departamento"].dropna().unique())
        if deptos and deptos != {"Santander"}:
            res.fallo(f"El filtro de departamento NO se aplica: {sorted(deptos)[:5]}")
        else:
            res.ok("El filtro de departamento se aplica.")

        # --- 4. Frescura del contrato más reciente ---
        fechas = muestra["fecha_de_inicio_del_contrato"].dropna()
        if len(fechas):
            reciente = max(str(f)[:10] for f in fechas)
            res.ok(f"Contrato más reciente en la muestra: {reciente}")

        # --- 5. El conteo respeta los filtros de fecha ---
        total_sin = contar_registros(departamento="Santander")
        total_con = contar_registros(
            departamento="Santander",
            fecha_inicio="01/01/2026",
            fecha_fin="31/01/2026",
        )
        if total_con >= total_sin:
            res.fallo(
                "contar_registros() ignora los filtros de fecha: la descarga "
                "se dimensionará mal."
            )
        else:
            res.ok(
                f"El conteo respeta las fechas ({total_sin:,} → {total_con:,})."
            )

    except Exception as exc:  # noqa: BLE001
        res.fallo(f"Error consultando la API: {exc}")


# ════════════════════════════════════════════════════════════
# ENTRADA
# ════════════════════════════════════════════════════════════


def verificar_catalogos(res: Resultado) -> None:
    """Comprueba que los valores del catálogo sigan existiendo en la API.

    Es la comprobación que evita el peor fallo silencioso del sistema:
    un valor de filtro que el portal renombró deja de casar con nada y la
    consulta devuelve cero registros sin ningún error. Pasó de verdad con
    "Bogotá D.C." (la API usa "Distrito Capital de Bogotá"), y ese
    departamento concentra casi dos millones de contratos.
    """
    from catalogos import DEPARTAMENTOS, ESTADOS, MODALIDADES, TIPOS_CONTRATO
    from api_scraper import contar_registros

    print("\nCatálogos de filtros")

    comprobaciones = (
        ("departamento", DEPARTAMENTOS, "departamento"),
        ("modalidad", MODALIDADES, "modalidad_de_contratacion"),
        ("tipo de contrato", TIPOS_CONTRATO, "tipo_de_contrato"),
        ("estado", ESTADOS, "estado_contrato"),
    )

    for nombre, catalogo, campo in comprobaciones:
        valores = sorted({v for o in catalogo for v in o.api_valores})
        if not valores:
            continue

        try:
            reales = {
                str(fila.get(campo))
                for fila in _valores_distintos(campo)
            }
        except Exception as exc:  # noqa: BLE001
            res.aviso(f"No se pudieron leer los valores de {nombre}: {exc}")
            continue

        huerfanos = [v for v in valores if v not in reales]
        if huerfanos:
            res.fallo(
                f"Estos valores de {nombre} ya no existen en la API y "
                f"devolverían cero registros: {huerfanos}"
            )
        else:
            res.ok(f"Los {len(valores)} valores de {nombre} siguen vigentes.")

        nuevos = [v for v in reales if v not in valores and v != "None"]
        if nuevos:
            res.aviso(
                f"La API expone valores de {nombre} que el catálogo no "
                f"ofrece: {sorted(nuevos)[:6]}"
            )

    # El caso concreto que provocó el fallo, como prueba de regresión.
    if contar_registros(departamento="Bogotá D.C.") == 0:
        res.fallo(
            "Filtrar por 'Bogotá D.C.' devuelve cero contratos: la "
            "traducción al nombre de la API está rota otra vez."
        )
    else:
        res.ok("Bogotá se traduce correctamente al nombre de la API.")


def _valores_distintos(campo: str) -> list[dict]:
    """Agrupa el dataset por un campo para listar sus valores reales."""
    import urllib.parse

    consulta = urllib.parse.urlencode(
        {"$select": f"{campo}, count(*) as n", "$group": campo}
    )
    url = (
        f"https://www.datos.gov.co/resource/"
        f"{SOCRATA_DATASET_CONTRATOS}.json?{consulta}"
    )
    peticion = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(peticion, timeout=300) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def main() -> int:
    """Ejecuta las comprobaciones y devuelve el código de salida."""
    analizador = argparse.ArgumentParser(
        description="Verifica que las fuentes de SECOP sigan operativas y actuales."
    )
    analizador.add_argument(
        "--rapido",
        action="store_true",
        help="Omitir SECOP I (evita peticiones al portal con WAF).",
    )
    args = analizador.parse_args()

    configurar_consola_utf8()
    setup_logging()
    logging.getLogger().setLevel(logging.WARNING)

    print("=" * 66)
    print("VERIFICACIÓN DE FUENTES SECOP")
    print(f"Fecha: {dt.datetime.now():%d/%m/%Y %H:%M}")
    print("=" * 66)

    res = Resultado()

    if not args.rapido:
        verificar_secop1(res)
    else:
        print("\nSECOP I — omitido (--rapido)")

    verificar_secop2(res)
    verificar_catalogos(res)

    print("\n" + "=" * 66)
    if res.fallos:
        print(f"RESULTADO: {len(res.fallos)} FALLO(S), {len(res.avisos)} aviso(s)")
        for fallo in res.fallos:
            print(f"  - {fallo}")
        print("=" * 66)
        return 1

    print(f"RESULTADO: todo correcto ({len(res.avisos)} aviso(s))")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
