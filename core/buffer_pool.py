from collections import OrderedDict
from core.gerenciador_disco import (
    ler_pagina, 
    escreve_pagina, 
    aloca, 
    PAGE_SIZE, 
    HEADER_SIZE, 
    RECORD_SIZE, 
    DB_FILE
)

class Pagina:
    def __init__(self, numero: int, dados: bytearray):
        self.numero = numero
        self.dados = dados
        self.pin_count = 0
        self.is_dirty = False

    def escrever_slot(self, slot_idx: int, registro_bytes: bytes, tam_registro: int = RECORD_SIZE):
        inicio = HEADER_SIZE + (slot_idx * tam_registro)
        fim = inicio + tam_registro
        if fim > PAGE_SIZE:
            raise ValueError("Índice de slot ultrapassa o limite da página.")
        self.dados[inicio:fim] = registro_bytes

    def ler_slot(self, slot_idx: int, tam_registro: int = RECORD_SIZE) -> bytearray:
        inicio = HEADER_SIZE + (slot_idx * tam_registro)
        fim = inicio + tam_registro
        if fim > PAGE_SIZE:
            raise ValueError("Índice de slot ultrapassa o limite da página.")
        return self.dados[inicio:fim]

class CachePaginas:
    def __init__(self, capacidade: int = 4, db_file: str = DB_FILE):
        self.capacidade = capacidade
        self.db_file = db_file
        self.frames: dict[int, Pagina] = {}
        self.lru: OrderedDict[int, None] = OrderedDict()

    def obter_pagina(self, n: int) -> Pagina:
        if n in self.frames:
            pag = self.frames[n]
            pag.pin_count += 1
            self.lru.pop(n, None)
            return pag

        if len(self.frames) >= self.capacidade:
            self._desalojar_pagina()

        dados_disco = ler_pagina(n, db_file=self.db_file)
        pag = Pagina(n, dados_disco)
        pag.pin_count = 1
        pag.is_dirty = False

        self.frames[n] = pag
        return pag

    def nova_pagina(self) -> Pagina:
        num_pagina = aloca(db_file=self.db_file)
        return self.obter_pagina(num_pagina)

    def liberar_pagina(self, n: int, modificada: bool = False):
        if n not in self.frames:
            return

        pag = self.frames[n]
        if modificada:
            pag.is_dirty = True

        if pag.pin_count > 0:
            pag.pin_count -= 1

        if pag.pin_count == 0:
            self.lru[n] = None
            self.lru.move_to_end(n)

    def _desalojar_pagina(self):
        if not self.lru:
            raise RuntimeError("Cache cheio: todas as páginas estão fixadas (pin_count > 0).")

        num_vitima, _ = self.lru.popitem(last=False)
        vitima = self.frames.pop(num_vitima)

        if vitima.is_dirty:
            escreve_pagina(vitima.numero, vitima.dados, db_file=self.db_file)
            vitima.is_dirty = False

    def flush_pagina(self, n: int):
        if n in self.frames:
            pag = self.frames[n]
            if pag.is_dirty:
                escreve_pagina(pag.numero, pag.dados, db_file=self.db_file)
                pag.is_dirty = False

    def flush_todas(self):
        for pag in list(self.frames.values()):
            if pag.is_dirty:
                escreve_pagina(pag.numero, pag.dados, db_file=self.db_file)
                pag.is_dirty = False