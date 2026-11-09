import logging
from core.gerenciador_disco import Schema
from execution.parser import ColunaDef

logger = logging.getLogger("minidb")

class Catalogo:
    def __init__(self):
        self.tabelas = {}
        logger.info("Catálogo inicializado na memória.")

    def criar_tabela(self, nome: str, colunas_def: list[ColunaDef]):
        """Regista uma nova tabela e inicializa o seu esquema de serialização."""
        if nome in self.tabelas:
            logger.error(f"Tentativa de recriar tabela existente: '{nome}'.")
            raise ValueError(f"Erro: A tabela '{nome}' já existe no catálogo.")
        
        tipos = [col.tipo.upper() for col in colunas_def]
        esquema = Schema(tipos)
        
        self.tabelas[nome] = {
            "colunas": colunas_def,
            "esquema": esquema
        }
        logger.debug(f"Tabela '{nome}' registada no catálogo. Schema de {esquema.tamanho} bytes.")

    def obter_esquema(self, nome: str) -> Schema:
        """Devolve o Schema de serialização de uma tabela para o disco/memória usar."""
        if nome not in self.tabelas:
            logger.warning(f"Schema da tabela '{nome}' não encontrado.")
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        return self.tabelas[nome]["esquema"]

    def obter_colunas(self, nome: str) -> list[ColunaDef]:
        """Devolve as definições lógicas das colunas (nomes e tipos)."""
        if nome not in self.tabelas:
            raise ValueError(f"Erro: A tabela '{nome}' não foi encontrada no catálogo.")
        return self.tabelas[nome]["colunas"]