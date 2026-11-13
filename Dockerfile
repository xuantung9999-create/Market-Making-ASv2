# Avellaneda-Stoikov market maker — reproducible environment
#
# Build:   docker build -t mm-as .
# Run:     docker run --rm -p 8000:8000 mm-as            (dashboard on http://localhost:8000)
# More:    see DOCKER.md, or use docker compose

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    TZ=UTC

WORKDIR /app

# Install dependencies first so code changes don't re-download packages
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Normalise line endings in case the repo was checked out on Windows with CRLF
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh \
 && mkdir -p data results \
 && useradd --create-home --uid 1000 mm && chown -R mm:mm /app
USER mm

# data/ (downloaded + recorded market data) and results/ (backtest output) live outside the image
VOLUME ["/app/data", "/app/results"]

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["dashboard"]
