import os
import logging
import struct

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
    return struct.pack(schema.formato, *valores)

def desserializa(schema, dados_bytes):
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