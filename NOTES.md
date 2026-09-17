
## Decisão de Projeto:
A decisão mais difícil do módulo foi garantir a escrita atômica da função `escreve_pagina`. No início, as operações de alto nível como `f.write()` atribuem a gravação ao page cache da memória RAM do sistema operacional. No cenário de falha (por exemplo, no teste de `kill -9` no meio de um commit), os dirty buffers seriam descartados, transgredindo a propriedade de durabilidade do modelo ACID. Para resolver isso, implementamos o esvaziamento do buffer da aplicação com o `f.flush()` e uma syscall direta de sincronização, o `os.fsync`. Desse modo, forçamos o hardware a gravar o bloco físico antes de liberar a execução.

## Endereçamento Físico
Seguindo o layout de páginas estáticas de 4096 bytes e um cabeçalho de 16 bytes, o registro de teste de 8 bytes destinado ao slot 0 da página 2 foi persistido no offset físico exato correspondente ao byte **8208** do arquivo `dados.db`.

# 17/09/2026

O arquivo possui 2 páginas. Sendo a página 0 com os metadados/cabeçalho mágico e a página 1 com o registro de dados alocado.

### Quantas leituras a varredura faz?
A varredura  fará 1 leitura. Como a página 0 é exclusiva para controle e metadados do SGBD, o executor começa a ler os dados a partir da página 1 até o final do arquivo.
