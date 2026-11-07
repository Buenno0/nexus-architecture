#!/usr/bin/env python3
"""Gerador de dados sinteticos para o Nexus Architecture.

**Todos os dados produzidos sao ficticios.** Nenhum dado pessoal real e utilizado.
Documentos, e-mails e telefones sao gerados pelo Faker e nao correspondem a pessoas
reais — ver SECURITY.md.

O gerador controla a taxa de duplicidade porque a plataforma precisa ser exercitada nos
tres casos distintos (ADR-002):

``--duplicate-rate``
    Fracao de registros reenviados com conteudo **byte-identico**. A API deve responder
    ``200`` com ``status="duplicate"`` e nao criar nova observacao.

``--variant-rate``
    Fracao de registros reenviados com a **mesma entidade e conteudo alterado**. A API
    deve responder ``202``: e uma atualizacao legitima, nao uma duplicata. Este e
    exatamente o caso que um desenho ingenuo de idempotencia descartaria em silencio.

Exemplos::

    python tools/generator.py --count 100 --post
    python tools/generator.py --count 1000 --duplicate-rate 0.2 --variant-rate 0.1 --post
    python tools/generator.py --count 5 --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from faker import Faker

DEFAULT_URL = "http://localhost:8080"
#: Teto rigido de seguranca e custo. Ver COSTS.md.
MAX_RECORDS = 10_000

ENDPOINTS = {
    "person": "/v1/records/person",
    "organization": "/v1/records/organization",
}


@dataclass
class Stats:
    accepted: int = 0
    duplicate: int = 0
    replayed: int = 0
    conflict: int = 0
    rejected: int = 0
    failed: int = 0

    def render(self) -> str:
        return (
            f"aceitos={self.accepted}  duplicados={self.duplicate}  "
            f"replays={self.replayed}  conflitos={self.conflict}  "
            f"rejeitados={self.rejected}  falhas={self.failed}"
        )


_EMAIL_UNSAFE = re.compile(r"[^a-z0-9]+")


def slug(value: str) -> str:
    """Reduz um texto a caracteres seguros para a parte local de um e-mail.

    Nomes em portugues trazem acentos e espacos, que o validador de e-mail recusa.
    Sem isso o gerador produziria enderecos invalidos e a API responderia 422 — o lote
    inteiro seria rejeitado por um defeito do gerador, nao da plataforma.

    O nome original e preservado em ``full_name``: o slug existe apenas para o endereco.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _EMAIL_UNSAFE.sub(".", ascii_only.lower()).strip(".") or "anon"


def make_person(fake: Faker, source: str) -> dict[str, Any]:
    first, last = fake.first_name(), fake.last_name()
    return {
        "source": source,
        "full_name": f"{first} {last}",
        "email": f"{slug(first)}.{slug(last)}.{fake.random_int(1, 9999)}@example.com",
        "document": fake.cpf(),
        "phone": fake.phone_number(),
        "birth_date": fake.date_of_birth(minimum_age=18, maximum_age=90).isoformat(),
    }


def make_organization(fake: Faker, source: str) -> dict[str, Any]:
    name = fake.company()
    return {
        "source": source,
        "legal_name": name,
        "trade_name": name.split()[0],
        "email": f"contato.{slug(name)[:40]}.{fake.random_int(1, 99999)}@example.com",
        "document": fake.cnpj(),
        "phone": fake.phone_number(),
        "country": "BR",
    }


def _transpose(value: str) -> str:
    """Troca duas letras adjacentes, imitando erro de digitacao."""
    letters = [index for index, char in enumerate(value) if char.isalpha()]
    if len(letters) < 2:
        return value
    position = random.choice(letters[:-1])
    chars = list(value)
    chars[position], chars[position + 1] = chars[position + 1], chars[position]
    return "".join(chars)


def _drop_middle_name(value: str) -> str:
    parts = value.split()
    return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else value


def vary(record: dict[str, Any], fake: Faker) -> dict[str, Any]:
    """Produz outra observacao da MESMA entidade, com diferencas realistas.

    Variar apenas o telefone tornaria a avaliacao inutil: documento, e-mail e nome
    continuariam identicos e qualquer resolvedor acertaria. As variacoes abaixo imitam
    o que acontece entre fontes de verdade — abreviacao, erro de digitacao, troca de
    provedor, campo nao informado.

    O gabarito continua sabendo que e a mesma entidade, entao uma variacao agressiva
    demais aparece honestamente como falso negativo na medicao, em vez de ficar
    escondida.
    """
    variant = dict(record)
    nome = "full_name" if "full_name" in variant else "legal_name"

    escolha = random.choice(
        ["phone", "name_short", "name_typo", "email_domain", "drop_phone", "drop_document"]
    )
    if escolha == "phone":
        variant["phone"] = fake.phone_number()
    elif escolha == "name_short":
        variant[nome] = _drop_middle_name(str(variant.get(nome, "")))
    elif escolha == "name_typo":
        variant[nome] = _transpose(str(variant.get(nome, "")))
    elif escolha == "email_domain":
        local = str(variant.get("email", "")).partition("@")[0]
        if local:
            variant["email"] = f"{local}@outro-provedor.com"
    elif escolha == "drop_phone":
        variant.pop("phone", None)
    elif escolha == "drop_document":
        # O caso mais dificil: sem o identificador forte, o par so e encontrado se
        # nome, e-mail ou telefone bastarem.
        variant.pop("document", None)
    return variant


def build_batch(
    fake: Faker,
    *,
    count: int,
    record_type: str,
    source: str,
    duplicate_rate: float,
    variant_rate: float,
) -> list[tuple[dict[str, Any], int]]:
    """Monta o lote e devolve cada registro com a entidade verdadeira que o originou.

    O indice da entidade e o **gabarito**: duplicatas e variantes herdam o indice do
    original de onde sairam. Sem ele nao da para afirmar que a resolucao funciona —
    so que ela roda.
    """
    factory = make_person if record_type == "person" else make_organization
    batch: list[tuple[dict[str, Any], int]] = []
    originals: list[tuple[dict[str, Any], int]] = []

    for _ in range(count):
        roll = random.random()
        if originals and roll < duplicate_rate:
            record, entity = random.choice(originals)
            batch.append((dict(record), entity))
        elif originals and roll < duplicate_rate + variant_rate:
            record, entity = random.choice(originals)
            batch.append((vary(record, fake), entity))
        else:
            record = factory(fake, source)
            entity = len(originals)
            originals.append((record, entity))
            batch.append((record, entity))
    return batch


def post_batch(
    client: httpx.Client,
    url: str,
    record_type: str,
    batch: list[tuple[dict[str, Any], int]],
    *,
    verbose: bool,
    manifest: dict[str, int] | None = None,
) -> Stats:
    stats = Stats()
    endpoint = f"{url}{ENDPOINTS[record_type]}"

    for index, (record, true_entity) in enumerate(batch, start=1):
        try:
            response = client.post(
                endpoint,
                json=record,
                # Chave nova por requisicao: cada envio e uma operacao distinta.
                # Reutiliza-la aqui transformaria todo reenvio em replay e esconderia
                # a deduplicacao por conteudo, que e justamente o que queremos exercitar.
                headers={"Idempotency-Key": str(uuid.uuid4())},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            stats.failed += 1
            print(f"  [{index}] falha de rede: {exc}", file=sys.stderr)
            continue

        if manifest is not None and response.status_code in (200, 202):
            # Duplicatas devolvem o record_id da observacao original, entao o mapa
            # permanece coerente: o mesmo registro nunca recebe duas entidades.
            record_id = response.json().get("record_id")
            if record_id:
                manifest[record_id] = true_entity

        if response.status_code == 202:
            stats.accepted += 1
        elif response.status_code == 200:
            body = response.json()
            if response.headers.get("Idempotency-Replayed") == "true":
                stats.replayed += 1
            elif body.get("status") == "duplicate":
                stats.duplicate += 1
        elif response.status_code == 409:
            stats.conflict += 1
        elif response.status_code == 422:
            stats.rejected += 1
            if verbose:
                print(f"  [{index}] rejeitado: {response.text}", file=sys.stderr)
        else:
            stats.failed += 1
            print(f"  [{index}] HTTP {response.status_code}: {response.text}", file=sys.stderr)

        if verbose and index % 100 == 0:
            print(f"  ... {index}/{len(batch)}", file=sys.stderr)

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera registros sinteticos para o Nexus Architecture.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--count", type=int, default=100, help="quantidade de registros")
    parser.add_argument("--type", choices=sorted(ENDPOINTS), default="person")
    parser.add_argument("--source", default="synthetic-generator")
    parser.add_argument("--duplicate-rate", type=float, default=0.0, metavar="0.0-1.0")
    parser.add_argument("--variant-rate", type=float, default=0.0, metavar="0.0-1.0")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--seed", type=int, default=None, help="semente para reprodutibilidade")
    parser.add_argument("--post", action="store_true", help="envia os registros para a API")
    parser.add_argument(
        "--manifest",
        default=None,
        metavar="ARQUIVO",
        help="grava o gabarito (record_id -> entidade verdadeira) para avaliar a resolucao",
    )
    parser.add_argument("--dry-run", action="store_true", help="imprime os registros em JSON")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.count < 1 or args.count > MAX_RECORDS:
        print(
            f"erro: --count deve estar entre 1 e {MAX_RECORDS} (teto de seguranca, ver COSTS.md)",
            file=sys.stderr,
        )
        return 2
    total_rate = args.duplicate_rate + args.variant_rate
    if not 0.0 <= total_rate <= 1.0:
        print(
            "erro: a soma de --duplicate-rate e --variant-rate deve ficar entre 0 e 1",
            file=sys.stderr,
        )
        return 2
    if not args.post and not args.dry_run:
        print("erro: informe --post para enviar ou --dry-run para apenas imprimir", file=sys.stderr)
        return 2

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    fake = Faker("pt_BR")
    batch = build_batch(
        fake,
        count=args.count,
        record_type=args.type,
        source=args.source,
        duplicate_rate=args.duplicate_rate,
        variant_rate=args.variant_rate,
    )

    if args.dry_run:
        for record, _ in batch:
            print(json.dumps(record, ensure_ascii=False))
        return 0

    manifest: dict[str, int] | None = {} if args.manifest else None

    print(f"Enviando {len(batch)} registros sinteticos ({args.type}) para {args.url} ...")
    with httpx.Client() as client:
        stats = post_batch(
            client, args.url, args.type, batch, verbose=args.verbose, manifest=manifest
        )

    print(stats.render())

    if args.manifest and manifest is not None:
        destino = Path(args.manifest)
        destino.write_text(
            json.dumps(
                {"record_type": args.type, "truth": manifest},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        entidades = len(set(manifest.values()))
        print(f"gabarito: {len(manifest)} registros, {entidades} entidades -> {destino}")

    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
