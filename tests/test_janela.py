"""Verificações da janela Qt sem alterar preferências do usuário."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QSettings, Qt, QTimer, QPoint
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from janela import TeleprompterWindow
from instancia import SingleInstance, send_command
from inicializador import Launcher
from sistema import ManagedSystem
from unittest.mock import patch


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.settings = QSettings(str(Path(self.temp.name) / "prefs.ini"), QSettings.IniFormat)
        self.windows = []

    def window(self, **kwargs):
        window = TeleprompterWindow(settings=self.settings, start_polling=False, **kwargs)
        self.windows.append(window)
        window.show()
        self.app.processEvents()
        return window

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, condition, timeout=2000):
        deadline = time.monotonic() + timeout / 1000
        while not condition():
            if time.monotonic() > deadline:
                self.fail("Tempo esgotado aguardando evento Qt")
            QTest.qWait(10)

    def test_all_messages_plain_text_and_new_message_highlight(self):
        window = self.window()
        window._receive_messages(["Maria pede um abraço", "<b>João</b>"])
        self.assertEqual(window.label.text(), "Maria pede um abraço\n\n<b>João</b>")
        self.assertEqual(window.label.textFormat(), Qt.PlainText)
        self.assertTrue(window._highlighted)
        window._clear_highlight()
        window._receive_messages(["<b>João</b>", "Maria pede um abraço"])
        self.assertFalse(window._highlighted, "Reordenar não deve parecer um novo recado")
        window.highlight_timer.setInterval(30)
        window._receive_messages(["<b>João</b>", "Maria pede um abraço", "Novo"])
        self.wait_until(lambda: not window._highlighted)
        window._receive_messages([])
        self.assertEqual(window.label.text(), "Aguardando recados…")

    def test_reading_mode_retains_warning_and_escape_restores_controls(self):
        window = self.window()
        window._receive_messages(["Recado"])
        window._clear_highlight()
        window.toggle_reading_mode()
        self.assertTrue(window.controls.isHidden())
        self.assertTrue(window.grip.isHidden())
        self.assertTrue(window.status_label.isHidden())
        window._connected = False
        window._refresh_status()
        self.assertFalse(window.status_label.isHidden())
        self.assertIn("desatualizados", window.status_label.text())
        window._escape()
        self.assertFalse(window.reading_mode)
        self.assertFalse(window.controls.isHidden())
        self.assertTrue(window.isVisible())

    def test_geometry_and_preferences_restored(self):
        window = self.window()
        window.resize(620, 340)
        window.move(25, 35)
        window.update_font_size(48)
        window.update_color("cyan")
        window.update_opacity(80)
        window.toggle_reading_mode()
        window.close()
        reopened = self.window()
        self.assertEqual(reopened.size(), window.size())
        self.assertEqual(reopened.pos(), window.pos())
        self.assertEqual(reopened.current_font_size, 48)
        self.assertEqual(reopened.current_color, "cyan")
        self.assertEqual(reopened.current_opacity, 80)
        self.assertTrue(reopened.reading_mode)

    def test_font_shortcuts_and_slider_stay_in_sync(self):
        window = self.window()
        window.activateWindow()
        self.app.processEvents()
        QTest.keyClick(window, Qt.Key_Equal, Qt.ControlModifier)
        self.assertEqual(window.current_font_size, 34)
        self.assertEqual(window.settings_window.font_slider.value(), 34)
        QTest.keyClick(window, Qt.Key_0, Qt.ControlModifier)
        self.assertEqual(window.current_font_size, 32)
        QTest.keyClick(window, Qt.Key_F2)
        self.assertTrue(window.reading_mode)
        QTest.keyClick(window, Qt.Key_Escape)
        self.assertFalse(window.reading_mode)
        window.update_font_size(100)
        self.assertEqual(window.current_font_size, 72)
        window.update_font_size(0)
        self.assertEqual(window.current_font_size, 12)

    def test_long_messages_remain_available_by_scrolling(self):
        window = self.window()
        window.resize(500, 240)
        messages = [f"Pessoa {i}: um abraço para toda a equipe!" for i in range(30)]
        window._receive_messages(messages)
        self.app.processEvents()
        self.assertIn(messages[-1], window.label.text())
        self.assertGreater(window.scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(window.overflow_label.isHidden())
        self.assertIn("abaixo", window.overflow_label.text())
        window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertIn("acima", window.overflow_label.text())
        window._receive_messages([])
        self.app.processEvents()
        self.assertTrue(window.overflow_label.isHidden())

    def test_removing_read_messages_shrinks_content_and_clears_scrolling(self):
        for scrolled_to_bottom in (False, True):
            with self.subTest(scrolled_to_bottom=scrolled_to_bottom):
                window = self.window()
                window.resize(600, 400)
                messages = [f"Pessoa {i}: um abraço para toda a equipe!" for i in range(20)]
                window._receive_messages(messages)
                self.wait_until(lambda: window.scroll.verticalScrollBar().maximum() > 0)
                QTest.qWait(30)
                bar = window.scroll.verticalScrollBar()
                original_height = window.label.height()
                if scrolled_to_bottom:
                    bar.setValue(bar.maximum())

                window._receive_messages(messages[-6:])
                self.wait_until(lambda: window.label.height() < original_height)
                self.assertGreater(bar.maximum(), 0, "Recados que ainda não cabem precisam de rolagem")
                self.assertEqual(window.label.text(), "\n\n".join(messages[-6:]))

                window._receive_messages(messages[-1:])
                self.wait_until(lambda: bar.maximum() == 0)
                self.assertEqual(bar.value(), 0)
                self.assertLessEqual(window.label.height(), window.scroll.viewport().height())
                self.assertTrue(window.overflow_label.isHidden())
                self.assertEqual(window.label.text(), messages[-1])

                # Novos recados devem poder aumentar a área novamente.
                window._receive_messages(messages)
                self.wait_until(lambda: bar.maximum() > 0)
                self.assertFalse(window.overflow_label.isHidden())

    def test_smaller_font_and_wider_window_release_unused_text_height(self):
        window = self.window()
        window.resize(430, 400)
        window.update_font_size(60)
        window._receive_messages(["Um abraço para todos que acompanham a transmissão ao vivo!"])
        self.wait_until(lambda: window.scroll.verticalScrollBar().maximum() > 0)
        QTest.qWait(30)
        original_height = window.label.height()
        window.update_font_size(20)
        window.resize(800, 400)
        self.wait_until(lambda: window.scroll.verticalScrollBar().maximum() == 0)
        self.assertLess(window.label.height(), original_height)
        self.assertTrue(window.overflow_label.isHidden())

    def test_context_menu_restores_controls_without_keyboard(self):
        window = self.window()
        window.toggle_reading_mode()
        failures = []

        def choose_controls():
            menu = QApplication.activePopupWidget()
            if menu is None:
                failures.append("Menu não abriu")
                return
            action = next((a for a in menu.actions() if a.text() == "Mostrar controles"), None)
            if action is None:
                failures.append("Ação ausente")
            else:
                action.trigger()
            menu.close()

        QTimer.singleShot(50, choose_controls)
        window.show_context_menu(window.mapToGlobal(QPoint(20, 20)))
        self.assertFalse(failures)
        self.assertFalse(window.reading_mode)
        self.assertFalse(window.controls.isHidden())

    def test_single_instance_activates_existing_component(self):
        name = "teste-" + uuid4().hex
        first = SingleInstance(name)
        second = SingleInstance(name)
        activations = []
        closings = []
        first.activate.connect(lambda: activations.append(True))
        first.close_requested.connect(lambda: closings.append(True))
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            self.wait_until(lambda: bool(activations))
            send_command(name, "close", -1)
            QTest.qWait(30)
            self.assertEqual(closings, [])
            send_command(name, "close", os.getpid())
            self.wait_until(lambda: bool(closings))
        finally:
            first.server.close()
            second.server.close()

    def test_launcher_startup_and_close_with_no_extra_windows(self):
        system = ManagedSystem()
        with patch.object(system, "start_server", return_value=True), patch.object(system, "stop") as stop:
            launcher = Launcher(system=system, auto_open=False)
            launcher.show()
            try:
                self.wait_until(lambda: launcher.panel_button.isEnabled())
                self.assertTrue(launcher.window_button.isEnabled())
                self.assertIn("encerra", launcher.owner.text())
                launcher.close()
                stop.assert_called_once()
            finally:
                if launcher.isVisible():
                    launcher.close()
                if launcher.worker:
                    launcher.worker.wait(2000)
                launcher.deleteLater()

    def test_launcher_startup_error_is_visible_and_allows_retry(self):
        system = ManagedSystem()
        with patch.object(system, "start_server", side_effect=RuntimeError("Servidor de outra versão")), patch.object(system, "stop"), self.assertLogs("inicializador", level="ERROR"):
            launcher = Launcher(system=system, auto_open=False)
            launcher.show()
            try:
                self.wait_until(lambda: launcher.start_button.isEnabled() and "outra versão" in launcher.status.text())
                self.assertFalse(launcher.panel_button.isEnabled())
                self.assertFalse(launcher.window_button.isEnabled())
            finally:
                launcher.close()
                if launcher.worker:
                    launcher.worker.wait(2000)
                launcher.deleteLater()

    def test_async_connection_timeout_validation_and_recovery(self):
        state = {"delay": .2, "body": {"mensagens": ["Maria", "João"]}, "status": 200, "calls": 0, "acks": []}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                state["calls"] += 1
                delay, body, status = state["delay"], state["body"], state["status"]
                time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    self.wfile.write(json.dumps(body).encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state["acks"].append((payload, self.headers.get("X-Delivery-Token")))
                self.send_response(200)
                self.end_headers()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        window = self.window(endpoint=f"http://127.0.0.1:{httpd.server_port}/mensagens")
        heartbeat = []
        timer = QTimer(window)
        timer.setInterval(10)
        timer.timeout.connect(lambda: heartbeat.append(True))
        timer.start()
        try:
            window.atualizar_mensagens()
            first = window._reply
            window.atualizar_mensagens()
            self.assertIs(window._reply, first, "Não deve sobrepor requisições")
            self.wait_until(lambda: window._reply is None)
            self.assertTrue(window._connected)
            self.assertGreater(len(heartbeat), 5, "A interface precisa continuar respondendo enquanto aguarda HTTP")
            self.assertEqual(state["calls"], 1)

            for body, status in (({"erro": "inválido"}, 200), ({"mensagens": [123]}, 200), ({"mensagens": []}, 503)):
                state.update(delay=0, body=body, status=status)
                window.atualizar_mensagens()
                self.wait_until(lambda: window._reply is None)
                self.assertFalse(window._connected)
                self.assertEqual(window.label.text(), "Maria\n\nJoão")

            state.update(delay=.2, body={"mensagens": ["Recuperado"]}, status=200)
            window.request_timeout_ms = 30
            window.atualizar_mensagens()
            self.wait_until(lambda: window._reply is None)
            self.assertFalse(window._connected)
            state["delay"] = 0
            state["body"].update(revision="revision-1", delivery_token="signed-token")
            window.request_timeout_ms = 1000
            window.atualizar_mensagens()
            self.wait_until(lambda: window._reply is None)
            self.assertTrue(window._connected)
            self.assertEqual(window.label.text(), "Recuperado")
            self.wait_until(lambda: len(state["acks"]) == 1)
            self.assertEqual(state["acks"][0][0]["revision"], "revision-1")
            self.assertEqual(state["acks"][0][0]["kind"], "janela")
            self.assertEqual(state["acks"][0][1], "signed-token")
            self.assertEqual(state["acks"][0][0]["overflow"], {"above": False, "below": False})

            state["body"]["mensagens"] = [f"Recado longo {index} para a equipe" for index in range(30)]
            window.resize(500, 240)
            window.atualizar_mensagens()
            self.wait_until(lambda: len(state["acks"]) >= 2)
            self.assertEqual(state["acks"][-1][0]["overflow"], {"above": False, "below": True})
            window.scroll.verticalScrollBar().setValue(window.scroll.verticalScrollBar().maximum())
            window.atualizar_mensagens()
            self.wait_until(lambda: len(state["acks"]) >= 3)
            self.assertEqual(state["acks"][-1][0]["overflow"], {"above": True, "below": False})

            state["delay"] = .2
            window.abrir_configuracoes()
            window.atualizar_mensagens()
            window.close()
            self.assertIsNone(window._reply)
            self.assertFalse(window.timer.isActive())
            self.assertFalse(window.settings_window.isVisible())
        finally:
            timer.stop()
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
