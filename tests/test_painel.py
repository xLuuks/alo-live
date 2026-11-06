import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import Teleprompter as server
from recados import Conflict, Recados
from youtube_chat import YouTubeChats
from test_projeto import comment, slot


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "mensagens.json"
        self.path.write_text("[]", encoding="utf-8")
        self.patches = [patch.object(server, "queue", Recados(self.path)),
                        patch.object(server, "youtube", YouTubeChats()),
                        patch.object(server, "receipts", {}), patch.dict(os.environ, {"YOUTUBE_API_KEY": ""})]
        for item in self.patches:
            item.start()
        self.client = server.app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def post(self, path, **data):
        return self.client.post(path, data=data, headers={"X-CSRF-Token": server.csrf_token})

    def entries(self):
        return server.queue.snapshot()["entries"]

    def test_pages_and_assets(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        for route in ("/editor", "/teleprompter", "/static/painel.js", "/static/painel.css", "/static/apresentador.js", "/static/apresentador.css"):
            with self.client.get(route) as response:
                self.assertEqual(response.status_code, 200, route)

    def test_manual_workflow_history_and_restore_after_restart(self):
        first = self.post("/adicionar", mensagem="Primeira").json["id"]
        second = self.post("/adicionar", mensagem="Segunda").json["id"]
        self.post(f"/recados/{second}/mover/cima")
        self.post(f"/recados/{second}/editar", novo_texto="Editada", version=1)
        self.assertEqual([e["text"] for e in self.entries()], ["Editada", "Primeira"])
        self.post(f"/recados/{first}/lido")
        history = server.queue.snapshot()["history"][0]
        server.queue = Recados(self.path)
        self.assertEqual(self.post(f"/historico/{history['id']}/restaurar").status_code, 200)
        self.assertEqual([e["id"] for e in self.entries()], [second, first])
        self.assertEqual(self.post(f"/historico/{history['id']}/restaurar").status_code, 409)
        self.post("/limpar", revision=server.queue.snapshot()["revision"])
        self.assertEqual(self.entries(), [])
        self.assertEqual(len(server.queue.snapshot()["history"]), 2)

    def test_stable_ids_do_not_remove_wrong_entry_after_queue_changes(self):
        first = server.queue.add("Primeira")["id"]
        second = server.queue.add("Segunda")["id"]
        third = server.queue.add("Terceira")["id"]
        self.post(f"/recados/{first}/lido")
        self.assertEqual(self.post(f"/recados/{second}/lido").status_code, 200)
        self.assertEqual([e["id"] for e in self.entries()], [third])
        self.assertEqual(self.post(f"/recados/{second}/lido").status_code, 409)
        self.assertEqual([e["id"] for e in self.entries()], [third])

    def test_stale_edits_and_clear_are_rejected(self):
        item = server.queue.add("Original")
        revision = server.queue.snapshot()["revision"]
        self.assertEqual(self.post(f"/recados/{item['id']}/editar", novo_texto="Alterada", version=1).status_code, 200)
        self.assertEqual(self.post(f"/recados/{item['id']}/editar", novo_texto="Desatualizada", version=1).status_code, 409)
        self.assertEqual(self.entries()[0]["text"], "Alterada")
        self.assertEqual(self.post("/limpar", revision=revision).status_code, 409)
        self.assertEqual(len(self.entries()), 1)

    def test_manual_retry_is_idempotent(self):
        first = self.post("/adicionar", mensagem="Recado", request_id="retry-1")
        second = self.post("/adicionar", mensagem="Recado", request_id="retry-1")
        self.assertEqual(first.json["id"], second.json["id"])
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.post("/adicionar", mensagem="Outro texto", request_id="retry-1").status_code, 409)

    def test_selected_comment_and_persisted_sent_mark(self):
        current = slot()
        server.youtube.slots[1] = current
        server.youtube._ingest(current, [comment()])
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.post("/youtube/enviar", id="abcdefghijk:m1", mensagem="Maria pede um abraço").status_code, 200)
        self.assertEqual(self.post("/youtube/enviar", id="abcdefghijk:m1", mensagem="Duplicada").status_code, 400)
        # Um coletor novo não permite duplicar o envio já salvo na fila/histórico.
        server.youtube = YouTubeChats()
        server.youtube.slots[1] = current
        server.youtube._ingest(current, [comment()])
        self.assertTrue(self.client.get("/youtube/estado").json["comments"][0]["sent"])
        self.assertEqual(self.post("/youtube/enviar", id="abcdefghijk:m1", mensagem="Duplicada").status_code, 409)
        self.assertEqual(len(self.entries()), 1)

    def test_youtube_retry_recovers_after_lost_response_restart_and_removal(self):
        current = slot()
        server.youtube.slots[1] = current
        server.youtube._ingest(current, [comment(), comment("m2")])
        data = {"id": "abcdefghijk:m1", "mensagem": "Maria pede um abraço", "request_id": "youtube-retry-1"}
        first = self.post("/youtube/enviar", **data)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json["replayed"])
        retry = self.post("/youtube/enviar", **data)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json["replayed"])
        self.assertEqual(retry.json["id"], first.json["id"])
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.post("/youtube/enviar", **dict(data, mensagem="Outro texto")).status_code, 409)
        self.assertEqual(self.post("/youtube/enviar", **dict(data, id="abcdefghijk:m2")).status_code, 409)
        server.queue.remove(first.json["id"])
        server.queue = Recados(self.path)
        server.youtube = YouTubeChats()  # O comentário já não precisa estar no buffer.
        retry = self.post("/youtube/enviar", **data)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json["replayed"])
        self.assertEqual(self.entries(), [], "Repetir um envio não restaura um recado já lido")

    def test_delivery_exposes_validated_scroll_state(self):
        feed = self.client.get("/mensagens").json
        payload = {"revision": feed["revision"], "client_id": "window-1", "kind": "janela", "active": True}
        headers = {"X-Delivery-Token": feed["delivery_token"]}
        for overflow in ({"above": False, "below": True}, {"above": True, "below": False}, {"above": False, "below": False}):
            response = self.client.post("/apresentador/confirmar", json=dict(payload, overflow=overflow), headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get("/recados").json["delivery"][0]["overflow"], overflow)
        for invalid in (True, {"above": "false", "below": True}, {"above": False}):
            self.assertEqual(self.client.post("/apresentador/confirmar", json=dict(payload, overflow=invalid), headers=headers).status_code, 400)

    def test_local_hosts_payload_limit_and_security_headers(self):
        self.assertEqual(self.client.get("/mensagens", base_url="http://example.com").status_code, 400)
        self.assertEqual(self.client.get("/mensagens", base_url="http://localhost:5000").status_code, 200)
        large = self.post("/adicionar", mensagem="x" * 70_000)
        self.assertEqual(large.status_code, 413)
        self.assertIn("muito grande", large.json["error"])
        self.assertEqual(self.entries(), [])
        response = self.client.get("/editor")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_failed_save_does_not_confirm_or_drop_existing_file(self):
        current = slot()
        server.youtube.slots[1] = current
        server.youtube._ingest(current, [comment()])
        with patch("recados.os.replace", side_effect=PermissionError("simulado")):
            response = self.post("/youtube/enviar", id="abcdefghijk:m1", mensagem="Recado")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.entries(), [])
        self.assertEqual(json.loads(self.path.read_text()), [])
        self.assertFalse(server.youtube.snapshot()["comments"][0]["sent"])
        self.assertEqual(list(Path(self.temp.name).glob("*.tmp")), [])

    def test_history_failure_preserves_queue(self):
        item = server.queue.add("Recado")
        with patch("recados.os.replace", side_effect=PermissionError("simulado")):
            self.assertEqual(self.post(f"/recados/{item['id']}/lido").status_code, 500)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(server.queue.snapshot()["history"], [])

    def test_delivery_requires_real_acknowledgment_and_current_revision(self):
        self.assertEqual(self.client.get("/recados").json["delivery"], [])
        feed = self.client.get("/mensagens").json
        payload = {"revision": feed["revision"], "client_id": "window-1", "kind": "janela", "active": True}
        self.assertEqual(self.client.post("/apresentador/confirmar", json=payload).status_code, 403)
        ack = self.client.post("/apresentador/confirmar", json=payload, headers={"X-Delivery-Token": feed["delivery_token"]})
        self.assertEqual(ack.status_code, 200)
        self.assertTrue(self.client.get("/recados").json["delivery"][0]["current"])
        server.queue.add("Novo")
        self.assertFalse(self.client.get("/recados").json["delivery"][0]["current"])
        with patch("Teleprompter.time.monotonic", return_value=next(iter(server.receipts.values()))["time"] + 31):
            self.assertEqual(self.client.get("/recados").json["delivery"], [])

    def test_missing_token_and_invalid_input(self):
        self.assertEqual(self.client.post("/adicionar", data={"mensagem": "x"}).status_code, 403)
        self.assertEqual(self.post("/adicionar", mensagem="  ").status_code, 400)
        self.assertEqual(self.post("/youtube/conectar", live1="abcdefghijk").status_code, 400)


class StoreTests(unittest.TestCase):
    def test_migration_preserves_text_and_generates_stable_ids(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mensagens.json"
            path.write_text(json.dumps(["Maria", "João"]), encoding="utf-8")
            store = Recados(path)
            before = store.snapshot()["entries"]
            store.add("Ana")
            after = Recados(path).snapshot()["entries"]
            self.assertEqual(after[:2], before)
            self.assertEqual([e["text"] for e in after], ["Maria", "João", "Ana"])

    def test_bad_storage_is_not_silently_replaced(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mensagens.json"
            path.write_text('{"invalid": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                Recados(path)
            self.assertEqual(path.read_text(), '{"invalid": true}')


if __name__ == "__main__":
    unittest.main()
