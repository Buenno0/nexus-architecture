"""Pontos de entrada do AWS Lambda.

Tres funcoes separadas, nao uma com roteamento interno. A razao e IAM: cada funcao
recebe exatamente as permissoes de que precisa. Uma funcao unica precisaria da uniao
de todas, e o privilegio minimo deixaria de existir.

Cada modulo configura logging **no nivel do modulo**, nao dentro do handler: isso roda
uma vez por container e e reaproveitado entre invocacoes, em vez de repetir a cada
requisicao.
"""
