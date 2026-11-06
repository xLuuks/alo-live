"""Fila, histórico, desfazer e cópias de segurança gravados atomicamente."""

from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

log = logging.getLogger(__name__)


class Conflict(ValueError):
    pass


class Recados:
    def __init__(self, path):
        self.path = Path(path)
        self.backup_dir = self.path.parent / "backups"
        self.lock = threading.RLock()
        self.recovery_notice = ""
        self.backup_error = False
        try:
            data = self._read(self.path)
        except (FileNotFoundError, ValueError, UnicodeError):
            candidates = sorted(self.backup_dir.glob("recados-*.json"), reverse=True)
            data = None
            for candidate in candidates:
                try:
                    data = self._read(candidate)
                    break
                except (OSError, ValueError, UnicodeError):
                    continue
            if data is not None:
                if self.path.exists():
                    damaged = self.path.with_name(f"mensagens.corrompido-{self._stamp()}.json")
                    self._atomic_bytes(damaged, self.path.read_bytes())
                self._atomic_json(self.path, data)
                self.recovery_notice = "Os recados foram recuperados da cópia de segurança mais recente disponível. Confira a fila e o histórico."
                log.warning("Arquivo de recados recuperado a partir de uma cópia válida.")
            elif self.path.exists():
                raise ValueError("mensagens.json inválido e nenhuma cópia válida disponível. O arquivo original foi preservado.") from None
            else:
                data = self._empty()
        self.data = data
        self._normalize_orders(self.data)

    @staticmethod
    def _stamp():
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    @staticmethod
    def _empty():
        return {"schema": 2, "revision": uuid4().hex, "entries": [], "history": [], "undo": None}

    @classmethod
    def _read(cls, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and all(isinstance(text, str) for text in data):
            data = dict(cls._empty(), entries=[cls._entry(text) for text in data])
        if not cls._valid(data):
            raise ValueError("Arquivo de recados inválido.")
        return data

    @staticmethod
    def _entry(text, source_id=None, request_id=None):
        return {"id": uuid4().hex, "text": text, "version": 1,
                "source_id": source_id, "request_id": request_id}

    @staticmethod
    def _valid(data):
        def entry(item):
            if not (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and isinstance(item.get("text"), str) and isinstance(item.get("version"), int)
                    and (item.get("source_id") is None or isinstance(item["source_id"], str))):
                return False
            if "order" in item:
                try:
                    Fraction(item["order"])
                except (ValueError, TypeError, ZeroDivisionError):
                    return False
            return True
        if not (isinstance(data, dict) and data.get("schema") == 2
                and isinstance(data.get("revision"), str)
                and isinstance(data.get("entries"), list) and all(entry(e) for e in data["entries"])
                and len({e["id"] for e in data["entries"]}) == len(data["entries"])
                and isinstance(data.get("history"), list)
                and all(isinstance(h, dict) and isinstance(h.get("id"), str)
                        and isinstance(h.get("position"), int) and isinstance(h.get("removed_at"), str)
                        and entry(h.get("entry")) for h in data["history"])):
            return False
        undo = data.get("undo")
        return undo is None or (isinstance(undo, dict) and isinstance(undo.get("id"), str)
                                and isinstance(undo.get("items"), list) and all(entry(e) for e in undo["items"]))

    @staticmethod
    def _normalize_orders(data):
        data.setdefault("undo", None)
        all_entries = data["entries"] + [h["entry"] for h in data["history"]]
        if data["undo"]:
            all_entries += data["undo"]["items"]
        if all("order" in e for e in all_entries):
            return
        virtual = [e["id"] for e in data["entries"]]
        for h in sorted(data["history"], key=lambda item: item["position"]):
            if h["entry"]["id"] not in virtual:
                virtual.insert(max(0, min(h["position"], len(virtual))), h["entry"]["id"])
        for entry in all_entries:
            if entry["id"] not in virtual:
                virtual.append(entry["id"])
        ranks = {ident: str(index) for index, ident in enumerate(virtual)}
        for entry in all_entries:
            entry["order"] = ranks[entry["id"]]

    def snapshot(self):
        with self.lock:
            return deepcopy(self.data)

    def storage_status(self):
        return {"recovery_notice": self.recovery_notice, "backup_error": self.backup_error}

    @staticmethod
    def _atomic_bytes(target, content):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                             prefix=target.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @classmethod
    def _atomic_json(cls, target, data):
        cls._atomic_bytes(target, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def _commit(self, data):
        data["revision"] = uuid4().hex
        self._atomic_json(self.path, data)
        self.data = data
        # A falha de backup não desfaz uma gravação principal já confirmada.
        try:
            self.backup_dir.mkdir(exist_ok=True)
            self._atomic_json(self.backup_dir / f"recados-{self._stamp()}-{uuid4().hex[:8]}.json", data)
            for old in sorted(self.backup_dir.glob("recados-*.json"), reverse=True)[20:]:
                if old.resolve().parent == self.backup_dir.resolve():
                    old.unlink()
            self.backup_error = False
        except OSError:
            if not self.backup_error:
                log.exception("Não foi possível atualizar a cópia de segurança; a fila principal foi salva.")
            self.backup_error = True

    @staticmethod
    def _text(text):
        text = text.strip()
        if not text or len(text) > 5000:
            raise ValueError("O recado deve ter entre 1 e 5.000 caracteres.")
        return text

    @staticmethod
    def _find(data, ident):
        for index, item in enumerate(data["entries"]):
            if item["id"] == ident:
                return index, item
        raise Conflict("Este recado já foi retirado. A fila será atualizada.")

    def sent_ids(self):
        with self.lock:
            entries = self.data["entries"] + [h["entry"] for h in self.data["history"]]
            if self.data["undo"]:
                entries += self.data["undo"]["items"]
            return {e["source_id"] for e in entries if e.get("source_id")}

    def find_request(self, text, source_id=None, request_id=None):
        """Reconhece um envio confirmado mesmo após reiniciar ou retirar da fila."""
        text = self._text(text)
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 100):
            raise ValueError("Identificador de envio inválido.")
        if not request_id:
            return None
        with self.lock:
            entries = self.data["entries"] + [h["entry"] for h in self.data["history"]]
            if self.data["undo"]:
                entries += self.data["undo"]["items"]
            previous = next((e for e in entries if e.get("request_id") == request_id), None)
            if previous and (previous["text"] != text or previous.get("source_id") != source_id):
                raise Conflict("Este envio já foi concluído com outro texto ou origem. Prepare um novo recado.")
            return deepcopy(previous)

    def add(self, text, source_id=None, request_id=None):
        text = self._text(text)
        with self.lock:
            previous = self.find_request(text, source_id, request_id)
            if previous:
                return previous
            entries = self.data["entries"] + [h["entry"] for h in self.data["history"]]
            if self.data["undo"]:
                entries += self.data["undo"]["items"]
            if source_id and source_id in self.sent_ids():
                raise Conflict("Este comentário já foi enviado. Use um recado manual para enviá-lo novamente.")
            data = self.snapshot()
            item = self._entry(text, source_id, request_id)
            item["order"] = str(max((Fraction(e["order"]) for e in entries), default=Fraction(-1)) + 1)
            data["entries"].append(item)
            self._commit(data)
            return item

    def edit(self, ident, text, version):
        text = self._text(text)
        with self.lock:
            data = self.snapshot()
            _, item = self._find(data, ident)
            if item["version"] != version:
                raise Conflict("Este recado foi alterado em outra aba. Confira a versão atual antes de salvar.")
            item.update(text=text, version=version + 1)
            self._commit(data)

    def move(self, ident, direction):
        if direction not in ("cima", "baixo"):
            raise ValueError("Movimento inválido.")
        with self.lock:
            data = self.snapshot()
            index, item = self._find(data, ident)
            target = index + (-1 if direction == "cima" else 1)
            if not 0 <= target < len(data["entries"]):
                return
            data["entries"].pop(index)
            data["entries"].insert(target, item)
            left = Fraction(data["entries"][target - 1]["order"]) if target else None
            right = Fraction(data["entries"][target + 1]["order"]) if target + 1 < len(data["entries"]) else None
            rank = (left + right) / 2 if left is not None and right is not None else left + 1 if left is not None else right - 1
            occupied = {Fraction(h["entry"]["order"]) for h in data["history"]}
            if data["undo"]:
                occupied.update(Fraction(e["order"]) for e in data["undo"]["items"])
            while rank in occupied:
                rank = (left + rank) / 2 if left is not None else rank - 1
            item["order"] = str(rank)
            self._commit(data)

    def remove(self, ident=None, revision=None):
        with self.lock:
            data = self.snapshot()
            if ident is None:
                if revision != data["revision"]:
                    raise Conflict("A fila mudou. Confira os recados e confirme a limpeza novamente.")
                selected = list(enumerate(data["entries"]))
            else:
                selected = [self._find(data, ident)]
            if not selected:
                return
            batch = uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            data["undo"] = {"id": batch, "items": [deepcopy(e) for _, e in selected]}
            for position, item in selected:
                data["history"].insert(0, {"id": uuid4().hex, "entry": item, "position": position,
                                           "removed_at": now, "batch": batch})
            removed = {item["id"] for _, item in selected}
            data["entries"] = [e for e in data["entries"] if e["id"] not in removed]
            data["history"] = data["history"][:200]
            self._commit(data)

    @staticmethod
    def _restore(data, items):
        active = {e["id"] for e in data["entries"]}
        for item in items:
            if item["id"] in active:
                raise Conflict("Este recado já está na fila.")
            item = deepcopy(item)
            item["version"] += 1
            data["entries"].append(item)
            active.add(item["id"])
        data["entries"].sort(key=lambda e: Fraction(e["order"]))
        restored = {e["id"] for e in items}
        data["history"] = [h for h in data["history"] if h["entry"]["id"] not in restored]
        if data["undo"]:
            data["undo"]["items"] = [e for e in data["undo"]["items"] if e["id"] not in restored]
            if not data["undo"]["items"]:
                data["undo"] = None

    def restore(self, history_id):
        with self.lock:
            data = self.snapshot()
            history = next((h for h in data["history"] if h["id"] == history_id), None)
            if history is None:
                raise Conflict("Este recado já foi restaurado ou não está mais no histórico.")
            self._restore(data, [history["entry"]])
            self._commit(data)

    def undo_remove(self, batch_id):
        with self.lock:
            data = self.snapshot()
            if not data["undo"] or data["undo"]["id"] != batch_id:
                raise Conflict("A última retirada mudou. Confira a fila antes de desfazer.")
            self._restore(data, data["undo"]["items"])
            self._commit(data)
