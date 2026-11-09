import os
import logging

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

    def log_insert(self, tx_id: int, tabela: str, chave: int, dados_hex: str):
        self._escrever(f"INSERT|{tx_id}|{tabela}|{chave}|{dados_hex}\n")
        logger.debug(f"WAL: Logged INSERT tx={tx_id} tabela={tabela} chave={chave}")

    def log_commit(self, tx_id: int):
        self._escrever(f"COMMIT|{tx_id}\n")
        logger.info(f"WAL: Logged COMMIT {tx_id}")

    def log_rollback(self, tx_id: int):
        self._escrever(f"ABORT|{tx_id}\n")
        logger.info(f"WAL: Logged ABORT {tx_id}")

    def recuperar(self, executor) -> int:
        """
        Analisa o log WAL na inicialização e refaz (REDO) todas as operações 
        de transações que deram COMMIT, descartando as incompletas (kill -9).
        """
        if not os.path.exists(self.wal_file):
            logger.info("WAL: Nenhum arquivo de log encontrado para recuperação.")
            return 0

        logger.info("WAL: Iniciando processo de recuperação pós-falha (REDO)...")
        
        comentarios_commit = set()
        operacoes = []

        with open(self.wal_file, 'r') as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                
                partes = linha.split('|')
                op = partes[0]
                
                if op == "COMMIT":
                    tx_id = int(partes[1])
                    comentarios_commit.add(tx_id)
                elif op == "INSERT":
                    tx_id = int(partes[1])
                    tabela = partes[2]
                    chave = int(partes[3])
                    dados_hex = partes[4]
                    operacoes.append((tx_id, tabela, chave, dados_hex))

        registros_refeitos = 0
        for tx_id, tabela, chave, dados_hex in operacoes:
            if tx_id in comentarios_commit:
                reg_bytes = bytes.fromhex(dados_hex)
                if tabela in executor.arvores:
                    arvore = executor.arvores[tabela]
                    arvore.inserir(chave, reg_bytes)
                    registros_refeitos += 1
                    logger.debug(f"WAL REDO: Registro {chave} reinserido na tabela '{tabela}'.")

        executor.cache.flush_todas()
        logger.info(f"WAL: Recuperação concluída. {registros_refeitos} operações refeitas.")
        return registros_refeitos