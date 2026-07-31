# Imagen para desplegar el dashboard en cualquier host de contenedores
# (Render, Railway, Fly.io, Hugging Face Spaces, Cloud Run...).
#
#   docker build -t adel-sector .
#   docker run -p 8501:8501 adel-sector
#
# Nota: Vercel NO sirve para esto. Streamlit necesita un proceso servidor
# de larga vida con WebSockets, y Vercel ejecuta funciones serverless de
# vida corta. Usa esta imagen o Streamlit Community Cloud.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# fonts-dejavu-core: necesario para la exportación a PDF (fpdf2 requiere
# una TrueType con soporte Unicode). curl: para el healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El pipeline crea estos directorios al importar config.py, pero se
# adelantan aquí para que existan aunque el contenedor sea de solo lectura.
RUN mkdir -p output logs

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Forma shell para que ${PORT} (Render/Railway lo inyectan) se expanda.
CMD streamlit run app.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0
