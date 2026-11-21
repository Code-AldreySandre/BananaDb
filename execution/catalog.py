import json
import logging
import struct
from core.gerenciador_disco import Schema, PAGE_SIZE, obter_pagina_catalogo
from core.buffer_pool import CachePaginas
from execution.parser import ColunaDef

logger = logging.getLogger("minidb")


class Catalogo:
    def __init__(self, cache: CachePaginas | None = None):
        self.cache = cache
        self.pagina_catalogo: int | None = None
        self.tabelas = {}

        if self.cache is not None:
            self.pagina_catalogo = obter_pagina_catalogo(self.cache.db_file)
            self.carregar()

        logger.info("Catálogo inicializado.")

    def carregar(self):
        if self.cache is None or self.pagina_catalogo is None:
            return

        self.tabelas.clear()
        pag = self.cache.obter_pagina(self.pagina_catalogo)

        pag = self.cache.obter_pagina(self.pagina_catalogo)
        try:
            tamanho = struct.unpack_from("<I", pag.dados, 0)[0]
            if tamanho == 0:
                return
            if tamanho > PAGE_SIZE - 4:
                raise RuntimeError("Página de catálogo corrompida.")
            raw = bytes(pag.dados[4:4 + tamanho])
        finally:
            self.cache.liberar_pagina(self.pagina_catalogo, modificada=False)

        dados = json.loads(raw.decode("utf-8"))
        for nome, info in dados.items():
            colunas_def = [ColunaDef(c["nome"], c["tipo"]) for c in info["colunas"]]
            tipos = [c.tipo.upper() for c in colunas_def]
            self.tabelas[nome] = {
                "colunas": colunas_def,
                "esquema": Schema(tipos),
                "pagina_raiz": info["pagina_raiz"],
            }
        logger.info(f"Catálogo carregado do disco com {len(self.tabelas)} tabela(s).")

    def salvar(self):
        if self.cache is None or self.pagina_catalogo is None:
            return

        dados = {
            nome: {
                "colunas": [{"nome": c.nome, "tipo": c.tipo} for c in info["colunas"]],
                "pagina_raiz": info["pagina_raiz"],
            }
            for nome, info in self.tabelas.items()
        }
        payload = json.dumps(dados).encode("utf-8")
        if len(payload) > PAGE_SIZE - 4:
            raise RuntimeError("Catálogo excedeu o tamanho máximo de uma página.")

        pag = self.cache.obter_pagina(self.pagina_catalogo)
        try:
            pag.dados[:] = bytearray(PAGE_SIZE)
            struct.pack_into("<I", pag.dados, 0, len(payload))
            pag.dados[4:4 + len(payload)] = payload
        finally:
            self.cache.liberar_pagina(self.pagina_catalogo, modificada=True)

        self.cache.flush_pagina(self.pagina_catalogo)

    def criar_tabela(self, nome: str, colunas_def: list[ColunaDef], pagina_raiz: int | None = None):
        if nome in self.tabelas:
            logger.error(f"Tentativa de recriar tabela existente: '{nome}'.")
            raise ValueError(f"Erro: A tabela '{nome}' já existe no catálogo.")

        tipos = [col.tipo.upper() for col in colunas_def]
        esquema = Schema(tipos)

        self.tabelas[nome] = {
            "colunas": colunas_def,
            "esquema": esquema,
            "pagina_raiz": pagina_raiz,
        }
        self.salvar()
        logger.debug(f"Tabela '{nome}' registada no catálogo. Schema de {esquema.tamanho} bytes.")

    def atualizar_raiz(self, nome: str, nova_raiz: int):
        if nome not in self.tabelas:
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        self.tabelas[nome]["pagina_raiz"] = nova_raiz
        self.salvar()

    def obter_raiz(self, nome: str) -> int | None:
        if nome not in self.tabelas:
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        return self.tabelas[nome]["pagina_raiz"]

    def listar_tabelas(self) -> list[str]:
        return list(self.tabelas.keys())

    def obter_esquema(self, nome: str) -> Schema:
        if nome not in self.tabelas:
            logger.warning(f"Schema da tabela '{nome}' não encontrado.")
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        return self.tabelas[nome]["esquema"]

    def obter_colunas(self, nome: str) -> list[ColunaDef]:
        if nome not in self.tabelas:
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        return self.tabelas[nome]["colunas"]