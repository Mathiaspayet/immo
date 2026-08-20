# ====================================================================
#  Dockerfile — Veille immobiliere
#
#  Un seul conteneur : FastAPI sert l'API, l'interface et le
#  planificateur (CDC 3). Image de base « slim », aucune chaine de
#  compilation : le frontend est en modules ES natifs, il n'y a rien a
#  construire.
# ====================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Identite du build, injectee par GitHub Actions et affichee dans l'ecran
# Reglages : savoir quelle version tourne sur le NAS evite bien des doutes.
ARG BUILD_VERSION=dev
ARG BUILD_DATE=inconnue
ENV BUILD_VERSION=${BUILD_VERSION} \
    BUILD_DATE=${BUILD_DATE}

# tzdata : sans la base des fuseaux, Europe/Paris serait inconnu et le
# planificateur retomberait sur UTC — les imports partiraient deux heures trop tot.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/app/
COPY healthcheck.py /app/

# /data est monte sur un volume : la base SQLite doit survivre au
# remplacement de l'image par Watchtower (CDC 2).
RUN mkdir -p /data
VOLUME ["/data"]
ENV VEILLE_BASE=/data/veille.db \
    VEILLE_PORT=8000 \
    TZ=Europe/Paris

EXPOSE 8000

# Sans sonde, un conteneur qui demarre mais ne repond plus reste « up » :
# Watchtower deploierait une image cassee sans que rien ne le signale.
HEALTHCHECK --interval=60s --timeout=10s --start-period=25s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD python -m uvicorn app.main:application \
      --host "${VEILLE_HOTE:-0.0.0.0}" --port "${VEILLE_PORT:-8000}"
