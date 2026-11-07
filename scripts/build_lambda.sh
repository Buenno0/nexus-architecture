#!/usr/bin/env bash
#
# Empacota a aplicacao para o AWS Lambda.
#
# Zip em vez de imagem de container: cold start menor e deploy mais simples. A imagem
# so se justificaria com dependencias grandes demais para o limite de 250 MB
# descompactados.
#
# A compilacao e CRUZADA: a maquina e macOS arm64, o destino e Linux arm64 (Graviton).
# Instalar as dependencias sem informar a plataforma traria wheels do macOS, que a
# Lambda nao consegue carregar — e o erro so apareceria no primeiro deploy.
#
# Uso:
#   ./scripts/build_lambda.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSTRUCAO="${RAIZ}/build/lambda"
DESTINO="${RAIZ}/dist"
PACOTE="${DESTINO}/nexus-lambda.zip"

# O runtime Python 3.13 do Lambda roda sobre Amazon Linux 2023 (glibc 2.34).
# "aarch64-manylinux_2_17" e conservador demais e resolveria para versoes antigas
# de pacotes compilados, como rapidfuzz.
PLATAFORMA="aarch64-unknown-linux-gnu"
VERSAO_PYTHON="3.13"

echo "==> Limpando construcao anterior"
rm -rf "${CONSTRUCAO}" "${PACOTE}"
mkdir -p "${CONSTRUCAO}" "${DESTINO}"

echo "==> Exportando dependencias de producao"
# --no-dev: pytest, ruff e companhia nao vao para a Lambda.
uv export --no-dev --no-emit-project --frozen --format requirements-txt \
  > "${CONSTRUCAO}/requirements.txt"

echo "==> Instalando para ${PLATAFORMA}, Python ${VERSAO_PYTHON}"
# --only-binary :all: e essencial: sem ele, uv COMPILA o pacote na maquina local
# quando nao acha wheel, gerando um binario macOS que a Lambda nao consegue carregar.
# O erro so apareceria no primeiro deploy.
uv pip install \
  --target "${CONSTRUCAO}" \
  --python-platform "${PLATAFORMA}" \
  --python-version "${VERSAO_PYTHON}" \
  --only-binary :all: \
  --no-installer-metadata \
  --no-compile-bytecode \
  --requirement "${CONSTRUCAO}/requirements.txt" \
  --quiet

echo "==> Copiando o codigo da aplicacao"
cp -R "${RAIZ}/src/nexus" "${CONSTRUCAO}/nexus"

echo "==> Removendo o que nao precisa rodar na nuvem"

# boto3 e botocore ja existem no ambiente do Lambda. O servidor Uvicorn e suas
# aceleracoes nao rodam la: o Mangum fala ASGI direto com o FastAPI, e uvloop sozinho
# pesa 16 MB — cada megabyte entra no tempo de cold start.
#
# Continuam instalados no ambiente local, onde o Docker de fato roda o Uvicorn.
DISPENSAVEIS=(boto3 botocore uvicorn uvloop httptools websockets watchfiles)

for pacote in "${DISPENSAVEIS[@]}"; do
  rm -rf "${CONSTRUCAO:?}/${pacote}"
  # Remove SOMENTE o metadado do pacote removido.
  #
  # Apagar todos os *.dist-info de uma vez quebra a aplicacao em producao: o
  # email-validator, que o Pydantic usa em EmailStr, consulta a propria versao via
  # importlib.metadata. Sem o dist-info ele levanta
  # "No package metadata was found for email-validator" no import, e a Lambda falha
  # antes de atender a primeira requisicao.
  rm -rf "${CONSTRUCAO:?}/${pacote}"-*.dist-info
  rm -rf "${CONSTRUCAO:?}/${pacote//-/_}"-*.dist-info
done

find "${CONSTRUCAO}" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "${CONSTRUCAO}" -type d -name "tests" -prune -exec rm -rf {} + 2>/dev/null || true
rm -f "${CONSTRUCAO}/requirements.txt"

echo "==> Verificando metadados que a aplicacao consulta em runtime"
# Pacotes que leem a propria versao com importlib.metadata. Sem dist-info, o import
# falha — e so na nuvem.
for obrigatorio in email_validator pydantic fastapi; do
  if ! ls -d "${CONSTRUCAO}/${obrigatorio//_/-}"-*.dist-info >/dev/null 2>&1 \
    && ! ls -d "${CONSTRUCAO}/${obrigatorio}"-*.dist-info >/dev/null 2>&1; then
    echo "ERRO: faltou o metadado de ${obrigatorio}" >&2
    exit 1
  fi
done

echo "==> Compactando"
(cd "${CONSTRUCAO}" && zip -qr "${PACOTE}" . -x '*.pyc')

TAMANHO=$(du -h "${PACOTE}" | cut -f1)
DESCOMPACTADO=$(du -sh "${CONSTRUCAO}" | cut -f1)

echo
echo "pacote:        ${PACOTE}"
echo "compactado:    ${TAMANHO}"
echo "descompactado: ${DESCOMPACTADO}  (limite da Lambda: 250 MB)"
