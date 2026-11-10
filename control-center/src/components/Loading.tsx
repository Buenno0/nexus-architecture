/**
 * Estado de carregamento.
 *
 * Existe porque "ainda nao sei" e "nao existe" sao afirmacoes diferentes, e a segunda
 * nao pode ser exibida no lugar da primeira. Uma lista vazia enquanto a resposta nao
 * chegou diz ao operador que nao ha nada — e ele pode agir com base nisso.
 */

export function Loading({ texto = "carregando…" }: { texto?: string | undefined }) {
  return (
    <p className="vazio" aria-busy="true">
      {texto}
    </p>
  );
}
