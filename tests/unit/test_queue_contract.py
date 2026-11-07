"""Bateria de contrato: a mesma verificacao contra SqliteQueue e SqsQueue.

## Por que existe

Duas implementacoes do mesmo contrato que divergem em comportamento sao uma armadilha:
o codigo passa nos testes locais e falha na nuvem, ou pior, funciona nos dois lugares
de formas diferentes. O defeito aparece em producao, onde custa caro.

Cada teste aqui roda duas vezes — uma por implementacao. Se as duas discordam, a suite
quebra na hora.

## O que NAO esta aqui

Diferencas legitimas, documentadas no ADR-008, ficam nos testes especificos de cada
implementacao:

| Comportamento | SQLite | SQS |
|---|---|---|
| `publish` repetido | `False` (deduplica por `event_id`) | `True` (nao deduplica) |
| Quem decide a DLQ | `fail`, contando entregas | O `redrive_policy` da fila |
| Ordem de entrega | Por `visible_at` | Sem garantia de ordem |

Forcar essas diferencas a coincidir esconderia o que realmente muda entre os ambientes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from nexus.queue.client import FailOutcome, QueueClient, QueueMessage
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.sqs import SqsQueue
from nexus.shared.config import Settings

REGION = "us-east-1"
MAX_RECEIVE = 3
#: Espera suficiente para a mensagem voltar em ambas as implementacoes.
RETRY_WAIT = 0.08


def msg(n: int = 1) -> QueueMessage:
    return QueueMessage(event_id=f"evt-{n}", record_id=f"rec-{n}", correlation_id=f"corr-{n}")


@pytest.fixture(params=["sqlite", "sqs"])
def queue(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[QueueClient]:
    """Entrega cada implementacao do contrato, configurada de forma equivalente."""
    if request.param == "sqlite":
        settings = Settings(
            env="local",
            queue_path=str(tmp_path / "fila.db"),
            queue_max_receive=MAX_RECEIVE,
            queue_retry_backoff_base_seconds=0.01,
            queue_visibility_timeout_seconds=30,
        )
        fila = SqliteQueue(settings=settings)
        try:
            yield fila
        finally:
            fila.close()
        return

    with mock_aws():
        client = boto3.client("sqs", region_name=REGION)
        dlq = client.create_queue(QueueName="contrato-dlq")["QueueUrl"]
        dlq_arn = client.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        main = client.create_queue(
            QueueName="contrato",
            Attributes={
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(MAX_RECEIVE)}
                )
            },
        )["QueueUrl"]
        yield SqsQueue(
            settings=Settings(
                env="aws",
                queue_backend="sqs",
                sqs_queue_url=main,
                sqs_dlq_url=dlq,
                aws_region=REGION,
                queue_visibility_timeout_seconds=30,
                # int(0.5) == 0: a mensagem volta imediatamente.
                queue_retry_backoff_base_seconds=0.5,
            )
        )


class TestHabilitacao:
    def test_fila_configurada_esta_habilitada(self, queue: QueueClient) -> None:
        assert queue.is_enabled is True


class TestPublicacao:
    def test_mensagem_publicada_fica_pendente(self, queue: QueueClient) -> None:
        queue.publish(msg())
        assert queue.stats().pending == 1

    def test_mensagens_distintas_coexistem(self, queue: QueueClient) -> None:
        for i in range(5):
            queue.publish(msg(i))
        assert queue.stats().pending == 5


class TestRecebimento:
    def test_entrega_os_campos_da_mensagem(self, queue: QueueClient) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=10)[0]

        assert recebida.event_id == "evt-1"
        assert recebida.record_id == "rec-1"
        assert recebida.correlation_id == "corr-1"
        assert recebida.receipt
        assert recebida.receive_count == 1

    def test_mensagem_entregue_fica_invisivel(self, queue: QueueClient) -> None:
        queue.publish(msg())
        queue.receive(max_messages=10)
        assert queue.receive(max_messages=10) == []

    def test_fila_vazia_devolve_lista_vazia(self, queue: QueueClient) -> None:
        assert queue.receive(max_messages=10) == []

    def test_lote_invalido_devolve_vazio(self, queue: QueueClient) -> None:
        queue.publish(msg())
        assert queue.receive(max_messages=0) == []

    def test_respeita_o_tamanho_do_lote(self, queue: QueueClient) -> None:
        for i in range(8):
            queue.publish(msg(i))
        assert len(queue.receive(max_messages=3)) <= 3


class TestRecibo:
    def test_apaga_com_recibo_valido(self, queue: QueueClient) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]

        assert queue.delete(recebida.receipt) is True
        assert queue.stats().total == 0

    def test_recibo_desconhecido_nao_apaga(self, queue: QueueClient) -> None:
        queue.publish(msg())
        queue.receive(max_messages=1)
        assert queue.delete("recibo-inventado") is False


class TestFalhaERetentativa:
    def test_falha_devolve_a_mensagem(self, queue: QueueClient) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]

        assert queue.fail(recebida.receipt, error="falha") is FailOutcome.RETRY
        time.sleep(RETRY_WAIT)
        assert len(queue.receive(max_messages=1)) == 1

    def test_contagem_de_entregas_cresce(self, queue: QueueClient) -> None:
        queue.publish(msg())
        primeira = queue.receive(max_messages=1)[0]
        queue.fail(primeira.receipt, error="falha")
        time.sleep(RETRY_WAIT)

        assert queue.receive(max_messages=1)[0].receive_count == 2

    def test_recibo_desconhecido_em_fail(self, queue: QueueClient) -> None:
        assert queue.fail("nao-existe", error="x") is FailOutcome.UNKNOWN_RECEIPT

    def test_mensagem_vai_para_dlq_apos_o_limite(self, queue: QueueClient) -> None:
        """Quem aplica a regra difere; o resultado observavel nao."""
        queue.publish(msg())
        for _ in range(MAX_RECEIVE + 1):
            lote = queue.receive(max_messages=1)
            if not lote:
                break
            queue.fail(lote[0].receipt, error="sempre falha")
            time.sleep(RETRY_WAIT)

        stats = queue.stats()
        assert stats.dead == 1
        assert stats.pending == 0


class TestDeadLetterExplicito:
    def test_move_sem_gastar_tentativas(self, queue: QueueClient) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]

        assert queue.dead_letter(recebida.receipt, error="irrecuperavel") is True
        assert queue.stats().dead == 1


class TestRedrive:
    def _envenenar(self, queue: QueueClient) -> None:
        queue.publish(msg())
        for _ in range(MAX_RECEIVE + 1):
            lote = queue.receive(max_messages=1)
            if not lote:
                break
            queue.fail(lote[0].receipt, error="falha")
            time.sleep(RETRY_WAIT)

    def test_devolve_com_contagem_exata(self, queue: QueueClient) -> None:
        self._envenenar(queue)
        assert queue.stats().dead == 1

        assert queue.redrive(limit=10) == 1
        assert queue.stats().dead == 0

    def test_mensagem_devolvida_e_consumivel(self, queue: QueueClient) -> None:
        self._envenenar(queue)
        queue.redrive(limit=10)

        recebida = queue.receive(max_messages=10)
        assert len(recebida) == 1
        assert recebida[0].record_id == "rec-1"

    def test_dlq_vazia(self, queue: QueueClient) -> None:
        assert queue.redrive(limit=10) == 0

    def test_limite_invalido(self, queue: QueueClient) -> None:
        self._envenenar(queue)
        assert queue.redrive(limit=0) == 0
        assert queue.stats().dead == 1


class TestEstatisticas:
    def test_soma_das_partes(self, queue: QueueClient) -> None:
        for i in range(4):
            queue.publish(msg(i))
        queue.receive(max_messages=2)

        stats = queue.stats()
        assert stats.total == stats.pending + stats.in_flight + stats.dead
        assert stats.total == 4

    def test_fila_vazia(self, queue: QueueClient) -> None:
        stats = queue.stats()
        assert (stats.pending, stats.in_flight, stats.dead) == (0, 0, 0)


class TestDiferencasDocumentadas:
    """Confirma que as divergencias conhecidas sao as que o ADR-008 declara.

    Se uma delas mudar sem o documento mudar junto, este teste avisa.
    """

    def test_deduplicacao_de_publicacao_difere(self, queue: QueueClient) -> None:
        queue.publish(msg())
        repetida = queue.publish(msg())

        if isinstance(queue, SqliteQueue):
            assert repetida is False, "a fila local deduplica por event_id"
            assert queue.stats().pending == 1
        else:
            assert repetida is True, "a fila SQS padrao nao deduplica"
            assert queue.stats().pending == 2
