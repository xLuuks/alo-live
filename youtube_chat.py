"""Leitura de até dois chats públicos pela YouTube Data API v3."""

from collections import OrderedDict
from datetime import datetime, timezone
import re
import threading
import logging
from urllib.parse import parse_qs, urlparse

import requests


class YouTubeError(Exception):
    def __init__(self, message, retry=False):
        super().__init__(message)
        self.retry = retry


def video_id(value):
    value = value.strip()
    if re.fullmatch(r"[\w-]{11}", value, flags=re.ASCII):
        return value
    url = urlparse(value if "://" in value else "https://" + value)
    host = (url.hostname or "").lower()
    parts = url.path.strip("/").split("/")
    result = ""
    if host in ("youtu.be", "www.youtu.be"):
        result = parts[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "www.youtube-nocookie.com"):
        if url.path == "/watch":
            result = parse_qs(url.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in ("live", "embed", "shorts"):
            result = parts[1]
    if not re.fullmatch(r"[\w-]{11}", result, flags=re.ASCII):
        raise ValueError("Cole o link da transmissão ou o ID do vídeo (11 caracteres).")
    return result


class YouTubeChats:
    def __init__(self):
        self.lock = threading.RLock()
        self.slots = {}
        self.comments = OrderedDict()
        self.seen = OrderedDict()

    def _get(self, resource, key, **params):
        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/" + resource,
                params=params, headers={"X-Goog-Api-Key": key}, timeout=(5, 15),
            )
            data = response.json()
        except (requests.RequestException, ValueError):
            raise YouTubeError("Sem resposta válida do YouTube. Tentando reconectar…", retry=True) from None
        if not isinstance(data, dict):
            raise YouTubeError("Resposta inesperada do YouTube.", retry=True)
        if not response.ok or "error" in data:
            error = data.get("error", {})
            errors = error.get("errors", []) if isinstance(error, dict) else []
            reason = errors[0].get("reason", "") if errors else ""
            messages = {
                "quotaExceeded": "Cota diária da API esgotada. Retome quando a cota for renovada.",
                "dailyLimitExceeded": "Limite diário da API atingido.",
                "keyInvalid": "Chave da API inválida.",
                "accessNotConfigured": "Ative a YouTube Data API v3 no projeto da chave.",
                "liveChatEnded": "Esta transmissão encerrou o chat.",
                "liveChatDisabled": "O chat desta transmissão está desativado.",
                "liveChatNotFound": "Chat não encontrado. Confira a transmissão.",
                "forbidden": "A chave não tem permissão para acessar este chat.",
                "rateLimitExceeded": "Consultas muito frequentes. Aguardando para tentar novamente…",
            }
            retry = response.status_code == 429 or response.status_code >= 500 or reason == "rateLimitExceeded"
            raise YouTubeError(messages.get(reason, "Não foi possível acessar o YouTube. Confira a chave, suas restrições e a transmissão."), retry)
        return data

    def connect(self, urls, key, interval=30):
        key = key.strip()
        if not key:
            raise ValueError("Informe sua chave da YouTube Data API v3.")
        ids = [(i, video_id(url)) for i, url in enumerate(urls, 1) if url.strip()]
        if not ids:
            raise ValueError("Informe pelo menos uma transmissão do YouTube.")
        if len({v for _, v in ids}) != len(ids):
            raise ValueError("Os dois campos precisam apontar para transmissões diferentes.")
        if interval not in (5, 15, 30, 60):
            raise ValueError("Intervalo de atualização inválido.")
        with self.lock:
            for number, vid in ids:
                other = self.slots.get(3 - number)
                desired = dict(ids)
                if other and other["video_id"] == vid and desired.get(3 - number, vid) == vid:
                    raise ValueError("Esta transmissão já está conectada no outro campo.")
            # Validar todos os campos antes de interromper qualquer coletor.
            for number, vid in ids:
                self._start(number, vid, key, interval)

    def _start(self, number, vid, key, interval):
        old = self.slots.get(number)
        same = old is not None and old["video_id"] == vid
        if old:
            old["stop"].set()
        if old and not same:
            self.comments = OrderedDict((i, c) for i, c in self.comments.items() if c["slot"] != number)
            self.seen = OrderedDict((i, value) for i, value in self.seen.items() if not i.startswith(old["video_id"] + ":"))
        slot = dict(old) if same else {"slot": number, "video_id": vid,
            "channel": f"Canal {number}", "title": "", "updated_at": None}
        slot.update(state="conectando", detail="Conectando ao chat…", stop=threading.Event(),
                    interval=interval, _key=key)
        self.slots[number] = slot
        threading.Thread(target=self._worker, args=(slot, key), daemon=True).start()

    def reconnect(self, number, url="", key="", interval=30):
        if number not in (1, 2) or interval not in (5, 15, 30, 60):
            raise ValueError("Transmissão ou intervalo inválido.")
        with self.lock:
            old = self.slots.get(number)
            vid = video_id(url) if url.strip() else old["video_id"] if old else None
            key = key.strip() or (old.get("_key", "") if old else "")
            if not vid or not key:
                raise ValueError("Preencha o link e a chave nas configurações para conectar este canal.")
            other = self.slots.get(3 - number)
            if other and other["video_id"] == vid:
                raise ValueError("Esta transmissão já está conectada no outro campo.")
            self._start(number, vid, key, interval)

    def disconnect(self, number=None):
        with self.lock:
            for slot in self.slots.values():
                if number is None or slot["slot"] == number:
                    slot["stop"].set()
                    slot.update(state="desconectado", detail="Coleta interrompida pelo operador.")

    def _update(self, slot, **values):
        with self.lock:
            if self.slots.get(slot["slot"]) is slot and not slot["stop"].is_set():
                slot.update(values)

    def _ingest(self, slot, items):
        with self.lock:
            if self.slots.get(slot["slot"]) is not slot or slot["stop"].is_set():
                return
            for item in items:
                snippet = item.get("snippet", {})
                text = snippet.get("displayMessage")
                ident = item.get("id")
                if not ident or not text or not snippet.get("hasDisplayContent", True):
                    continue
                ident = slot["video_id"] + ":" + ident
                if ident in self.seen:
                    continue
                self.seen[ident] = True
                while len(self.seen) > 10000:
                    self.seen.popitem(last=False)
                self.comments[ident] = {
                    "id": ident, "slot": slot["slot"], "channel": slot["channel"],
                    "author": item.get("authorDetails", {}).get("displayName", "Espectador"),
                    "text": text, "published_at": snippet.get("publishedAt", ""), "sent": False,
                }
                while len(self.comments) > 1000:
                    self.comments.popitem(last=False)

    def _worker(self, slot, key):
        stop = slot["stop"]
        chat_id = slot.get("_chat_id")
        token = slot.get("_token")
        backoff = 15
        while not stop.is_set():
            try:
                if chat_id is None:
                    data = self._get("videos", key, part="snippet,liveStreamingDetails", id=slot["video_id"])
                    items = data.get("items", [])
                    if not items:
                        raise YouTubeError("Vídeo não encontrado ou sem acesso público.")
                    video = items[0]
                    chat_id = video.get("liveStreamingDetails", {}).get("activeLiveChatId")
                    if not chat_id:
                        raise YouTubeError("Sem chat ativo. Confira se a live já começou e o chat está habilitado.")
                    self._update(slot, channel=video["snippet"].get("channelTitle", slot["channel"]), title=video["snippet"].get("title", ""))
                    self._update(slot, _chat_id=chat_id)
                if stop.is_set():
                    return
                params = {"liveChatId": chat_id, "part": "id,snippet,authorDetails", "maxResults": 2000}
                if token:
                    params["pageToken"] = token
                data = self._get("liveChat/messages", key, **params)
                self._ingest(slot, data.get("items", []))
                token = data.get("nextPageToken")
                self._update(slot, _token=token)
                now = datetime.now(timezone.utc).isoformat()
                wait = max(slot["interval"], float(data.get("pollingIntervalMillis", 5000)) / 1000)
                self._update(slot, state="conectado", detail=f"Atualização a cada {wait:g} segundos.", updated_at=now)
                backoff = 15
                if data.get("offlineAt") or not token:
                    self._update(slot, state="encerrado", detail="Chat encerrado. Comentários recebidos continuam disponíveis.")
                    return
                stop.wait(wait)
            except YouTubeError as exc:
                logging.getLogger(__name__).warning("Transmissão %s: %s", slot["slot"], exc)
                self._update(slot, state="reconectando" if exc.retry else "erro", detail=str(exc))
                if not exc.retry:
                    return
                stop.wait(max(slot["interval"], backoff))
                backoff = min(backoff * 2, 120)
            except (KeyError, TypeError, ValueError, AttributeError):
                logging.getLogger(__name__).exception("Resposta inesperada na transmissão %s.", slot["slot"])
                self._update(slot, state="erro", detail="Resposta inesperada do YouTube. Conecte novamente para tentar.")
                return

    def snapshot(self):
        with self.lock:
            slots = [{k: v for k, v in slot.items() if k != "stop" and not k.startswith("_")} for slot in self.slots.values()]
            comments = sorted((dict(c) for c in self.comments.values()), key=lambda c: (c["published_at"], c["id"]), reverse=True)
            return {"sources": slots, "comments": comments}

    def send(self, ident, text, save):
        with self.lock:
            comment = self.comments.get(ident)
            if comment is None:
                raise ValueError("Comentário indisponível. Selecione outro comentário.")
            if comment["sent"]:
                raise ValueError("Este comentário já foi enviado ao apresentador.")
            result = save(text)
            comment["sent"] = True
            return result
