"""Janela única para abrir e encerrar o ambiente local de produção."""

import logging
import json
import sys
import webbrowser

from PyQt5.QtCore import QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from instancia import SingleInstance
from registros import configure_logging
from sistema import ManagedSystem, PANEL_VERSION, workspace_id
from marca import APP_NAME, ICON_PATH


class Startup(QThread):
    ready = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, system, parent=None):
        super().__init__(parent)
        self.system = system

    def run(self):
        try:
            self.ready.emit(self.system.start_server())
        except Exception as error:
            logging.getLogger(__name__).exception("Falha ao iniciar o sistema.")
            self.failed.emit(str(error))


class Launcher(QWidget):
    def __init__(self, system=None, auto_open=True, start_immediately=True):
        super().__init__()
        self.system = system or ManagedSystem()
        self.auto_open = auto_open
        self.worker = None
        self._closing = False
        self._reply = None
        self.setWindowTitle(f"{APP_NAME} · Iniciar sistema")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumWidth(510)
        self.setStyleSheet("QWidget { background: #131d2f; color: #e8eef8; font-family: Segoe UI; font-size: 14px; } QPushButton { background: #253b51; padding: 12px; border: 1px solid #52627c; border-radius: 6px; } QPushButton:disabled { color: #8291aa; } QLabel { padding: 4px; }")
        layout = QVBoxLayout(self)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ICON_PATH)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(64, 64)
        logo.setStyleSheet("padding: 0;")
        brand.addWidget(logo)
        title = QLabel(f"{APP_NAME}\nComentários ao vivo")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        brand.addWidget(title, 1)
        layout.addLayout(brand)
        self.status = QLabel("Preparando o sistema…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.owner = QLabel()
        self.owner.setWordWrap(True)
        layout.addWidget(self.owner)
        row = QHBoxLayout()
        self.panel_button = QPushButton("Abrir painel")
        self.panel_button.clicked.connect(lambda: webbrowser.open(self.system.base + "/editor"))
        self.window_button = QPushButton("Abrir janela do apresentador")
        self.window_button.clicked.connect(self.open_presenter)
        row.addWidget(self.panel_button)
        row.addWidget(self.window_button)
        layout.addLayout(row)
        self.start_button = QPushButton("Iniciar / reconectar")
        self.start_button.clicked.connect(self.start)
        layout.addWidget(self.start_button)
        self.close_button = QPushButton("Encerrar sistema")
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        help_text = QLabel("Mantenha esta janela aberta durante a transmissão.\nOs recados são salvos automaticamente. Registros de falhas ficam na pasta logs.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("font-size: 12px; color: #aebcd0;")
        layout.addWidget(help_text)
        self.network = QNetworkAccessManager(self)
        self.monitor = QTimer(self)
        self.monitor.setInterval(2000)
        self.monitor.timeout.connect(self.check_connection)
        self.panel_button.setEnabled(False)
        self.window_button.setEnabled(False)
        if start_immediately:
            QTimer.singleShot(0, self.start)

    def activate_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start(self):
        if self._closing or (self.worker is not None and self.worker.isRunning()):
            return
        self.status.setText("Abrindo o servidor…")
        self.system.cancel.clear()
        self.start_button.setEnabled(False)
        self.worker = Startup(self.system, self)
        self.worker.ready.connect(self.ready)
        self.worker.failed.connect(self.failed)
        self.worker.start()

    def ready(self, owned):
        if self._closing:
            return
        self.status.setText("Sistema conectado. O painel e a janela podem ser usados.")
        self.owner.setText("Este inicializador mantém o servidor em execução e o encerra ao fechar." if owned else "O servidor já estava aberto e foi reutilizado. Ele continuará aberto ao fechar este inicializador; encerre-o pelo terminal original.")
        self.close_button.setText("Encerrar sistema" if owned else "Fechar inicializador")
        self.start_button.setEnabled(True)
        self.panel_button.setEnabled(True)
        self.window_button.setEnabled(True)
        self.monitor.start()
        if self.auto_open:
            webbrowser.open(self.system.base + "/editor")
            self.open_presenter()

    def failed(self, message):
        if not self._closing:
            self.status.setText(message)
            self.start_button.setEnabled(True)
            self.panel_button.setEnabled(False)
            self.window_button.setEnabled(False)

    def open_presenter(self):
        try:
            self.system.open_window()
        except OSError:
            logging.getLogger(__name__).exception("Não foi possível abrir a janela do apresentador.")
            self.status.setText("Não foi possível abrir a janela. Confira o registro em logs/inicializador.log.")

    def check_connection(self):
        if self._reply is not None or self._closing:
            return
        reply = self.network.get(QNetworkRequest(QUrl(self.system.base + "/sistema/estado")))
        self._reply = reply
        timeout = QTimer(reply)
        timeout.setSingleShot(True)
        timeout.timeout.connect(reply.abort)
        timeout.start(2000)

        def finished():
            timeout.stop()
            self._reply = None
            if not self._closing:
                connected = reply.error() == QNetworkReply.NoError and reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) == 200
                try:
                    data = json.loads(bytes(reply.readAll()))
                    connected = connected and data.get("app") == "central-de-recados" and data.get("version") == PANEL_VERSION and data.get("workspace") == workspace_id(self.system.root)
                except (ValueError, AttributeError):
                    connected = False
                self.status.setText("Sistema conectado. Pronto para receber e exibir recados." if connected else "O servidor perdeu a conexão. Clique em Iniciar / reconectar para recuperá-la.")
                self.panel_button.setEnabled(connected)
                self.window_button.setEnabled(connected)
            reply.deleteLater()

        reply.finished.connect(finished)

    def closeEvent(self, event):
        self._closing = True
        self.monitor.stop()
        if self._reply is not None:
            self._reply.abort()
        self.system.stop()
        if self.worker is not None:
            self.worker.wait(2500)
        super().closeEvent(event)


def main():
    configure_logging("inicializador")
    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    instance = SingleInstance("inicializador")
    if not instance.acquire():
        return 0
    window = Launcher()
    instance.activate.connect(window.activate_window)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
