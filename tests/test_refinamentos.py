from itertools import permutations
import json
import logging
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from recados import Conflict, Recados
from registros import PrivateFormatter
from sistema import ManagedSystem, workspace_id


class StorageRefinements(unittest.TestCase):
    def test_restore_preserves_order_for_all_permutations_and_restart(self):
        for order in permutations(range(3)):
            with self.subTest(order=order), TemporaryDirectory() as folder:
                path = Path(folder) / "mensagens.json"
                path.write_text(json.dumps(["A", "B", "C"]), encoding="utf-8")
                store = Recados(path)
                store.remove(revision=store.snapshot()["revision"])
                history = list(reversed(store.snapshot()["history"]))
                store = Recados(path)
                for index in order:
                    store.restore(history[index]["id"])
                self.assertEqual([e["text"] for e in store.snapshot()["entries"]], ["A", "B", "C"])

    def test_undo_clear_restores_more_than_history_limit(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mensagens.json"
            texts = [f"Recado {n}" for n in range(205)]
            path.write_text(json.dumps(texts), encoding="utf-8")
            store = Recados(path)
            store.remove(revision=store.snapshot()["revision"])
            self.assertEqual(len(store.snapshot()["history"]), 200)
            store = Recados(path)
            store.undo_remove(store.snapshot()["undo"]["id"])
            self.assertEqual([e["text"] for e in store.snapshot()["entries"]], texts)
            self.assertIsNone(store.snapshot()["undo"])

    def test_stale_undo_rejected_and_manual_moves_preserved(self):
        with TemporaryDirectory() as folder:
            store = Recados(Path(folder) / "mensagens.json")
            a, b, c = [store.add(text)["id"] for text in "ABC"]
            store.remove(b)
            history = store.snapshot()["history"][0]["id"]
            old_undo = store.snapshot()["undo"]["id"]
            store.move(c, "cima")
            store.restore(history)
            self.assertEqual([e["text"] for e in store.snapshot()["entries"]], ["C", "A", "B"])
            store.remove(a)
            with self.assertRaises(Conflict):
                store.undo_remove(old_undo)
            store.undo_remove(store.snapshot()["undo"]["id"])
            self.assertEqual([e["text"] for e in store.snapshot()["entries"]], ["C", "A", "B"])

    def test_corrupt_and_missing_primary_recover_latest_valid_backup(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mensagens.json"
            store = Recados(path)
            store.add("A")
            store.add("B")
            (store.backup_dir / "recados-99999999-invalid.json").write_text("invalid", encoding="utf-8")
            path.write_text("arquivo danificado", encoding="utf-8")
            recovered = Recados(path)
            self.assertEqual([e["text"] for e in recovered.snapshot()["entries"]], ["A", "B"])
            self.assertTrue(recovered.recovery_notice)
            originals = list(Path(folder).glob("mensagens.corrompido-*.json"))
            self.assertEqual(originals[0].read_text(), "arquivo danificado")
            path.unlink()
            recovered = Recados(path)
            self.assertEqual([e["text"] for e in recovered.snapshot()["entries"]], ["A", "B"])

    def test_backup_failure_does_not_report_saved_message_as_failed(self):
        with TemporaryDirectory() as folder:
            store = Recados(Path(folder) / "mensagens.json")
            atomic = Recados._atomic_json

            def write(target, data):
                if target.parent == store.backup_dir:
                    raise PermissionError("simulação de falha do backup")
                atomic(target, data)

            with patch.object(Recados, "_atomic_json", side_effect=write):
                store.add("Mensagem confirmada")
            self.assertTrue(store.backup_error)
            self.assertEqual(Recados(store.path).snapshot()["entries"][0]["text"], "Mensagem confirmada")
            store.add("Outra")
            self.assertFalse(store.backup_error)

    def test_backup_retention_is_bounded(self):
        with TemporaryDirectory() as folder:
            store = Recados(Path(folder) / "mensagens.json")
            for i in range(23):
                store.add(str(i))
            self.assertEqual(len(list(store.backup_dir.glob("recados-*.json"))), 20)


class LauncherTests(unittest.TestCase):
    def test_reuses_compatible_server_without_stopping_it(self):
        system = ManagedSystem()
        health = {"app": "central-de-recados", "version": "5", "workspace": workspace_id(system.root), "pid": 123}
        with patch.object(system, "health", return_value=health), patch.object(system, "_spawn") as spawn:
            self.assertFalse(system.start_server())
            system.stop()
            spawn.assert_not_called()

    def test_other_version_or_workspace_not_terminated(self):
        system = ManagedSystem()
        for health in ({"app": "central-de-recados", "version": "3"},
                       {"app": "central-de-recados", "version": "5", "workspace": "outra"}):
            with patch.object(system, "health", return_value=health), patch.object(system, "_spawn") as spawn:
                with self.assertRaises(RuntimeError):
                    system.start_server()
                spawn.assert_not_called()

    def test_cancelled_start_does_not_spawn(self):
        system = ManagedSystem()
        system.cancel.set()
        with patch.object(system, "_spawn") as spawn:
            with self.assertRaises(RuntimeError):
                system.start_server()
            spawn.assert_not_called()

    def test_window_not_spawned_twice(self):
        system = ManagedSystem()
        process = Mock()
        process.poll.return_value = None
        with patch("instancia.send_command", return_value=False), patch.object(system, "_spawn", return_value=process) as spawn:
            system.open_window()
            system.open_window()
            spawn.assert_called_once_with("janela.py")

    def test_real_server_start_health_reuse_and_shutdown(self):
        with TemporaryDirectory(prefix="recados-system-test-") as folder:
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                port = port_socket.getsockname()[1]
            import os
            environment = {"TELEPROMPTER_DATA_DIR": folder, "TELEPROMPTER_LOG_DIR": str(Path(folder) / "logs")}
            first = ManagedSystem(port=port)
            second = ManagedSystem(port=port)
            with patch.dict(os.environ, environment):
                try:
                    self.assertTrue(first.start_server())
                    self.assertEqual(first.health()["version"], "5")
                    self.assertFalse(second.start_server())
                    second.stop()
                    self.assertTrue(first.health())
                    process = first.server_process
                    first.stop()
                    self.assertIsNotNone(process.poll())
                    self.assertIsNone(first.health())
                finally:
                    first.stop()
                    second.stop()


class LogTests(unittest.TestCase):
    def test_key_hidden_in_file_formatter(self):
        record = logging.LogRecord("test", logging.ERROR, "", 0,
                                   "api_key=secret-123 X-Goog-Api-Key: another-token AIza12345678901234567890", (), None)
        text = PrivateFormatter().format(record)
        for secret in ("secret-123", "another-token", "AIza12345678901234567890"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
