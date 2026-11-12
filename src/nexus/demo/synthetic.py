"""Geracao de registros sinteticos **dentro do pacote**.

Ja existe um gerador em ``tools/generator.py``. Este modulo existe por duas restricoes
que aquele nao satisfaz:

1. ``scripts/build_lambda.sh`` empacota apenas ``src/nexus``. O que estiver em
   ``tools/`` nao chega a Lambda, e a rota de semeadura da demo roda la dentro.
2. ``faker`` e dependencia de desenvolvimento. Promove-la a dependencia de producao
   acrescentaria megabytes de dados de localizacao ao pacote para gerar, no pior caso,
   algumas centenas de registros.

**O que e compartilhado sao as variacoes** — abreviacao, erro de digitacao, troca de
provedor, campo omitido. Sao elas que tornam a resolucao de identidade visivel na tela,
e duplicar essa logica criaria duas definicoes do que e "a mesma entidade observada de
outro jeito". Elas divergiriam, e a divergencia apareceria como uma qualidade de
resolucao que muda conforme quem gerou os dados.

O que **nao** e compartilhado sao os nomes: aqui vem de listas pequenas embutidas, la
vem do Faker em pt_BR. Para a demo isso basta; para medir qualidade, nao — por isso a
avaliacao da Fase 5 continua usando ``tools/generator.py``.

Todos os dados produzidos aqui sao sinteticos. Nenhum corresponde a pessoa real.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Callable
from typing import Any

#: Nomes inventados para composicao. A combinacao e que gera variedade: 24 x 24 da 576
#: nomes distintos, suficiente para os poucos milhares de registros que uma demo cria.
PRIMEIROS = (
    "Ana",
    "Bruno",
    "Camila",
    "Diego",
    "Elisa",
    "Fabio",
    "Gabriela",
    "Henrique",
    "Isabela",
    "Joao",
    "Karina",
    "Lucas",
    "Mariana",
    "Nelson",
    "Olivia",
    "Paulo",
    "Queila",
    "Rafael",
    "Sofia",
    "Tiago",
    "Ursula",
    "Vitor",
    "Wagner",
    "Yara",
)
MEIOS = (
    "Alves",
    "Barbosa",
    "Cardoso",
    "Duarte",
    "Esteves",
    "Ferraz",
    "Gomes",
    "Henriques",
)
ULTIMOS = (
    "Almeida",
    "Barros",
    "Carvalho",
    "Dias",
    "Esteves",
    "Fonseca",
    "Guimaraes",
    "Horta",
    "Infante",
    "Jardim",
    "Klein",
    "Lima",
    "Macedo",
    "Nogueira",
    "Oliveira",
    "Pires",
    "Queiroz",
    "Ribeiro",
    "Santana",
    "Teixeira",
    "Uchoa",
    "Vasques",
    "Werneck",
    "Xavier",
)
RAMOS = (
    "Logistica",
    "Industria",
    "Comercio",
    "Servicos",
    "Tecnologia",
    "Engenharia",
    "Distribuidora",
    "Consultoria",
)
SUFIXOS = ("Ltda", "S.A.", "ME", "EIRELI")

_EMAIL_UNSAFE = re.compile(r"[^a-z0-9]+")


def slug(value: str) -> str:
    """Reduz um texto a caracteres seguros para a parte local de um e-mail.

    Nomes em portugues trazem acentos e espacos, que o validador de e-mail recusa. Sem
    isso o gerador produziria enderecos invalidos e a API responderia 422 — o lote
    inteiro seria rejeitado por defeito do gerador, nao da plataforma.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _EMAIL_UNSAFE.sub(".", ascii_only.lower()).strip(".") or "anon"


def transpose(value: str, rng: random.Random) -> str:
    """Troca duas letras adjacentes, imitando erro de digitacao.

    ``rng`` e explicito: usar o ``random`` global aqui tornaria o lote irreprodutivel
    mesmo com semente, porque qualquer outro codigo do processo que sorteasse um numero
    deslocaria a sequencia.
    """
    letters = [index for index, char in enumerate(value) if char.isalpha()]
    if len(letters) < 2:
        return value
    position = rng.choice(letters[:-1])
    chars = list(value)
    chars[position], chars[position + 1] = chars[position + 1], chars[position]
    return "".join(chars)


def drop_middle_name(value: str) -> str:
    parts = value.split()
    return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else value


def vary(
    record: dict[str, Any],
    *,
    rng: random.Random,
    telefone: Callable[[], str],
) -> dict[str, Any]:
    """Produz outra observacao da MESMA entidade, com diferencas realistas.

    Variar apenas o telefone tornaria a demonstracao inutil: documento, e-mail e nome
    continuariam identicos e qualquer resolvedor acertaria. As variacoes abaixo imitam
    o que acontece entre fontes de verdade.

    ``telefone`` e injetado porque e a unica variacao que precisa de um valor novo, e
    ``tools/generator.py`` quer o do Faker enquanto a demo quer o daqui. Era o unico
    ponto em que esta funcao dependia do Faker.
    """
    variant = dict(record)
    nome = "full_name" if "full_name" in variant else "legal_name"

    escolha = rng.choice(
        ["phone", "name_short", "name_typo", "email_domain", "drop_phone", "drop_document"]
    )
    if escolha == "phone":
        variant["phone"] = telefone()
    elif escolha == "name_short":
        variant[nome] = drop_middle_name(str(variant.get(nome, "")))
    elif escolha == "name_typo":
        variant[nome] = transpose(str(variant.get(nome, "")), rng)
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
    factory: Callable[[], dict[str, Any]],
    *,
    count: int,
    duplicate_rate: float,
    variant_rate: float,
    rng: random.Random,
    telefone: Callable[[], str],
) -> list[tuple[dict[str, Any], int]]:
    """Monta o lote e devolve cada registro com a entidade verdadeira que o originou.

    O indice da entidade e o **gabarito**: duplicatas e variantes herdam o indice do
    original de onde sairam. Sem ele nao da para afirmar que a resolucao funciona — so
    que ela roda.
    """
    batch: list[tuple[dict[str, Any], int]] = []
    originals: list[tuple[dict[str, Any], int]] = []

    for _ in range(count):
        roll = rng.random()
        if originals and roll < duplicate_rate:
            record, entity = rng.choice(originals)
            batch.append((dict(record), entity))
        elif originals and roll < duplicate_rate + variant_rate:
            record, entity = rng.choice(originals)
            batch.append((vary(record, rng=rng, telefone=telefone), entity))
        else:
            record = factory()
            entity = len(originals)
            originals.append((record, entity))
            batch.append((record, entity))
    return batch


# ------------------------------------------------------------------ fabricas locais


def telefone_sintetico(rng: random.Random) -> str:
    return f"({rng.randint(11, 99)}) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


def _digitos(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def _cpf(rng: random.Random) -> str:
    """Documento com a FORMA de um CPF, sem digito verificador valido.

    Deliberado: um documento sintetico que passa na validacao oficial e indistinguivel
    de um documento real, e pode colidir com o de alguem. A plataforma trata o
    documento como texto normalizado, entao a forma basta. Ja registrado como limitacao
    conhecida desde a Fase 1.
    """
    return f"{_digitos(rng, 3)}.{_digitos(rng, 3)}.{_digitos(rng, 3)}-{_digitos(rng, 2)}"


def _cnpj(rng: random.Random) -> str:
    """Idem, com a forma de um CNPJ."""
    return (
        f"{_digitos(rng, 2)}.{_digitos(rng, 3)}.{_digitos(rng, 3)}"
        f"/{_digitos(rng, 4)}-{_digitos(rng, 2)}"
    )


def pessoa_sintetica(rng: random.Random, source: str) -> dict[str, Any]:
    primeiro = rng.choice(PRIMEIROS)
    ultimo = rng.choice(ULTIMOS)
    # Nome do meio em parte dos registros: e o que torna a variacao "abreviacao de
    # nome" possivel, e foi exatamente esse caso que a Fase 5 pegou como falso negativo.
    meio = f"{rng.choice(MEIOS)} " if rng.random() < 0.5 else ""
    nome = f"{primeiro} {meio}{ultimo}"
    return {
        "source": source,
        "full_name": nome,
        "email": f"{slug(primeiro)}.{slug(ultimo)}.{rng.randint(1, 9999)}@example.com",
        "document": _cpf(rng),
        "phone": telefone_sintetico(rng),
    }


def organizacao_sintetica(rng: random.Random, source: str) -> dict[str, Any]:
    marca = rng.choice(ULTIMOS)
    nome = f"{marca} {rng.choice(RAMOS)} {rng.choice(SUFIXOS)}"
    return {
        "source": source,
        "legal_name": nome,
        "trade_name": marca,
        "email": f"contato.{slug(marca)}.{rng.randint(1, 9999)}@example.com",
        "document": _cnpj(rng),
        "phone": telefone_sintetico(rng),
        "country": "BR",
    }
