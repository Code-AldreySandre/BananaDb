# 🍌 BananaDb (MiniDB)
 
SGBD relacional minimalista, escrito em **Python puro** e construído do zero (*bottom-up*) para a disciplina de **Banco de Dados 2**. O objetivo é entender a engenharia interna de um banco de dados: do gerenciamento de bytes no disco até índices, execução de consultas, transações e recuperação de falhas.
 
> Projeto educacional. Não é indicado para uso em produção (veja [Limitações](#-limitações-conhecidas)).
 
---
 
## Funcionalidades
 
- **Armazenamento paginado:** arquivo único `.db` com páginas de 4096 bytes, serialização *Little-Endian* via `struct` e escrita durável com `flush` + `fsync`.
- **Buffer Pool com LRU:** cache de páginas com `pin_count`, *dirty flag* e política de desalojamento *Least Recently Used*.
- **Índice Árvore B+:** baseada em páginas, com divisão de folhas e nós internos, crescimento da raiz e folhas encadeadas para varredura sequencial.
- **Parser SQL próprio:** sem bibliotecas externas, gera uma AST com `dataclasses`.
- **Catálogo persistido em disco:** metadados das tabelas e a raiz de cada B+ sobrevivem a reinicializações.
- **Executor com dois planos de acesso:** *Index Scan* e *Sequential Scan*.
- **Transações:** `BEGIN`, `COMMIT` e `ROLLBACK`, com *autocommit* para comandos fora de um bloco.
- **Recuperação de falhas (WAL):** *Write-Ahead Log* com UNDO + REDO, testado com `kill -9`.
---
 
## Arquitetura
 
O projeto foi construído em módulos, cada um dependendo dos anteriores:
 
| Módulo | Tema | Arquivo(s) |
|:------:|------|-----------|
| **M1** | Página e arquivo de dados | `core/gerenciador_disco.py` |
| **M2** | Cache de páginas (Buffer Pool) | `core/buffer_pool.py` |
| **M3** | Árvore B+ | `index/bplus_tree.py` |
| **M4** | Parser SQL e Catálogo | `execution/parser.py`, `execution/catalog.py` |
| **M5** | Executor de consultas | `execution/executor.py` |
| **M6** | Transações | `transaction/transaction.py` |
| **M7** | Recuperação (WAL) | `transaction/wal.py` |
 
```text
SQL (stdin) ─► Parser ─► AST ─► Executor ─► Árvore B+ ─► Buffer Pool ─► Disco (.db)
                                   │                          ▲
                                   └──► Transações ──► WAL (.db.wal)
```
 
### Estrutura de diretórios
 
```text
BananaDb/
├── core/                      # Armazenamento físico e cache
│   ├── gerenciador_disco.py   # Páginas, offsets, Schema, serialização, fsync
│   └── buffer_pool.py         # Pagina e CachePaginas (LRU, pin, flush)
├── index/                     # Indexação
│   └── bplus_tree.py          # ArvoreBPlus (nós internos e folhas)
├── execution/                 # Processamento de SQL
│   ├── parser.py              # ParserSQL + dataclasses da AST
│   ├── catalog.py             # Catalogo (metadados persistidos na página 1)
│   └── executor.py            # Executor (Index Scan / Sequential Scan)
├── transaction/               # Transações e resiliência
│   ├── transaction.py         # GerenciadorTransacoes (begin/commit/rollback)
│   └── wal.py                 # WALManager (log, UNDO e REDO)
├── tests/
│   ├── test_bananadb.py       # Testes de integração (M1 a M7)
│   └── test_recuperacao.py    # Testes de falha com SIGKILL
├── main.py                    # CLI: lê SQL via stdin e imprime resultados
├── NOTES.md                   # Decisões de projeto e respostas teóricas
└── pyproject.toml
```
 
---
 
## Como executar
 
### Requisitos
 
- **Python 3.12+**
- O núcleo do SGBD usa apenas a biblioteca padrão. Não há dependências externas para rodar o banco.
### Executando
 
O `main.py` lê comandos SQL da entrada padrão e imprime o resultado de cada um. Cada comando termina com `;` e pode ocupar várias linhas. O primeiro argumento (opcional) é o caminho do arquivo do banco; se omitido, usa `dados.db`.
 
```bash
# Modo interativo
python main.py meu_banco.db
 
# Ou enviando um script
python main.py meu_banco.db < comandos.sql
```
 
O WAL do banco fica ao lado dele, em `<arquivo_do_banco>.wal`, e o log de depuração em `minidb.log`.
 
---
 
## Exemplo de uso
 
```sql
CREATE TABLE aluno (id INT, matricula INT);
INSERT INTO aluno VALUES (1, 20260001);
INSERT INTO aluno VALUES (2, 20260002);
 
SELECT * FROM aluno WHERE id = 1;
SELECT * FROM aluno;
 
BEGIN;
INSERT INTO aluno VALUES (3, 20260003);
ROLLBACK;
 
SELECT * FROM aluno WHERE id >= 2;
```
 
Saída:
 
```text
OK
OK 1
OK 1
1|20260001
(1 linha)
1|20260001
2|20260002
(2 linhas)
OK
OK 1
OK
2|20260002
(1 linha)
```
 
### SQL suportado
 
| Comando | Observações |
|---------|-------------|
| `CREATE TABLE t (col INT, col INT)` | Apenas colunas do tipo `INT` |
| `INSERT INTO t VALUES (v1, v2)` | A **primeira coluna é a chave primária** (única) |
| `SELECT ... FROM t [WHERE col op valor]` | Operadores: `=`, `!=`, `>`, `<`, `>=`, `<=` |
| `BEGIN` / `COMMIT` / `ROLLBACK` | `BEGIN TRANSACTION` também é aceito |
 
Os comandos não diferenciam maiúsculas de minúsculas.
 
---
 
## Como funciona por dentro
 
### Layout de página
- Páginas de **4096 bytes** com cabeçalho de **16 bytes**.
- **Página 0:** metadados (`MINIDB26` + tamanho da página + ponteiro do catálogo).
- **Página 1:** catálogo (JSON precedido por 4 bytes com o tamanho do payload).
- **Página 2 em diante:** nós das árvores B+.
- Registros de **8 bytes** (`<ii`, dois inteiros de 32 bits).

### Árvore B+
- Capacidade de **510 chaves por folha** e **509 por nó interno** (nós internos precisam de *k + 1* ponteiros).
- Chaves duplicadas são rejeitadas antes de qualquer divisão.
- Quando a raiz sofre *split*, o catálogo é atualizado via callback `on_root_change`.
### Planos de execução
| Plano | Quando é usado | Custo |
|-------|----------------|-------|
| **Index Scan** | `WHERE` com `=` sobre a primeira coluna (chave primária) | O(log N) |
| **Sequential Scan** | Qualquer outro caso | Percorre as folhas encadeadas |
 
### Transações e recuperação
- Antes de qualquer página suja ser gravada no disco, a imagem anterior é registrada no WAL (`UNDO_PAGE`), o que permite desfazer transações não confirmadas (política *STEAL*).
- No `COMMIT`, o registro é gravado no WAL com `fsync` e só depois as páginas são descarregadas.
- Na inicialização, `recuperar()` executa:
  1. **UNDO:** restaura as páginas de transações sem `COMMIT` nem `ABORT`.
  2. **REDO:** reaplica de forma idempotente os `INSERT` de transações confirmadas.
  3. **Checkpoint:** descarrega o cache e trunca o WAL.
- Linhas do WAL sem `\n` no final (cortadas por um `kill -9`) são descartadas.
Mais detalhes e justificativas de cada decisão estão em [`NOTES.md`](NOTES.md).
 
---
 
## Limitações conhecidas
 
- Apenas o tipo `INT` (32 bits com sinal), e o esquema precisa somar exatamente **8 bytes** (duas colunas `INT`).
- A primeira coluna é sempre a chave primária.
- Sem `UPDATE`, `DELETE`, `JOIN`, `ORDER BY`, índices secundários ou múltiplas tabelas com relacionamento.
- O `SELECT` retorna sempre todas as colunas; a lista de colunas é interpretada, mas não filtra a saída.
- O catálogo cabe em uma única página (4 KB).
- Páginas órfãs deixadas por transações abortadas após um *split* não são reaproveitadas (não há *freelist*).
- Um único processo e uma única transação por vez (sem controle de concorrência).
 
 
## Autores

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/Filipealfaia-dev" title="Perfil do Filipe Alfaia no GitHub">
        <img src="https://avatars.githubusercontent.com/u/225216570?v=4" width="100px;" alt="Foto do Filipe Alfaia no GitHub"/><br />
        <sub>
          <b>Filipe Alfaia</b>
        </sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Code-AldreySandre" title="Perfil do Aldrey Sandre no GitHub">
        <img src="https://avatars.githubusercontent.com/u/165036139?s=400&u=e8da42903e0745cb7e2f751c1fb42aae6b7a67b8&v=4" width="100px;" alt="Aldrey Sandre, autor do projeto BananaDb, perfil profissional no GitHub"/><br />
        <sub>
          <b>Aldrey Sandre</b>
        </sub>
      </a>
    </td>
  </tr>
</table>


