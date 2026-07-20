# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm AS runtime

ARG AHS_MODEL_EXTRAS="ui"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/ahs-home \
    PORT=8501

WORKDIR /app

RUN groupadd --system --gid 10001 ahs \
    && useradd --system --uid 10001 --gid ahs --home-dir /tmp/ahs-home --shell /usr/sbin/nologin ahs

COPY --chown=ahs:ahs pyproject.toml README.md ./
COPY --chown=ahs:ahs src ./src

RUN python -m pip install ".[${AHS_MODEL_EXTRAS}]" \
    && python -m pip check

COPY --chown=ahs:ahs config ./config
COPY --chown=ahs:ahs metadata ./metadata
COPY --chown=ahs:ahs scripts ./scripts
COPY --chown=ahs:ahs tests/fixtures/synthetic ./tests/fixtures/synthetic
COPY --chown=ahs:ahs .streamlit/config.toml ./.streamlit/config.toml

RUN chmod 0555 /app/scripts/start.sh /app/scripts/docker-doctor.sh \
    && chmod 0444 /app/scripts/healthcheck.py /app/scripts/preflight.py \
    && python -m compileall -q /app/src /app/scripts

USER 10001:10001

EXPOSE 8501
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/scripts/healthcheck.py"]

ENTRYPOINT ["/app/scripts/start.sh"]
