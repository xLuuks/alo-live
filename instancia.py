"""Uma instância por componente, com ativação por comunicação local do Qt."""

import hashlib
import json
import os
from pathlib import Path

from PyQt5.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket


def instance_name(component):
    root = str(Path(__file__).resolve().parent).lower()
    return "recados-" + hashlib.sha256((root + ":" + component).encode()).hexdigest()[:24]


def send_command(component, command="activate", pid=None):
    socket = QLocalSocket()
    socket.connectToServer(instance_name(component))
    if not socket.waitForConnected(250):
        socket.abort()
        return False
    socket.write(json.dumps({"command": command, "pid": pid}).encode() + b"\n")
    socket.flush()
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    socket.readyRead.connect(loop.quit)
    socket.disconnected.connect(loop.quit)
    if not socket.bytesAvailable() and socket.state() != QLocalSocket.UnconnectedState:
        timer.start(500)
        loop.exec_()
    timer.stop()
    socket.disconnectFromServer()
    return True


class SingleInstance(QObject):
    activate = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, component, parent=None):
        super().__init__(parent)
        self.component = component
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept)

    def acquire(self):
        if send_command(self.component):
            return False
        return self.server.listen(instance_name(self.component))

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket):
        if not socket.canReadLine():
            return
        try:
            data = json.loads(bytes(socket.readLine()))
            socket.write(b"ok\n")
            socket.flush()
            if data.get("command") == "activate":
                self.activate.emit()
            elif data.get("command") == "close" and data.get("pid") == os.getpid():
                self.close_requested.emit()
        except (ValueError, AttributeError):
            pass
        socket.disconnectFromServer()
