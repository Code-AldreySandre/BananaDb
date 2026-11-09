import struct
from core.gerenciador_disco import (
    PAGE_SIZE,
    HEADER_SIZE,
    RECORD_SIZE,
)
from core.buffer_pool import (
    CachePaginas,
    Pagina,
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
            self.cache.flush_pagina(self.pagina_raiz)
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
        if offset + 4 > PAGE_SIZE:
            raise ValueError(f"Offset {offset} excede o limite da página.")
        return struct.unpack_from("<i", pag.dados, offset)[0]

    def _escrever_filho(self, pag: Pagina, idx: int, num_pag: int):
        offset = HEADER_SIZE + (idx * 8)
        struct.pack_into("<i", pag.dados, offset, num_pag)

    def _ler_chave_interna(self, pag: Pagina, idx: int) -> int:
        offset = HEADER_SIZE + 4 + (idx * 8)
        if offset + 4 > PAGE_SIZE:
            raise ValueError(f"Offset {offset} excede o limite da página.")
        return struct.unpack_from("<i", pag.dados, offset)[0]

    def _escrever_chave_interna(self, pag: Pagina, idx: int, chave: int):
        offset = HEADER_SIZE + 4 + (idx * 8)
        struct.pack_into("<i", pag.dados, offset, chave)

    def _encontrar_folha(self, chave: int) -> list[int]:
        caminho = []
        num_atual = self.pagina_raiz

        while True:
            if num_atual == 0:
                raise RuntimeError("Erro estrutural: Tentativa de ler a Página 0 (reservada para metadados) como nó de dados.")

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

    def _dividir_folha(self, caminho: list[int], chave_nova: int, reg_bytes: bytes):
        num_pag_antiga = caminho[-1]
        pag_antiga = self.cache.obter_pagina(num_pag_antiga)
        eh_folha, num_chaves, prox_folha, reservado = self._ler_header(pag_antiga)

        registros = []
        for i in range(num_chaves):
            registros.append(self._ler_slot_folha(pag_antiga, i))
        
        inserido = False
        for i, (c, _) in enumerate(registros):
            if chave_nova < c:
                registros.insert(i, (chave_nova, reg_bytes))
                inserido = True
                break
        if not inserido:
            registros.append((chave_nova, reg_bytes))

        pag_nova = self.cache.nova_pagina()
        num_pag_nova = pag_nova.numero

        meio = len(registros) // 2
        regs_esq = registros[:meio]
        regs_dir = registros[meio:]
        chave_promovida = regs_dir[0][0]

        for i, (_, reg) in enumerate(regs_esq):
            self._escrever_slot_folha(pag_antiga, i, reg)
        self._escrever_header(pag_antiga, 1, len(regs_esq), num_pag_nova, reservado)
        
        for i, (_, reg) in enumerate(regs_dir):
            self._escrever_slot_folha(pag_nova, i, reg)
        self._escrever_header(pag_nova, 1, len(regs_dir), prox_folha, reservado)

        self.cache.liberar_pagina(num_pag_antiga, modificada=True)
        self.cache.liberar_pagina(num_pag_nova, modificada=True)
        self.cache.flush_pagina(num_pag_antiga)
        self.cache.flush_pagina(num_pag_nova)

        caminho.pop()
        self._propagar_subida(caminho, chave_promovida, num_pag_nova)

    def _dividir_interno(self, caminho: list[int], num_pag_antiga: int, chave_nova: int, filho_dir_novo: int):
        pag_antiga = self.cache.obter_pagina(num_pag_antiga)
        eh_folha, num_chaves, prox_folha, reservado = self._ler_header(pag_antiga)

        chaves = []
        filhos = [self._ler_filho(pag_antiga, 0)]
        for i in range(num_chaves):
            chaves.append(self._ler_chave_interna(pag_antiga, i))
            filhos.append(self._ler_filho(pag_antiga, i + 1))

        inserido = False
        for i, c in enumerate(chaves):
            if chave_nova < c:
                chaves.insert(i, chave_nova)
                filhos.insert(i + 1, filho_dir_novo)
                inserido = True
                break
        if not inserido:
            chaves.append(chave_nova)
            filhos.append(filho_dir_novo)

        pag_nova = self.cache.nova_pagina()
        num_pag_nova = pag_nova.numero

        meio = len(chaves) // 2
        chave_promovida = chaves[meio]
        
        chaves_esq = chaves[:meio]
        filhos_esq = filhos[:meio+1]
        
        chaves_dir = chaves[meio+1:]
        filhos_dir = filhos[meio+1:]

        self._escrever_filho(pag_antiga, 0, filhos_esq[0])
        for i, c in enumerate(chaves_esq):
            self._escrever_chave_interna(pag_antiga, i, c)
            self._escrever_filho(pag_antiga, i + 1, filhos_esq[i+1])
        self._escrever_header(pag_antiga, 0, len(chaves_esq), -1, reservado)

        self._escrever_filho(pag_nova, 0, filhos_dir[0])
        for i, c in enumerate(chaves_dir):
            self._escrever_chave_interna(pag_nova, i, c)
            self._escrever_filho(pag_nova, i + 1, filhos_dir[i+1])
        self._escrever_header(pag_nova, 0, len(chaves_dir), -1, reservado)

        self.cache.liberar_pagina(num_pag_antiga, modificada=True)
        self.cache.liberar_pagina(num_pag_nova, modificada=True)
        self.cache.flush_pagina(num_pag_antiga)
        self.cache.flush_pagina(num_pag_nova)

        self._propagar_subida(caminho, chave_promovida, num_pag_nova)

    def _propagar_subida(self, caminho: list[int], chave_promovida: int, filho_dir: int):
        if not caminho:
            pag_nova_raiz = self.cache.nova_pagina()
            self._escrever_filho(pag_nova_raiz, 0, self.pagina_raiz)
            self._escrever_chave_interna(pag_nova_raiz, 0, chave_promovida)
            self._escrever_filho(pag_nova_raiz, 1, filho_dir)
            self._escrever_header(pag_nova_raiz, 0, 1, -1, 0)
            self.cache.liberar_pagina(pag_nova_raiz.numero, modificada=True)
            self.cache.flush_pagina(pag_nova_raiz.numero)
            self.pagina_raiz = pag_nova_raiz.numero
            return

        num_pag_pai = caminho.pop()
        pag_pai = self.cache.obter_pagina(num_pag_pai)
        _, num_chaves_pai, _, _ = self._ler_header(pag_pai)

        if num_chaves_pai < self.max_chaves:
            self._inserir_no_interno(pag_pai, chave_promovida, filho_dir)
            self.cache.liberar_pagina(num_pag_pai, modificada=True)
        else:
            self.cache.liberar_pagina(num_pag_pai, modificada=False)
            self._dividir_interno(caminho, num_pag_pai, chave_promovida, filho_dir)

    def inserir(self, chave: int, reg_bytes: bytes):
        caminho = self._encontrar_folha(chave)
        num_folha = caminho[-1]

        pag = self.cache.obter_pagina(num_folha)
        _, num_chaves, _, _ = self._ler_header(pag)

        if num_chaves < self.max_chaves:
            self._inserir_na_folha(pag, chave, reg_bytes)
            self.cache.liberar_pagina(num_folha, modificada=True)
        else:
            self.cache.liberar_pagina(num_folha, modificada=False)
            self._dividir_folha(caminho, chave, reg_bytes)