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

## Licencia

MIT