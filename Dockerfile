# syntax=docker/dockerfile:1
FROM python:3.13-slim

# uv: resolucao e instalacao deterministicas a partir do uv.lock
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencias primeiro: aproveita o cache de camadas quando so o codigo muda.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src/ ./src/
COPY tools/ ./tools/
RUN uv sync --frozen

# Processo sem privilegios
RUN useradd --create-home --uid 10001 nexus && chown -R nexus:nexus /app

# /data recebe o volume nomeado da fila. Um volume vazio herda dono e permissoes do
# diretorio correspondente na imagem — sem este chown ele nasceria pertencendo a root
# e o processo sem privilegios nao conseguiria abrir o banco.
RUN mkdir -p /data && chown nexus:nexus /data
VOLUME ["/data"]

USER nexus

EXPOSE 8080
CMD ["uvicorn", "nexus.ingestion.api:app", "--host", "0.0.0.0", "--port", "8080"]
