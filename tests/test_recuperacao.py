import os
import signal
import subprocess
import sys
import tempfile

from core.gerenciador_disco import inicializa_pagina_zero
from core.buffer_pool import CachePaginas
from execution.catalog import Catalogo
from execution.parser import ParserSQL
from execution.executor import Executor
from transaction.wal import WALManager
from transaction.transaction import GerenciadorTransacoes


def rodar_sql(db_path: str, comandos: str) -> str:
    res = subprocess.run(
        [sys.executable, "main.py", db_path],
        input=comandos,
        text=True,
        capture_output=True,
        check=True,
    )
    return res.stdout


def test_kill9_no_meio_do_commit_faz_redo():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "redo.db")
        rodar_sql(db_path, "CREATE TABLE aluno (id INT, matricula INT);\n")

        script_filho = f"""
import time
from core.gerenciador_disco import inicializa_pagina_zero
from core.buffer_pool import CachePaginas
from execution.catalog import Catalogo
from execution.parser import ParserSQL
from execution.executor import Executor
from transaction.wal import WALManager
from transaction.transaction import GerenciadorTransacoes

db_path = {db_path!r}
inicializa_pagina_zero(db_path)
cache = CachePaginas(capacidade=8, db_file=db_path)
cat = Catalogo(cache)
wal = WALManager(f"{{db_path}}.wal")
tx = GerenciadorTransacoes(cache, wal)
exe = Executor(cat, cache, tx)
parser = ParserSQL()

exe.executar(parser.parse("BEGIN;"))
exe.executar(parser.parse("INSERT INTO aluno VALUES (42, 20260042);"))
wal.log_commit(tx.transacao_atual.tx_id)
print("PRONTO_PARA_KILL", flush=True)
time.sleep(30)
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", script_filho],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        linha = proc.stdout.readline().strip()
        assert linha == "PRONTO_PARA_KILL", proc.stderr.read()

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()

        saida = rodar_sql(db_path, "SELECT * FROM aluno WHERE id = 42;\n")
        assert "42|20260042" in saida and "(1 linha)" in saida, saida
        print("[OK] kill -9 no meio do commit recuperado via REDO")


def test_kill9_antes_do_commit_com_split_faz_undo():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "undo.db")
        rodar_sql(
            db_path,
            "CREATE TABLE aluno (id INT, matricula INT);\n"
            "INSERT INTO aluno VALUES (1, 1001);\n",
        )

        script_filho = f"""
import time
from core.gerenciador_disco import inicializa_pagina_zero
from core.buffer_pool import CachePaginas
from execution.catalog import Catalogo
from execution.parser import ParserSQL
from execution.executor import Executor
from transaction.wal import WALManager
from transaction.transaction import GerenciadorTransacoes

db_path = {db_path!r}
inicializa_pagina_zero(db_path)
cache = CachePaginas(capacidade=4, db_file=db_path)
cat = Catalogo(cache)
wal = WALManager(f"{{db_path}}.wal")
tx = GerenciadorTransacoes(cache, wal)
exe = Executor(cat, cache, tx)
parser = ParserSQL()

exe.arvores["aluno"].max_chaves_folha = 2
exe.arvores["aluno"].max_chaves_interno = 2

exe.executar(parser.parse("BEGIN;"))
for i in range(2, 10):
    exe.executar(parser.parse(f"INSERT INTO aluno VALUES ({{i}}, {{1000 + i}});"))
print("PRONTO_PARA_KILL", flush=True)
time.sleep(30)
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", script_filho],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        linha = proc.stdout.readline().strip()
        assert linha == "PRONTO_PARA_KILL", proc.stderr.read()

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()

        saida = rodar_sql(db_path, "SELECT * FROM aluno;\n")
        assert saida.strip() == "1|1001\n(1 linha)", saida
        print("[OK] kill -9 antes do commit com split revertido via UNDO")


def test_linha_truncada_no_wal_ignorada():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "torn.db")
        rodar_sql(db_path, "CREATE TABLE aluno (id INT, matricula INT);\n")

        wal_path = f"{db_path}.wal"
        with open(wal_path, "w") as f:
            f.write("BEGIN|1\n")
            f.write("INSERT|1|aluno|7|07000000e8030000\n")
            f.write("COMMIT|1")  # sem \n (simulando torn write de COMMIT|10)

        saida = rodar_sql(db_path, "SELECT * FROM aluno;\n")
        assert saida.strip() == "(0 linhas)", saida
        print("[OK] Linha truncada sem quebra de linha ignorada no WAL")


def test_rollback_preserva_autocommit_e_desfaz_split():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "rollback.db")
        inicializa_pagina_zero(db_path)
        cache = CachePaginas(capacidade=4, db_file=db_path)
        cat = Catalogo(cache)
        wal = WALManager(f"{db_path}.wal")
        tx = GerenciadorTransacoes(cache, wal)
        exe = Executor(cat, cache, tx)
        parser = ParserSQL()

        exe.executar(parser.parse("CREATE TABLE aluno (id INT, matricula INT);"))
        exe.arvores["aluno"].max_chaves_folha = 2
        exe.arvores["aluno"].max_chaves_interno = 2

        exe.executar(parser.parse("INSERT INTO aluno VALUES (10, 2010);"))

        exe.executar(parser.parse("BEGIN;"))
        for i in range(11, 20):
            exe.executar(parser.parse(f"INSERT INTO aluno VALUES ({i}, {2000 + i});"))
        exe.executar(parser.parse("ROLLBACK;"))

        saida = exe.executar(parser.parse("SELECT * FROM aluno;"))
        assert saida.strip() == "10|2010\n(1 linha)", saida
        print("[OK] ROLLBACK desfez splits e preservou autocommit anterior")


if __name__ == "__main__":
    test_kill9_no_meio_do_commit_faz_redo()
    test_kill9_antes_do_commit_com_split_faz_undo()
    test_linha_truncada_no_wal_ignorada()
    test_rollback_preserva_autocommit_e_desfaz_split()
    print("\nTodos os testes de recuperação passaram!")