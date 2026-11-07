"""Testes do adaptador SQS com `moto`.

`moto` simula a API do SQS em memoria: nenhuma chamada sai da maquina e nenhum recurso
AWS e criado. Suficiente para verificar o contrato; **nao** substitui um teste contra o
SQS real, cuja limitacao esta registrada no relatorio da fase.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from nexus.queue.client import FailOutcome, QueueMessage
from nexus.queue.sqs import SqsQueue
from nexus.shared.config import Settings

REGION = "us-east-1"
MAX_RECEIVE = 3


@pytest.fixture
def sqs_urls() -> Iterator[tuple[str, str]]:
    """Cria fila principal e DLQ ligadas por redrive policy, como o Terraform fara."""
    with mock_aws():
        client = boto3.client("sqs", region_name=REGION)
        dlq = client.create_queue(QueueName="nexus-dlq")["QueueUrl"]
        dlq_arn = client.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        main = client.create_queue(
            QueueName="nexus-queue",
            Attributes={
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(MAX_RECEIVE)}
                )
            },
        )["QueueUrl"]
        yield main, dlq


@pytest.fixture
def settings(sqs_urls: tuple[str, str]) -> Settings:
    main, dlq = sqs_urls
    return Settings(
        env="aws",
        queue_backend="sqs",
        sqs_queue_url=main,
        sqs_dlq_url=dlq,
        aws_region=REGION,
        queue_visibility_timeout_seconds=30,
        # int(0.5) == 0 segundos de visibilidade: a mensagem volta na hora, sem sleep.
        queue_retry_backoff_base_seconds=0.5,
    )


@pytest.fixture
def queue(settings: Settings) -> SqsQueue:
    return SqsQueue(settings=settings)


def msg(n: int = 1) -> QueueMessage:
    return QueueMessage(event_id=f"evt-{n}", record_id=f"rec-{n}", correlation_id=f"corr-{n}")


class TestConstrucao:
    def test_exige_url(self) -> None:
        with pytest.raises(ValueError, match="sqs_queue_url"):
            SqsQueue(settings=Settings(env="local", queue_backend="sqlite"))

    def test_habilitada(self, queue: SqsQueue) -> None:
        assert queue.is_enabled is True


class TestPublicacaoERecebimento:
    def test_publica_e_recebe(self, queue: SqsQueue) -> None:
        assert queue.publish(msg()) is True
        recebidas = queue.receive(max_messages=10)

        assert len(recebidas) == 1
        assert recebidas[0].event_id == "evt-1"
        assert recebidas[0].record_id == "rec-1"
        assert recebidas[0].correlation_id == "corr-1"
        assert recebidas[0].receipt

    def test_preserva_correlation_id(self, queue: SqsQueue) -> None:
        """A trilha de log precisa atravessar a fronteira da fila."""
        queue.publish(QueueMessage("e", "r", "trilha-externa"))
        assert queue.receive(max_messages=1)[0].correlation_id == "trilha-externa"

    def test_torna_invisivel(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        queue.receive(max_messages=10)
        assert queue.receive(max_messages=10) == []

    def test_respeita_o_lote(self, queue: SqsQueue) -> None:
        for i in range(5):
            queue.publish(msg(i))
        assert len(queue.receive(max_messages=2)) <= 2

    def test_teto_do_sqs(self, queue: SqsQueue) -> None:
        """O SQS entrega no maximo 10 por chamada, mesmo pedindo mais."""
        for i in range(20):
            queue.publish(msg(i))
        assert len(queue.receive(max_messages=50)) <= 10

    def test_lote_invalido(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        assert queue.receive(max_messages=0) == []

    def test_fila_vazia(self, queue: SqsQueue) -> None:
        assert queue.receive(max_messages=10) == []


class TestRecibo:
    def test_apaga_com_recibo_valido(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]
        assert queue.delete(recebida.receipt) is True
        assert queue.stats().pending == 0

    def test_recibo_invalido_nao_derruba(self, queue: SqsQueue) -> None:
        assert queue.delete("recibo-inventado") is False

    def test_contagem_de_entregas_cresce(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        primeira = queue.receive(max_messages=1)[0]
        assert primeira.receive_count == 1

        queue.fail(primeira.receipt, error="falha")
        assert queue.receive(max_messages=1)[0].receive_count == 2


class TestFalhaEDlq:
    def test_falha_devolve_para_a_fila(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]

        assert queue.fail(recebida.receipt, error="falha") is FailOutcome.RETRY
        assert len(queue.receive(max_messages=1)) == 1

    def test_fail_nunca_move_para_dlq(self, queue: SqsQueue) -> None:
        """Quem conta tentativas e decide e o redrive_policy, nao a aplicacao.

        Duplicar a regra nos dois lugares faria as duas divergirem.
        """
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]
        assert queue.fail(recebida.receipt, error="falha") is not FailOutcome.DEAD_LETTERED

    def test_redrive_policy_move_apos_o_limite(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        for _ in range(MAX_RECEIVE + 1):
            lote = queue.receive(max_messages=1)
            if not lote:
                break
            queue.fail(lote[0].receipt, error="sempre falha")

        stats = queue.stats()
        assert stats.dead == 1
        assert stats.pending == 0

    def test_recibo_desconhecido_em_fail(self, queue: SqsQueue) -> None:
        assert queue.fail("nao-existe", error="x") is FailOutcome.UNKNOWN_RECEIPT

    def test_dead_letter_explicito(self, queue: SqsQueue) -> None:
        """O SQS nao oferece 'mover agora': e envio para a DLQ e remocao da principal."""
        queue.publish(msg())
        recebida = queue.receive(max_messages=1)[0]

        assert queue.dead_letter(recebida.receipt, error="registro inexistente") is True
        assert queue.stats().dead == 1

    def test_dead_letter_sem_dlq_configurada(self, settings: Settings) -> None:
        sem_dlq = SqsQueue(settings=settings.model_copy(update={"sqs_dlq_url": None}))
        sem_dlq.publish(msg())
        recebida = sem_dlq.receive(max_messages=1)[0]
        assert sem_dlq.dead_letter(recebida.receipt, error="x") is False


class TestEstatisticas:
    def test_contadores(self, queue: SqsQueue) -> None:
        for i in range(3):
            queue.publish(msg(i))
        assert queue.stats().pending == 3

        queue.receive(max_messages=2)
        stats = queue.stats()
        assert stats.in_flight >= 1
        assert stats.total == 3

    def test_fila_vazia(self, queue: SqsQueue) -> None:
        stats = queue.stats()
        assert stats.pending == 0
        assert stats.dead == 0


class TestRedrive:
    def _envenenar(self, queue: SqsQueue) -> None:
        queue.publish(msg())
        for _ in range(MAX_RECEIVE + 1):
            lote = queue.receive(max_messages=1)
            if not lote:
                break
            queue.fail(lote[0].receipt, error="falha")

    def test_devolve_da_dlq_com_contagem_exata(self, queue: SqsQueue) -> None:
        """A contagem real importa: as duas implementacoes prometem a mesma coisa."""
        self._envenenar(queue)
        assert queue.stats().dead == 1

        assert queue.redrive(limit=10) == 1
        assert queue.stats().dead == 0
        assert len(queue.receive(max_messages=10)) == 1

    def test_dlq_vazia(self, queue: SqsQueue) -> None:
        assert queue.redrive(limit=10) == 0

    def test_preserva_atributos_ao_devolver(self, queue: SqsQueue) -> None:
        self._envenenar(queue)
        queue.redrive(limit=10)
        recebida = queue.receive(max_messages=1)[0]
        assert recebida.record_id == "rec-1"
        assert recebida.correlation_id == "corr-1"

    def test_limite_invalido(self, queue: SqsQueue) -> None:
        assert queue.redrive(limit=0) == 0
