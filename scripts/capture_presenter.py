"""Captura a janela real com preferências temporárias e recados fictícios."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from janela import TeleprompterWindow


def main():
    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory(prefix="recados-screenshot-") as folder:
        settings = QSettings(str(Path(folder) / "prefs.ini"), QSettings.IniFormat)
        window = TeleprompterWindow(settings=settings, start_polling=False)
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        try:
            window.resize(900, 420)
            window._receive_messages([
                "Marina, um abraço para você e todos que estão acompanhando!",
                "Ana e família, em Recife, recebam nosso abraço!",
            ])
            window._clear_highlight()
            window.show()
            QTest.qWait(100)
            target = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "03-janela-apresentador.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(target)):
                raise RuntimeError("Não foi possível salvar a captura.")
            print("Captura da janela gerada com dados fictícios.")
        finally:
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
