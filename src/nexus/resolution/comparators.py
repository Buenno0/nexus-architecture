"""Comparadores de campo.

Funcoes puras que devolvem similaridade entre 0,0 e 1,0. Nenhuma acessa banco,
fila ou rede — o que as torna exaustivamente testaveis.

## Por que similaridade bruta nao serve

Jaro-Winkler entre duas strings **sem relacao nenhuma** costuma ficar entre 0,35 e 0,50,
nao perto de zero. Somada com peso, essa similaridade de fundo inflaria o score de pares
que nao tem nada a ver um com o outro.

Por isso toda similaridade aproximada passa por um piso: abaixo dele o resultado e
exatamente ``0.0``; acima, o valor e reescalado para a faixa cheia. Similaridade fraca
deixa de contribuir, em vez de contribuir pouco.
"""

from __future__ import annotations

from rapidfuzz.distance import JaroWinkler, Levenshtein
from rapidfuzz.fuzz import token_set_ratio, token_sort_ratio

from nexus.resolution.text import alnum, digits, fold, tokens

#: Piso para nomes. Abaixo disso a semelhanca e ruido estatistico.
NAME_FLOOR = 0.70
#: Piso para documentos. Um digito trocado em 11 da ~0,91; dois documentos distintos
#: raramente passam disso.
DOCUMENT_FLOOR = 0.85
#: Piso para a parte local de e-mails.
EMAIL_LOCAL_FLOOR = 0.75
#: Quantos digitos finais de telefone sao comparados (ignora DDI e formatacao).
PHONE_SUFFIX_DIGITS = 8
#: Teto para similaridade obtida por subconjunto de tokens. Conter todos os tokens do
#: outro nome e evidencia forte, mas nao identidade: fica abaixo de 1,0 de proposito.
TOKEN_SUBSET_CEILING = 0.95
#: Tokens em comum exigidos para aplicar o criterio de subconjunto. Com apenas um,
#: "Maria" casaria igualmente com "Maria Souza" e "Maria Pereira".
MIN_SHARED_TOKENS = 2


def rescale(similarity: float, floor: float) -> float:
    """Zera similaridade abaixo do piso e reescala o restante para 0-1."""
    if similarity < floor:
        return 0.0
    if floor >= 1.0:
        return 1.0
    return (similarity - floor) / (1.0 - floor)


def exact(left: str | None, right: str | None) -> float:
    """Igualdade apos normalizacao. Campos ausentes nunca correspondem."""
    a, b = fold(left), fold(right)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else 0.0


def name_similarity(left: str | None, right: str | None) -> float:
    """Similaridade de nomes, tolerante a erro de digitacao e a ordem dos tokens.

    Usa o maior entre Jaro-Winkler (bom para trocas e prefixos) e ``token_sort_ratio``
    (bom para "Maria Souza" contra "Souza Maria"). Nomes chegam em ordens diferentes
    conforme a fonte, e tratar isso como divergencia produziria falso negativo.
    """
    a, b = fold(left), fold(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    candidates = [JaroWinkler.similarity(a, b), token_sort_ratio(a, b) / 100.0]

    # Subconjunto de tokens: "Enzo Cunha" dentro de "Enzo Gabriel da Cunha". Nome do
    # meio omitido e das variacoes mais comuns entre fontes, e as duas medidas acima
    # a pontuam baixo — o nome mais curto parece simplesmente diferente.
    #
    # Exigir dois tokens em comum e o que separa evidencia de coincidencia: com um so,
    # "Maria" casaria igualmente com "Maria Souza" e com "Maria Pereira".
    if len(set(tokens(a)) & set(tokens(b))) >= MIN_SHARED_TOKENS:
        candidates.append(TOKEN_SUBSET_CEILING * (token_set_ratio(a, b) / 100.0))

    return rescale(max(candidates), NAME_FLOOR)


def document_similarity(left: str | None, right: str | None) -> float:
    """Similaridade de documentos, tolerante a um digito trocado.

    Documento e identificador forte: a tolerancia existe para erro de digitacao na
    origem, nao para aproximar documentos diferentes. Dai o piso alto.
    """
    a, b = alnum(left), alnum(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return rescale(Levenshtein.normalized_similarity(a, b), DOCUMENT_FLOOR)


def email_similarity(left: str | None, right: str | None) -> float:
    """Similaridade de e-mails, separando parte local e dominio.

    Compartilhar dominio e evidencia fraca — todo mundo em ``example.com`` compartilha.
    A parte local carrega quase toda a informacao, entao pesa 0,75 contra 0,25 do
    dominio.

    Consequencias: mesma parte local em dominios diferentes da 0,75 (a mesma pessoa com
    dois provedores e plausivel); partes locais sem relacao no mesmo dominio da 0,25,
    que sozinho nao alcanca nenhum limiar.
    """
    a, b = fold(left), fold(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    local_a, _, domain_a = a.partition("@")
    local_b, _, domain_b = b.partition("@")

    if local_a == local_b:
        local_score = 1.0
    else:
        local_score = rescale(JaroWinkler.similarity(local_a, local_b), EMAIL_LOCAL_FLOOR)

    domain_score = 1.0 if domain_a and domain_a == domain_b else 0.0
    return min(1.0, 0.75 * local_score + 0.25 * domain_score)


def phone_similarity(left: str | None, right: str | None) -> float:
    """Compara os ultimos digitos, ignorando DDI e formatacao.

    Decisao binaria de proposito: telefones parecidos nao sao evidencia de nada —
    um digito de diferenca e outra linha, nao erro de digitacao provavel.
    """
    a, b = digits(left), digits(right)
    if len(a) < PHONE_SUFFIX_DIGITS or len(b) < PHONE_SUFFIX_DIGITS:
        return 1.0 if a and a == b else 0.0
    return 1.0 if a[-PHONE_SUFFIX_DIGITS:] == b[-PHONE_SUFFIX_DIGITS:] else 0.0


#: Comparador aplicado a cada campo conhecido.
COMPARATORS = {
    "document": document_similarity,
    "email": email_similarity,
    "full_name": name_similarity,
    "legal_name": name_similarity,
    "trade_name": name_similarity,
    "phone": phone_similarity,
    "country": exact,
}
