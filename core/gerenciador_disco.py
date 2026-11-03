import os
import logging
import struct
from collections import OrderedDict

logger = logging.getLogger("minidb")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("minidb.log", mode='a')
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(file_handler)

PAGE_SIZE = 4096
HEADER_SIZE = 16
RECORD_SIZE = 8
DB_FILE = "dados.db"
MAGIC_NUMBER = b'MINIDB26'


class Schema:
    def __init__(self, colunas):
        """
        Deriva o formato do struct a partir de uma lista de tipos de colunas.
        Ex: ['INT', 'INT'] vira '<ii' (little-endian, 2 inteiros de 4 bytes = 8 bytes).
        """
        mapa_tipos = {
            'INT': 'i'
        }
        
        formato = '<'
        for col in colunas:
            if col in mapa_tipos:
                formato += mapa_tipos[col]
            else:
                raise ValueError(f"Tipo de coluna não suportado: {col}")
                
        self.formato = formato
        self.tamanho = struct.calcsize(self.formato)
        
        if self.tamanho != RECORD_SIZE:
            logger.warning(f"Aviso: O tamanho do esquema ({self.tamanho} bytes) difere de RECORD_SIZE ({RECORD_SIZE}).")


def serializa(schema, *valores):
    """Empacota uma quantidade variável de valores com base no esquema."""
    return struct.pack(schema.formato, *valores)


def desserializa(schema, dados_bytes):
    """Desempacota os bytes de volta para uma tupla de valores."""
    return struct.unpack(schema.formato, dados_bytes)


def _calcula_offset(n):
    return n * PAGE_SIZE


def sync(f):
    f.flush()
    os.fsync(f.fileno())


def contagem_paginas(db_file: str = DB_FILE) -> int:
    if not os.path.exists(db_file):
        return 0
    return os.path.getsize(db_file) // PAGE_SIZE


def aloca(db_file: str = DB_FILE) -> int:
    n = contagem_paginas(db_file)
    pagina_vazia = bytearray(PAGE_SIZE)
    escreve_pagina(n, pagina_vazia, db_file=db_file)
    return n


def inicializa_pagina_zero(db_file: str = DB_FILE):
    if contagem_paginas(db_file) == 0:
        pagina_zero = bytearray(PAGE_SIZE)
        struct.pack_into("<8si", pagina_zero, 0, MAGIC_NUMBER, PAGE_SIZE)
        escreve_pagina(0, pagina_zero, db_file=db_file)


def escreve_pagina(n: int, page_bytes: bytearray, db_file: str = DB_FILE):
    if len(page_bytes) != PAGE_SIZE:
        raise ValueError(f"A página deve conter apenas {PAGE_SIZE} bytes.")
    
    modo = 'r+b' if os.path.exists(db_file) else 'w+b'

    with open(db_file, modo) as f:
        offset = _calcula_offset(n)
        f.seek(offset)
        f.write(page_bytes)
        sync(f)


def ler_pagina(n: int, db_file: str = DB_FILE) -> bytearray:
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Banco de dados '{db_file}' não encontrado!")
    
    with open(db_file, 'r+b') as f:
        offset = _calcula_offset(n)
        f.seek(offset)
        page_bytes = f.read(PAGE_SIZE)

        if not page_bytes:
            return bytearray(PAGE_SIZE)
        return bytearray(page_bytes)


class Pagina:
    def __init__(self, numero: int, dados: bytearray):
        self.numero = numero
        self.dados = dados
        self.pin_count = 0
        self.is_dirty = False

    def escrever_slot(self, slot_idx: int, registro_bytes: bytes, tam_registro: int = RECORD_SIZE):
        """Escreve os bytes de um registro no slot indicado, respeitando o HEADER_SIZE."""
        inicio = HEADER_SIZE + (slot_idx * tam_registro)
        fim = inicio + tam_registro
        if fim > PAGE_SIZE:
            raise ValueError("Índice de slot ultrapassa o limite da página.")
        self.dados[inicio:fim] = registro_bytes

    def ler_slot(self, slot_idx: int, tam_registro: int = RECORD_SIZE) -> bytearray:
        """Lê e retorna a fatia de bytes correspondente ao slot indicado."""
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
        """Aloca uma página nova no arquivo de banco e já a retorna fixada no cache."""
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


if __name__ == "__main__":
    inicializa_pagina_zero()

    cache = CachePaginas(capacidade=4)
    esquema_aluno = Schema(['INT', 'INT'])

    pagina = cache.nova_pagina()
    num_pagina = pagina.numero

    id_aluno = 1
    matricula = 20260001
    registro_bytes = serializa(esquema_aluno, id_aluno, matricula)

    pagina.dados[0:HEADER_SIZE] = bytearray(HEADER_SIZE)
    pagina.escrever_slot(0, registro_bytes, esquema_aluno.tamanho)

    cache.liberar_pagina(num_pagina, modificada=True)

    pagina_lida = cache.obter_pagina(num_pagina)
    bytes_recuperados = pagina_lida.ler_slot(0, esquema_aluno.tamanho)
    registro_recuperado = desserializa(esquema_aluno, bytes_recuperados)
    cache.liberar_pagina(num_pagina, modificada=False)

    cache.flush_todas()

    print(f"Registro gravado e recuperado na página {num_pagina}: ID={registro_recuperado[0]}, Matricula={registro_recuperado[1]}")