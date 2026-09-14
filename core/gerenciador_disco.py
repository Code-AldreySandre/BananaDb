import os 
import logging

logger = logging.getLogger("minidb")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("minidb.log", mode='a')
formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

PAGE_SIZE = 4096
HEADER_SIZE = 16
RECORD_SIZE = 8
DB_FILE = "dados.db"

def escreve_pagina(n,page_bytes):
    if len(page_bytes) != PAGE_SIZE:
        raise ValueError(f"A página deve conter apenas {PAGE_SIZE} bytes.")
    modo = 'r+b' if os.path.exists(DB_FILE) else 'w+b'

    with open(DB_FILE, modo) as f:
        offset = n*PAGE_SIZE
        f.seek(offset)
        f.write(page_bytes)

def ler_pagina(n):
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError("Banco de dados não encontrado!")
    
    with open(DB_FILE, 'r+b') as f:
        offset = n*PAGE_SIZE
        f.seek(offset)
        page_bytes = f.read(PAGE_SIZE)

        if not page_bytes:
            return bytearray(PAGE_SIZE)
        return page_bytes


if __name__ == "__main__":
    pagina = bytearray(PAGE_SIZE)
    registro_teste = b'ABCDEFGH'

    inicio_slot = HEADER_SIZE
    fim_slot = HEADER_SIZE + RECORD_SIZE
    pagina[inicio_slot:fim_slot] = registro_teste

    escreve_pagina(2, pagina)
    print("Pagina 2 gravada com sucesso.")
