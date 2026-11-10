# 🍌 BananaDb (MiniDB)

Um Sistema Gerenciador de Banco de Dados (SGBD) relacional construído do zero (bottom-up) para a disciplina de Banco de Dados 2. O objetivo deste projeto é entender a engenharia interna de um banco de dados, implementando desde o gerenciamento bruto de bytes no disco até o controle de transações e recuperação de falhas.

## Arquitetura

O desenvolvimento se deu por módulos com interdependência dos demais no que se segue:

- **M1: Página e arquivo de dados:** Gerenciamento de disco, serialização Little-Endian, páginas de 4096 bytes. 
- **M2: Cache de páginas:** (Buffer pool para manter as páginas mais acessadas em memória).
- **M3: Árvore B+:** (Estrutura para busca e inserção eficientes sem varrer a tabela inteira).
- **M4: Parser e Catálogo:** (Transformação do texto SQL em uma árvore de execução compreensível pelo programa).
- **M5: Executor:** (Operadores que produzem linhas através de varredura sequencial e por índice).
- **M6: Transações:** (Suporte a BEGIN, COMMIT e ROLLBACK).
- **M7: Recuperação:** (Log de escrita antecipada / Write-Ahead Log para sobrevivência a falhas/kill -9).

## Estrutura de Diretórios

Para manter a coerência ao longo do crescimento do SGBD, o projeto é modularizado da seguinte forma:

```text
BananaDb/
├── core/                   # Camada de Armazenamento Físico e Cache
│   ├── __init__.py
│   ├── gerenciador_disco.py  # Manipulação direta de bytes, offset e struct
│   └── buffer_pool.py        # Buffer Pool LRU, gerenciamento de frames e flush
├── index/                  # Camada de Indexação
│   ├── __init__.py
│   └── bplus_tree.py         # Árvore B+ baseada em páginas (nós internos e folhas)
├── execution/              # Camada de Processamento de SQL
│   ├── __init__.py
│   ├── parser.py             # Parser SQL (AST com dataclasses)
│   ├── catalog.py            # Dicionário de dados/metadados da tabela
│   └── executor.py           # Engine de execução (Index Scan / Full Scan)
├── transaction/            # Camada de Concorrência e Resiliência
│   ├── __init__.py
│   ├── transaction.py        # Gerenciador de ciclo de vida transacional
│   └── wal.py                # Write-Ahead Log síncrono e motor REDO
├── tests/                  # Suíte de Testes Automatizados
│   ├── __init__.py
│   └── test_bananadb.py      # Testes de integração unitários (M1 ao M7)
├── main.py                 # Ponto de entrada CLI (integração via stdin/stdout)
├── NOTES.md                # Respostas teóricas e anotações do laboratório
├── minidb.log              # Log centralizado de execução/debug
├── minidb.wal              # Log de transações físicas no disco
└── dados.db                # Arquivo binário de dados mantido pelo SGBD