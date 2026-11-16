# Validação integrada — 15 de novembro de 2026

A validação usou dados sintéticos criados pelos fluxos da própria aplicação, DynamoDB Local em memória e fila SQLite temporária. As telas foram percorridas no navegador com a API disponível; a jornada de um registro foi conferida da entrada à resolução. Também foram observados os estados de indisponibilidade e a distinção entre métricas do processo e dados persistidos. A navegação foi verificada em largura de 390 px e as tabelas largas passaram a ter rolagem própria.

Este registro descreve a validação inicial. A implantação e a verificação posterior com a credencial de visitante estão registradas na [ADR-011](../adr/ADR-011-demonstracao-somente-leitura.md).

## Verificações

- Backend: 481 testes unitários e 105 testes de integração passaram; os últimos usaram DynamoDB Local isolado.
- Interface: 142 testes passaram, assim como lint e build. O build informa um bundle superior a 500 kB.
- Infraestrutura: formatação e validação do Terraform passaram.
- Fila SQS: os testes usam Moto, sem acessar a AWS. A mensagem encaminhada à fila de falhas mantém os identificadores originais; falha no envio não é reportada como sucesso. Envio e remoção são operações distintas, portanto duplicações ainda são possíveis.
- Demonstração: em modo de demonstração local, operações de escrita e ingestão livre retornaram 404, e uma solicitação acima do limite de geração retornou 429. Na demonstração pública foram feitas apenas verificações sem autenticação: saúde disponível, fila protegida e ingestão livre indisponível. Isso não verifica o comportamento de operações autenticadas com a credencial de visitante.

## Correções durante a validação

Foram corrigidos o encaminhamento SQS para a fila de falhas, a identificação do processo de origem para cálculo das taxas, a formatação decimal das latências, a descrição dos emissores na jornada, a rolagem de tabelas no celular e um link para o diretório de infraestrutura. Essas alterações continuam locais; a implantação posterior foi restrita à segurança da demonstração.
