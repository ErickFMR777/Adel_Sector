# Adel_Sector — Pipeline de Scraping SECOP I

Pipeline automatizado de extracción, parsing y limpieza de datos de contratación pública del portal **SECOP I** ([contratos.gov.co](https://www.contratos.gov.co)).

---

## Arquitectura

```
Selenium (scraper.py)
    │
    ├── Formulario dinámico (palabra clave, fechas, modalidad, departamento)
    ├── Manejo robusto de iframe
    ├── Paginación automática (todas las páginas)
    └── Detección de reCAPTCHA
    │
    ▼
BeautifulSoup (parser.py)
    │
    ├── Localización inteligente de tabla (3 estrategias)
    ├── Extracción de encabezados y filas
    ├── URLs de detalle por proceso
    └── Consolidación multi-página
    │
    ▼
Pandas (cleaning.py)
    │
    ├── Normalización de strings
    ├── Conversión monetaria colombiana → float
    ├── Parseo de fechas (múltiples formatos)
    ├── Eliminación de filas vacías
    └── Reporte de calidad de datos
    │
    ▼
CSV / Parquet (output/)
```

## Estructura del Proyecto

```
Adel_Sector/
├── config.py            # Constantes, selectores, logging, SearchParams
├── exceptions.py        # Excepciones personalizadas del pipeline
├── scraper.py           # Automatización Selenium (formulario, iframe, paginación)
├── parser.py            # Parsing HTML → DataFrame estructurado
├── cleaning.py          # Limpieza y tipificación de datos
├── detail_scraper.py    # Extracción de detalles individuales de proceso
├── main.py              # Orquestador CLI (punto de entrada)
├── requirements.txt     # Dependencias Python
├── output/              # Archivos CSV/Parquet generados (auto-creado)
├── logs/                # Logs rotativos del pipeline (auto-creado)
└── README.md
```

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/ErickFMR777/Adel_Sector.git
cd Adel_Sector

# Crear entorno virtual (recomendado)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt
```

> **Requisito:** Google Chrome debe estar instalado en el sistema. `webdriver-manager` descarga ChromeDriver automáticamente.

## Uso

### Modo Búsqueda (por defecto)

Rellena el formulario de SECOP I con los parámetros dados, extrae la tabla de resultados completa (todas las páginas) y exporta un CSV limpio.

```bash
# Búsqueda por palabra clave
python main.py --palabra-clave "vigilancia"

# Búsqueda con filtros completos
python main.py \
    --palabra-clave "consultoría" \
    --fecha-inicio "01/01/2025" \
    --fecha-fin "30/06/2025" \
    --departamento "ANTIOQUIA" \
    --modalidad "Licitación pública" \
    --salida output/consultoria_antioquia.csv

# Con salida personalizada y límite de páginas
python main.py \
    --palabra-clave "obra civil" \
    --max-paginas 10 \
    --salida output/obra_civil.csv
```

### Modo Detalle

Toma un CSV previamente generado (con columna `url_detalle`) e ingresa a cada proceso individual para extraer datos enriquecidos (proveedor, NIT, valor adjudicado, etc.).

```bash
python main.py \
    --modo detalle \
    --entrada output/consultoria_antioquia.csv \
    --salida output/detalles_antioquia.csv

# Con base histórica incremental
python main.py \
    --modo detalle \
    --entrada output/resultados.csv \
    --historica output/base_historica.csv
```

### Variables de Entorno

| Variable | Valor | Descripción |
|---|---|---|
| `SECOP_HEADLESS` | `0` / `1` | Ejecutar Chrome sin ventana visible |
| `SECOP_DEBUG` | `0` / `1` | Logging nivel DEBUG (más verboso) |

```bash
# Modo headless + debug
SECOP_HEADLESS=1 SECOP_DEBUG=1 python main.py --palabra-clave "vigilancia"
```

### Todos los argumentos

```
python main.py --help
```

| Argumento | Alias | Descripción |
|---|---|---|
| `--modo` | | `busqueda` (default) o `detalle` |
| `--palabra-clave` | `-k` | Objeto del contrato (texto libre) |
| `--numero-proceso` | | Número específico de proceso |
| `--entidad` | | Nombre (parcial) de la entidad |
| `--fecha-inicio` | `-fi` | Fecha apertura desde (`dd/MM/yyyy`) |
| `--fecha-fin` | `-ff` | Fecha apertura hasta (`dd/MM/yyyy`) |
| `--modalidad` | `-m` | Modalidad de contratación |
| `--departamento` | `-d` | Departamento |
| `--municipio` | | Municipio |
| `--estado` | | Estado del proceso |
| `--max-paginas` | | Límite de páginas (default: 200) |
| `--entrada` | `-i` | Archivo CSV de entrada (modo detalle) |
| `--salida` | `-o` | Ruta del archivo de salida |
| `--historica` | | Ruta de base histórica incremental |
| `--delay-detalle` | | Segundos entre cada detalle (default: 1.5) |
| `--debug` | | Activar logging DEBUG |

## Campos Extraídos

### Tabla de Resultados (modo búsqueda)

| Columna | Descripción |
|---|---|
| `numero_proceso` | Identificador único del proceso |
| `entidad` | Entidad compradora |
| `objeto_contrato` | Descripción del objeto a contratar |
| `modalidad` | Modalidad de contratación |
| `fecha_apertura` | Fecha de apertura del proceso |
| `fecha_cierre` | Fecha de cierre |
| `cuantia` | Valor estimado (COP) |
| `estado` | Estado actual del proceso |
| `departamento` | Departamento |
| `municipio` | Municipio |
| `url_detalle` | URL para acceder a la ficha individual |

### Detalle Individual (modo detalle)

Incluye todos los campos anteriores más:

| Columna | Descripción |
|---|---|
| `valor_estimado` | Presupuesto estimado (COP) |
| `valor_adjudicado` | Valor de adjudicación (COP) |
| `valor_contrato` | Valor del contrato (COP) |
| `proveedor` | Razón social del contratista adjudicado |
| `nit_proveedor` | NIT del proveedor |
| `fecha_adjudicacion` | Fecha de adjudicación |

## Manejo de Errores

El pipeline define excepciones tipadas en `exceptions.py`:

| Excepción | Cuándo se lanza |
|---|---|
| `SecopTimeoutError` | Elemento no cargó dentro del timeout |
| `SecopRecaptchaError` | reCAPTCHA detectado (pausa para resolución manual) |
| `SecopIframeError` | No se pudo acceder al iframe de resultados |
| `SecopEmptyTableError` | La consulta retornó 0 registros |
| `SecopFormError` | Error al interactuar con el formulario |
| `SecopPaginationError` | Error navegando entre páginas |
| `SecopParsingError` | Error al parsear el HTML |
| `SecopExportError` | Error al guardar el archivo |

Cada excepción lleva un `context` dict para depuración detallada en los logs.

## Logging

Los logs se guardan en `logs/secop_pipeline.log` (rotativo, 5 MB × 5 backups) y se imprimen en consola.

```
2025-06-15 14:30:22 | INFO     | scraper              | rellenar_formulario   | Formulario rellenado: palabra_clave='vigilancia', ...
2025-06-15 14:30:25 | INFO     | scraper              | cambiar_a_iframe      | Cambio a iframe 'iframeVentana' exitoso.
2025-06-15 14:30:28 | INFO     | scraper              | recopilar_html_paginas| Recopilando página 1...
```

## Escalabilidad

El proyecto está diseñado para crecer:

1. **`detail_scraper.py`**: Ya soporta extracción masiva con rate limiting y base histórica incremental.
2. **`actualizar_base_historica()`**: Combina datos nuevos con un CSV/Parquet existente, deduplicando por `numero_proceso`.
3. **`SearchParams`**: Dataclass inmutable que facilita crear scripts de barrido por departamento, modalidad, etc.

```python
# Ejemplo: barrido por departamento
from config import SearchParams
from scraper import ejecutar_scraping

departamentos = ["BOGOTÁ D.C.", "ANTIOQUIA", "VALLE DEL CAUCA"]

for depto in departamentos:
    params = SearchParams(
        palabra_clave="consultoría",
        departamento=depto,
        fecha_inicio="01/01/2025",
        fecha_fin="31/12/2025",
    )
    html_pages, urls = ejecutar_scraping(params)
    # ... parsear y guardar por departamento
```

## El dashboard consulta en vivo

`app.py` **no muestra un archivo viejo**: consulta los portales en el
momento de la búsqueda. Se define el alcance en la barra lateral
(portales, departamento, modalidad, estado, fechas) y se pulsa
**🔎 Buscar en SECOP**.

| | SECOP II (API) | SECOP I (portal) |
|---|---|---|
| Velocidad | segundos | ~4 s por página de 100 procesos |
| Filtros | en el servidor, incluido el texto libre | en local sobre lo descargado |
| Frescura | rezago de publicación de unos días | tiempo real |
| Límite | ninguno relevante | `Páginas de SECOP I` en la barra lateral |

Consultar los dos a la vez da la imagen más completa: SECOP II aporta el
detalle de los contratos ya formalizados y SECOP I los procesos más
recientes. La columna `fuente` indica de dónde viene cada fila.

### Filtros disponibles

Todos son desplegables, no campos de texto: se elige de una lista y la
aplicación envía a cada portal el valor exacto que ese portal espera.
Así no hay forma de fallar por una tilde o una mayúscula.

| Filtro | Opciones | Alcance |
|---|---|---|
| Departamento | los 33 departamentos + **Todo el país** | ambos portales |
| Modalidad | 27, anotadas si solo existen en un portal | ambos |
| Tipo de contrato | 24 (Obra, Consultoría, Interventoría…) | solo SECOP II |
| Estado | 19 | ambos |
| Fechas, palabra clave | libres | ambos |

La consulta **nacional** (sin departamento) da el panorama completo del
país. Como son casi 6 millones de contratos, hay un tope configurable de
descarga; si la consulta lo supera, la aplicación avisa cuántos
coincidían en total para que puedas acotar.

> Los dos portales no nombran igual las mismas cosas: la API llama
> "Distrito Capital de Bogotá" a lo que SECOP I llama "Bogotá D.C.".
> `catalogos.py` guarda esas equivalencias; por eso los filtros son
> desplegables y no texto libre.

**Por qué la consulta va con botón y no automática:** Streamlit reejecuta
el script con cada interacción. Si la descarga colgara del flujo normal,
mover un filtro dispararía una petición al portal y el WAF de
contratos.gov.co bloquearía la IP en minutos. Por eso la descarga solo
ocurre al pulsar el botón, hay una caché de 5 minutos por combinación de
filtros, y los controles de "Refinar resultados" trabajan en local.

El modo **Archivo CSV** sigue disponible en la barra lateral para abrir
descargas previas sin tocar la red.

## Estudio del Sector (Guía V3 de Colombia Compra Eficiente)

La pestaña **📑 Estudio del Sector** genera el documento con la
estructura del apartado 5.2 de la [Guía para la Elaboración de Estudios
del Sector V3 (2025)](https://www.colombiacompra.gov.co/wp-content/uploads/2025/09/Guia-para-la-Elaboracion-de-Estudios-del-Sector-V3.pdf)
de la ANCP–CCE, exportable a **Word** y **PDF**:

| Numeral de la guía | Contenido generado |
|---|---|
| 5.2.1 Aspectos generales | Encabezado y contextos (guiados) |
| 5.2.3 Gasto histórico — **demanda** | Modalidades, tipos de contrato, entidades, comportamiento anual y estacionalidad |
| 5.2.4 Estudio de la **oferta** | Proveedores identificados y concentración del mercado |
| 5.2.5 Estudio de **mercado** | Análisis de precios completo (ver abajo) |
| 5.2.6 **Conclusiones** | Precio de referencia, rango, oferentes, modalidad predominante |
| Anexo | Relación contrato por contrato (proceso, contratista, objeto, valor, plazo, enlace) |

El análisis estadístico sigue el apartado 8 de la guía: tendencia
central, dispersión (incluido el coeficiente de variación), medidas de
posición, **identificación de datos atípicos por rango intercuartílico**
y **estadísticas descriptivas ajustadas**.

Ese último punto no es un adorno. En una prueba real sobre 459 contratos
de obra en Santander:

```
Media sin ajustar : $1.092.848.668
Media ajustada    :   $180.556.942   ← tras excluir 59 atípicos (12,9 %)
Coef. de variación: 396 %
```

Tomar el promedio simple habría inflado el precio de referencia seis
veces. Por eso la guía exige el ajuste y por eso el documento propone
como precio de referencia la media ajustada, dejando constancia del
criterio.

El anexo detalla los 50 contratos de mayor valor: el documento lleva una
ficha por contrato, y sin ese tope una consulta de 20.000 registros
tardaría minutos y pesaría decenas de MB. El CSV de la pestaña de
resultados sí incluye todos.

> Los apartados que dependen del criterio de la entidad —contexto
> técnico y regulatorio, presupuesto oficial, requisitos habilitantes,
> riesgos— se emiten señalados como *«Por completar por la Entidad
> Estatal»*. No se inventan.

## Despliegue del dashboard

> **Vercel no sirve para esta aplicación.** Streamlit necesita un proceso
> servidor de larga vida que mantiene una conexión WebSocket con cada
> navegador; Vercel ejecuta funciones serverless de vida corta y sin
> WebSockets persistentes. No existe una forma soportada de alojar
> Streamlit ahí. Usa cualquiera de las opciones de abajo.

### Opción A — Streamlit Community Cloud (recomendada, gratis)

1. Sube el repositorio a GitHub.
2. Entra en [share.streamlit.io](https://share.streamlit.io) → *New app*.
3. Selecciona el repo, la rama y `app.py` como archivo principal.
4. *Deploy*.

El repositorio ya trae lo que necesita esa plataforma:

| Archivo | Para qué |
|---|---|
| `requirements.txt` | dependencias de Python |
| `packages.txt` | `fonts-dejavu-core`, necesario para exportar a PDF |
| `.streamlit/config.toml` | tema oscuro y ajustes del servidor |

Como `output/` está en `.gitignore`, la instancia arranca sin datos y
muestra una pestaña **"Descargar de SECOP"** para traerlos desde la API
en el momento. También puedes subir un CSV a mano.

### Opción B — Contenedor (Render, Railway, Fly.io, HF Spaces, Cloud Run)

```bash
docker build -t adel-sector .
docker run -p 8501:8501 adel-sector
```

La imagen instala `fonts-dejavu-core` y respeta la variable `PORT` que
inyectan Render y Railway. En esos servicios basta con apuntar al
`Dockerfile`; no hace falta configurar el comando de arranque.

### Variables de entorno del dashboard

| Variable | Efecto |
|---|---|
| `SECOP_CSV` | Ruta a un CSV concreto en vez de autodetectar el más reciente de `output/` |
| `PDF_FONT_DIR` | Carpeta con `DejaVuSans.ttf` si el sistema no trae ninguna fuente TrueType |
| `SOCRATA_APP_TOKEN` | Evita el *throttling* de la API al descargar desde la app |

### Persistencia de los datos

El sistema de archivos de Streamlit Cloud y de la mayoría de PaaS es
**efímero**: los CSV descargados desde la app se pierden al reiniciar el
contenedor. Para un panel que deba mantenerse actualizado sin
intervención, las opciones son:

- Programar `python main.py --fuente api ...` en una máquina propia y
  publicar el CSV en un almacenamiento persistente (S3, un volumen), y
  apuntar `SECOP_CSV` ahí.
- O versionar un CSV base en el repositorio y usar el botón
  *"Actualizar desde SECOP"* de la barra lateral cuando haga falta.

## Verificación de las fuentes

Los portales cambian sin avisar. El riesgo real no es que el scraper
falle con estrépito —eso se nota— sino que siga corriendo y devuelva
datos vacíos o sin filtrar. Para detectarlo:

```bash
python verificar_fuentes.py            # informe completo
python verificar_fuentes.py --rapido   # solo la API (no toca SECOP I)
```

Comprueba que el formulario conserve sus campos, que los filtros se
apliquen de verdad, que los códigos de modalidad y departamento sigan
alineados con los del portal, y cuánto tiempo hace que se actualizó cada
fuente. Devuelve código de salida 1 si algo se rompió, así que se puede
programar en cron o en GitHub Actions.

## Licencia

MIT