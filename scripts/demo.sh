#!/usr/bin/env bash
#
# Demonstracao reproduzivel do Nexus Architecture — Fase 8.
#
# Roteirizada, nao gravada: um video envelhece em silencio e nao pode ser verificado.
# Este script roda contra a pilha real e mostra o que o sistema de fato faz. Se uma
# etapa parar de funcionar, ele falha aqui, no lugar certo.
#
# TODOS OS DADOS SAO SINTETICOS, gerados por tools/generator.py com semente fixa.
# Nenhum dado pessoal real e usado em nenhum momento do projeto.
#
#   ./scripts/demo.sh                 # roteiro completo
#   ./scripts/demo.sh --registros 200
#   ./scripts/demo.sh --pausar        # espera ENTER entre os atos
#   ./scripts/demo.sh --zerar         # DESTRUTIVO: apaga os dados locais antes
#   ./scripts/demo.sh --manter        # nao derruba a pilha no fim

set -euo pipefail

cd "$(dirname "$0")/.."

PY=.venv/bin/python
API=http://localhost:8080
REGISTROS=120
SEMENTE=808
PAUSAR=0
ZERAR=0
MANTER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --registros) REGISTROS="$2"; shift 2 ;;
    --semente)   SEMENTE="$2";   shift 2 ;;
    --pausar)    PAUSAR=1; shift ;;
    --zerar)     ZERAR=1;  shift ;;
    --manter)    MANTER=1; shift ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

AZUL=$'\033[36m'; CINZA=$'\033[90m'; FIM=$'\033[0m'

ato() {
  printf '\n%s%s%s\n' "$AZUL" "══ $* " "$FIM"
  [ "$PAUSAR" = 1 ] && { printf '%s(ENTER para seguir)%s' "$CINZA" "$FIM"; read -r _; } || true
}
nota() { printf '%s   %s%s\n' "$CINZA" "$*" "$FIM"; }
json() { "$PY" -m json.tool; }

# Le um campo da profundidade da fila. O roteiro decide o que fazer a partir do estado
# real, nunca a partir do tempo que ele imagina ter esperado.
fila() { curl -fsS "$API/v1/ops/queue" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
alertas() { curl -fsS "$API/v1/observability/alerts" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["alerts"]))'; }

# Uma narracao que nao corresponde ao estado e pior que nenhuma narracao. Se o roteiro
# anuncia que o alerta acendeu, ele precisa quebrar quando nao acendeu.
exige() { [ "$1" = "$2" ] || { printf "\nFALHA: esperava %s, obtive %s (%s)\n" "$2" "$1" "$3" >&2; exit 1; }; }

# ---------------------------------------------------------------- pre-requisitos

command -v docker >/dev/null || { echo "docker nao encontrado" >&2; exit 1; }
[ -x "$PY" ] || { echo "ambiente Python ausente. Execute: uv sync" >&2; exit 1; }

if [ "$ZERAR" = 1 ]; then
  ato "Zerando os dados locais (--zerar)"
  docker compose down -v
fi

# --------------------------------------------------------------------- ato 1

ato "1. Subindo a plataforma"
docker compose up -d --build --wait
nota "DynamoDB Local + API. Nenhum recurso de nuvem e criado; custo US\$ 0,00."

# O healthcheck do compose ja cobre isso, mas o roteiro tambem roda contra uma pilha
# que alguem subiu de outro jeito. Esperar aqui custa nada e evita um connection reset
# intermitente que pareceria defeito da API.
espera=0
until curl -fsS -o /dev/null "$API/health"; do
  espera=$((espera + 1))
  [ "$espera" -gt 60 ] && { echo "a API nao respondeu em 60s" >&2; exit 1; }
  sleep 1
done

curl -fsS "$API/health" | json
nota "'queue: enabled' e 'trail_enabled' vem da configuracao efetiva do processo,"
nota "nao de um rotulo passado por quem executa."

# --------------------------------------------------------------------- ato 2

ato "2. Ingestao de $REGISTROS registros sinteticos (semente $SEMENTE)"
nota "duplicate-rate 0.15 e variant-rate 0.30: o acervo inclui repeticoes exatas"
nota "e variacoes da mesma pessoa, que e o que a resolucao precisa enfrentar."
"$PY" tools/generator.py \
  --count "$REGISTROS" --duplicate-rate 0.15 --variant-rate 0.30 \
  --seed "$SEMENTE" --post --url "$API"

ato "3. O que a transacao deixou pendente"
curl -fsS "$API/v1/ops/queue" | json
nota "'pending' e a fila; 'outbox_pending' e o que a publicacao inline nao conseguiu"
nota "entregar. Os dois vem do armazenamento, nao de contador em memoria."

# --------------------------------------------------------------------- ato 3

ato "4. Despachando o outbox e consumindo a fila"
nota "Sob demanda: nenhum worker fica residente. Nada processa sozinho."
docker compose exec -T api python -m nexus.queue.dispatcher --limit 1000 || true
docker compose exec -T api python -m nexus.queue.worker --drain

curl -fsS "$API/v1/ops/queue" | json

# --------------------------------------------------------------------- ato 4

ato "5. A jornada de um registro, atravessando dois processos"
REC=$(curl -fsS "$API/v1/records?limit=1" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["record_id"])')
nota "registro: $REC"
curl -fsS "$API/v1/observability/trail/$REC" | json
nota "'service' muda entre os marcos: 'accepted' veio da API, 'consumed' e 'resolved'"
nota "do worker. Antes da Fase 6 essas duas metades viviam em logs que nunca se"
nota "encontravam. 'delta_ms' entre published e consumed e espera na fila — e o"
nota "numero que separa 'o processamento esta lento' de 'a fila esta acumulando'."

# --------------------------------------------------------------------- ato 5

ato "6. Resolucao de identidade"
curl -fsS "$API/v1/resolution/stats" | json
nota "POSSIBLE_MATCH nunca funde sozinho: fica pendente de decisao humana."
curl -fsS "$API/v1/resolution/reviews?limit=3" | json

# --------------------------------------------------------------------- ato 6

ato "7. Falha deliberada: retentativa, backoff e DLQ"
nota "NEXUS_FAILURE_INJECTION_RATE=1.0 faz todo processamento falhar. Exercita o"
nota "caminho de erro sem adulterar nenhum dado de entrada."
"$PY" tools/generator.py --count 10 --seed $((SEMENTE + 1)) --post --url "$API" >/dev/null
docker compose exec -T api python -m nexus.queue.dispatcher --limit 100 || true

# O numero de tentativas ate a DLQ e queue_max_receive, mas o intervalo entre elas e
# backoff exponencial: a mensagem fica invisivel, e um 'drain' nesse meio tempo nao
# recebe nada e termina na hora. Esperar um tempo fixo e o erro obvio — na primeira
# versao deste roteiro, tres passadas com 2s entre elas devolviam 'dead: 0' e os dois
# atos seguintes narravam um alerta que nunca acendeu.
tentativa=0
while [ "$(fila dead)" = "0" ]; do
  tentativa=$((tentativa + 1))
  if [ "$tentativa" -gt 12 ]; then
    echo "a DLQ nao recebeu nada em 12 passadas — o caminho de falha regrediu" >&2
    curl -fsS "$API/v1/ops/queue" | json >&2
    exit 1
  fi
  docker compose exec -T -e NEXUS_FAILURE_INJECTION_RATE=1.0 api \
    python -m nexus.queue.worker --drain || true
  sleep 3
done
curl -fsS "$API/v1/ops/queue" | json
nota "'dead' subiu depois de queue_max_receive entregas, cada uma seguida de backoff."

ato "8. O alerta acende sozinho"
curl -fsS "$API/v1/observability/alerts" | json
exige "$([ "$(alertas)" -gt 0 ] && echo sim || echo nao)" "sim" "a DLQ nao esta vazia, o alerta deveria estar aceso"
nota "Nenhum limiar foi configurado em outro lugar: a condicao e calculada a partir"
nota "do estado real. Foi essa a licao da Fase 4, onde um campo fixo no codigo"
nota "declarava 'nao implementado' um modulo que ja existia."

# --------------------------------------------------------------------- ato 7

ato "9. Redrive: devolvendo a DLQ para a fila"
curl -fsS -X POST "$API/v1/ops/redrive" -H 'content-type: application/json' -d '{"limit":100}' | json
# Sem injecao de falha, agora processa. O laco existe porque o redrive devolve as
# mensagens com o prazo de visibilidade corrente, nao necessariamente todas visiveis ja.
passada=0
while [ "$(fila pending)" != "0" ] || [ "$(fila in_flight)" != "0" ]; do
  passada=$((passada + 1))
  [ "$passada" -gt 12 ] && { echo "a fila nao esvaziou apos o redrive" >&2; exit 1; }
  docker compose exec -T api python -m nexus.queue.worker --drain || true
  sleep 2
done
curl -fsS "$API/v1/ops/queue" | json
exige "$(fila dead)" "0" "a DLQ deveria estar vazia depois do redrive"

ato "10. O alerta apaga"
curl -fsS "$API/v1/observability/alerts" | json
exige "$(alertas)" "0" "nenhuma condicao deveria estar ativa"
nota "Mesma consulta do ato 8. A diferenca e o estado, nao a configuracao."

# --------------------------------------------------------------------- fim

ato "11. Metricas e serie persistida"
curl -fsS "$API/metrics" | json
nota "'scope: in_process' esta declarado: estes contadores sao de UM processo e"
nota "zeram no reinicio. A profundidade da fila, essa vem do armazenamento."
curl -fsS "$API/v1/observability/series?metric=platform&window=30" | json
nota "'gaps' conta os baldes sem amostra. A amostragem e oportunista: sem ninguem"
nota "observando, nada e amostrado — e a interface diz isso em vez de interpolar."

ato "Fim"
nota "Control Center:  make dashboard   (http://localhost:5173)"
nota "API e docs:      $API/docs"
if [ "$MANTER" = 1 ]; then
  nota "Pilha mantida no ar (--manter). Para derrubar: make down"
else
  nota "Derrubando a pilha (os dados sao preservados; use 'make clean' para apagar)."
  docker compose down
fi
