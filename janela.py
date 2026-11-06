"""Janela transparente de recados, com consultas assíncronas ao painel local."""

from collections import Counter
import json
import logging
import os
import sys
from uuid import uuid4

from PyQt5.QtCore import QEvent, QSettings, Qt, QTimer, QUrl
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QShortcut, QSizeGrip, QSizePolicy, QSlider, QVBoxLayout, QWidget, QMenu,
)
from registros import configure_logging
from marca import APP_NAME, ICON_PATH

log = logging.getLogger(__name__)

COLORS = {"Branco": "white", "Amarelo": "yellow", "Vermelho": "red", "Ciano": "cyan", "Verde": "lime"}


class SettingsWindow(QWidget):
    def __init__(self, teleprompter):
        super().__init__(teleprompter, Qt.Window)
        self.teleprompter = teleprompter
        self.setWindowTitle(f"{APP_NAME} · Configurações")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumWidth(330)
        layout = QVBoxLayout(self)

        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(12, 72)
        self.font_slider.setValue(teleprompter.current_font_size)
        self.font_value = QLabel()
        self.font_slider.valueChanged.connect(teleprompter.update_font_size)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(teleprompter.current_opacity)
        self.opacity_value = QLabel()
        self.opacity_slider.valueChanged.connect(teleprompter.update_opacity)

        self.color_selector = QComboBox()
        for title, color in COLORS.items():
            self.color_selector.addItem(title, color)
        self.color_selector.setCurrentIndex(self.color_selector.findData(teleprompter.current_color))
        self.color_selector.currentIndexChanged.connect(
            lambda index: teleprompter.update_color(self.color_selector.itemData(index)))

        layout.addWidget(self.font_value)
        layout.addWidget(self.font_slider)
        layout.addWidget(QLabel("Cor do texto"))
        layout.addWidget(self.color_selector)
        layout.addWidget(self.opacity_value)
        layout.addWidget(self.opacity_slider)
        hint = QLabel("Arraste pelo texto para mover a janela.\nUse a alça no canto inferior direito para redimensionar.\n\nF2: modo de leitura\nCtrl + / Ctrl −: ajustar fonte\nCtrl 0: fonte padrão\nEsc: sair da leitura; fora dela, fechar\nCtrl Q: fechar a janela")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.sync_values()

    def sync_values(self):
        for control, value in ((self.font_slider, self.teleprompter.current_font_size),
                               (self.opacity_slider, self.teleprompter.current_opacity)):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.font_value.setText(f"Tamanho da fonte: {self.teleprompter.current_font_size} px")
        self.opacity_value.setText(f"Opacidade da janela: {self.teleprompter.current_opacity}%")


class TeleprompterWindow(QWidget):
    def __init__(self, settings=None, endpoint="http://127.0.0.1:5000/mensagens", start_polling=True):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} · Apresentador")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(360, 220)
        self.settings = settings if settings is not None else QSettings("TeleprompterApp", "Teleprompter")
        self.endpoint = endpoint
        self.old_pos = None
        self._closing = False
        self._reply = None
        self._ack_reply = None
        self._client_id = uuid4().hex
        self._ack_failure = False
        self._messages = []
        self._connected = None
        self._highlighted = False
        self.reading_mode = self.settings.value("reading_mode", False, type=bool)
        self.current_font_size = self._preference_int("font_size", 32, 12, 72)
        self.current_opacity = self._preference_int("opacity", 100, 30, 100)
        color = str(self.settings.value("color", "white"))
        self.current_color = color if color in COLORS.values() else "white"

        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.setInterval(400)
        self.geometry_timer.timeout.connect(self.save_preferences)
        self.highlight_timer = QTimer(self)
        self.highlight_timer.setSingleShot(True)
        self.highlight_timer.setInterval(3000)
        self.highlight_timer.timeout.connect(self._clear_highlight)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        self.frame = QFrame()
        self.frame.setObjectName("recadosFrame")
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(12, 10, 12, 6)
        self.status_label = QLabel("Conectando ao painel…")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.label = QLabel("Aguardando recados…")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.scroll.setWidget(self.label)
        layout.addWidget(self.scroll, 1)
        self.overflow_label = QLabel()
        self.overflow_label.setWordWrap(True)
        self.overflow_label.setStyleSheet("color: #ffd18b; background: transparent; font-size: 13px;")
        self.overflow_label.hide()
        layout.addWidget(self.overflow_label)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._update_overflow)
        self.scroll.verticalScrollBar().valueChanged.connect(self._update_overflow)

        self.controls = QWidget()
        buttons = QHBoxLayout(self.controls)
        buttons.setContentsMargins(0, 0, 0, 0)
        for title, callback in (("Configurações", self.abrir_configuracoes),
                                ("Leitura (F2)", self.toggle_reading_mode),
                                ("Minimizar", self.showMinimized), ("Fechar", self.close)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addWidget(self.controls)
        self.grip = QSizeGrip(self)
        layout.addWidget(self.grip, 0, Qt.AlignRight)

        for widget in (self.frame, self.label, self.status_label, self.scroll.viewport()):
            widget.installEventFilter(self)
        for widget in (self, self.frame, self.label, self.status_label, self.scroll.viewport(), self.overflow_label):
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda position, w=widget: self.show_context_menu(w.mapToGlobal(position)))

        self.settings_window = SettingsWindow(self)
        self._shortcuts = []
        for sequence, callback in (("F2", self.toggle_reading_mode),
                                   ("Ctrl+=", lambda: self.update_font_size(self.current_font_size + 2)),
                                   ("Ctrl++", lambda: self.update_font_size(self.current_font_size + 2)),
                                   ("Ctrl+-", lambda: self.update_font_size(self.current_font_size - 2)),
                                   ("Ctrl+0", lambda: self.update_font_size(32)),
                                   ("Ctrl+Q", self.close), ("Esc", self._escape)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        self.resize(800, 400)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except TypeError:
                pass
        self._keep_on_screen()
        self.setWindowOpacity(self.current_opacity / 100.0)
        self._apply_reading_mode()
        self.apply_style()

        self.network = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.atualizar_mensagens)
        self.request_timeout_ms = 2500
        if start_polling:
            self.timer.start()
            QTimer.singleShot(0, self.atualizar_mensagens)

    def _preference_int(self, key, default, minimum, maximum):
        try:
            return max(minimum, min(maximum, int(self.settings.value(key, default))))
        except (ValueError, TypeError):
            return default

    def _keep_on_screen(self):
        screens = QApplication.screens()
        if not screens:
            return
        screen = next((s for s in screens if s.availableGeometry().intersects(self.frameGeometry())), QApplication.primaryScreen())
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        self.move(max(area.left(), min(self.x(), area.right() - self.width() + 1)),
                  max(area.top(), min(self.y(), area.bottom() - self.height() + 1)))

    def save_preferences(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("reading_mode", self.reading_mode)
        self.settings.sync()

    def abrir_configuracoes(self):
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def show_context_menu(self, position):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #152033; color: #edf4ff; border: 1px solid #52627c; padding: 5px; } QMenu::item { padding: 7px 18px; } QMenu::item:selected { background: #304960; }")
        menu.addAction("Configurações", self.abrir_configuracoes)
        menu.addAction("Mostrar controles" if self.reading_mode else "Esconder controles (leitura)", self.toggle_reading_mode)
        menu.addSeparator()
        menu.addAction("Aumentar fonte", lambda: self.update_font_size(self.current_font_size + 2))
        menu.addAction("Diminuir fonte", lambda: self.update_font_size(self.current_font_size - 2))
        menu.addSeparator()
        menu.addAction("Minimizar", self.showMinimized)
        menu.addAction("Fechar", self.close)
        menu.exec_(position)
        menu.deleteLater()

    def activate_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _update_overflow(self, *args):
        bar = self.scroll.verticalScrollBar()
        if not self._messages or bar.maximum() <= 0:
            self.overflow_label.hide()
            return
        above = bar.value() > 1
        below = bar.value() < bar.maximum() - 1
        direction = "acima e abaixo" if above and below else "abaixo" if below else "acima"
        self.overflow_label.setText(f"Há recados {direction} — use a rolagem para ler todos.")
        self.overflow_label.show()

    def update_font_size(self, value):
        self.current_font_size = max(12, min(72, int(value)))
        self.apply_style()
        self.settings.setValue("font_size", self.current_font_size)
        self.settings_window.sync_values()

    def update_color(self, color):
        if color in COLORS.values():
            self.current_color = color
            self.apply_style()
            self.settings.setValue("color", color)

    def update_opacity(self, value):
        self.current_opacity = max(30, min(100, int(value)))
        self.setWindowOpacity(self.current_opacity / 100.0)
        self.settings.setValue("opacity", self.current_opacity)
        self.settings_window.sync_values()

    def apply_style(self):
        border = "#78dfb4" if self._highlighted else "rgba(255, 255, 255, 55)"
        self.frame.setStyleSheet(f"QFrame#recadosFrame {{ background-color: rgba(0, 0, 0, 170); border: 2px solid {border}; border-radius: 10px; }}")
        self.label.setStyleSheet(f"background: transparent; color: {self.current_color}; padding: 12px; font-size: {self.current_font_size}px;")
        self._fit_text()

    def _fit_text(self):
        if hasattr(self, "label"):
            # QLabel.heightForWidth respeita o mínimo anterior. Limpe-o antes
            # de medir para que a área também encolha ao retirar recados.
            self.label.setMinimumHeight(0)
            height = self.label.heightForWidth(max(1, self.scroll.viewport().width()))
            self.label.setMinimumHeight(max(0, height))

    def toggle_reading_mode(self):
        self.reading_mode = not self.reading_mode
        self._apply_reading_mode()
        self.save_preferences()

    def _apply_reading_mode(self):
        self.controls.setVisible(not self.reading_mode)
        self.grip.setVisible(not self.reading_mode)
        self._refresh_status()

    def _escape(self):
        if self.reading_mode:
            self.toggle_reading_mode()
        else:
            self.close()

    def _refresh_status(self):
        if self._connected is False:
            text = "Sem conexão com o painel — os recados podem estar desatualizados. Tentando reconectar…"
            color = "#ffd18b"
        elif self._connected is None:
            text, color = "Conectando ao painel…", "#cbd5e1"
        else:
            count = len(self._messages)
            text = f"{count} {'recado' if count == 1 else 'recados'}"
            if self._highlighted:
                text += " · Novo recado"
            color = "#78dfb4" if self._highlighted else "#cbd5e1"
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"background: transparent; color: {color}; font-size: 13px;")
        self.status_label.setVisible(not self.reading_mode or self._connected is not True or self._highlighted)

    def _clear_highlight(self):
        self._highlighted = False
        self.apply_style()
        self._refresh_status()

    def _receive_messages(self, messages):
        if self._connected is False:
            log.info("Conexão com o painel restabelecida.")
        if messages != self._messages:
            added = Counter(messages) - Counter(self._messages)
            position = self.scroll.verticalScrollBar().value()
            self._messages = list(messages)
            self.label.setText("\n\n".join(messages) if messages else "Aguardando recados…")
            self._fit_text()
            self.scroll.verticalScrollBar().setValue(position)
            if added:
                self._highlighted = True
                self.highlight_timer.start()
            elif not messages:
                self.highlight_timer.stop()
                self._highlighted = False
            self.apply_style()
        self._connected = True
        self._refresh_status()
        self._update_overflow()

    def atualizar_mensagens(self):
        if self._closing or self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self.endpoint))
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
        reply = self.network.get(request)
        self._reply = reply
        timeout = QTimer(reply)
        timeout.setSingleShot(True)
        timeout.timeout.connect(reply.abort)
        timeout.start(self.request_timeout_ms)
        reply.finished.connect(lambda: self._request_finished(reply, timeout))

    def _request_finished(self, reply, timeout):
        timeout.stop()
        if self._reply is reply:
            self._reply = None
        try:
            if self._closing:
                return
            if reply.error() != QNetworkReply.NoError or reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200:
                raise ValueError("Falha na consulta")
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            messages = data.get("mensagens") if isinstance(data, dict) else None
            if not isinstance(messages, list) or any(not isinstance(m, str) for m in messages):
                raise ValueError("Lista de recados inválida")
            self._receive_messages(messages)
            if isinstance(data.get("revision"), str) and isinstance(data.get("delivery_token"), str):
                QTimer.singleShot(0, lambda: self._confirm_receipt(data["revision"], data["delivery_token"]))
        except (ValueError, UnicodeError):
            if self._connected is not False:
                log.warning("Consulta ao painel falhou (rede=%s, HTTP=%s).", int(reply.error()), reply.attribute(QNetworkRequest.HttpStatusCodeAttribute))
            self._connected = False
            self._refresh_status()
        finally:
            reply.deleteLater()

    def _confirm_receipt(self, revision, token):
        if self._closing or self._ack_reply is not None:
            return
        url = QUrl(self.endpoint)
        url.setPath("/apresentador/confirmar")
        url.setQuery("")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setRawHeader(b"X-Delivery-Token", token.encode("utf-8"))
        bar = self.scroll.verticalScrollBar()
        overflow = {"above": bool(self._messages) and bar.value() > 1,
                    "below": bool(self._messages) and bar.value() < bar.maximum() - 1}
        payload = json.dumps({"client_id": self._client_id, "kind": "janela", "revision": revision,
                              "overflow": overflow,
                              "active": self.isVisible() and not self.isMinimized()}).encode("utf-8")
        reply = self.network.post(request, payload)
        self._ack_reply = reply
        timeout = QTimer(reply)
        timeout.setSingleShot(True)
        timeout.timeout.connect(reply.abort)
        timeout.start(self.request_timeout_ms)

        def finished():
            timeout.stop()
            failed = reply.error() != QNetworkReply.NoError or reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200
            if failed and not self._ack_failure and not self._closing:
                log.warning("Falha na confirmação de entrega (HTTP=%s).", reply.attribute(QNetworkRequest.HttpStatusCodeAttribute))
            self._ack_failure = failed
            self._ack_reply = None
            reply.deleteLater()

        reply.finished.connect(finished)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            self._fit_text()
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()
            return True
        if event.type() == QEvent.MouseMove and self.old_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPos()
            return True
        if event.type() == QEvent.MouseButtonRelease:
            self.old_pos = None
        return super().eventFilter(watched, event)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start()

    def closeEvent(self, event):
        self._closing = True
        self.timer.stop()
        self.geometry_timer.stop()
        self.highlight_timer.stop()
        if self._reply is not None:
            self._reply.abort()
        if self._ack_reply is not None:
            self._ack_reply.abort()
        self.save_preferences()
        self.settings_window.close()
        super().closeEvent(event)


if __name__ == "__main__":
    configure_logging("janela")
    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    from instancia import SingleInstance
    instance = SingleInstance("janela")
    if not instance.acquire():
        sys.exit(0)
    window = TeleprompterWindow(endpoint=os.environ.get("TELEPROMPTER_SERVER_URL", "http://127.0.0.1:5000").rstrip("/") + "/mensagens")
    instance.activate.connect(window.activate_window)
    instance.close_requested.connect(window.close)
    window.show()
    sys.exit(app.exec_())
