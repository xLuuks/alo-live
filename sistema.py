"""Processos iniciados pelo gerenciador; encerra somente os filhos que ele abriu."""

import hashlib
import logging
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import threading
import time

import requests
from processos import child_pids

log = logging.getLogger(__name__)
PANEL_VERSION = "5"


def workspace_id(root):
    return hashlib.sha256(str(Path(root).resolve()).lower().encode()).hexdigest()[:16]


class ManagedSystem:
    def __init__(self, root=None, port=5000):
        self.root = Path(root) if root else Path(__file__).resolve().parent
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.server_process = None
        self.window_process = None
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.session = requests.Session()
        self.session.trust_env = False

    @property
    def owns_server(self):
        return self.server_process is not None and self.server_process.poll() is None

    def health(self):
        try:
            response = self.session.get(self.base + "/sistema/estado", timeout=(.3, .5))
            data = response.json()
            if response.status_code == 200 and isinstance(data, dict):
                return data
        except (requests.RequestException, ValueError):
            pass
        return None

    def _validate(self, health):
        if health.get("app") != "central-de-recados" or health.get("version") != PANEL_VERSION:
            raise RuntimeError("Há um servidor de outra versão aberto. Feche o terminal antigo com Ctrl+C e clique em Iniciar novamente.")
        if health.get("workspace") != workspace_id(self.root):
            raise RuntimeError("Outra pasta do projeto está usando a porta 5000. Encerre esse servidor antes de abrir esta instalação.")

    def _spawn(self, filename):
        folder = Path(os.environ.get("TELEPROMPTER_LOG_DIR") or self.root / "logs")
        folder.mkdir(exist_ok=True, parents=True)
        environment = os.environ.copy()
        environment["TELEPROMPTER_PORT"] = str(self.port)
        environment["TELEPROMPTER_SERVER_URL"] = self.base
        with (folder / "processos.log").open("ab") as stream:
            return subprocess.Popen([sys.executable, "-B", str(self.root / filename)], cwd=self.root,
                                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                    env=environment,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def start_server(self, timeout=12):
        if self.cancel.is_set():
            raise RuntimeError("Abertura cancelada.")
        health = self.health()
        if health:
            self._validate(health)
            return self.owns_server
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=.3):
                raise RuntimeError("A porta 5000 já está em uso por um servidor sem identificação compatível. Feche o servidor antigo e tente novamente.")
        except (ConnectionRefusedError, TimeoutError, OSError):
            pass
        with self.lock:
            if self.cancel.is_set():
                raise RuntimeError("Abertura cancelada.")
            self.server_process = self._spawn("Teleprompter.py")
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline and not self.cancel.is_set():
                health = self.health()
                if health:
                    self._validate(health)
                    if health.get("pid") not in [self.server_process.pid, *child_pids(self.server_process.pid)]:
                        self._stop_process(self.server_process)
                        self.server_process = None
                        return False
                    log.info("Servidor iniciado pelo gerenciador.")
                    return True
                if self.server_process.poll() is not None:
                    raise RuntimeError("O servidor não conseguiu iniciar. Confira logs/servidor.log e logs/processos.log; o arquivo de recados foi preservado.")
                self.cancel.wait(.15)
            raise RuntimeError("O servidor não ficou disponível a tempo. Confira os registros em logs/ e tente novamente.")
        except Exception:
            self.stop_server()
            raise

    def open_window(self):
        from instancia import send_command
        if send_command("janela"):
            return
        with self.lock:
            if self.window_process is None or self.window_process.poll() is not None:
                self.window_process = self._spawn("janela.py")

    @staticmethod
    def _stop_process(process):
        if process is None or process.poll() is not None:
            return
        for pid in reversed(child_pids(process.pid)):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def stop_server(self):
        with self.lock:
            self._stop_process(self.server_process)
            self.server_process = None

    def stop(self):
        self.cancel.set()
        with self.lock:
            if self.window_process is not None and self.window_process.poll() is None:
                from instancia import send_command
                for pid in reversed([self.window_process.pid, *child_pids(self.window_process.pid)]):
                    send_command("janela", "close", pid)
                try:
                    self.window_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._stop_process(self.window_process)
            self.window_process = None
            self.stop_server()
