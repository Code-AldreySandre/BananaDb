import os
import unittest

from core.gerenciador_disco import (
    Schema, serializa, desserializa, inicializa_pagina_zero
)
from core.buffer_pool import CachePaginas
from index.bplus_tree import ArvoreBPlus
from execution.parser import ParserSQL
from execution.catalog import Catalogo
from execution.executor import Executor
from transaction.transaction import GerenciadorTransacoes
from transaction.wal import WALManager

TEST_DB = "test_dados.db"
TEST_WAL = "test_minidb.wal"

class TestBananaDB(unittest.TestCase):
    def setUp(self):
        self.limpar_arquivos()
        inicializa_pagina_zero(db_file=TEST_DB)
        self.cache = CachePaginas(capacidade=8, db_file=TEST_DB)
        self.catalogo = Catalogo()
        self.parser = ParserSQL()
        self.wal_manager = WALManager(wal_file=TEST_WAL)
        self.tx_manager = GerenciadorTransacoes(self.cache, self.wal_manager)
        self.executor = Executor(self.catalogo, self.cache, self.tx_manager)

        ast_create = self.parser.parse("CREATE TABLE aluno (id INT, matricula INT);")
        self.executor.executar(ast_create)

    def tearDown(self):
        self.cache.flush_todas()
        self.limpar_arquivos()

    def limpar_arquivos(self):
        for filename in [TEST_DB, TEST_WAL, "minidb.log"]:
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except PermissionError:
                    pass

    def test_m1_m2_serializacao_e_schema(self):
        esquema = Schema(['INT', 'INT'])
        bytes_reg = serializa(esquema, 10, 20261010)
        self.assertEqual(len(bytes_reg), 8)
        
        val1, val2 = desserializa(esquema, bytes_reg)
        self.assertEqual(val1, 10)
        self.assertEqual(val2, 20261010)

    def test_m3_arvore_bplus_busca_e_split(self):
        arvore = ArvoreBPlus(self.cache, max_chaves=2)
        esquema = Schema(['INT', 'INT'])
        
        for i in range(1, 6):
            b = serializa(esquema, i, 20260000 + i)
            arvore.inserir(i, b)
        self.cache.flush_todas()

        res = arvore.buscar(3)
        self.assertIsNotNone(res)
        self.assertEqual(desserializa(esquema, res), (3, 20260003))

    def test_m4_m5_sql_execution(self):
        cmd_insert = self.parser.parse("INSERT INTO aluno VALUES (1, 20260001);")
        res_insert = self.executor.executar(cmd_insert)
        self.assertEqual(res_insert, "OK 1")

        cmd_select = self.parser.parse("SELECT * FROM aluno WHERE id = 1;")
        res_select = self.executor.executar(cmd_select)
        self.assertIn("1|20260001", res_select)

    def test_m6_transacoes_rollback_e_commit(self):
        self.executor.executar(self.parser.parse("BEGIN;"))
        self.executor.executar(self.parser.parse("INSERT INTO aluno VALUES (99, 20260099);"))
        self.executor.executar(self.parser.parse("ROLLBACK;"))
        
        res_rollback = self.executor.executar(self.parser.parse("SELECT * FROM aluno WHERE id = 99;"))
        self.assertIn("(0 linhas)", res_rollback)

        self.executor.executar(self.parser.parse("BEGIN;"))
        self.executor.executar(self.parser.parse("INSERT INTO aluno VALUES (100, 20260100);"))
        self.executor.executar(self.parser.parse("COMMIT;"))
        
        res_commit = self.executor.executar(self.parser.parse("SELECT * FROM aluno WHERE id = 100;"))
        self.assertIn("100|20260100", res_commit)

    def test_m7_wal_recovery(self):

        self.executor.executar(self.parser.parse("BEGIN;"))
        self.executor.executar(self.parser.parse("INSERT INTO aluno VALUES (50, 20260050);"))
        self.executor.executar(self.parser.parse("COMMIT;"))

        self.executor.executar(self.parser.parse("BEGIN;"))
        self.executor.executar(self.parser.parse("INSERT INTO aluno VALUES (999, 20260999);"))

        novo_cache = CachePaginas(capacidade=8, db_file=TEST_DB)
        novo_catalogo = Catalogo()
        novo_tx_mgr = GerenciadorTransacoes(novo_cache, self.wal_manager)
        novo_executor = Executor(novo_catalogo, novo_cache, novo_tx_mgr)
        
        novo_executor.executar(self.parser.parse("CREATE TABLE aluno (id INT, matricula INT);"))
        self.wal_manager.recuperar(novo_executor)

        res_recuperado = novo_executor.executar(self.parser.parse("SELECT * FROM aluno WHERE id = 50;"))
        self.assertIn("50|20260050", res_recuperado)

        res_nao_recuperado = novo_executor.executar(self.parser.parse("SELECT * FROM aluno WHERE id = 999;"))
        self.assertIn("(0 linhas)", res_nao_recuperado)

if __name__ == "__main__":
    unittest.main()