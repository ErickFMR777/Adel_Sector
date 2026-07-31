# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Contexto

Pipeline de extracción de datos de contratación pública colombiana + dashboard Streamlit para generar informes de "Análisis de la Demanda". Módulos planos en la raíz (no hay paquete instalable). Todo el código, docstrings y logs están en español; mantener esa convención.

## Comandos

```bash
pip install -r requirements.txt

# Búsqueda en SECOP I (contratos.gov.co) — HTTP directo, sin navegador
python main.py --fuente secop1 --departamento Santander \
    --modalidad "Mínima Cuantía" --estado Celebrado \
    --fecha-inicio 01/01/2026 --fecha-fin 31/03/2026

# Búsqueda en SECOP II (API de datos.gov.co)
python main.py --fuente api --departamento Santander --modalidad "Mínima cuantía"

# auto (default): intenta SECOP I y cae a la API si falla
python main.py --palabra-clave vigilancia

# Enriquecer con la ficha de detalle (usa la columna url_detalle)
python main.py --modo detalle --entrada output/resultados.csv

# Solo API, consulta predefinida Santander/Mínima/Celebrado
python api_scraper.py

# Smoke test sin red (HTML mock con la estructura real → parser → cleaning → CSV)
python demo_pipeline.py

# Chequeo de salud de las fuentes (exit 1 si un portal cambió)
python verificar_fuentes.py [--rapido]

streamlit run app.py
```

Variables de entorno: `SECOP_DELAY` (segundos entre páginas, default 2.5), `SECOP_HEADLESS=1`, `SECOP_DEBUG=1`, `CHROME_BINARY` (ruta a Chrome), `SOCRATA_APP_TOKEN` (evita throttling de la API), `SOCRATA_PAGE_SIZE`.

No hay suite de tests, linter ni CI. `demo_pipeline.py` es el único chequeo automatizable.

## Arquitectura

Dos rutas de extracción independientes, con **esquemas de columnas distintos**, que convergen en `cleaning.limpiar_dataframe()`:

```
Ruta A — SECOP I (contratos.gov.co)        Ruta B — SECOP II (API Socrata)
scraper.py   → HTML crudo por página       api_scraper.py → JSON de datos.gov.co
parser.py    → DataFrame sin tipar         (columnas COLUMNAS_API)
(columnas config.COLUMNAS_RESULTADO)                    │
             │                                          │
             └──────────► cleaning.py ◄─────────────────┘
                              │
                        CSV en output/
```

`main.py:ejecutar_modo_busqueda` respeta `--fuente`; en `auto` intenta la Ruta A y cae a la B ante cualquier excepción o si el DataFrame sale vacío. Un CSV en `output/` puede tener cualquiera de los dos esquemas — inspeccionar columnas antes de asumir.

### El dashboard consulta en vivo

`app.py` **no lee un CSV por defecto**: ejecuta el pipeline en el momento de la búsqueda, contra uno o ambos portales. La orquestación está en `consulta.py`:

- `consultar_secop2()` → API (filtros en servidor, segundos).
- `consultar_secop1()` → portal (acotado por `max_paginas`; 100 procesos por página con pausa entre ellas).
- `consultar_en_vivo()` combina fuentes, añade la columna `fuente` y devuelve `(df, informe)`. Si una fuente falla, se registra en `informe["errores"]` y se sigue con la otra: mejor resultado parcial que ninguno.

`consulta.normalizar_esquema()` es la **única** traducción de esquemas (SECOP I → el de la API, contra el que está escrito todo el dashboard). Al añadir columnas a una ruta, actualizar `EQUIVALENCIAS_SECOP1` ahí, no en `app.py`.

Reglas de la interfaz que hay que respetar al modificarla:

- **La consulta solo se dispara con el botón "Buscar en SECOP"**, nunca en el rerun de un filtro. Streamlit reejecuta el script con cada interacción; si la descarga colgara del flujo normal, cada clic golpearía el portal y el WAF bloquearía la IP.
- `_consulta_cacheada` usa `@st.cache_data(ttl=300)` indexado por los parámetros de búsqueda. El botón "Forzar descarga nueva" incrementa `_version_consulta`, que forma parte de la clave de caché.
- Los resultados viven en `st.session_state["_df"]` para sobrevivir a los reruns; los filtros de la barra lateral refinan **en local** sin volver a la red.
- El modo "Archivo CSV" sigue disponible: `CSV_PATH` se resuelve con `SECOP_CSV` o el CSV más reciente de `output/`.

### SECOP I: cómo funciona de verdad

Esto no es evidente leyendo el portal y condiciona todo el diseño de `scraper.py`:

- **El endpoint real de datos es `resultadosConsulta.do`** (`SECOP_RESULTADOS_DATA_URL`). El POST del formulario devuelve solo un cascarón con `<h2>cargando...</h2>` y un `<iframe>` que apunta a ese endpoint con los filtros en la query string. Acepta GET y **no exige token de reCAPTCHA**, así que la vía preferente (`ejecutar_scraping_http`) no usa navegador. Selenium es solo respaldo.
- **Hay que "calentar" la sesión** con un GET a `inicioConsulta.do` para obtener `JSESSIONID`; sin eso el endpoint no responde datos.
- **Todos los parámetros deben ir presentes aunque vayan vacíos.** Si falta alguno el servidor ignora los filtros y devuelve el listado completo.
- **No existe búsqueda por texto libre.** El formulario solo filtra por UNSPSC, entidad, fechas, modalidad, estado, ubicación y cuantía. `--palabra-clave` se aplica en local con `cleaning.filtrar_por_palabra_clave()` sobre lo ya descargado. En la API sí viaja al servidor.
- **`estado` es un ID numérico** (`4` = Celebrado), no el texto visible. `modalidad`, `departamento` y `cuantia` también van por código. `SearchParams.normalizada()` + `config.resolver_codigo()` aceptan indistintamente código o nombre.
- **Paginación por `paginaObjetivo`**, con `registrosXPagina=100` como máximo. El total se lee del input oculto `totalResultados`.
- **El sitio está tras un WAF (Zenedge)** que devuelve 403 *"Access to the website is blocked"* ante ráfagas. De ahí `HTTP_DELAY`, el backoff de `_get()` y `SecopBlockedError`. Al depurar contra el portal, espaciar las peticiones.
- **reCAPTCHA v3 (invisible)**: siempre inyecta un iframe y el badge `.grecaptcha-badge`. `_hay_reto_recaptcha()` solo considera reto real un widget **visible** (`api2/bframe`); detectar cualquier iframe de recaptcha da falso positivo permanente.
- La tabla de resultados **no tiene clase CSS**; se localiza por el encabezado "Número de Proceso". El enlace de detalle no es un `href` sino `javascript: consultaProceso('26-13-14700654')`; de ahí sale `id_proceso`, y la ficha se arma como `detalleProceso.do?numConstancia=<id>`.
- Los códigos oficiales (`MODALIDAD_SECOP1`, `DEPARTAMENTO_SECOP1`, `ESTADO_SECOP1`) salen de los JS del portal: `/entidades/comun/js/tProceso.js`, `/entidades/comun/js/deptos.js` y `ServletComboEstado.select?valor=<modalidad>`. Si el portal añade opciones, esa es la fuente a consultar.

### `catalogos.py` — los dos portales no nombran igual las mismas cosas

Es la **única fuente de verdad** de los valores seleccionables, y existe por un fallo real: filtrar por `"Bogotá D.C."` (el nombre de SECOP I) devolvía **cero** contratos en la API, que usa `"Distrito Capital de Bogotá"` — casi dos millones de registros invisibles, sin ningún error.

Cada `Opcion` lleva la etiqueta que se muestra, el `codigo_secop1` que espera el formulario y el `valor_api` exacto del dataset. Discrepancias verificadas:

| Concepto | SECOP I | SECOP II |
|---|---|---|
| Bogotá | `Bogotá D.C.` (cód. 1100) | `Distrito Capital de Bogotá` |
| Norte de Santander | `Norte De Santander` | `Norte de Santander` |
| Mínima cuantía | `Contratación Mínima Cuantía` | `Mínima cuantía` |
| Subasta inversa | `Subasta` | `Selección abreviada subasta inversa` |

Reglas al tocarlo:

- `valor_api` es un valor **literal** del dataset. Cuando un concepto no tiene equivalente único se usa `valores_api` (tupla): es el caso de "Celebrado", que en SECOP I es un estado del *proceso* y en SECOP II se reparte entre `Cerrado`, `En ejecución`, `Modificado`… Usar `valor_api` para eso hace que el verificador lo marque como inexistente, con razón.
- `codigo_secop1=None` o `api_valores` vacío significa que el concepto **no existe** en ese portal; el filtro se omite en vez de enviarse como literal (enviarlo devolvería cero en silencio).
- Los tipos de contrato son **solo de SECOP II**: la tabla de resultados de SECOP I no trae ese dato.
- `verificar_fuentes.verificar_catalogos()` comprueba contra el dataset que ningún `valor_api` haya desaparecido, y avisa de valores nuevos que el catálogo no ofrece. Ejecutarlo tras tocar el catálogo.

### `estudio_sector.py` — el entregable final

Genera el **Estudio del Sector** con la estructura del apartado 5.2 de la *Guía para la Elaboración de Estudios del Sector V3 (2025)* de la ANCP–CCE, en Word (`python-docx`) y PDF (`fpdf2`).

- La estadística sigue el **apartado 8** de la guía: atípicos por rango intercuartílico (`Q1 − 1,5·RIC`, `Q3 + 1,5·RIC`) y **estadísticas ajustadas** recalculadas sin ellos. No es opcional: en datos reales la media cruda salió 6× por encima de la ajustada, así que el precio de referencia se toma de la ajustada.
- Solo se automatiza lo que **se deriva de SECOP**. Lo que exige criterio de la entidad (contexto técnico y regulatorio, presupuesto oficial, requisitos habilitantes, riesgos) se emite con el marcador `_POR_COMPLETAR`; no inventar contenido ahí.
- El resolutor de fuentes TTF vive en `config.resolver_fuente_pdf()` y lo comparten `app.py` y este módulo — no duplicarlo.

### Contratos entre capas

- **`config.py` es la única fuente de verdad** de endpoints, nombres de parámetros, códigos, selectores, timeouts y `SearchParams`. Importar de ahí en vez de repetir literales.
- **Separación estricta**: `scraper.py` devuelve HTML y nunca lo interpreta; `parser.py` estructura sin convertir tipos (`cuantia` sigue siendo `'$255.000.000,00'`); `cleaning.py` es el único que tipifica. Respetar esa frontera.
- **Al añadir una modalidad, departamento o tipo de contrato** se toca un solo sitio: el catálogo. `api_scraper._traducir_*()` resuelve contra él y acepta código, nombre de SECOP I o nombre de SECOP II, sin distinguir tildes ni mayúsculas: una diferencia de una letra devuelve cero registros sin ningún error visible, así que la resolución debe seguir siendo tolerante.
- **Errores**: jerarquía tipada en `exceptions.py`, todas con un dict `context` que se serializa en `__str__`. Lanzar la específica, no `Exception`.
- **API Socrata**: se pagina con `$order=:id`. Ordenar por fecha produce empates y, al paginar por `$offset`, duplica y pierde filas. `contar_registros()` debe recibir **los mismos filtros** que `consultar_contratos()`, fechas incluidas, o el total no corresponde y la descarga se trunca.

### Formatos de datos (trampas reales)

- **El portal mezcla dos convenciones monetarias**: la tabla de resultados usa formato colombiano (`$255.000.000,00`) y la ficha de detalle usa anglosajón (`$9,062,000.00 Peso Colombiano`). `_convertir_moneda_colombiana()` deduce cuál es el separador decimal (el de más a la derecha; si uno solo aparece repetido o con 3 dígitos detrás, es de miles). No simplificar asumiendo una sola convención.
- **Fechas**: SECOP I entrega `dd-mm-yyyy`, la API entrega ISO `yyyy-mm-ddTHH:MM:SS.mmm`. `_parsear_fecha()` decide `dayfirst` según la forma de la cadena; aplicar `dayfirst=True` a una fecha ISO invierte día y mes en silencio.
- Exportación CSV siempre en `utf-8-sig` (BOM para Excel español).

## Entorno

- **Python 3.14 + pandas 3**: pandas 2.x no publica wheels para 3.13+, así que pip resuelve pandas 3, donde el dtype por defecto de strings pasó de `object` a `str`. Usar `cleaning._columnas_texto()` en vez de `select_dtypes(include=["object"])`.
- **Consola Windows**: `config.configurar_consola_utf8()` (invocado desde `setup_logging()`) fuerza UTF-8 en stdout/stderr. Sin eso, cualquier `print` con acentos, emoji o caracteres de caja lanza `UnicodeEncodeError` en cp1252 y aborta el pipeline.
- **Chrome**: `config.detectar_binario_chrome()` lo busca según el sistema operativo y admite override con `CHROME_BINARY`.

## Despliegue

**Vercel no puede alojar Streamlit** (funciones serverless de vida corta, sin WebSockets persistentes). Los destinos válidos son Streamlit Community Cloud (`requirements.txt` + `packages.txt` + `.streamlit/config.toml`, ya presentes) o cualquier host de contenedores vía el `Dockerfile`.

- La **exportación a PDF necesita una TTF Unicode**: `app._resolver_fuente_pdf()` busca DejaVu (Linux), Arial/Segoe (Windows) y Arial (macOS), y admite `PDF_FONT_DIR`. Si no encuentra ninguna, el botón se deshabilita en vez de tumbar la página. De ahí `packages.txt` con `fonts-dejavu-core`.
- El PDF se genera **bajo demanda** (botón + `session_state`), no en cada rerun: construirlo es caro y una excepción ahí rompería toda la página.
- `config._asegurar_directorio()` degrada a aviso el fallo de `mkdir`, porque `config.py` se importa al arrancar la app y muchos PaaS montan el FS en solo lectura.
- El FS de esos hosts es **efímero**: los CSV descargados desde la app se pierden al reiniciar. Para un panel permanentemente actualizado hay que programar el pipeline fuera y apuntar `SECOP_CSV` a un almacenamiento persistente.

## Pendientes conocidos

- `output/` y `logs/` se crean como efecto secundario de importar `config.py`; su contenido está ignorado por git.
- `.github/workflows/verificar-fuentes.yml` ejecuta `verificar_fuentes.py --rapido` cada lunes; omite SECOP I porque el WAF bloquea las IP de los runners compartidos.
