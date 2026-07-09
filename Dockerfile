FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN chmod +x /app/scripts/*.sh || true

RUN python -m pip install --upgrade pip setuptools wheel \
    && if [ -f requirements.txt ]; then pip install -r requirements.txt; fi \
    && if [ -f pyproject.toml ] && grep -q "^prod =" pyproject.toml; then pip install -e ".[prod]"; elif [ -f pyproject.toml ]; then pip install -e .; fi

VOLUME ["/app/data", "/app/logs"]

EXPOSE 8000

ENTRYPOINT ["/app/scripts/run-local.sh"]
