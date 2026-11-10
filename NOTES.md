# BananaDb — Notas de Engenharia e Decisões de Projeto (`NOTES.md`)

Documento técnico de acompanhamento da disciplina de Banco de Dados 2, contendo as anotações teóricas, respostas dos laboratórios e decisões de arquitetura referentes à implementação dos Módulos 1 a 7.

---

## M1: Gerenciamento de Disco e Serialização Física

### Decisão de Projeto: Escrita Atômica & Sincronização
A decisão mais difícil do módulo foi garantir a escrita atômica da função `escreve_pagina`. No início, as operações de alto nível como `f.write()` atribuem a gravação ao *page cache* da memória RAM do sistema operacional. No cenário de falha (por exemplo, no teste de `kill -9` no meio de um commit), os *dirty buffers* seriam descartados, transgredindo a propriedade de durabilidade do modelo ACID. Para resolver isso, implementamos o esvaziamento do buffer da aplicação com o `f.flush()` e uma *syscall* direta de sincronização, o `os.fsync`. Desse modo, forçamos o hardware a gravar o bloco físico antes de liberar a execução.

### Endereçamento Físico e Cálculo de Offset
Seguindo o layout de páginas estáticas de 4096 bytes e um cabeçalho de 16 bytes, o registro de teste de 8 bytes destinado ao slot 0 da página 2 foi persistido no offset físico exato correspondente ao byte **8208** do arquivo `dados.db`.
$$\text{Offset} = (\text{Número da Página} \times \text{PAGE\_SIZE}) + \text{HEADER\_SIZE} = (2 \times 4096) + 16 = 8208 \text{ bytes}$$

### Formato de Serialização e Little-Endian
A serialização é realizada via biblioteca nativa `struct` com a formatação `<ii`. 
* O caractere `<` força explicitamente o formato *Little-Endian* (byte menos significativo no menor endereço físico de memória).
* Cada `i` representa um inteiro de 4 bytes de tamanho fixo, garantindo que o `RECORD_SIZE` totalize milimetricamente 8 bytes.

### Análise de Páginas e Varredura Sequencial (Laboratório 17/09/2026)
* **Quantas páginas tem o arquivo inicial?**  
  O arquivo possui **2 páginas** (Página 0 reservada para o número mágico `MINIDB26` e tamanho de página; Página 1 contendo o primeiro registro alocado).
* **Quantas leituras a varredura faz?**  
  A varredura (*Full Table Scan*) fará **1 leitura**. Como a Página 0 é exclusiva para controle e metadados do SGBD, o executor inicia a leitura dos dados a partir da Página 1 em diante até o final do arquivo.

---

## M2: Cache de Páginas 

### Política de Substituição LRU (*Least Recently Used*)
* Implementada utilizando a classe `collections.OrderedDict` para controlar os quadros (*frames*) em memória RAM com complexidade $O(1)$.
* **Controle de Desalojamento:** Quando a capacidade do cache atinge seu limite (ex: 4 ou 8 páginas), a página mais antiga e não fixada (`pin_count == 0`) é removida. Se a página selecionada for suja (`is_dirty == True`), seu conteúdo é obrigatoriamente persistido no disco via `escreve_pagina` antes do desalojamento.

### Mecanismo de Fixação 
* **`pin_count > 0`:** Impede que páginas que estejam sendo lidas ou alteradas por operações ativas sejam desalojadas pelo algoritmo LRU, prevenindo inconsistência de memória concorrente.

---

## M3: Indexação por Árvore B+

### Layout Físico dos Nós
* **Cabeçalho da Página de Índice (`FORMATO_HEADER = "<iiii"`):** 16 bytes que armazenam:
  1. `eh_folha` (1 se for nó folha, 0 se for nó interno)
  2. `num_chaves` (quantidade atual de chaves no nó)
  3. `prox_folha` (número da próxima página folha para encadeamento de varredura sequencial)
  4. `reservado` (campo para alinhamento de memória)

### Mecanismo de Divisão 
* **Divisão de Folha:** Quando o nó atinge `MAX_CHAVES`, uma nova página é alocada no disco. As chaves e dados são divididos em partes iguais, o ponteiro `prox_folha` da folha antiga passa a apontar para a nova página, e a menor chave do nó direito é promovida para o pai.
* **Divisão Interna:** Quando um nó interno enche, a chave mediana sobe para o nó pai e os ponteiros de filhos são redistribuídos entre o nó antigo e o novo nó interno. Se a raiz estiver cheia, uma nova página raiz é alocada, aumentando a altura da árvore.

### Persistência Inicial da Raiz
* **Problema Encontrado:** Ao instanciar uma nova `ArvoreBPlus`, a página raiz era alocada no Buffer Pool como *dirty*, porém seu cabeçalho não era imediatamente descarregado para o arquivo `.db`. Durante um `ROLLBACK`, o gerenciador recarregava os dados brutos de zeros do disco, zerando `eh_folha` para `0` e fazendo a busca ler a Página 0 (metadados), resultando em estouro de buffer no `struct`.
* **Solução:** Na criação da raiz, a chamada de marcação `liberar_pagina(pagina_raiz, modificada=True)` deve ser feita obrigatoriamente **antes** do `flush_pagina(pagina_raiz)` para garantir o sincronismo físico no disco.

---

## M4: Parser SQL e Catálogo de Metadados

### Compilador SQL Lexical (AST)
* Sem utilizar bibliotecas externas, o `ParserSQL` compila comandos SQL textuais em classes de dados (*dataclasses*) estruturadas: `CreateTable`, `Insert`, `Select`, `Where`, `Begin`, `Commit` e `Rollback`.
* Suporte a extração de predicados simples em cláusulas `WHERE` (`=`, `>`, `<`, `>=`, `<=`, `!=`).

### Catálogo de Dados
* Armazena em memória as definições lógicas das tabelas (`ColunaDef`) e converte dinamicamente a lista de tipos (ex: `['INT', 'INT']`) para o objeto `Schema` de serialização em bytes.

---

## 5. M5: Executor de Consultas (Engine)

### Planos de Acesso
1. **Varredura por Índice (*Index Scan*):** Ativada em consultas `SELECT` contendo a cláusula `WHERE` de igualdade (`=`) sobre a chave primária. Navega pela Árvore B+ da raiz até a folha com complexidade $O(\log N)$.
2. **Varredura Sequencial (*Sequential Scan*):** Ativada quando não há filtro por chave primária. Percorre a lista encadeada de folhas da Árvore B+ utilizando o ponteiro `prox_folha`, aplicando a filtragem em memória.

### Formatação do Contrato de I/O
* Formatação de saída com separador por barra vertical (`|`), finalizando com o número de linhas retornadas:
  ```text
  1|20260001
  (1 linha)