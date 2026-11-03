import struct
from core.gerenciador_disco import (
    CachePaginas,
    Pagina,
    PAGE_SIZE,
    HEADER_SIZE,
    RECORD_SIZE,
)

FORMATO_HEADER = "<iiii"
MAX_CHAVES = (PAGE_SIZE - HEADER_SIZE) // RECORD_SIZE


class ArvoreBPlus:
    def __init__(self, cache: CachePaginas, pagina_raiz: int | None = None, max_chaves: int = MAX_CHAVES):
        self.cache = cache
        self.max_chaves = max_chaves

        if pagina_raiz is None:
            pag_raiz = self.cache.nova_pagina()
            self.pagina_raiz = pag_raiz.numero
            self._escrever_header(pag_raiz, 1, 0, -1, 0)
            self.cache.liberar_pagina(self.pagina_raiz, modificada=True)
        else:
            self.pagina_raiz = pagina_raiz

    def _ler_header(self, pag: Pagina) -> tuple[int, int, int, int]:
        return struct.unpack_from(FORMATO_HEADER, pag.dados, 0)

    def _escrever_header(self, pag: Pagina, eh_folha: int, num_chaves: int, prox_folha: int = -1, reservado: int = 0):
        struct.pack_into(FORMATO_HEADER, pag.dados, 0, eh_folha, num_chaves, prox_folha, reservado)

    def _ler_slot_folha(self, pag: Pagina, idx: int) -> tuple[int, bytes]:
        reg_bytes = bytes(pag.ler_slot(idx, RECORD_SIZE))
        chave = struct.unpack_from("<i", reg_bytes, 0)[0]
        return chave, reg_bytes

    def _escrever_slot_folha(self, pag: Pagina, idx: int, reg_bytes: bytes):
        pag.escrever_slot(idx, reg_bytes, RECORD_SIZE)

    def _ler_filho(self, pag: Pagina, idx: int) -> int:
        offset = HEADER_SIZE + (idx * 8)
        return struct.unpack_from("<i", pag.dados, offset)[0]

    def _escrever_filho(self, pag: Pagina, idx: int, num_pag: int):
        offset = HEADER_SIZE + (idx * 8)
        struct.pack_into("<i", pag.dados, offset, num_pag)

    def _ler_chave_interna(self, pag: Pagina, idx: int) -> int:
        offset = HEADER_SIZE + 4 + (idx * 8)
        return struct.unpack_from("<i", pag.dados, offset)[0]

    def _escrever_chave_interna(self, pag: Pagina, idx: int, chave: int):
        offset = HEADER_SIZE + 4 + (idx * 8)
        struct.pack_into("<i", pag.dados, offset, chave)

    def _encontrar_folha(self, chave: int) -> list[int]:
        caminho = []
        num_atual = self.pagina_raiz

        while True:
            caminho.append(num_atual)
            pag = self.cache.obter_pagina(num_atual)
            eh_folha, num_chaves, _, _ = self._ler_header(pag)

            if eh_folha == 1:
                self.cache.liberar_pagina(num_atual, modificada=False)
                return caminho

            idx_filho = num_chaves
            for i in range(num_chaves):
                if chave < self._ler_chave_interna(pag, i):
                    idx_filho = i
                    break

            prox_num = self._ler_filho(pag, idx_filho)
            self.cache.liberar_pagina(num_atual, modificada=False)
            num_atual = prox_num

    def buscar(self, chave: int) -> bytes | None:
        caminho = self._encontrar_folha(chave)
        num_folha = caminho[-1]

        pag = self.cache.obter_pagina(num_folha)
        _, num_chaves, _, _ = self._ler_header(pag)

        for i in range(num_chaves):
            chave_atual, reg_bytes = self._ler_slot_folha(pag, i)
            if chave_atual == chave:
                self.cache.liberar_pagina(num_folha, modificada=False)
                return reg_bytes
            if chave_atual > chave:
                break

        self.cache.liberar_pagina(num_folha, modificada=False)
        return None

    def listar_todos(self) -> list[bytes]:
        num_atual = self.pagina_raiz
        while True:
            pag = self.cache.obter_pagina(num_atual)
            eh_folha, _, _, _ = self._ler_header(pag)
            if eh_folha == 1:
                self.cache.liberar_pagina(num_atual, modificada=False)
                break
            primeiro_filho = self._ler_filho(pag, 0)
            self.cache.liberar_pagina(num_atual, modificada=False)
            num_atual = primeiro_filho

        registros = []
        while num_atual != -1:
            pag = self.cache.obter_pagina(num_atual)
            _, num_chaves, prox_folha, _ = self._ler_header(pag)
            for i in range(num_chaves):
                _, reg_bytes = self._ler_slot_folha(pag, i)
                registros.append(reg_bytes)
            self.cache.liberar_pagina(num_atual, modificada=False)
            num_atual = prox_folha

        return registros

    def _inserir_na_folha(self, pag: Pagina, chave: int, reg_bytes: bytes):
        eh_folha, num_chaves, prox_folha, reservado = self._ler_header(pag)

        pos = num_chaves
        for i in range(num_chaves):
            chave_existente, _ = self._ler_slot_folha(pag, i)
            if chave < chave_existente:
                pos = i
                break

        for i in range(num_chaves, pos, -1):
            _, reg_ant = self._ler_slot_folha(pag, i - 1)
            self._escrever_slot_folha(pag, i, reg_ant)

        self._escrever_slot_folha(pag, pos, reg_bytes)
        self._escrever_header(pag, eh_folha, num_chaves + 1, prox_folha, reservado)

    def _inserir_no_interno(self, pag: Pagina, chave: int, filho_dir: int):
        eh_folha, num_chaves, prox_folha, reservado = self._ler_header(pag)

        pos = num_chaves
        for i in range(num_chaves):
            if chave < self._ler_chave_interna(pag, i):
                pos = i
                break

        for i in range(num_chaves, pos, -1):
            self._escrever_chave_interna(pag, i, self._ler_chave_interna(pag, i - 1))
            self._escrever_filho(pag, i + 1, self._ler_filho(pag, i))

        self._escrever_chave_interna(pag, pos, chave)
        self._escrever_filho(pag, pos + 1, filho_dir)
        self._escrever_header(pag, eh_folha, num_chaves + 1, prox_folha, reservado)

    def _dividir_folha(self, pag: Pagina, chave: int, reg_bytes: bytes):
        pass

    def _dividir_interno(self, pag: Pagina, chave: int, filho_dir: int):
        pass

    def inserir(self, chave: int, reg_bytes: bytes):
        caminho = self._encontrar_folha(chave)
        num_folha = caminho[-1]

        pag = self.cache.obter_pagina(num_folha)
        _, num_chaves, _, _ = self._ler_header(pag)

        if num_chaves < self.max_chaves:
            self._inserir_na_folha(pag, chave, reg_bytes)
            self.cache.liberar_pagina(num_folha, modificada=True)
            return

        self.cache.liberar_pagina(num_folha, modificada=False)


if __name__ == "__main__":
    from core.gerenciador_disco import inicializa_pagina_zero, Schema, serializa, desserializa

    inicializa_pagina_zero()
    cache = CachePaginas(capacidade=8)
    esquema = Schema(['INT', 'INT'])
    arvore = ArvoreBPlus(cache)

    dados = [(30, 20260030), (10, 20260010), (40, 20260040), (20, 20260020)]
    for id_aluno, matr in dados:
        arvore.inserir(id_aluno, serializa(esquema, id_aluno, matr))

    cache.flush_todas()

    res = arvore.buscar(20)
    if res:
        print("Encontrado:", desserializa(esquema, res))

    todos = [desserializa(esquema, b) for b in arvore.listar_todos()]
    print("Registros na folha:", todos)