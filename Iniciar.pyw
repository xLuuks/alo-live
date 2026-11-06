"""Abra este arquivo com dois cliques para iniciar o sistema completo."""

import ctypes
from pathlib import Path
import subprocess
import sys

# Dois cliques também utilizam a instalação isolada, quando ela existir.
root = Path(__file__).resolve().parent
venv_python = root / ".venv" / "Scripts" / "pythonw.exe"
if venv_python.exists() and Path(sys.prefix).resolve() != (root / ".venv").resolve():
    subprocess.Popen([str(venv_python), str(Path(__file__).resolve())], cwd=root,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sys.exit(0)

try:
    from inicializador import main
except ImportError:
    ctypes.windll.user32.MessageBoxW(None,
        "Não foi possível carregar os componentes. Na pasta do projeto, execute:\n\npython -m pip install -r requirements.txt",
        "Alô Live · Instalação", 0x10)
    sys.exit(1)

sys.exit(main())
