import logging
from collections.abc import Callable
from enum import Enum
from typing import Optional
from core.buffer_pool import CachePaginas
from core.gerenciador_disco import ler_pagina, escreve_pagina
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
        self.paginas_undo: dict[int, bytes] = {}


class GerenciadorTransacoes:
    def __init__(self, cache: CachePaginas, wal_manager: WALManager):
        self.cache = cache
        self.wal_manager = wal_manager
        self.prox_tx_id = self.wal_manager.obter_ultimo_tx_id() + 1
        self.transacao_atual: Optional[Transacao] = None
        self.on_rollback: Callable[[], None] | None = None
        self.cache.on_before_write = self._ao_gravar_pagina_suja

    def _ao_gravar_pagina_suja(self, num_pag: int):
        tx = self.transacao_atual
        if tx is None or tx.status != StatusTransacao.ATIVA:
            return
        if num_pag not in tx.paginas_undo:
            antes = bytes(ler_pagina(num_pag, db_file=self.cache.db_file))
            self.wal_manager.log_undo_page(tx.tx_id, num_pag, antes.hex())
            tx.paginas_undo[num_pag] = antes

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

        tx.status = StatusTransacao.COMMITTED
        self.cache.flush_todas()
        self.transacao_atual = None
        return "OK"

    def rollback(self) -> str:
        if self.transacao_atual is None or self.transacao_atual.status != StatusTransacao.ATIVA:
            raise RuntimeError("Nenhuma transação ativa para efetuar ROLLBACK.")

        tx = self.transacao_atual
        tx.status = StatusTransacao.ABORTADA

        for num_pag, dados_originais in tx.paginas_undo.items():
            escreve_pagina(num_pag, bytearray(dados_originais), db_file=self.cache.db_file)

        self.cache.limpar()
        self.wal_manager.log_rollback(tx.tx_id)
        self.transacao_atual = None

        if self.on_rollback is not None:
            self.on_rollback()

        return "OK"