"""
app.py — Buscador de contratos SECOP y Análisis de Demanda (Streamlit).

Usa el CSV exportado como base de datos local.
Permite buscar contratos por palabras clave en el objeto del contrato,
filtrar por ciudad/tipo/estado, y generar un informe formal de
Análisis de la Demanda con los contratos seleccionados.
"""

import os
import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

# ────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"


def _descubrir_csv() -> Path | None:
    """Localiza el CSV de contratos más reciente.

    Antes se apuntaba a un archivo con timestamp fijo que además está en
    ``.gitignore``, así que en cualquier despliegue nuevo la app arrancaba
    sin datos. Ahora se resuelve por orden de preferencia:

      1. Variable de entorno ``SECOP_CSV`` (útil en producción).
      2. El CSV más reciente de ``output/``.

    Returns:
        Ruta al CSV, o ``None`` si no hay ninguno (la app pedirá subirlo).
    """
    ruta_env = os.getenv("SECOP_CSV")
    if ruta_env and Path(ruta_env).exists():
        return Path(ruta_env)

    if not OUTPUT_DIR.exists():
        return None

    candidatos = sorted(
        OUTPUT_DIR.glob("*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidatos[0] if candidatos else None


CSV_PATH = _descubrir_csv()

st.set_page_config(
    page_title="Análisis del Sector SECOP — Santander",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ────────────────────────────────────────────────────────────
# ESTILOS CSS PERSONALIZADOS
# ────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ══════════════════════════════════════════════════════════
   SECOP Análisis del Sector — Dark Professional Theme
   Inspired by modern SaaS dashboards
   ══════════════════════════════════════════════════════════ */

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* ── Fondo oscuro global ── */
.stApp, .main {
    background-color: #0d1117 !important;
}
header[data-testid="stHeader"] { background: transparent !important; }
.block-container { padding-top: 0.5rem !important; max-width: 1200px; }

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   HERO SECTION — Gradiente profundo
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.main-header {
    background: linear-gradient(135deg, #050d1a 0%, #0a1628 20%, #0f2847 45%, #162f5a 65%, #1e3a6e 80%, #2a4a82 100%);
    padding: 3rem 3.5rem 2.5rem 3.5rem;
    border-radius: 18px;
    margin-bottom: 1.8rem;
    color: #ffffff;
    box-shadow: 0 12px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05);
    position: relative;
    overflow: hidden;
}
.main-header::before {
    content: '';
    position: absolute; top: -50%; right: -20%;
    width: 500px; height: 500px;
    background: radial-gradient(circle, rgba(99,102,241,0.12) 0%, rgba(59,130,246,0.06) 40%, transparent 70%);
    pointer-events: none;
}
.main-header::after {
    content: '';
    position: absolute; bottom: -30%; left: 10%;
    width: 400px; height: 400px;
    background: radial-gradient(circle, rgba(6,182,212,0.08) 0%, transparent 60%);
    pointer-events: none;
}
.hero-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(16,185,129,0.12);
    border: 1px solid rgba(16,185,129,0.25);
    padding: 0.35rem 1rem;
    border-radius: 20px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #34d399;
    margin-bottom: 1rem;
}
.hero-badge::before {
    content: '';
    width: 7px; height: 7px;
    background: #10b981;
    border-radius: 50%;
    box-shadow: 0 0 6px rgba(16,185,129,0.5);
}
.main-header h1 {
    margin: 0; font-size: 2.6rem; font-weight: 900;
    letter-spacing: -1px; color: #ffffff;
    line-height: 1.1;
    text-shadow: 0 2px 10px rgba(0,0,0,0.3);
}
.hero-line {
    width: 60px; height: 3px;
    background: linear-gradient(90deg, #3b82f6, #6366f1);
    border-radius: 2px;
    margin: 1rem 0;
}
.main-header .hero-desc {
    margin: 0; font-size: 0.92rem;
    color: #94a3b8; font-weight: 400;
    max-width: 600px; line-height: 1.5;
}
.hero-stats {
    display: flex; gap: 2.5rem;
    margin-top: 1.5rem;
    padding-top: 1.2rem;
    border-top: 1px solid rgba(255,255,255,0.06);
}
.hero-stat .hs-value {
    font-size: 1.4rem; font-weight: 800;
    color: #ffffff;
}
.hero-stat .hs-label {
    font-size: 0.62rem; font-weight: 600;
    color: #64748b; text-transform: uppercase;
    letter-spacing: 0.8px; margin-top: 2px;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   FEATURE CARDS — Con línea gradiente superior
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.feature-cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.feature-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 14px;
    padding: 1.5rem 1.2rem;
    text-align: center;
    position: relative;
    overflow: hidden;
    transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
}
.feature-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 3px;
}
.feature-card:nth-child(1)::before { background: linear-gradient(90deg, #3b82f6, #6366f1); }
.feature-card:nth-child(2)::before { background: linear-gradient(90deg, #f43f5e, #ec4899); }
.feature-card:nth-child(3)::before { background: linear-gradient(90deg, #10b981, #06b6d4); }
.feature-card:nth-child(4)::before { background: linear-gradient(90deg, #f59e0b, #ef4444); }
.feature-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
    border-color: #30363d;
}
.feature-card .fc-icon {
    width: 48px; height: 48px;
    border-radius: 12px;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 1.4rem;
    margin-bottom: 0.7rem;
}
.feature-card:nth-child(1) .fc-icon { background: rgba(59,130,246,0.12); }
.feature-card:nth-child(2) .fc-icon { background: rgba(244,63,94,0.12); }
.feature-card:nth-child(3) .fc-icon { background: rgba(16,185,129,0.12); }
.feature-card:nth-child(4) .fc-icon { background: rgba(245,158,11,0.12); }
.feature-card .fc-title {
    font-size: 0.82rem; font-weight: 700; color: #e2e8f0;
    margin-bottom: 0.3rem;
}
.feature-card .fc-desc {
    font-size: 0.7rem; color: #64748b;
    line-height: 1.4;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   TARJETAS DE MÉTRICAS — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.metric-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 14px;
    padding: 1.4rem 1rem;
    text-align: center;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #3b82f6, #6366f1);
}
.metric-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
}
.metric-card .metric-icon {
    font-size: 1.5rem; margin-bottom: 0.4rem;
}
.metric-card .metric-value {
    font-size: 1.7rem; font-weight: 800; color: #f0f6fc;
    margin: 0.25rem 0; line-height: 1.2;
}
.metric-card .metric-label {
    font-size: 0.68rem; color: #8b949e; text-transform: uppercase;
    letter-spacing: 0.7px; font-weight: 600;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   SIDEBAR — Tema oscuro profesional
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
section[data-testid="stSidebar"] {
    background: #0d1117 !important;
    border-right: 1px solid #21262d !important;
}
section[data-testid="stSidebar"] > div {
    padding-top: 0.5rem;
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] span {
    color: #c9d1d9 !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stMultiSelect > div > div {
    background: #161b22 !important;
    border-color: #30363d !important;
    color: #c9d1d9 !important;
}
section[data-testid="stSidebar"] .stSlider > div > div > div {
    color: #c9d1d9 !important;
}

/* Sidebar brand */
.sidebar-brand {
    background: linear-gradient(135deg, #0a1628, #162f5a);
    margin: -1rem -1rem 1.2rem -1rem;
    padding: 1.6rem 1.2rem;
    border-radius: 0 0 14px 14px;
    text-align: center;
    border-bottom: 1px solid rgba(59,130,246,0.15);
}
.sidebar-brand h3 {
    color: #f0f6fc; margin: 0; font-size: 1.05rem;
    font-weight: 800; letter-spacing: 0.3px;
}
.sidebar-brand p {
    color: #64748b; margin: 0.4rem 0 0 0;
    font-size: 0.72rem; font-weight: 400;
}

/* Section labels in sidebar */
.filter-label {
    font-size: 0.78rem; font-weight: 700; color: #c9d1d9;
    margin: 0.8rem 0 0.3rem 0; padding: 0;
    display: flex; align-items: center; gap: 0.4rem;
}
.filter-label .fl-icon {
    display: inline-flex; align-items: center;
    justify-content: center; width: 24px; height: 24px;
    background: rgba(59,130,246,0.1); border-radius: 7px; font-size: 0.7rem;
}

/* Sidebar divider */
.sidebar-divider {
    height: 1px; background: #21262d;
    margin: 1rem 0; border: none;
}

/* DB counter card in sidebar */
.db-counter {
    text-align: center; padding: 1.1rem;
    background: linear-gradient(135deg, #0a1628, #162f5a);
    border-radius: 12px;
    margin-top: 0.5rem;
    border: 1px solid rgba(59,130,246,0.12);
}
.db-counter .db-label {
    color: #64748b; font-size: 0.68rem;
    text-transform: uppercase; font-weight: 700;
    letter-spacing: 1px;
}
.db-counter .db-value {
    color: #f0f6fc; font-size: 1.6rem;
    font-weight: 900; margin: 0.2rem 0;
}
.db-counter .db-sub {
    color: #475569; font-size: 0.68rem; font-weight: 400;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BARRA DE BÚSQUEDA — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.search-container {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 14px;
    padding: 1.1rem 1.4rem;
    margin-bottom: 1.2rem;
    transition: border-color 0.3s, box-shadow 0.3s;
}
.search-container:focus-within {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59,130,246,0.12);
}
.search-hint {
    font-size: 0.78rem; color: #8b949e;
    margin-top: 0.4rem;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   INPUTS globales — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.stTextInput > div > div > input {
    background: #0d1117 !important;
    border-color: #30363d !important;
    color: #c9d1d9 !important;
    border-radius: 10px !important;
}
.stTextInput > div > div > input::placeholder {
    color: #484f58 !important;
}
.stTextInput > div > div > input:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   TABLA DE DATOS — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    border: 1px solid #21262d;
}

/* Tabs — Tema oscuro */
button[data-baseweb="tab"] {
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: #8b949e !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #f0f6fc !important;
}
div[data-baseweb="tab-list"] {
    background: #161b22 !important;
    border-radius: 10px;
    padding: 4px;
    border: 1px solid #21262d;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ANÁLISIS HEADER — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.analisis-header {
    background: linear-gradient(135deg, #050d1a 0%, #0f2847 50%, #1e3a6e 100%);
    color: #ffffff;
    padding: 1.5rem 2.2rem;
    border-radius: 14px;
    margin: 1rem 0;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    border: 1px solid rgba(59,130,246,0.1);
}
.analisis-header h2 {
    margin: 0; font-size: 1.3rem; font-weight: 800;
    color: #ffffff;
}
.analisis-header p {
    color: #94a3b8;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ESTADÍSTICOS — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.8rem;
    margin: 1rem 0 1.5rem 0;
}
.stat-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 1.1rem 1.2rem;
    border-left: 3px solid #3b82f6;
    transition: border-color 0.2s, transform 0.2s;
}
.stat-card:hover {
    border-left-color: #6366f1;
    transform: translateX(2px);
}
.stat-card .stat-title {
    font-size: 0.65rem; font-weight: 700;
    color: #8b949e; text-transform: uppercase;
    letter-spacing: 0.6px; margin-bottom: 0.3rem;
}
.stat-card .stat-value {
    font-size: 1.25rem; font-weight: 800;
    color: #f0f6fc; margin-bottom: 0.15rem;
}
.stat-card .stat-sub {
    font-size: 0.68rem; color: #484f58;
}
.stats-section-title {
    font-size: 0.9rem; font-weight: 700; color: #c9d1d9;
    margin: 1.2rem 0 0.6rem 0;
    display: flex; align-items: center; gap: 0.5rem;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   FICHAS DE CONTRATO — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.contract-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 14px;
    padding: 0;
    margin: 1.2rem 0;
    overflow: hidden;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    transition: box-shadow 0.2s, border-color 0.2s;
}
.contract-card:hover {
    box-shadow: 0 8px 32px rgba(0,0,0,0.45);
    border-color: #30363d;
}
.contract-card-header {
    background: linear-gradient(135deg, #0a1628, #162f5a);
    color: #f0f6fc;
    padding: 0.8rem 1.4rem;
    font-weight: 700;
    font-size: 0.82rem;
    letter-spacing: 0.5px;
    border-bottom: 1px solid rgba(59,130,246,0.12);
}
.contract-card table {
    width: 100%; border-collapse: collapse;
}
.contract-card table td {
    padding: 0.6rem 1.1rem;
    font-size: 0.8rem;
    color: #c9d1d9;
    border-bottom: 1px solid #21262d;
    vertical-align: top;
    line-height: 1.4;
}
.contract-card table td:first-child {
    width: 170px;
    font-weight: 700;
    color: #8b949e;
    background: rgba(13,17,23,0.5);
    border-right: 1px solid #21262d;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.contract-card table tr:last-child td {
    border-bottom: none;
}
.contract-card table tr:hover td {
    background: rgba(59,130,246,0.03);
}
.contract-card table tr:hover td:first-child {
    background: rgba(59,130,246,0.06);
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   BOTONES DE DESCARGA — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.stDownloadButton > button {
    background: linear-gradient(135deg, #1e3a6e, #3b82f6) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.65rem 1.6rem !important;
    font-weight: 700 !important;
    font-size: 0.82rem !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 4px 14px rgba(59,130,246,0.3) !important;
    letter-spacing: 0.2px !important;
}
.stDownloadButton > button:hover {
    background: linear-gradient(135deg, #2a4a82, #6366f1) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 24px rgba(59,130,246,0.4) !important;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   UTILIDADES — Tema oscuro
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
.custom-divider {
    height: 1px;
    background: linear-gradient(90deg, #3b82f6 0%, #6366f1 30%, transparent 100%);
    margin: 1.8rem 0;
    border: none;
}

/* Empty state — Tema oscuro */
.empty-state {
    text-align: center; padding: 3.5rem 2rem;
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 14px;
}
.empty-state .es-icon {
    font-size: 2.8rem; margin-bottom: 0.5rem;
}
.empty-state .es-title {
    font-size: 1.05rem; font-weight: 600; color: #c9d1d9;
    margin: 0.3rem 0;
}
.empty-state .es-desc {
    font-size: 0.82rem; color: #8b949e;
}

/* Markdown text colors */
.stMarkdown, .stMarkdown p, .stMarkdown li {
    color: #c9d1d9 !important;
}
.stMarkdown a { color: #58a6ff !important; }

/* Success count pill */
.result-pill {
    display: inline-block;
    background: rgba(16,185,129,0.12); color: #34d399;
    border: 1px solid rgba(16,185,129,0.2);
    padding: 0.3rem 1rem; border-radius: 20px;
    font-size: 0.78rem; font-weight: 600;
    margin-bottom: 0.8rem;
}

/* Scrollbar */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: #0d1117; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484f58; }
</style>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────────────────
# CARGA DE DATOS
# ────────────────────────────────────────────────────────────


# La normalización de esquemas vive en consulta.py, que es la que usan
# tanto la consulta en vivo como la carga de archivos.
from config import resolver_fuente_pdf  # noqa: E402
from catalogos import (  # noqa: E402
    DEPARTAMENTOS,
    ESTADOS,
    MODALIDADES,
    NACIONAL,
    TIPOS_CONTRATO,
    opciones_desplegable,
)
from consulta import normalizar_esquema  # noqa: E402


@st.cache_data(show_spinner="Cargando contratos...")
def cargar_datos(
    path: Path | None = None,
    uploaded_file=None,
    _firma: str = "",
) -> pd.DataFrame:
    """Carga el CSV desde disco o desde un archivo subido por el usuario.

    Args:
        path:          Ruta al CSV en disco.
        uploaded_file: Archivo subido vía ``st.file_uploader``.
        _firma:        Cadena que invalida la caché cuando cambia el
                       archivo (ruta + fecha de modificación).

    Returns:
        DataFrame con el esquema del dashboard ya tipado.
    """
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file, dtype=str)
    elif path is not None and Path(path).exists():
        df = pd.read_csv(path, dtype=str)
    else:
        raise FileNotFoundError(f"No se encontró el archivo de datos: {path}")

    df = normalizar_esquema(df)

    df["valor_del_contrato"] = pd.to_numeric(
        df["valor_del_contrato"], errors="coerce"
    )
    df["valor_pagado"] = pd.to_numeric(df["valor_pagado"], errors="coerce")
    df["fecha_inicio"] = pd.to_datetime(
        df["fecha_de_inicio_del_contrato"], errors="coerce", format="mixed"
    )
    df["fecha_fin"] = pd.to_datetime(
        df["fecha_de_fin_del_contrato"], errors="coerce", format="mixed"
    )
    # Columna de búsqueda normalizada (minúsculas)
    df["_busqueda"] = (
        df["objeto_del_contrato"].astype("string").fillna("").str.lower()
    )
    return df


def buscar(df: pd.DataFrame, texto: str) -> pd.DataFrame:
    """Busca contratos cuyo objeto contenga TODAS las palabras clave.

    Cada palabra se busca de forma independiente (AND lógico).
    Soporta búsqueda parcial — no requiere coincidencia exacta.
    """
    if not texto.strip():
        return df

    palabras = texto.lower().split()
    mascara = pd.Series([True] * len(df), index=df.index)

    for palabra in palabras:
        # Escapar caracteres regex especiales del input
        palabra_safe = re.escape(palabra)
        mascara &= df["_busqueda"].str.contains(palabra_safe, na=False)

    return df[mascara]


# ────────────────────────────────────────────────────────────
# FUNCIONES DE EXPORTACIÓN
# ────────────────────────────────────────────────────────────


def _extraer_url(url_raw: str) -> str:
    """Extrae URL limpia del campo urlproceso."""
    url_raw = str(url_raw)
    if "url" in url_raw and "secop.gov.co" in url_raw:
        import ast
        try:
            url_dict = ast.literal_eval(url_raw)
            return url_dict.get("url", url_raw)
        except Exception:
            return url_raw
    return url_raw if url_raw and url_raw != "nan" else "N/D"


def _calcular_plazo(row) -> str:
    """Calcula el plazo entre fecha inicio y fin."""
    f_ini = row.get("fecha_inicio")
    f_fin = row.get("fecha_fin")
    if pd.notna(f_ini) and pd.notna(f_fin):
        dias = (f_fin - f_ini).days
        if dias >= 30:
            meses = round(dias / 30)
            return f"{meses} {'MES' if meses == 1 else 'MESES'} ({dias} días)"
        return f"{dias} DÍAS"
    return "N/D"


def _generar_informe_texto(contratos: pd.DataFrame) -> str:
    """Genera el informe de Análisis de Demanda en texto plano."""
    lineas = []
    lineas.append("ANÁLISIS DE LA DEMANDA")
    lineas.append("=" * 70)
    lineas.append("")
    lineas.append(
        "Se validan en el portal de contratación SECOP procesos adelantados "
        "en los últimos años por algunas entidades estatales del departamento "
        "y por este municipio para satisfacer las necesidades requeridas."
    )
    lineas.append(
        "De acuerdo a la consulta en el portal único de contratación estatal — "
        "SECOP www.colombiacompra.gov.co, se observa la siguiente información:"
    )
    lineas.append("")

    for idx, (_, row) in enumerate(contratos.iterrows(), 1):
        proceso = str(row.get("proceso_de_compra", "N/D"))
        modalidad = str(row.get("modalidad_de_contratacion", "N/D")).upper()
        contratista = str(row.get("proveedor_adjudicado", "N/D")).upper()
        entidad = str(row.get("nombre_entidad", "N/D")).upper()
        ciudad = str(row.get("ciudad", "")).upper()
        contratante = f"{entidad}, {ciudad}" if ciudad else entidad
        objeto = str(row.get("objeto_del_contrato", "N/D")).upper()
        valor = row.get("valor_del_contrato", 0)
        valor_fmt = f"$ {valor:,.0f}" if pd.notna(valor) else "N/D"
        plazo = _calcular_plazo(row)
        enlace = _extraer_url(str(row.get("urlproceso", "")))

        lineas.append(f"{'─' * 70}")
        lineas.append(f"CONTRATO {idx}")
        lineas.append(f"{'─' * 70}")
        lineas.append(f"{'No PROCESO SECOP':<20} {proceso}")
        lineas.append(f"{'MODALIDAD':<20} {modalidad}")
        lineas.append(f"{'CONTRATISTA':<20} {contratista}")
        lineas.append(f"{'CONTRATANTE':<20} {contratante}")
        lineas.append(f"{'OBJETO':<20} {objeto}")
        lineas.append(f"{'VALOR':<20} {valor_fmt}")
        lineas.append(f"{'PLAZO':<20} {plazo}")
        lineas.append(f"{'ENLACE':<20} {enlace}")
        lineas.append(f"{'OBSERVACIONES':<20} Se evidencia adicional al contrato")
        lineas.append("")

    lineas.append(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    return "\n".join(lineas)


def _generar_informe_excel(contratos: pd.DataFrame) -> bytes:
    """Genera el informe de Análisis de Demanda en formato Excel."""
    filas = []
    for idx, (_, row) in enumerate(contratos.iterrows(), 1):
        proceso = str(row.get("proceso_de_compra", "N/D"))
        modalidad = str(row.get("modalidad_de_contratacion", "N/D")).upper()
        contratista = str(row.get("proveedor_adjudicado", "N/D")).upper()
        entidad = str(row.get("nombre_entidad", "N/D")).upper()
        ciudad = str(row.get("ciudad", "")).upper()
        contratante = f"{entidad}, {ciudad}" if ciudad else entidad
        objeto = str(row.get("objeto_del_contrato", "N/D")).upper()
        valor = row.get("valor_del_contrato", 0)
        valor_fmt = f"$ {valor:,.0f}" if pd.notna(valor) else "N/D"
        plazo = _calcular_plazo(row)
        enlace = _extraer_url(str(row.get("urlproceso", "")))

        filas.append({
            "No": idx,
            "No PROCESO SECOP": proceso,
            "MODALIDAD": modalidad,
            "CONTRATISTA": contratista,
            "CONTRATANTE": contratante,
            "OBJETO": objeto,
            "VALOR": valor_fmt,
            "PLAZO": plazo,
            "ENLACE": enlace,
            "OBSERVACIONES": "Se evidencia adicional al contrato",
        })

    df_informe = pd.DataFrame(filas)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_informe.to_excel(writer, index=False, sheet_name="Análisis Demanda")
        ws = writer.sheets["Análisis Demanda"]

        # Ajustar anchos
        anchos = {"A": 5, "B": 22, "C": 20, "D": 35, "E": 40, "F": 60,
                  "G": 18, "H": 20, "I": 60, "J": 40}
        for col_letter, width in anchos.items():
            ws.column_dimensions[col_letter].width = width

        # Ajustar alto de filas para el objeto
        for row_num in range(2, len(df_informe) + 2):
            ws.row_dimensions[row_num].height = 60

    return buffer.getvalue()


# La resolución de fuentes vive en config.py y la comparten este módulo
# y estudio_sector.py. Mantener una copia aquí ya provocó que ambos
# ficheros quedaran desincronizados.
def hay_soporte_pdf() -> bool:
    """Indica si el entorno puede generar PDFs."""
    try:
        import fpdf  # noqa: F401
    except ImportError:
        return False
    return resolver_fuente_pdf() is not None


def _generar_informe_pdf(contratos: pd.DataFrame, palabras_busqueda: str = "") -> bytes:
    """Genera el informe de Análisis de Demanda en formato PDF profesional.

    Raises:
        RuntimeError: Si no hay ninguna fuente TrueType disponible.
    """
    from fpdf import FPDF

    fuentes = resolver_fuente_pdf()
    if fuentes is None:
        raise RuntimeError(
            "No se encontró una fuente TrueType para generar el PDF. "
            "Instala 'fonts-dejavu-core' o define PDF_FONT_DIR."
        )
    ruta_regular, ruta_negrita = fuentes

    FONT = "InformeSans"

    # Márgenes y dimensiones (A4 = 210 x 297 mm)
    MARGIN_L = 15
    MARGIN_R = 15
    PAGE_W = 210
    USABLE_W = PAGE_W - MARGIN_L - MARGIN_R  # 180 mm
    COL_LABEL = 38
    COL_VALUE = USABLE_W - COL_LABEL  # 142 mm

    # Colores
    AZUL_OSCURO = (0, 51, 102)
    AZUL_CLARO = (230, 240, 250)
    GRIS_FONDO = (245, 245, 248)
    BLANCO = (255, 255, 255)
    NEGRO = (0, 0, 0)
    GRIS_TEXTO = (80, 80, 80)
    GRIS_LINEA = (180, 180, 190)

    class InformePDF(FPDF):
        def header(self):
            # Barra superior azul
            self.set_fill_color(*AZUL_OSCURO)
            self.rect(0, 0, PAGE_W, 14, "F")
            self.set_font(FONT, "B", 9)
            self.set_text_color(*BLANCO)
            self.set_y(3)
            self.cell(0, 8, "ANÁLISIS DE LA DEMANDA — SECOP — COLOMBIA COMPRA EFICIENTE", align="C")
            self.ln(14)

        def footer(self):
            self.set_y(-12)
            self.set_draw_color(*GRIS_LINEA)
            self.line(MARGIN_L, self.get_y(), PAGE_W - MARGIN_R, self.get_y())
            self.ln(2)
            self.set_font(FONT, "", 6.5)
            self.set_text_color(*GRIS_TEXTO)
            self.cell(0, 5, f"Página {self.page_no()}/{{nb}}", align="R")

    pdf = InformePDF(orientation="P", unit="mm", format="A4")
    pdf.add_font(FONT, "", ruta_regular)
    pdf.add_font(FONT, "B", ruta_negrita)
    pdf.add_font(FONT, "I", ruta_regular)
    pdf.add_font(FONT, "BI", ruta_negrita)
    pdf.set_left_margin(MARGIN_L)
    pdf.set_right_margin(MARGIN_R)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # ── Título principal ──
    pdf.set_font(FONT, "B", 15)
    pdf.set_text_color(*AZUL_OSCURO)
    pdf.cell(0, 10, "ANÁLISIS DE LA DEMANDA", new_x="LMARGIN", new_y="NEXT")
    # Línea decorativa bajo el título
    pdf.set_draw_color(*AZUL_OSCURO)
    pdf.set_line_width(0.6)
    pdf.line(MARGIN_L, pdf.get_y(), MARGIN_L + 60, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(5)

    # ── Texto introductorio ──
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*GRIS_TEXTO)
    intro = (
        "Se validan en el portal de contratación SECOP procesos adelantados "
        "en los últimos años por algunas entidades estatales del departamento "
        "y por este municipio para satisfacer las necesidades requeridas.\n\n"
        "De acuerdo a la consulta en el portal único de contratación estatal — "
        "SECOP (www.colombiacompra.gov.co), se observa la siguiente información:"
    )
    pdf.multi_cell(0, 4.5, intro)
    pdf.ln(4)

    if palabras_busqueda:
        pdf.set_fill_color(*AZUL_CLARO)
        pdf.set_font(FONT, "B", 8)
        pdf.set_text_color(*AZUL_OSCURO)
        pdf.cell(0, 7, f"  Palabras clave: {palabras_busqueda}", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    total = len(contratos)
    valor_total = contratos["valor_del_contrato"].sum()
    valor_promedio = contratos["valor_del_contrato"].mean()
    valor_mediana = contratos["valor_del_contrato"].median()
    valor_min_c = contratos["valor_del_contrato"].min()
    valor_max_c = contratos["valor_del_contrato"].max()
    n_entidades = contratos["nombre_entidad"].nunique()
    n_ciudades = contratos["ciudad"].nunique()
    n_modalidades = contratos["modalidad_de_contratacion"].nunique()
    n_proveedores = contratos["proveedor_adjudicado"].nunique()

    top_mod = contratos["modalidad_de_contratacion"].value_counts()
    top_mod_nombre = top_mod.index[0] if len(top_mod) > 0 else "N/D"
    top_mod_pct = (top_mod.iloc[0] / total * 100) if len(top_mod) > 0 else 0
    top_ent = contratos["nombre_entidad"].value_counts()
    top_ent_nombre = top_ent.index[0] if len(top_ent) > 0 else "N/D"
    top_ent_count = top_ent.iloc[0] if len(top_ent) > 0 else 0

    # ── Sección de Estadísticos ──
    pdf.set_font(FONT, "B", 11)
    pdf.set_text_color(*AZUL_OSCURO)
    pdf.cell(0, 8, "ESTADÍSTICOS DEL RESULTADO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*AZUL_OSCURO)
    pdf.set_line_width(0.4)
    pdf.line(MARGIN_L, pdf.get_y(), MARGIN_L + 50, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(4)

    # Tabla de estadísticos
    stat_rows = [
        ("Total contratos", f"{total:,}"),
        ("Entidades únicas", f"{n_entidades:,}"),
        ("Ciudades", f"{n_ciudades:,}"),
        ("Proveedores únicos", f"{n_proveedores:,}"),
        ("Modalidades", f"{n_modalidades}"),
        ("Valor total", f"$ {valor_total:,.0f}"),
        ("Valor promedio", f"$ {valor_promedio:,.0f}" if pd.notna(valor_promedio) else "N/D"),
        ("Valor mediana", f"$ {valor_mediana:,.0f}" if pd.notna(valor_mediana) else "N/D"),
        ("Valor mínimo", f"$ {valor_min_c:,.0f}" if pd.notna(valor_min_c) else "N/D"),
        ("Valor máximo", f"$ {valor_max_c:,.0f}" if pd.notna(valor_max_c) else "N/D"),
        ("Modalidad predominante", f"{top_mod_nombre} ({top_mod_pct:.1f}%)"),
        ("Entidad con más contratos", f"{top_ent_nombre} ({top_ent_count})"),
    ]

    col_label_w = 55
    col_val_w = USABLE_W - col_label_w
    for i, (label, value) in enumerate(stat_rows):
        y0 = pdf.get_y()
        if i % 2 == 0:
            pdf.set_fill_color(*GRIS_FONDO)
        else:
            pdf.set_fill_color(*BLANCO)

        pdf.set_font(FONT, "B", 7.5)
        pdf.set_text_color(*AZUL_OSCURO)
        pdf.set_xy(MARGIN_L, y0)
        pdf.cell(col_label_w, 6, f"  {label}", border=0, fill=True)

        pdf.set_font(FONT, "", 7.5)
        pdf.set_text_color(*NEGRO)
        pdf.set_xy(MARGIN_L + col_label_w, y0)
        pdf.cell(col_val_w, 6, f"  {value}", border=0, fill=True)
        pdf.set_y(y0 + 6)

    pdf.ln(6)
    # Línea separadora
    pdf.set_draw_color(*GRIS_LINEA)
    pdf.line(MARGIN_L + 20, pdf.get_y(), PAGE_W - MARGIN_R - 20, pdf.get_y())
    pdf.ln(6)

    def _altura_multi(txt: str, ancho: float, font_size: float = 7.5) -> float:
        """Calcula la altura que ocupará un multi_cell."""
        pdf.set_font(FONT, "", font_size)
        # Estimar caracteres por línea (DejaVu ~2.2mm por char a 7.5pt)
        cpl = max(1, int(ancho / 2.1))
        lineas = 1
        for linea in txt.split("\n"):
            lineas += max(1, -(-len(linea) // cpl)) if linea else 1  # ceil division
        return lineas * 4.2

    # ── Fichas de cada contrato ──
    for idx, (_, row) in enumerate(contratos.iterrows(), 1):
        proceso = str(row.get("proceso_de_compra", "N/D"))
        modalidad = str(row.get("modalidad_de_contratacion", "N/D")).upper()
        contratista = str(row.get("proveedor_adjudicado", "N/D")).upper()
        entidad = str(row.get("nombre_entidad", "N/D")).upper()
        ciudad_val = str(row.get("ciudad", "")).upper()
        contratante = f"{entidad}, {ciudad_val}" if ciudad_val else entidad
        objeto = str(row.get("objeto_del_contrato", "N/D")).upper()
        valor = row.get("valor_del_contrato", 0)
        valor_fmt = f"$ {valor:,.0f}" if pd.notna(valor) else "N/D"
        plazo = _calcular_plazo(row)
        enlace = _extraer_url(str(row.get("urlproceso", "")))

        ficha = [
            ("No PROCESO SECOP", proceso),
            ("MODALIDAD", modalidad),
            ("CONTRATISTA", contratista),
            ("CONTRATANTE", contratante),
            ("OBJETO", objeto),
            ("VALOR", valor_fmt),
            ("PLAZO", plazo),
            ("ENLACE", enlace),
            ("OBSERVACIONES", "Se evidencia adicional al contrato"),
        ]

        # Estimar altura total de la ficha para decidir salto de página
        alt_ficha = 8  # encabezado
        for _, v in ficha:
            alt_ficha += max(6, _altura_multi(v, COL_VALUE - 4))
        if pdf.get_y() + alt_ficha > 270:
            pdf.add_page()

        # ── Encabezado del contrato ──
        pdf.set_font(FONT, "B", 9)
        pdf.set_fill_color(*AZUL_OSCURO)
        pdf.set_text_color(*BLANCO)
        pdf.cell(0, 8, f"   CONTRATO {idx} DE {total}", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*NEGRO)

        # ── Filas de la ficha ──
        for i, (campo, valor_campo) in enumerate(ficha):
            # Calcular altura necesaria
            h_val = max(6, _altura_multi(valor_campo, COL_VALUE - 4))

            # Verificar salto de página
            if pdf.get_y() + h_val > 278:
                pdf.add_page()

            y_start = pdf.get_y()
            x_start = pdf.l_margin

            # Color alterno
            if i % 2 == 0:
                fill_color = GRIS_FONDO
            else:
                fill_color = BLANCO

            # ── Celda ETIQUETA ──
            pdf.set_fill_color(*AZUL_CLARO)
            pdf.set_font(FONT, "B", 7.5)
            pdf.set_text_color(*AZUL_OSCURO)
            pdf.set_xy(x_start, y_start)
            pdf.cell(COL_LABEL, h_val, f"  {campo}", border="LTB", fill=True)

            # ── Celda VALOR (multi_cell para wrapping) ──
            pdf.set_fill_color(*fill_color)
            pdf.set_font(FONT, "", 7.5)
            pdf.set_text_color(*NEGRO)
            pdf.set_xy(x_start + COL_LABEL, y_start)

            # Dibujar el fondo y bordes del valor manualmente
            pdf.rect(x_start + COL_LABEL, y_start, COL_VALUE, h_val, "DF")
            pdf.set_xy(x_start + COL_LABEL + 2, y_start + 1)
            pdf.multi_cell(COL_VALUE - 4, 4.2, valor_campo, border=0, fill=False)

            # Mover cursor a la siguiente fila
            pdf.set_y(y_start + h_val)

        # Separador entre contratos
        pdf.ln(4)
        pdf.set_draw_color(*GRIS_LINEA)
        pdf.line(MARGIN_L + 20, pdf.get_y(), PAGE_W - MARGIN_R - 20, pdf.get_y())
        pdf.ln(4)

    # ── Pie del informe ──
    pdf.ln(3)
    pdf.set_draw_color(*AZUL_OSCURO)
    pdf.set_line_width(0.4)
    pdf.line(MARGIN_L, pdf.get_y(), PAGE_W - MARGIN_R, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(3)
    pdf.set_font(FONT, "I", 7)
    pdf.set_text_color(*GRIS_TEXTO)
    pdf.cell(
        0, 5,
        f"Informe generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
        f"Total contratos: {total}  |  "
        f"Fuente: SECOP II — datos.gov.co",
        new_x="LMARGIN", new_y="NEXT",
    )

    return bytes(pdf.output())


# ────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────

# ── Panel de consulta (barra lateral) ──
# La app consulta los portales EN VIVO: lo que se define aquí es el
# alcance de la búsqueda que se enviará a SECOP al pulsar "Buscar".
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <h3>🔎 Consulta a SECOP</h3>
        <p>Los datos se descargan al momento de buscar</p>
    </div>
    """, unsafe_allow_html=True)

    modo_datos = st.radio(
        "Origen de los datos",
        ["Consulta en vivo", "Archivo CSV"],
        help=(
            "«Consulta en vivo» interroga los portales en el momento. "
            "«Archivo CSV» abre una descarga previa, sin tocar la red."
        ),
    )

    uploaded_file = None
    ejecutar_consulta = False
    fuentes_sel: list[str] = []
    q_depto = q_modalidad = q_estado = q_tipo = ""
    q_fecha_ini = q_fecha_fin = None
    q_max_paginas = 3
    q_max_api = 20000

    if modo_datos == "Consulta en vivo":
        fuentes_sel = st.multiselect(
            "Portales a consultar",
            ["SECOP II", "SECOP I"],
            default=["SECOP II"],
            help=(
                "SECOP II (API): rápido, filtros en servidor, publica con "
                "unos días de rezago. SECOP I (portal): más reciente, pero "
                "va paginado y más lento."
            ),
        )

        # Desplegables construidos desde catalogos.py: la etiqueta es
        # legible, pero lo que viaja a cada portal es su valor exacto.
        # Así es imposible fallar por una tilde o una mayúscula.
        mapa_deptos = opciones_desplegable(DEPARTAMENTOS, NACIONAL)
        etiquetas_deptos = list(mapa_deptos)
        q_depto_label = st.selectbox(
            "Departamento",
            etiquetas_deptos,
            index=etiquetas_deptos.index("Santander"),
            help="Elige «Todo el país» para una consulta nacional.",
        )
        opcion_depto = mapa_deptos[q_depto_label]
        q_depto = opcion_depto.etiqueta if opcion_depto else ""

        mapa_modalidades = opciones_desplegable(MODALIDADES)
        q_modalidad_label = st.selectbox(
            "Modalidad de contratación", list(mapa_modalidades)
        )
        opcion_modalidad = mapa_modalidades[q_modalidad_label]
        q_modalidad = opcion_modalidad.etiqueta if opcion_modalidad else ""

        # Todos los tipos son exclusivos de SECOP II, así que la nota va
        # en la ayuda del campo en vez de repetirse en cada opción.
        mapa_tipos = opciones_desplegable(TIPOS_CONTRATO, anotar=False)
        q_tipo_label = st.selectbox(
            "Tipo de contrato",
            list(mapa_tipos),
            help=(
                "Solo filtra en SECOP II: la tabla de resultados de "
                "SECOP I no incluye el tipo de contrato."
            ),
        )
        opcion_tipo = mapa_tipos[q_tipo_label]
        q_tipo = opcion_tipo.etiqueta if opcion_tipo else ""

        mapa_estados = opciones_desplegable(ESTADOS)
        q_estado_label = st.selectbox("Estado", list(mapa_estados))
        opcion_estado = mapa_estados[q_estado_label]
        q_estado = opcion_estado.etiqueta if opcion_estado else ""

        usar_fechas = st.checkbox("Acotar por fechas", value=False)
        if usar_fechas:
            col_fi, col_ff = st.columns(2)
            with col_fi:
                q_fecha_ini = st.date_input(
                    "Desde", value=date(date.today().year, 1, 1),
                    format="DD/MM/YYYY",
                )
            with col_ff:
                q_fecha_fin = st.date_input(
                    "Hasta", value=date.today(), format="DD/MM/YYYY",
                )

        if "SECOP I" in fuentes_sel:
            q_max_paginas = st.slider(
                "Páginas de SECOP I", 1, 20, 3,
                help=(
                    "100 procesos por página, con pausa entre ellas para no "
                    "activar el bloqueo del portal. Más páginas = más "
                    "cobertura y más espera."
                ),
            )

        if "SECOP II" in fuentes_sel:
            q_max_api = st.select_slider(
                "Máximo de contratos (SECOP II)",
                options=[1000, 5000, 20000, 50000, 100000, 250000],
                value=20000,
                help=(
                    "Una consulta nacional sin filtros supera los 5,8 "
                    "millones de contratos: este tope evita descargas "
                    "interminables. Si se alcanza, se avisa."
                ),
            )

        ejecutar_consulta = st.button(
            "🔎 Buscar en SECOP", type="primary", width="stretch"
        )
        st.caption(
            "La consulta solo se ejecuta con este botón: los demás filtros "
            "refinan lo ya descargado sin volver a la red."
        )
    else:
        uploaded_file = st.file_uploader(
            "Cargar archivo CSV de contratos",
            type=["csv"],
            help="Acepta CSV de cualquiera de las dos rutas del pipeline.",
        )
        if uploaded_file is None and CSV_PATH is not None:
            st.caption(f"Usando el más reciente: `{Path(CSV_PATH).name}`")

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

# Reserva el espacio del encabezado: se rellena cuando ya hay resultados.
hero_slot = st.empty()

# ── Barra de búsqueda ──
st.markdown('<div class="search-container">', unsafe_allow_html=True)
consulta = st.text_input(
    "🔍 Buscar por objeto del contrato",
    placeholder="Ej: suministro alimentos, vigilancia, consultoría, combustible...",
    help=(
        "Palabras separadas por espacio; se exige que el objeto las contenga "
        "TODAS. En SECOP II el filtro viaja al servidor; en SECOP I se aplica "
        "sobre las páginas descargadas."
    ),
    label_visibility="collapsed",
)
if not consulta.strip():
    st.markdown(
        '<p class="search-hint">💡 Escribe palabras clave y pulsa '
        '<em>Buscar en SECOP</em> en la barra lateral.</p>',
        unsafe_allow_html=True,
    )
st.markdown('</div>', unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def _consulta_cacheada(
    fuentes: tuple[str, ...],
    departamento: str,
    modalidad: str,
    estado: str,
    palabra_clave: str,
    fecha_inicio: str,
    fecha_fin: str,
    tipo_contrato: str,
    max_paginas: int,
    max_registros_api: int,
    _version: int,
):
    """Envoltura cacheada de la consulta en vivo.

    La caché dura 5 minutos y está indexada por los parámetros de
    búsqueda: repetir la misma consulta dentro de esa ventana no vuelve
    a golpear los portales (importante para no activar el WAF de
    SECOP I). ``_version`` permite forzar una descarga nueva.
    """
    from consulta import consultar_en_vivo

    return consultar_en_vivo(
        fuentes=fuentes,
        departamento=departamento,
        modalidad=modalidad,
        estado=estado,
        palabra_clave=palabra_clave,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        tipo_contrato=tipo_contrato,
        max_paginas_secop1=max_paginas,
        max_registros_api=max_registros_api,
    )


# ── Obtención de los datos ──
df = None
informe_consulta = st.session_state.get("_informe")

if modo_datos == "Consulta en vivo":
    if ejecutar_consulta:
        if not fuentes_sel:
            st.warning("Selecciona al menos un portal en la barra lateral.")
        else:
            try:
                with st.spinner(
                    f"Consultando {' y '.join(fuentes_sel)} en tiempo real..."
                ):
                    df, informe_consulta = _consulta_cacheada(
                        tuple(fuentes_sel),
                        q_depto,
                        q_modalidad,
                        q_estado,
                        consulta,
                        q_fecha_ini.strftime("%d/%m/%Y") if q_fecha_ini else "",
                        q_fecha_fin.strftime("%d/%m/%Y") if q_fecha_fin else "",
                        q_tipo,
                        q_max_paginas,
                        q_max_api,
                        st.session_state.get("_version_consulta", 0),
                    )
                st.session_state["_df"] = df
                st.session_state["_informe"] = informe_consulta
            except Exception as exc:  # noqa: BLE001
                st.error(f"La consulta falló: {exc}")
                df = st.session_state.get("_df")
    else:
        df = st.session_state.get("_df")

    if df is None:
        st.info(
            "Define el alcance en la barra lateral y pulsa "
            "**🔎 Buscar en SECOP** para traer contratos actuales."
        )
        st.stop()
else:
    try:
        firma = ""
        if uploaded_file is None and CSV_PATH is not None:
            firma = f"{CSV_PATH}:{Path(CSV_PATH).stat().st_mtime}"
        elif uploaded_file is None:
            st.info("Sube un CSV o cambia a «Consulta en vivo».")
            st.stop()
        df = cargar_datos(CSV_PATH, uploaded_file, _firma=firma)
        informe_consulta = None
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:  # noqa: BLE001
        st.error("Error al cargar los datos: " + str(exc))
        st.stop()

# Tipado de las columnas que usa el resto del dashboard.
df = df.copy()
df["valor_del_contrato"] = pd.to_numeric(
    df["valor_del_contrato"], errors="coerce"
)
df["valor_pagado"] = pd.to_numeric(df.get("valor_pagado"), errors="coerce")
df["fecha_inicio"] = pd.to_datetime(
    df["fecha_de_inicio_del_contrato"], errors="coerce", format="mixed"
)
df["fecha_fin"] = pd.to_datetime(
    df["fecha_de_fin_del_contrato"], errors="coerce", format="mixed"
)
if "_busqueda" not in df.columns:
    df["_busqueda"] = (
        df["objeto_del_contrato"].astype("string").fillna("").str.lower()
    )

# Avisos de la consulta: truncado por tope, filtros no aplicables a un
# portal, etc. Se muestran arriba para que no pasen desapercibidos.
for aviso in (informe_consulta or {}).get("avisos", []):
    st.info(aviso, icon="ℹ️")

if df.empty:
    st.warning(
        "La consulta no devolvió contratos. Prueba a ampliar el rango de "
        "fechas, quitar la modalidad o cambiar de portal."
    )
    st.stop()

n_total = len(df)
n_entidades_hero = df["nombre_entidad"].nunique()
n_modalidades_hero = df["modalidad_de_contratacion"].nunique()

hero_slot.markdown(f"""
<div class="main-header">
    <div class="hero-badge">CONTRATACIÓN PÚBLICA</div>
    <h1>ANÁLISIS DEL SECTOR<br>SECOP COLOMBIA</h1>
    <div class="hero-line"></div>
    <p class="hero-desc">Herramienta para el análisis automatizado de contratación pública del departamento de Santander</p>
    <div class="hero-stats">
        <div class="hero-stat">
            <div class="hs-value">{n_total:,}</div>
            <div class="hs-label">Contratos</div>
        </div>
        <div class="hero-stat">
            <div class="hs-value">{n_entidades_hero}</div>
            <div class="hs-label">Entidades</div>
        </div>
        <div class="hero-stat">
            <div class="hs-value">{n_modalidades_hero}</div>
            <div class="hs-label">Modalidades</div>
        </div>
        <div class="hero-stat">
            <div class="hs-value">3</div>
            <div class="hs-label">Formatos Export</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Feature Cards ──
st.markdown("""
<div class="feature-cards">
    <div class="feature-card">
        <div class="fc-icon">📊</div>
        <div class="fc-title">Búsqueda Inteligente</div>
        <div class="fc-desc">Busca contratos por palabras clave con filtros avanzados</div>
    </div>
    <div class="feature-card">
        <div class="fc-icon">📋</div>
        <div class="fc-title">Análisis de Demanda</div>
        <div class="fc-desc">Genera informes formales automáticamente</div>
    </div>
    <div class="feature-card">
        <div class="fc-icon">📄</div>
        <div class="fc-title">Exportar PDF</div>
        <div class="fc-desc">Descarga informes profesionales en PDF</div>
    </div>
    <div class="feature-card">
        <div class="fc-icon">📈</div>
        <div class="fc-title">Estadísticas</div>
        <div class="fc-desc">Análisis estadístico detallado de contratos</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Refinado de los resultados (barra lateral) ──
# Estos controles NO vuelven a consultar los portales: filtran en local
# lo que ya se descargó.
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <h3>🎛️ Refinar resultados</h3>
        <p>Filtra lo descargado sin volver a consultar</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<p class="filter-label"><span class="fl-icon">📑</span> Modalidad de contratación</p>', unsafe_allow_html=True)
    modalidades = sorted(df["modalidad_de_contratacion"].dropna().unique())
    modalidad_sel = st.multiselect("Modalidad", modalidades, label_visibility="collapsed")

    st.markdown('<p class="filter-label"><span class="fl-icon">🏙️</span> Ciudad</p>', unsafe_allow_html=True)
    ciudades = sorted(df["ciudad"].dropna().unique())
    ciudad_sel = st.multiselect("Ciudad", ciudades, label_visibility="collapsed")

    st.markdown('<p class="filter-label"><span class="fl-icon">📝</span> Tipo de contrato</p>', unsafe_allow_html=True)
    tipos = sorted(df["tipo_de_contrato"].dropna().unique())
    tipo_sel = st.multiselect("Tipo", tipos, label_visibility="collapsed")

    st.markdown('<p class="filter-label"><span class="fl-icon">📌</span> Estado</p>', unsafe_allow_html=True)
    estados = sorted(df["estado_contrato"].dropna().unique())
    estado_sel = st.multiselect("Estado", estados, label_visibility="collapsed")

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    # Fechas
    st.markdown('<p class="filter-label"><span class="fl-icon">📅</span> Rango de fechas</p>', unsafe_allow_html=True)
    fecha_min = df["fecha_inicio"].min()
    fecha_max = df["fecha_fin"].max()
    if pd.isna(fecha_min):
        fecha_min = pd.Timestamp("2015-01-01")
    if pd.isna(fecha_max):
        fecha_max = pd.Timestamp.now()

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        fecha_desde = st.date_input(
            "Desde",
            value=fecha_min.date(),
            min_value=fecha_min.date(),
            max_value=fecha_max.date(),
        )
    with col_f2:
        fecha_hasta = st.date_input(
            "Hasta",
            value=fecha_max.date(),
            min_value=fecha_min.date(),
            max_value=fecha_max.date(),
        )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    # Valor
    st.markdown('<p class="filter-label"><span class="fl-icon">💰</span> Valor del contrato</p>', unsafe_allow_html=True)
    max_valor_m = int(df["valor_del_contrato"].max() / 1_000_000) + 1
    rango_valor = st.slider(
        "Millones COP",
        min_value=0,
        max_value=max_valor_m,
        value=(0, max_valor_m),
        step=1,
        label_visibility="collapsed",
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="db-counter">
            <div class="db-label">Base de datos</div>
            <div class="db-value">{len(df):,}</div>
            <div class="db-sub">contratos indexados</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Procedencia y frescura de lo que se está viendo ──
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="filter-label"><span class="fl-icon">🕒</span> '
        'Procedencia de los datos</p>',
        unsafe_allow_html=True,
    )

    if informe_consulta:
        momento = informe_consulta["consultado_en"]
        minutos = (datetime.now() - momento).total_seconds() / 60
        frescura = "ahora mismo" if minutos < 1 else f"hace {int(minutos)} min"
        st.caption(f"🟢 Consultado **{frescura}** · {momento:%d/%m/%Y %H:%M:%S}")

        for fuente, cantidad in informe_consulta.get("por_fuente", {}).items():
            st.caption(f"· {fuente}: **{cantidad:,}** contratos")

        coincidencias = informe_consulta.get("coincidencias_api")
        if coincidencias is not None and informe_consulta.get("truncado"):
            st.caption(f"· Coincidencias totales: **{coincidencias:,}**")

        for fuente, error in informe_consulta.get("errores", {}).items():
            st.warning(f"{fuente} falló: {error}", icon="⚠️")

        if st.button("↻ Forzar descarga nueva", width="stretch"):
            st.session_state["_version_consulta"] = (
                st.session_state.get("_version_consulta", 0) + 1
            )
            st.cache_data.clear()
            st.rerun()

    elif CSV_PATH is not None and Path(CSV_PATH).exists():
        modificado = datetime.fromtimestamp(Path(CSV_PATH).stat().st_mtime)
        antiguedad = (datetime.now() - modificado).days
        if antiguedad <= 7:
            icono = "🟢"
        elif antiguedad <= 30:
            icono = "🟡"
        else:
            icono = "🔴"
        st.caption(
            f"{icono} Archivo extraído hace **{antiguedad} día(s)**  \n"
            f"`{Path(CSV_PATH).name}`"
        )
    else:
        st.caption("Archivo subido manualmente.")

    fecha_max_datos = df["fecha_inicio"].max()
    if pd.notna(fecha_max_datos):
        st.caption(f"Contrato más reciente: **{fecha_max_datos:%d/%m/%Y}**")

    if modo_datos == "Consulta en vivo" and not df.empty:
        st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        st.download_button(
            "💾 Guardar esta consulta (CSV)",
            data=df.drop(columns=["_busqueda"], errors="ignore")
                   .to_csv(index=False).encode("utf-8-sig"),
            file_name=f"secop_consulta_{datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv",
            width="stretch",
        )

# ── Aplicar búsqueda y filtros ──
resultado = buscar(df, consulta)

if modalidad_sel:
    resultado = resultado[resultado["modalidad_de_contratacion"].isin(modalidad_sel)]
if ciudad_sel:
    resultado = resultado[resultado["ciudad"].isin(ciudad_sel)]
if tipo_sel:
    resultado = resultado[resultado["tipo_de_contrato"].isin(tipo_sel)]
if estado_sel:
    resultado = resultado[resultado["estado_contrato"].isin(estado_sel)]

resultado = resultado[
    (resultado["valor_del_contrato"] >= rango_valor[0] * 1_000_000)
    & (resultado["valor_del_contrato"] <= rango_valor[1] * 1_000_000)
]

# Filtro de fechas
resultado = resultado[
    (resultado["fecha_inicio"].isna() | (resultado["fecha_inicio"] >= pd.Timestamp(fecha_desde)))
    & (resultado["fecha_fin"].isna() | (resultado["fecha_fin"] <= pd.Timestamp(fecha_hasta)))
]

# ── Métricas con tarjetas ──
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-icon">📄</div>
        <div class="metric-value">{len(resultado):,}</div>
        <div class="metric-label">Contratos encontrados</div>
    </div>""", unsafe_allow_html=True)

with col2:
    valor_total = resultado["valor_del_contrato"].sum()
    if valor_total >= 1_000_000_000:
        valor_display = f"${valor_total/1_000_000_000:,.1f}B"
    elif valor_total >= 1_000_000:
        valor_display = f"${valor_total/1_000_000:,.0f}M"
    else:
        valor_display = f"${valor_total:,.0f}"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-icon">💰</div>
        <div class="metric-value">{valor_display}</div>
        <div class="metric-label">Valor total</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-icon">🏛️</div>
        <div class="metric-value">{resultado['nombre_entidad'].nunique():,}</div>
        <div class="metric-label">Entidades únicas</div>
    </div>""", unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-icon">🏙️</div>
        <div class="metric-value">{resultado['ciudad'].nunique():,}</div>
        <div class="metric-label">Ciudades</div>
    </div>""", unsafe_allow_html=True)

st.markdown("")

# ── Columnas a mostrar ──
columnas_display = [
    # Al combinar portales hay que poder distinguir el origen de cada fila.
    "fuente",
    "nombre_entidad",
    "ciudad",
    "modalidad_de_contratacion",
    "objeto_del_contrato",
    "tipo_de_contrato",
    "estado_contrato",
    "valor_del_contrato",
    "valor_pagado",
    "proveedor_adjudicado",
    "fecha_inicio",
    "fecha_fin",
    "urlproceso",
]
columnas_existentes = [c for c in columnas_display if c in resultado.columns]

if resultado.empty:
    st.markdown("""
    <div class="empty-state">
        <div class="es-icon">🔍</div>
        <p class="es-title">No se encontraron contratos</p>
        <p class="es-desc">Ajusta los filtros o modifica las palabras clave de búsqueda</p>
    </div>
    """, unsafe_allow_html=True)
else:
    # Tabs para organizar contenido
    tab_tabla, tab_analisis, tab_estudio = st.tabs([
        "📊 Tabla de Resultados",
        "📋 Análisis de la Demanda",
        "📑 Estudio del Sector",
    ])

    with tab_tabla:
        st.dataframe(
            resultado[columnas_existentes].reset_index(drop=True),
            width="stretch",
            height=550,
            column_config={
                "fuente": st.column_config.TextColumn("Portal", width="small"),
                "nombre_entidad": st.column_config.TextColumn("Entidad", width="medium"),
                "ciudad": st.column_config.TextColumn("Ciudad", width="small"),
                "modalidad_de_contratacion": st.column_config.TextColumn("Modalidad", width="medium"),
                "objeto_del_contrato": st.column_config.TextColumn("Objeto del Contrato", width="large"),
                "tipo_de_contrato": st.column_config.TextColumn("Tipo", width="small"),
                "estado_contrato": st.column_config.TextColumn("Estado", width="small"),
                "valor_del_contrato": st.column_config.NumberColumn("Valor Contrato", format="$%,.0f"),
                "valor_pagado": st.column_config.NumberColumn("Valor Pagado", format="$%,.0f"),
                "proveedor_adjudicado": st.column_config.TextColumn("Proveedor", width="medium"),
                "fecha_inicio": st.column_config.DateColumn("Inicio", format="DD/MM/YYYY"),
                "fecha_fin": st.column_config.DateColumn("Fin", format="DD/MM/YYYY"),
                "urlproceso": st.column_config.TextColumn("URL", width="small"),
            },
        )

        st.download_button(
            label="📥 Descargar tabla filtrada (CSV)",
            data=resultado[columnas_existentes].to_csv(index=False).encode("utf-8-sig"),
            file_name="contratos_filtrados.csv",
            mime="text/csv",
        )

    with tab_analisis:
        if not consulta.strip():
            st.markdown("""
            <div class="empty-state">
                <div class="es-icon">💡</div>
                <p class="es-title">Ingresa palabras clave en el buscador</p>
                <p class="es-desc">El Análisis de la Demanda se genera automáticamente con los contratos encontrados</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            contratos_informe = resultado.reset_index(drop=True)
            total_contratos = len(contratos_informe)

            # Header del análisis
            st.markdown(f"""
            <div class="analisis-header">
                <h2>📋 ANÁLISIS DE LA DEMANDA</h2>
                <p style="margin:0.3rem 0 0 0; opacity:0.85; font-size:0.85rem;">
                    {total_contratos} contratos encontrados · Palabras clave: <strong>{consulta}</strong>
                </p>
            </div>
            """, unsafe_allow_html=True)

            col_exp1, col_exp2, col_exp3, col_exp4 = st.columns(4)
            sello = datetime.now().strftime("%Y%m%d_%H%M")

            with col_exp1:
                csv_bytes = (
                    contratos_informe[columnas_existentes]
                    .to_csv(index=False)
                    .encode("utf-8-sig")
                )
                st.download_button(
                    label="📥 CSV",
                    data=csv_bytes,
                    file_name=f"analisis_demanda_{sello}.csv",
                    mime="text/csv",
                    width="stretch",
                )

            with col_exp2:
                st.download_button(
                    label="📄 TXT",
                    data=_generar_informe_texto(contratos_informe).encode("utf-8"),
                    file_name=f"analisis_demanda_{sello}.txt",
                    mime="text/plain",
                    width="stretch",
                )

            with col_exp3:
                try:
                    excel_bytes = _generar_informe_excel(contratos_informe)
                    st.download_button(
                        label="📗 Excel",
                        data=excel_bytes,
                        file_name=f"analisis_demanda_{sello}.xlsx",
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        width="stretch",
                    )
                except Exception as exc:  # noqa: BLE001
                    st.button(
                        "📗 Excel", disabled=True, width="stretch",
                        help=f"No disponible: {exc}",
                    )

            with col_exp4:
                # El PDF se genera solo cuando se pide: construirlo en cada
                # recarga es costoso y, si falla, tumbaría toda la página.
                if not hay_soporte_pdf():
                    st.button(
                        "📕 PDF", disabled=True, width="stretch",
                        help=(
                            "Falta una fuente TrueType en el sistema. "
                            "Instala 'fonts-dejavu-core' o define PDF_FONT_DIR."
                        ),
                    )
                elif st.session_state.get("_pdf_listo") == sello:
                    st.download_button(
                        label="📕 Descargar PDF",
                        data=st.session_state["_pdf_bytes"],
                        file_name=f"analisis_demanda_{sello}.pdf",
                        mime="application/pdf",
                        width="stretch",
                    )
                elif st.button("📕 Generar PDF", width="stretch"):
                    try:
                        with st.spinner("Generando PDF..."):
                            st.session_state["_pdf_bytes"] = _generar_informe_pdf(
                                contratos_informe, consulta
                            )
                        st.session_state["_pdf_listo"] = sello
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo generar el PDF: {exc}")

            st.markdown(
                "Se validan en el portal de contratación SECOP procesos adelantados "
                "en los últimos años por algunas entidades estatales del departamento "
                "y por este municipio para satisfacer las necesidades requeridas. "
                "De acuerdo a la consulta en el portal único de contratación estatal — "
                "SECOP [www.colombiacompra.gov.co](https://www.colombiacompra.gov.co), "
                "se observa la siguiente información:"
            )

            # ── Sección de Estadísticos ──
            valor_total_inf = contratos_informe["valor_del_contrato"].sum()
            valor_promedio = contratos_informe["valor_del_contrato"].mean()
            valor_mediana = contratos_informe["valor_del_contrato"].median()
            valor_min = contratos_informe["valor_del_contrato"].min()
            valor_max = contratos_informe["valor_del_contrato"].max()
            n_entidades = contratos_informe["nombre_entidad"].nunique()
            n_ciudades = contratos_informe["ciudad"].nunique()
            n_modalidades = contratos_informe["modalidad_de_contratacion"].nunique()
            n_proveedores = contratos_informe["proveedor_adjudicado"].nunique()

            # Top modalidad
            top_mod = contratos_informe["modalidad_de_contratacion"].value_counts()
            top_mod_nombre = top_mod.index[0] if len(top_mod) > 0 else "N/D"
            top_mod_pct = (top_mod.iloc[0] / total_contratos * 100) if len(top_mod) > 0 else 0

            # Top entidad
            top_ent = contratos_informe["nombre_entidad"].value_counts()
            top_ent_nombre = top_ent.index[0] if len(top_ent) > 0 else "N/D"
            top_ent_count = top_ent.iloc[0] if len(top_ent) > 0 else 0

            def _fmt_cop(v):
                if pd.isna(v) or v == 0:
                    return "$0"
                if abs(v) >= 1_000_000_000:
                    return f"${v/1_000_000_000:,.2f}B"
                if abs(v) >= 1_000_000:
                    return f"${v/1_000_000:,.1f}M"
                return f"${v:,.0f}"

            st.markdown('<p class="stats-section-title">📊 Estadísticos del Resultado</p>', unsafe_allow_html=True)

            st.markdown(f"""
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">Total contratos</div>
                    <div class="stat-value">{total_contratos:,}</div>
                    <div class="stat-sub">{n_entidades} entidades · {n_ciudades} ciudades</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Valor total</div>
                    <div class="stat-value">{_fmt_cop(valor_total_inf)}</div>
                    <div class="stat-sub">Suma de todos los contratos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Valor promedio</div>
                    <div class="stat-value">{_fmt_cop(valor_promedio)}</div>
                    <div class="stat-sub">Mediana: {_fmt_cop(valor_mediana)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Rango de valores</div>
                    <div class="stat-value">{_fmt_cop(valor_min)} — {_fmt_cop(valor_max)}</div>
                    <div class="stat-sub">Mínimo — Máximo</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Proveedores únicos</div>
                    <div class="stat-value">{n_proveedores:,}</div>
                    <div class="stat-sub">{n_modalidades} modalidades</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Modalidad predominante</div>
                    <div class="stat-value" style="font-size:0.95rem;">{top_mod_nombre}</div>
                    <div class="stat-sub">{top_mod_pct:.1f}% de los contratos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Entidad con más contratos</div>
                    <div class="stat-value" style="font-size:0.85rem;">{top_ent_nombre}</div>
                    <div class="stat-sub">{top_ent_count} contratos</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)

            # Fichas de contratos con HTML profesional
            for idx, (_, row) in enumerate(contratos_informe.iterrows(), 1):
                proceso = str(row.get("proceso_de_compra", "N/D"))
                modalidad = str(row.get("modalidad_de_contratacion", "N/D")).upper()
                contratista = str(row.get("proveedor_adjudicado", "N/D")).upper()
                entidad = str(row.get("nombre_entidad", "N/D")).upper()
                ciudad = str(row.get("ciudad", "")).upper()
                contratante = f"{entidad}, {ciudad}" if ciudad else entidad
                objeto = str(row.get("objeto_del_contrato", "N/D")).upper()
                valor = row.get("valor_del_contrato", 0)
                valor_fmt = f"$ {valor:,.0f}" if pd.notna(valor) else "N/D"
                plazo = _calcular_plazo(row)
                enlace = _extraer_url(str(row.get("urlproceso", "")))

                st.markdown(f"""
                <div class="contract-card">
                    <div class="contract-card-header">
                        CONTRATO {idx} DE {total_contratos}
                    </div>
                    <table>
                        <tr><td>No PROCESO SECOP</td><td>{proceso}</td></tr>
                        <tr><td>MODALIDAD</td><td>{modalidad}</td></tr>
                        <tr><td>CONTRATISTA</td><td>{contratista}</td></tr>
                        <tr><td>CONTRATANTE</td><td>{contratante}</td></tr>
                        <tr><td>OBJETO</td><td>{objeto}</td></tr>
                        <tr><td>VALOR</td><td>{valor_fmt}</td></tr>
                        <tr><td>PLAZO</td><td>{plazo}</td></tr>
                        <tr><td>ENLACE</td><td style="word-break:break-all;">{enlace}</td></tr>
                        <tr><td>OBSERVACIONES</td><td>Se evidencia adicional al contrato</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)


    # ══════════════════════════════════════════════════════════
    # ESTUDIO DEL SECTOR (Guía V3 de Colombia Compra Eficiente)
    # ══════════════════════════════════════════════════════════
    with tab_estudio:
        from estudio_sector import (
            ContextoEstudio,
            construir_estudio,
            cop,
            exportar_docx,
            exportar_pdf,
            hay_soporte_pdf,
        )

        st.markdown("""
        <div class="analisis-header">
            <h2>📑 ESTUDIO DEL SECTOR</h2>
            <p style="margin:0.3rem 0 0 0; opacity:0.85; font-size:0.85rem;">
                Estructura de la Guía para la Elaboración de Estudios del
                Sector V3 (2025) — Colombia Compra Eficiente
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(
            "El documento se construye con los contratos actualmente "
            "filtrados. Completa los datos de encabezado y descárgalo en "
            "**Word** (para seguir editándolo) o en **PDF** (para anexarlo)."
        )

        base_estudio = resultado.reset_index(drop=True)
        st.caption(
            f"Muestra: **{len(base_estudio):,}** contratos · "
            f"Valor total: **{cop(base_estudio['valor_del_contrato'].sum())}**"
        )

        with st.form("form_estudio"):
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                e_objeto = st.text_area(
                    "Objeto a contratar",
                    value=consulta.strip().capitalize() if consulta.strip() else "",
                    height=80,
                    placeholder="Ej: Suministro de combustible para el parque automotor…",
                )
                e_entidad = st.text_input("Entidad Estatal")
                e_modalidad = st.text_input("Modalidad prevista")
            with col_e2:
                e_depto = st.text_input(
                    "Departamento",
                    value=q_depto if modo_datos == "Consulta en vivo" else "",
                )
                e_municipio = st.text_input("Municipio")
                e_unspsc = st.text_input(
                    "Código UNSPSC", placeholder="Ej: 15101505",
                )
            e_elaborado = st.text_input("Elaborado por")
            e_obs = st.text_area(
                "Contexto económico del sector (opcional)",
                height=80,
                placeholder=(
                    "Notas sobre el sector: dinámica de precios, agentes, "
                    "gremios, factores que inciden en el costo…"
                ),
            )
            generar = st.form_submit_button(
                "📑 Generar Estudio del Sector", type="primary"
            )

        if generar:
            try:
                contexto = ContextoEstudio(
                    objeto=e_objeto,
                    entidad=e_entidad,
                    departamento=e_depto,
                    municipio=e_municipio,
                    modalidad_prevista=e_modalidad,
                    codigo_unspsc=e_unspsc,
                    elaborado_por=e_elaborado,
                    observaciones=e_obs,
                    filtros={
                        "Palabra clave": consulta,
                        "Departamento": e_depto,
                        "Modalidad": q_modalidad if modo_datos == "Consulta en vivo" else "",
                        "Tipo de contrato": q_tipo if modo_datos == "Consulta en vivo" else "",
                    },
                    fuentes=(
                        sorted(base_estudio["fuente"].dropna().unique())
                        if "fuente" in base_estudio.columns else ["SECOP"]
                    ),
                    consultado_en=(
                        informe_consulta.get("consultado_en")
                        if informe_consulta else None
                    ),
                )
                with st.spinner("Analizando el sector y construyendo el documento..."):
                    st.session_state["_estudio"] = construir_estudio(
                        base_estudio, contexto
                    )
                st.success("Estudio generado.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo generar el estudio: {exc}")

        estudio = st.session_state.get("_estudio")
        if estudio:
            est = estudio["mercado"]["estadisticas"]
            sello_est = datetime.now().strftime("%Y%m%d_%H%M")

            if est.get("n"):
                st.markdown("#### Resumen del análisis de precios")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Precio promedio", cop(est["media"]))
                m2.metric("Mediana", cop(est["mediana"]))
                m3.metric(
                    "Promedio ajustado", cop(est["ajustadas"].get("media")),
                    help=(
                        "Excluye los valores atípicos según el criterio del "
                        "rango intercuartílico que recomienda la guía."
                    ),
                )
                m4.metric(
                    "Atípicos detectados",
                    f"{est['atipicos']['n']} ({est['atipicos']['pct']:.1f}%)",
                )
                st.caption(
                    f"Coeficiente de variación: **{est['coef_variacion']:.1f}%** — "
                    f"{estudio['mercado']['interpretacion']}."
                )

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                try:
                    st.download_button(
                        "📘 Descargar en Word (.docx)",
                        data=exportar_docx(estudio),
                        file_name=f"estudio_del_sector_{sello_est}.docx",
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document"
                        ),
                        width="stretch",
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Word no disponible: {exc}")

            with col_d2:
                if not hay_soporte_pdf():
                    st.button(
                        "📕 PDF", disabled=True, width="stretch",
                        help=(
                            "Falta una fuente TrueType. Instala "
                            "'fonts-dejavu-core' o define PDF_FONT_DIR."
                        ),
                    )
                else:
                    try:
                        st.download_button(
                            "📕 Descargar en PDF",
                            data=exportar_pdf(estudio),
                            file_name=f"estudio_del_sector_{sello_est}.pdf",
                            mime="application/pdf",
                            width="stretch",
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"PDF no disponible: {exc}")

            st.caption(
                "Los apartados que exigen criterio de la Entidad (contexto "
                "técnico y regulatorio, presupuesto oficial, requisitos "
                "habilitantes, riesgos) se emiten señalados para que los "
                "completes: no se derivan de los datos de SECOP."
            )
