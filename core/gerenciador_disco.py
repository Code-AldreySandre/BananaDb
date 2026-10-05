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

def contagem_paginas():
    if not os.path.exists(DB_FILE):
        return 0
    return os.path.getsize(DB_FILE) // PAGE_SIZE

def aloca():
    n = contagem_paginas()
    pagina_vazia = bytearray(PAGE_SIZE)
    escreve_pagina(n, pagina_vazia)
    return n

def inicializa_pagina_zero():
    if contagem_paginas() == 0:
        pagina_zero = bytearray(PAGE_SIZE)
        struct.pack_into(f"<8si", pagina_zero, 0, MAGIC_NUMBER, PAGE_SIZE)
        escreve_pagina(0, pagina_zero)

def escreve_pagina(n, page_bytes):
    if len(page_bytes) != PAGE_SIZE:
        raise ValueError(f"A página deve conter apenas {PAGE_SIZE} bytes.")
    
    modo = 'r+b' if os.path.exists(DB_FILE) else 'w+b'

    with open(DB_FILE, modo) as f:
        offset = _calcula_offset(n)
        f.seek(offset)
        f.write(page_bytes)     
        sync(f)
        
def ler_pagina(n):
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError("Banco de dados não encontrado!")
    
    with open(DB_FILE, 'r+b') as f:
        offset = _calcula_offset(n)
        f.seek(offset)
        page_bytes = f.read(PAGE_SIZE)

        if not page_bytes:
            return bytearray(PAGE_SIZE)
        return bytearray(page_bytes)

if __name__ == "__main__":
    inicializa_pagina_zero()
    
    esquema_aluno = Schema(['INT', 'INT'])
    
    num_pagina = aloca()
    pagina = ler_pagina(num_pagina)
    
    id_aluno = 1
    matricula = 20260001
    
    registro_bytes = serializa(esquema_aluno, id_aluno, matricula)
    
    cabecalho_bytes = bytearray(HEADER_SIZE) 
    pagina[0:HEADER_SIZE] = cabecalho_bytes
    
    inicio_slot = HEADER_SIZE
    fim_slot = HEADER_SIZE + RECORD_SIZE
    pagina[inicio_slot:fim_slot] = registro_bytes
    
    escreve_pagina(num_pagina, pagina)
    pagina_lida = ler_pagina(num_pagina)
    
    registro_recuperado = desserializa(esquema_aluno, pagina_lida[inicio_slot:fim_slot])
    print(f"Registro gravado e recuperado na página {num_pagina}: ID={registro_recuperado[0]}, Matricula={registro_recuperado[1]}")