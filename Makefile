.PHONY: help up down logs test test-unit test-int lint fmt generate table clean \
        dispatch process drain queue-stats redrive pipeline reprocess resolution \
        reviews fail-test lambda tf-validate tf-plan dashboard dashboard-build \
        dashboard-test dashboard-check demo ci

PY := .venv/bin/python
N  ?= 100

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:        ## Sobe DynamoDB Local + API
	docker compose up -d --build
	@echo "API: http://localhost:8080/docs"

down:      ## Derruba os servicos (preserva os dados)
	docker compose down

logs:      ## Acompanha os logs da API
	docker compose logs -f api

table:     ## Cria a tabela no DynamoDB Local (idempotente)
	$(PY) -m nexus.persistence.tables

# A fila SQLite vive dentro do container (ADR-004): WAL nao atravessa a fronteira
# host/VM no macOS. Por isso os comandos rodam via 'docker compose exec', nao no host.
DC := docker compose exec -T api

dispatch:  ## Publica eventos pendentes do outbox na fila
	$(DC) python -m nexus.queue.dispatcher $(if $(LIMIT),--limit $(LIMIT),)

process:   ## Consome um lote da fila
	$(DC) python -m nexus.queue.worker $(if $(BATCH),--batch-size $(BATCH),)

drain:     ## Consome ate esvaziar a fila (ainda sob demanda, nao residente)
	$(DC) python -m nexus.queue.worker --drain

dashboard: ## Sobe o Control Center em modo de desenvolvimento (porta 5173)
	cd control-center && npm run dev

dashboard-build: ## Compila o Control Center para producao
	cd control-center && npm run build

dashboard-test: ## Testes do Control Center
	cd control-center && npm run test

dashboard-check: ## Tipos, lint e testes do Control Center
	cd control-center && npx tsc --noEmit && npm run lint && npm run test

lambda:    ## Empacota a aplicacao para o AWS Lambda
	./scripts/build_lambda.sh

tf-validate: ## Valida o Terraform (nao cria nada, nao exige credenciais)
	cd infra/terraform && terraform fmt -check && terraform init -backend=false -input=false >/dev/null && terraform validate

tf-plan:   ## Mostra o que seria criado (EXIGE credenciais; nao cria nada)
	cd infra/terraform && terraform plan -input=false

reprocess: ## Reenfileira o acervo sob a versao corrente do processador
	$(DC) python -m nexus.queue.reprocess $(if $(LIMIT),--limit $(LIMIT),)

resolution: ## Contadores de Entity Resolution
	@curl -s localhost:8080/v1/resolution/stats | $(PY) -m json.tool

reviews:   ## Pares aguardando decisao humana
	@curl -s 'localhost:8080/v1/resolution/reviews?limit=10' | $(PY) -m json.tool

fail-test: ## Consome com injecao de falhas, para exercitar retentativa e DLQ
	docker compose exec -T -e NEXUS_FAILURE_INJECTION_RATE=$(or $(RATE),0.5) api \
		python -m nexus.queue.worker --drain

queue-stats: ## Profundidade da fila, em voo e DLQ
	@curl -s localhost:8080/v1/ops/queue | $(PY) -m json.tool

redrive:   ## Devolve mensagens da DLQ para a fila
	@curl -s -X POST localhost:8080/v1/ops/redrive | $(PY) -m json.tool

pipeline:  ## Ciclo completo: despacha e processa tudo
	$(MAKE) dispatch && $(MAKE) drain && $(MAKE) queue-stats

test:      ## Suite completa
	.venv/bin/pytest --cov=src/nexus --cov-report=term-missing

test-unit: ## Apenas testes unitarios (nao requer Docker)
	.venv/bin/pytest tests/unit -m "not integration"

test-int:  ## Apenas testes de integracao (requer DynamoDB Local)
	.venv/bin/pytest tests/integration -m integration

lint:      ## ruff + mypy strict
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/mypy

fmt:       ## Formata o codigo
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

generate:  ## Gera e envia N registros sinteticos (make generate N=1000)
	$(PY) tools/generator.py --count $(N) --post

load:      ## Uma corrida de carga (make load NOME=exp USUARIOS=50 DURACAO=60s)
	$(PY) tools/loadtest.py --nome $(or $(NOME),ad-hoc) \
		--usuarios $(or $(USUARIOS),50) --duracao $(or $(DURACAO),60s)

campaign:  ## Campanha completa da Fase 7 (DESTRUTIVO: zera os dados entre corridas)
	$(PY) tools/campanha.py --tudo

demo:      ## Demonstracao roteirizada ponta a ponta (make demo ARGS=--pausar)
	./scripts/demo.sh $(ARGS)

ci:        ## Os mesmos comandos que o pipeline roda, nesta maquina
	$(MAKE) lint
	docker compose up -d --wait dynamodb
	NEXUS_TEST_REQUIRE_DYNAMO=1 .venv/bin/pytest --cov=src/nexus --cov-report=term-missing
	$(MAKE) dashboard-check

clean:     ## Remove containers e volumes (DESTRUTIVO: apaga os dados locais)
	docker compose down -v
