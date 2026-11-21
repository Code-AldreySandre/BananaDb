import os
import logging
from core.gerenciador_disco import escreve_pagina

logger = logging.getLogger("minidb")
WAL_FILE = "minidb.wal"


class WALManager:
    def __init__(self, wal_file: str = WAL_FILE):
        self.wal_file = wal_file

    def _escrever(self, linha: str):
        modo = 'a' if os.path.exists(self.wal_file) else 'w'
        with open(self.wal_file, modo) as f:
            f.write(linha)
            f.flush()
            os.fsync(f.fileno())

    def log_begin(self, tx_id: int):
        self._escrever(f"BEGIN|{tx_id}\n")
        logger.debug(f"WAL: Logged BEGIN {tx_id}")

    def log_undo_page(self, tx_id: int, num_pag: int, page_hex: str):
        self._escrever(f"UNDO_PAGE|{tx_id}|{num_pag}|{page_hex}\n")
        logger.debug(f"WAL: Logged UNDO_PAGE tx={tx_id} pag={num_pag}")

    def log_insert(self, tx_id: int, tabela: str, chave: int, dados_hex: str):
        self._escrever(f"INSERT|{tx_id}|{tabela}|{chave}|{dados_hex}\n")
        logger.debug(f"WAL: Logged INSERT tx={tx_id} tabela={tabela} chave={chave}")

    def log_commit(self, tx_id: int):
        self._escrever(f"COMMIT|{tx_id}\n")
        logger.info(f"WAL: Logged COMMIT {tx_id}")

    def log_rollback(self, tx_id: int):
        self._escrever(f"ABORT|{tx_id}\n")
        logger.info(f"WAL: Logged ABORT {tx_id}")

    def obter_ultimo_tx_id(self) -> int:
        if not os.path.exists(self.wal_file):
            return 0

        maior_id = 0
        with open(self.wal_file, 'r') as f:
            for linha in f:
                if not linha.endswith("\n"):
                    continue
                partes = linha.strip().split('|')
                if len(partes) >= 2:
                    try:
                        tx_id = int(partes[1])
                        if tx_id > maior_id:
                            maior_id = tx_id
                    except ValueError:
                        continue
        return maior_id

    def truncar(self):
        if os.path.exists(self.wal_file):
            with open(self.wal_file, 'w') as f:
                f.flush()
                os.fsync(f.fileno())
            logger.debug("WAL: Log truncado após checkpoint.")

    def recuperar(self, executor) -> int:
        if not os.path.exists(self.wal_file):
            logger.info("WAL: Nenhum arquivo de log encontrado para recuperação.")
            return 0

        logger.info("WAL: Iniciando processo de recuperação pós-falha...")

        txs_commitadas = set()
        txs_abortadas = set()
        undo_paginas: dict[int, dict[int, str]] = {}
        operacoes_insert = []

        with open(self.wal_file, 'r') as f:
            for linha in f:
                if not linha.endswith("\n"):
                    logger.warning("WAL: Linha truncada sem quebra de linha ignorada.")
                    continue

                linha_limpa = linha.strip()
                if not linha_limpa:
                    continue

                partes = linha_limpa.split('|')
                op = partes[0]

                try:
                    if op == "COMMIT" and len(partes) == 2:
                        txs_commitadas.add(int(partes[1]))
                    elif op == "ABORT" and len(partes) == 2:
                        txs_abortadas.add(int(partes[1]))
                    elif op == "UNDO_PAGE" and len(partes) == 4:
                        tx_id = int(partes[1])
                        num_pag = int(partes[2])
                        page_hex = partes[3]
                        if tx_id not in undo_paginas:
                            undo_paginas[tx_id] = {}
                        if num_pag not in undo_paginas[tx_id]:
                            undo_paginas[tx_id][num_pag] = page_hex
                    elif op == "INSERT" and len(partes) == 5:
                        tx_id = int(partes[1])
                        tabela = partes[2]
                        chave = int(partes[3])
                        dados_hex = partes[4]
                        operacoes_insert.append((tx_id, tabela, chave, dados_hex))
                except ValueError:
                    logger.warning(f"WAL: Registro corrompido ignorado: '{linha_limpa}'")

        desfez_paginas = False
        for tx_id in sorted(undo_paginas.keys(), reverse=True):
            if tx_id not in txs_commitadas and tx_id not in txs_abortadas:
                for num_pag, page_hex in undo_paginas[tx_id].items():
                    dados_originais = bytearray.fromhex(page_hex)
                    escreve_pagina(num_pag, dados_originais, db_file=executor.cache.db_file)
                    desfez_paginas = True
                logger.info(f"WAL UNDO: Páginas da transação inacabada {tx_id} restauradas.")

        if desfez_paginas:
            executor.cache.limpar()
            executor.recarregar_estado()

        registros_refeitos = 0
        for tx_id, tabela, chave, dados_hex in operacoes_insert:
            if tx_id in txs_commitadas:
                if tabela not in executor.arvores:
                    logger.error(f"WAL REDO: Tabela '{tabela}' não encontrada no catálogo para chave {chave}.")
                    continue
                arvore = executor.arvores[tabela]
                if arvore.buscar(chave) is None:
                    reg_bytes = bytes.fromhex(dados_hex)
                    arvore.inserir(chave, reg_bytes)
                    registros_refeitos += 1
                    logger.debug(f"WAL REDO: Registro {chave} reinserido na tabela '{tabela}'.")

        executor.cache.flush_todas()
        self.truncar()
        logger.info(f"WAL: Recuperação concluída. {registros_refeitos} operações refeitas.")
        return registros_refeitos