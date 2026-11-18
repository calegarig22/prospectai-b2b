"""Configuração centralizada de logging.

Escreve simultaneamente no console e em um arquivo dentro de ``logs/``,
facilitando o acompanhamento da execução e a depuração posterior.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Fuso de BRASÍLIA em TODO o processo (lote, logs, datas) — mesmo na nuvem (que roda em UTC).
# Brasil não usa horário de verão desde 2019, então America/Sao_Paulo = UTC-3 o ano todo.
os.environ["TZ"] = "America/Sao_Paulo"
try:
    time.tzset()                      # aplica o fuso (Linux/Mac; a nuvem é Linux)
except (AttributeError, OSError):     # Windows não tem tzset — ignora (uso local)
    pass

LOGGER_NAME = "prospectai"


def enable_utf8_console() -> None:
    """Garante que o console aceite UTF-8 (texto acentuado, símbolos).

    No Windows, o console legado usa code pages como cp850/cp1252, o que pode
    causar ``UnicodeEncodeError`` ao imprimir caracteres acentuados em português.
    Reconfigurar para UTF-8 (disponível no Python 3.7+) evita esse erro de forma
    segura e idempotente; em sistemas onde já é UTF-8 (Mac/Linux), é inofensivo.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def setup_logger(level: str = "INFO", directory: str | Path = "logs") -> logging.Logger:
    """Cria (ou recupera) o logger da aplicação.

    Gera um arquivo de log com timestamp por execução e também imprime no
    console. Chamadas repetidas não duplicam handlers.
    """
    enable_utf8_console()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))

    # Evita adicionar handlers múltiplas vezes se a função for chamada de novo.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_dir = Path(directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.debug("Logger inicializado. Arquivo de log: %s", log_file)
    return logger
