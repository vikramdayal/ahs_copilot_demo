# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS runtime

ARG AHS_MODEL_EXTRAS="ui,model-openai,model-anthropic,model-bedrock"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/ahs-home \
    PORT=8501

WORKDIR /app

RUN groupadd --system ahs \
    && useradd --system --gid ahs --home-dir /tmp/ahs-home --shell /usr/sbin/nologin ahs

COPY --chown=ahs:ahs pyproject.toml README.md ./
COPY --chown=ahs:ahs src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[${AHS_MODEL_EXTRAS}]"

COPY --chown=ahs:ahs . .

RUN chmod 0555 /app/scripts/start.sh \
    && chmod 0444 /app/scripts/healthcheck.py /app/scripts/preflight.py

USER ahs

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/scripts/healthcheck.py"]

ENTRYPOINT ["/app/scripts/start.sh"]
