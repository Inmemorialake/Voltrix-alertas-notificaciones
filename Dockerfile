# syntax=docker/dockerfile:1

# ---------- Etapa 1: dependencias en un virtualenv ----------
FROM python:3.12-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY app/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

# ---------- Etapa 2: imagen final ----------
FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENAPI_PATH=/srv/openapi.yaml \
    DOCS_PATH=/srv/index.html
RUN groupadd --system --gid 10001 alertas \
 && useradd --system --uid 10001 --gid alertas --no-create-home --shell /usr/sbin/nologin alertas
WORKDIR /srv
COPY --from=deps /opt/venv /opt/venv
COPY app/ ./app/
COPY openapi.yaml index.html ./
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "app"]
