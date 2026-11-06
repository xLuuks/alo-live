"""Logs locais com limite de tamanho e ocultação de chaves da API."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        message = super().format(record)
        message = re.sub(r"AIza[A-Za-z0-9_-]{15,}", "[chave ocultada]", message)
        return re.sub(r"(?i)((?:api_key|x-goog-api-key|authorization|delivery_token)[\s\"':=]+)[^\s,;\"'}]+",
                      r"\1[ocultado]", message)


def configure_logging(component, directory=None):
    folder = Path(directory or os.environ.get("TELEPROMPTER_LOG_DIR") or Path(__file__).with_name("logs"))
    folder.mkdir(exist_ok=True, parents=True)
    target = folder / f"{component}.log"
    handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(PrivateFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    previous = sys.excepthook

    def report(kind, value, traceback):
        if not issubclass(kind, KeyboardInterrupt):
            logging.getLogger(component).critical("Falha não tratada", exc_info=(kind, value, traceback))
        previous(kind, value, traceback)

    sys.excepthook = report
    return target
