import logging
from enum import Enum
from typing import Optional, Set
from core.buffer_pool import CachePaginas
from core.gerenciador_disco import ler_pagina
from transaction.wal import WALManager

logger = logging.getLogger("minidb")

class StatusTransacao(Enum):
    ATIVA = "ATIVA"
    COMMITTED = "COMMITTED"
    ABORTADA = "ABORTADA"

class Transacao:
    def __init__(self, tx_id: int):
        self.tx_id = tx_id
        self.status = StatusTransacao.ATIVA

class GerenciadorTransacoes:
    def __init__(self, cache: CachePaginas, wal_manager: WALManager):
        self.cache = cache
        self.wal_manager = wal_manager
        self.prox_tx_id = 1
        self.transacao_atual: Optional[Transacao] = None

    def begin(self) -> str:
        if self.transacao_atual is not None and self.transacao_atual.status == StatusTransacao.ATIVA:
            return "OK"
        
        tx = Transacao(self.prox_tx_id)
        self.prox_tx_id += 1
        self.transacao_atual = tx
        
        self.wal_manager.log_begin(tx.tx_id)
        return "OK"

    def commit(self) -> str:
        if self.transacao_atual is None or self.transacao_atual.status != StatusTransacao.ATIVA:
            raise RuntimeError("Nenhuma transação ativa para efetuar COMMIT.")

        tx = self.transacao_atual
        
        self.wal_manager.log_commit(tx.tx_id)
        
        self.cache.flush_todas()
        
        tx.status = StatusTransacao.COMMITTED
        self.transacao_atual = None
        return "OK"

    def rollback(self) -> str:
        if self.transacao_atual is None or self.transacao_atual.status != StatusTransacao.ATIVA:
            raise RuntimeError("Nenhuma transação ativa para efetuar ROLLBACK.")

        tx = self.transacao_atual
        self.wal_manager.log_rollback(tx.tx_id)

        for num_pag in list(self.cache.frames.keys()):
            if self.cache.frames[num_pag].is_dirty:
                dados_originais = ler_pagina(num_pag, db_file=self.cache.db_file)
                self.cache.frames[num_pag].dados = dados_originais
                self.cache.frames[num_pag].is_dirty = False
                self.cache.frames[num_pag].pin_count = 0

        tx.status = StatusTransacao.ABORTADA
        self.transacao_atual = None
        return "OK"