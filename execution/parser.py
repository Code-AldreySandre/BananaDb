import re
import logging
from dataclasses import dataclass
from typing import List, Any, Optional

logger = logging.getLogger("minidb")


@dataclass
class Begin:
    pass

@dataclass
class Commit:
    pass

@dataclass
class Rollback:
    pass

@dataclass
class ColunaDef:
    nome: str
    tipo: str

@dataclass
class CreateTable:
    tabela: str
    colunas: List[ColunaDef]

@dataclass
class Insert:
    tabela: str
    valores: List[Any]

@dataclass
class Where:
    coluna: str
    operador: str
    valor: Any

@dataclass
class Select:
    tabela: str
    colunas: List[str]
    where: Optional[Where]

class ParserSQL:
    def parse(self, query: str):
        query_limpa = query.strip().strip(";")
        logger.debug(f"Iniciando parse da consulta SQL: '{query_limpa}'")

        if re.match(r"^BEGIN(?:\s+TRANSACTION)?$", query_limpa, re.IGNORECASE):
            logger.info("SQL parsed: BEGIN")
            return Begin()
        
        if re.match(r"^COMMIT$", query_limpa, re.IGNORECASE):
            logger.info("SQL parsed: COMMIT")
            return Commit()

        if re.match(r"^ROLLBACK$", query_limpa, re.IGNORECASE):
            logger.info("SQL parsed: ROLLBACK")
            return Rollback()
        
        match_create = re.match(r"CREATE\s+TABLE\s+(\w+)\s*\((.+)\)", query_limpa, re.IGNORECASE)
        if match_create:
            nome_tabela = match_create.group(1)
            cols_str = match_create.group(2).split(',')
            colunas = []
            for c in cols_str:
                partes = c.strip().split()
                colunas.append(ColunaDef(partes[0], partes[1]))
            logger.info(f"SQL parsed: CREATE TABLE para a tabela '{nome_tabela}'.")
            return CreateTable(nome_tabela, colunas)

        match_insert = re.match(r"INSERT\s+INTO\s+(\w+)\s+VALUES\s*\((.+)\)", query_limpa, re.IGNORECASE)
        if match_insert:
            nome_tabela = match_insert.group(1)
            vals_str = match_insert.group(2).split(',')
            valores = []
            for v in vals_str:
                v_limpo = v.strip().strip("'\"")
                if v_limpo.isdigit():
                    valores.append(int(v_limpo))
                else:
                    valores.append(v_limpo)
            logger.info(f"SQL parsed: INSERT INTO para a tabela '{nome_tabela}' com {len(valores)} valores.")
            return Insert(nome_tabela, valores)

        match_select = re.match(r"SELECT\s+(.+)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?", query_limpa, re.IGNORECASE)
        if match_select:
            cols = [c.strip() for c in match_select.group(1).split(',')]
            nome_tabela = match_select.group(2)
            where_clause = None
            
            where_str = match_select.group(3)
            if where_str:
                match_where = re.match(r"(\w+)\s*(=|>|<|>=|<=|!=)\s*(.+)", where_str)
                if match_where:
                    val_str = match_where.group(3).strip().strip("'\"")
                    val = int(val_str) if val_str.isdigit() else val_str
                    where_clause = Where(match_where.group(1), match_where.group(2), val)
            
            logger.info(f"SQL parsed: SELECT na tabela '{nome_tabela}'.")
            return Select(nome_tabela, cols, where_clause)

        logger.error(f"Falha de sintaxe ao interpretar SQL: '{query_limpa}'")
        raise ValueError(f"Erro de sintaxe. Comando SQL não reconhecido: {query}")