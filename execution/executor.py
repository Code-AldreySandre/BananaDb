import logging
from execution.parser import CreateTable, Insert, Select, Begin, Commit, Rollback
from transaction.transaction import GerenciadorTransacoes
from execution.catalog import Catalogo
from core.buffer_pool import CachePaginas
from core.gerenciador_disco import serializa, desserializa
from index.bplus_tree import ArvoreBPlus

logger = logging.getLogger("minidb")
INT32_MIN = -(2**31)
INT32_MAX = (2**31) - 1

class Executor:
    def __init__(self, catalogo: Catalogo, cache: CachePaginas, tx_manager: GerenciadorTransacoes):
        self.catalogo = catalogo
        self.cache = cache
        self.tx_manager = tx_manager
        self.arvores = {}

        for nome in self.catalogo.listar_tabelas():
            raiz = self.catalogo.obter_raiz(nome)
            self.arvores[nome] = ArvoreBPlus(
                self.cache,
                pagina_raiz=raiz,
                on_root_change=lambda nova_raiz, t=nome: self.catalogo.atualizar_raiz(t, nova_raiz),
            )
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
        arvore = ArvoreBPlus(
            self.cache,
            on_root_change=lambda nova_raiz, t=ast.tabela: self.catalogo.atualizar_raiz(t, nova_raiz),
        )
        self.catalogo.atualizar_raiz(ast.tabela, arvore.pagina_raiz)
        self.arvores[ast.tabela] = arvore
        logger.info(f"Tabela '{ast.tabela}' e índice B+ inicializados na raiz {arvore.pagina_raiz}.")
        return "OK"

    def _validar_int32(self, valor, nome_coluna: str):
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ValueError(f"Valor inválido para coluna INT '{nome_coluna}': {valor!r}")
        if valor < INT32_MIN or valor > INT32_MAX:
            raise ValueError(f"Valor fora do intervalo INT de 32 bits para '{nome_coluna}': {valor}")

    def _executar_insert(self, ast: Insert) -> str:
        if ast.tabela not in self.arvores:
            raise ValueError(f"Tabela '{ast.tabela}' não encontrada no catálogo.")

        colunas_def = self.catalogo.obter_colunas(ast.tabela)
        if len(ast.valores) != len(colunas_def):
            raise ValueError(
                f"Esperado(s) {len(colunas_def)} valor(es) para '{ast.tabela}', recebido(s) {len(ast.valores)}."
            )

        for col, val in zip(colunas_def, ast.valores):
            if col.tipo.upper() == "INT":
                self._validar_int32(val, col.nome)

        esquema = self.catalogo.obter_esquema(ast.tabela)
        chave = ast.valores[0]
        reg_bytes = serializa(esquema, *ast.valores)

        arvore = self.arvores[ast.tabela]
        if arvore.buscar(chave) is not None:
            raise ValueError(f"Chave duplicada na tabela '{ast.tabela}': {chave}")

        if self.tx_manager.transacao_atual:
            tx_id = self.tx_manager.transacao_atual.tx_id
            self.tx_manager.wal_manager.log_insert(tx_id, ast.tabela, chave, reg_bytes.hex())

        arvore.inserir(chave, reg_bytes)

        logger.info(f"Registro com chave {chave} inserido na tabela '{ast.tabela}'.")
        return "OK 1"

    def _executar_select(self, ast: Select) -> str:
        if ast.tabela not in self.arvores:
            raise ValueError(f"Tabela '{ast.tabela}' não encontrada no catálogo.")

        esquema = self.catalogo.obter_esquema(ast.tabela)
        colunas_def = self.catalogo.obter_colunas(ast.tabela)
        arvore = self.arvores[ast.tabela]

        idx_where = None
        if ast.where:
            idx_where = next((i for i, c in enumerate(colunas_def) if c.nome == ast.where.coluna), None)
            if idx_where is None:
                raise ValueError(f"Coluna '{ast.where.coluna}' não existe na tabela '{ast.tabela}'.")
            if colunas_def[idx_where].tipo.upper() == "INT":
                self._validar_int32(ast.where.valor, ast.where.coluna)

        linhas = []

        if ast.where and idx_where == 0 and ast.where.operador == "=":
            logger.debug(f"Executando Varredura por Índice (chave: {ast.where.valor}).")
            reg_bytes = arvore.buscar(ast.where.valor)
            if reg_bytes:
                linhas.append(desserializa(esquema, reg_bytes))
        else:
            logger.debug("Executando Varredura Sequencial (Full Scan em folhas).")
            todos_bytes = arvore.listar_todos()
            for b in todos_bytes:
                val_tupla = desserializa(esquema, b)

                if ast.where:
                    val_col = val_tupla[idx_where]
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