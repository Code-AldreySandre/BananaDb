import sys
from core.gerenciador_disco import inicializa_pagina_zero, DB_FILE
from core.buffer_pool import CachePaginas
from execution.catalog import Catalogo
from execution.parser import ParserSQL
from execution.executor import Executor
from transaction.transaction import GerenciadorTransacoes
from transaction.wal import WALManager

def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DB_FILE

    # 1. Inicializa subsistemas
    inicializa_pagina_zero(db_file=db_path)
    cache = CachePaginas(capacidade=8, db_file=db_path)
    catalogo = Catalogo()
    parser = ParserSQL()
    wal_manager = WALManager()
    tx_manager = GerenciadorTransacoes(cache, wal_manager)
    executor = Executor(catalogo, cache, tx_manager)

    # Cria tabela padrão no Boot para aceitar conexões e testes
    ast_init = parser.parse("CREATE TABLE aluno (id INT, matricula INT);")
    executor.executar(ast_init)

    # 2. FASE DE RECUPERAÇÃO (M7): Processa o WAL para recuperar transações após crash
    wal_manager.recuperar(executor)

    # 3. Processamento Normal
    try:
        buffer_comando = ""
        for linha in sys.stdin:
            linha_limpa = linha.strip()
            if not linha_limpa:
                continue

            buffer_comando += " " + linha_limpa

            if ";" in linha_limpa:
                ast = parser.parse(buffer_comando)
                resultado = executor.executar(ast)
                print(resultado)
                buffer_comando = ""

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        cache.flush_todas()

if __name__ == "__main__":
    main()