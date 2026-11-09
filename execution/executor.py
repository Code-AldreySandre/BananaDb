import logging
from execution.parser import CreateTable, Insert, Select, Begin, Commit, Rollback
from transaction.transaction import GerenciadorTransacoes
from execution.catalog import Catalogo
from core.buffer_pool import CachePaginas
from core.gerenciador_disco import serializa, desserializa
from index.bplus_tree import ArvoreBPlus

logger = logging.getLogger("minidb")

class Executor:
    def __init__(self, catalogo: Catalogo, cache: CachePaginas, tx_manager: GerenciadorTransacoes):
        self.catalogo = catalogo
        self.cache = cache
        self.tx_manager = tx_manager
        self.arvores = {}

    def executar(self, ast) -> str:
        if isinstance(ast, Begin):
            return self.tx_manager.begin()
        elif isinstance(ast, Commit):
            return self.tx_manager.commit()
        elif isinstance(ast, Rollback):
            return self.tx_manager.rollback()
        elif isinstance(ast, CreateTable):
            return self._executar_create(ast)
        elif isinstance(ast, Insert):
            return self._executar_insert(ast)
        elif isinstance(ast, Select):
            return self._executar_select(ast)
        else:
            raise ValueError("Comando AST não suportado pelo Executor.")
        
    def _executar_create(self, ast: CreateTable) -> str:
        self.catalogo.criar_tabela(ast.tabela, ast.colunas)
        self.arvores[ast.tabela] = ArvoreBPlus(self.cache)
        logger.info(f"Tabela '{ast.tabela}' e índice B+ inicializados.")
        return "OK"

    def _executar_insert(self, ast: Insert) -> str:
        if ast.tabela not in self.arvores:
            raise ValueError(f"Tabela '{ast.tabela}' não encontrada no catálogo.")

        esquema = self.catalogo.obter_esquema(ast.tabela)
        chave = ast.valores[0]
        reg_bytes = serializa(esquema, *ast.valores)
        
        if self.tx_manager.transacao_atual:
            tx_id = self.tx_manager.transacao_atual.tx_id
            self.tx_manager.wal_manager.log_insert(tx_id, ast.tabela, chave, reg_bytes.hex())

        arvore = self.arvores[ast.tabela]
        arvore.inserir(chave, reg_bytes)
        
        logger.info(f"Registro com chave {chave} inserido na tabela '{ast.tabela}'.")
        return "OK 1"

    def _executar_select(self, ast: Select) -> str:
        if ast.tabela not in self.arvores:
            raise ValueError(f"Tabela '{ast.tabela}' não encontrada no catálogo.")

        esquema = self.catalogo.obter_esquema(ast.tabela)
        colunas_def = self.catalogo.obter_colunas(ast.tabela)
        arvore = self.arvores[ast.tabela]
        
        linhas = []

        if ast.where and ast.where.coluna == colunas_def[0].nome and ast.where.operador == "=":
            logger.debug(f"Executando Varredura por Índice (chave: {ast.where.valor}).")
            reg_bytes = arvore.buscar(ast.where.valor)
            if reg_bytes:
                val_tupla = desserializa(esquema, reg_bytes)
                linhas.append(val_tupla)
        else:
            logger.debug("Executando Varredura Sequencial (Full Scan em folhas).")
            todos_bytes = arvore.listar_todos()
            for b in todos_bytes:
                val_tupla = desserializa(esquema, b)
                
                if ast.where:
                    idx_col = next((i for i, c in enumerate(colunas_def) if c.nome == ast.where.coluna), None)
                    if idx_col is not None:
                        val_col = val_tupla[idx_col]
                        op = ast.where.operador
                        alvo = ast.where.valor
                        
                        if op == "=" and not (val_col == alvo): continue
                        if op == ">" and not (val_col > alvo): continue
                        if op == "<" and not (val_col < alvo): continue
                        if op == ">=" and not (val_col >= alvo): continue
                        if op == "<=" and not (val_col <= alvo): continue
                        if op == "!=" and not (val_col != alvo): continue

                linhas.append(val_tupla)

        saida = []
        for l in linhas:
            saida.append("|".join(str(v) for v in l))

        qtd = len(linhas)
        sufixo = "(1 linha)" if qtd == 1 else f"({qtd} linhas)"
        saida.append(sufixo)

        return "\n".join(saida)