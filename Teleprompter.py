"""Painel local de produção para comentários e recados do apresentador."""

import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for
from recados import Conflict, Recados
from youtube_chat import YouTubeChats
from registros import configure_logging
from sistema import PANEL_VERSION, workspace_id
from marca import APP_NAME

if __name__ == "__main__":
    configure_logging("servidor")

app = Flask(__name__)
app.config.update(TRUSTED_HOSTS=["127.0.0.1", "localhost"],
                  MAX_CONTENT_LENGTH=65_536, MAX_FORM_MEMORY_SIZE=65_536, MAX_FORM_PARTS=20)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
queue = Recados(Path(os.environ.get("TELEPROMPTER_DATA_DIR") or Path(__file__).resolve().parent) / "mensagens.json")
csrf_token = secrets.token_urlsafe(32)
youtube = YouTubeChats()
receipts = {}
receipt_lock = threading.Lock()


def delivery_token(revision):
    return hmac.new(csrf_token.encode(), revision.encode(), hashlib.sha256).hexdigest()


def delivery_status(revision):
    now = time.monotonic()
    with receipt_lock:
        expired = [key for key, receipt in receipts.items() if now - receipt["time"] > 30]
        for key in expired:
            del receipts[key]
        return [{"kind": r["kind"], "active": r["active"],
                 "overflow": r.get("overflow"),
                 "age": round(now - r["time"], 1), "current": r["revision"] == revision}
                for r in receipts.values()]


@app.before_request
def proteger_alteracoes():
    if request.method == "POST" and request.endpoint != "confirmar_recebimento":
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not secrets.compare_digest(supplied.encode(), csrf_token.encode()):
            return jsonify(error="Página expirada. Recarregue o painel; seu rascunho será preservado."), 403


@app.after_request
def sem_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


@app.errorhandler(413)
def requisicao_grande(error):
    return jsonify(error="Envio muito grande. O recado deve ter até 5.000 caracteres."), 413


@app.errorhandler(ValueError)
def erro_validacao(error):
    return jsonify(error=str(error)), 409 if isinstance(error, Conflict) else 400


@app.errorhandler(OSError)
def erro_gravacao(error):
    app.logger.error("Falha ao gravar os recados: %s", type(error).__name__)
    return jsonify(error="Não foi possível salvar. Confira a permissão de gravação e tente novamente."), 500


@app.get("/")
def inicio():
    return redirect(url_for("editor"))


@app.get("/editor")
def editor():
    return render_template("editor.html", csrf_token=csrf_token,
                           panel_version=PANEL_VERSION,
                           key_available=bool(os.environ.get("YOUTUBE_API_KEY")))


@app.get("/teleprompter")
def teleprompter():
    return render_template("teleprompter.html")


@app.get("/mensagens")
def obter_mensagens():
    data = queue.snapshot()
    return jsonify(mensagens=[e["text"] for e in data["entries"]], revision=data["revision"],
                   delivery_token=delivery_token(data["revision"]))


@app.get("/recados")
def obter_recados():
    data = queue.snapshot()
    if data["undo"]:
        data["undo"] = {"id": data["undo"]["id"], "count": len(data["undo"]["items"])}
    data["storage"] = queue.storage_status()
    data["delivery"] = delivery_status(data["revision"])
    return jsonify(data)


@app.post("/apresentador/confirmar")
def confirmar_recebimento():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Confirmação inválida.")
    revision = data.get("revision", "")
    supplied = request.headers.get("X-Delivery-Token", "")
    if not isinstance(revision, str) or len(revision) > 100 or not hmac.compare_digest(supplied.encode(), delivery_token(revision).encode()):
        return jsonify(error="Confirmação inválida."), 403
    client = data.get("client_id")
    if not isinstance(client, str) or not 1 <= len(client) <= 100 or data.get("kind") not in ("janela", "navegador"):
        raise ValueError("Confirmação inválida.")
    overflow = data.get("overflow")
    if overflow is not None and (not isinstance(overflow, dict)
            or any(type(overflow.get(key)) is not bool for key in ("above", "below"))):
        raise ValueError("Estado da rolagem inválido.")
    with receipt_lock:
        if client not in receipts and len(receipts) >= 20:
            oldest = min(receipts, key=lambda ident: receipts[ident]["time"])
            del receipts[oldest]
        receipts[client] = {"time": time.monotonic(), "revision": revision,
                            "overflow": {key: overflow[key] for key in ("above", "below")} if overflow is not None else None,
                            "kind": data["kind"], "active": data.get("active") is True}
    return jsonify(ok=True)


@app.post("/adicionar")
def adicionar():
    item = queue.add(request.form.get("mensagem", ""), request_id=request.form.get("request_id") or None)
    return jsonify(ok=True, id=item["id"])


@app.post("/recados/<ident>/editar")
def editar(ident):
    queue.edit(ident, request.form.get("novo_texto", ""), int(request.form.get("version", "0")))
    return jsonify(ok=True)


@app.post("/recados/<ident>/lido")
def remover(ident):
    queue.remove(ident)
    return jsonify(ok=True)


@app.post("/recados/<ident>/mover/<direcao>")
def mover(ident, direcao):
    queue.move(ident, direcao)
    return jsonify(ok=True)


@app.post("/limpar")
def limpar():
    queue.remove(revision=request.form.get("revision"))
    return jsonify(ok=True)


@app.post("/historico/<ident>/restaurar")
def restaurar(ident):
    queue.restore(ident)
    return jsonify(ok=True)


@app.post("/historico/desfazer")
def desfazer_retirada():
    queue.undo_remove(request.form.get("batch_id", ""))
    return jsonify(ok=True)


@app.get("/sistema/estado")
def estado_sistema():
    return jsonify(app="central-de-recados", version=PANEL_VERSION, pid=os.getpid(),
                   workspace=workspace_id(Path(__file__).resolve().parent))


@app.get("/youtube/estado")
def estado_youtube():
    data = youtube.snapshot()
    sent = queue.sent_ids()
    for comment in data["comments"]:
        comment["sent"] = comment["sent"] or comment["id"] in sent
    return jsonify(data)


@app.post("/youtube/conectar")
def conectar_youtube():
    key = request.form.get("api_key", "").strip() or os.environ.get("YOUTUBE_API_KEY", "")
    youtube.connect([request.form.get("live1", ""), request.form.get("live2", "")],
                    key, int(request.form.get("interval", "30")))
    return jsonify(ok=True)


@app.post("/youtube/<int:number>/reconectar")
def reconectar_youtube(number):
    youtube.reconnect(number, request.form.get("url", ""),
                      request.form.get("api_key", "").strip() or os.environ.get("YOUTUBE_API_KEY", ""),
                      int(request.form.get("interval", "30")))
    return jsonify(ok=True)


@app.post("/youtube/desconectar")
def desconectar_youtube():
    youtube.disconnect()
    return jsonify(ok=True)


@app.post("/youtube/<int:number>/desconectar")
def desconectar_canal(number):
    if number not in (1, 2):
        raise ValueError("Transmissão inválida.")
    youtube.disconnect(number)
    return jsonify(ok=True)


@app.post("/youtube/enviar")
def enviar_youtube():
    ident = request.form.get("id", "")
    text = request.form.get("mensagem", "")
    request_id = request.form.get("request_id") or None
    # O mesmo bloqueio cobre a consulta e o envio: duas tentativas simultâneas
    # reconhecem o mesmo registro, mesmo que o comentário já tenha saído do buffer.
    with youtube.lock:
        previous = queue.find_request(text, source_id=ident, request_id=request_id)
        if previous:
            return jsonify(ok=True, id=previous["id"], replayed=True)
        item = youtube.send(ident, text, lambda value: queue.add(value, source_id=ident, request_id=request_id))
        return jsonify(ok=True, id=item["id"], replayed=False)


if __name__ == "__main__":
    port = int(os.environ.get("TELEPROMPTER_PORT", "5000"))
    print(f"{APP_NAME} · Painel do operador: http://127.0.0.1:{port}/editor")
    print(f"{APP_NAME} · Tela do apresentador: http://127.0.0.1:{port}/teleprompter")
    try:
        app.run(host="127.0.0.1", port=port, debug=False)
    finally:
        youtube.disconnect()
