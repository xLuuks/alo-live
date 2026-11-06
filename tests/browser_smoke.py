"""Teste opcional em Chrome/Edge: requer websockets (pip install websockets)."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir
import threading
import time

import requests
from flask import jsonify, request
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Teleprompter as server
from recados import Recados
from sistema import ManagedSystem


@contextmanager
def browser_workspace():
    temporary = TemporaryDirectory(prefix="teleprompter-browser-")
    folder = Path(temporary.name).resolve()
    if folder.parent != Path(gettempdir()).resolve() or not folder.name.startswith("teleprompter-browser-"):
        raise RuntimeError("Pasta temporária de teste fora do destino esperado.")
    try:
        yield str(folder)
    finally:
        # O Windows pode liberar os arquivos do perfil um pouco depois do Chrome.
        # Tente novamente por um prazo curto, sem ocultar falhas persistentes.
        deadline = time.monotonic() + 5
        while True:
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)


def close_browser(process, folder):
    if process.poll() is not None:
        return
    try:
        port, endpoint = (Path(folder) / "DevToolsActivePort").read_text().splitlines()[:2]
        # Encerre apenas o navegador deste perfil, permitindo que ele feche os
        # renderizadores e libere o armazenamento antes de remover os arquivos.
        with connect(f"ws://127.0.0.1:{port}{endpoint}", proxy=None,
                     open_timeout=2, close_timeout=2) as browser_socket:
            browser_socket.send(json.dumps({"id": 1, "method": "Browser.close"}))
    except (OSError, ValueError, TimeoutError, ConnectionClosed):
        pass
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        # Se o fechamento normal falhar, encerre a árvore deste processo filho.
        ManagedSystem._stop_process(process)


def check_browser(browser, folder, base, manual_only=False, refinements=False):
    process = subprocess.Popen([str(browser), "--headless=new", "--no-first-run",
        "--no-default-browser-check", "--disable-gpu", "--no-sandbox", "--remote-debugging-port=0",
        "--user-data-dir=" + folder, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        port_file = Path(folder) / "DevToolsActivePort"
        deadline = time.monotonic() + 15
        while not port_file.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Chrome não iniciou o depurador.")
            time.sleep(.1)
        port = port_file.read_text().splitlines()[0]
        session = requests.Session()
        session.trust_env = False
        targets = session.get(f"http://127.0.0.1:{port}/json/list", timeout=15).json()
        target = next(t for t in targets if t["type"] == "page")
        with connect(target["webSocketDebuggerUrl"], proxy=None, open_timeout=5) as socket:
            ident = 0
            exceptions = []

            def cdp(method, **params):
                nonlocal ident
                ident += 1
                socket.send(json.dumps({"id": ident, "method": method, "params": params}))
                while True:
                    message = json.loads(socket.recv(timeout=10))
                    if message.get("method") == "Runtime.exceptionThrown":
                        exceptions.append(message["params"])
                    if message.get("id") == ident:
                        if "error" in message:
                            raise RuntimeError(message["error"])
                        return message.get("result", {})

            def evaluate(expression):
                result = cdp("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True, userGesture=True)
                if "exceptionDetails" in result:
                    raise RuntimeError(result["exceptionDetails"])
                return result["result"].get("value")

            def wait_for(expression):
                deadline = time.monotonic() + 10
                while not evaluate(expression):
                    if time.monotonic() > deadline:
                        raise AssertionError("Tempo esgotado: " + expression)
                    time.sleep(.1)

            cdp("Runtime.enable")
            if "--no-broadcast" in sys.argv:
                cdp("Page.addScriptToEvaluateOnNewDocument", source="window.BroadcastChannel = class { constructor() { throw new DOMException('Bloqueio simulado', 'SecurityError'); } };")
            cdp("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)
            cdp("Page.navigate", url=base + "/editor")
            if "--readme" in sys.argv:
                import base64
                screenshots = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
                screenshots.mkdir(parents=True, exist_ok=True)
                wait_for("document.getElementById('panel-health')?.textContent === 'Painel conectado'")
                evaluate("document.getElementById('connection-settings').open = false; document.getElementById('message').value = 'Rafael, de Fortaleza, manda um abraço para toda a equipe!'; document.getElementById('message').dispatchEvent(new Event('input'))")
                def capture(name):
                    size = cdp("Page.getLayoutMetrics")["cssContentSize"]
                    data = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                               clip={"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1})
                    (screenshots / name).write_bytes(base64.b64decode(data["data"]))
                capture("01-painel-desktop.png")
                evaluate("document.getElementById('mode-manual').click()")
                capture("02-modo-manual.png")
                assert evaluate("document.querySelector('.site-footer a').href === 'https://github.com/xLuuks'")
                assert not exceptions, exceptions
                print("Capturas do painel geradas com dados fictícios em docs/screenshots/.")
                return
            if "--delivery-refinements" in sys.argv:
                wait_for("document.querySelectorAll('.comment').length === 1")
                evaluate("document.querySelector('.comment button').click()")
                # O servidor salva, mas o navegador perde somente a resposta do envio.
                evaluate("window.originalFetch = window.fetch; window.loseResponse = true; window.fetch = async (path, options) => { const result = await originalFetch(path, options); if (path === '/youtube/enviar' && loseResponse) { loseResponse = false; throw new TypeError('Resposta perdida simulada'); } return result; }")
                evaluate("document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.getElementById('notice').textContent.includes('Resposta perdida') && !document.querySelector('#compose-form button[type=submit]').disabled")
                assert len(server.queue.snapshot()["entries"]) == 1
                assert evaluate("document.getElementById('message').value.startsWith('Maria:')")
                evaluate("document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.getElementById('message').value === '' && document.querySelectorAll('.queued').length === 1")
                assert len(server.queue.snapshot()["entries"]) == 1
                evaluate("window.fetch = originalFetch")
                evaluate("(async () => { for (let i=0;i<12;i++) await api('/adicionar', {mensagem:'Pessoa ' + i + ': um abraço para toda a equipe!',request_id:uid()}); await refreshQueue(true); })()")
                wait_for("document.querySelectorAll('.queued').length === 13")
                evaluate("window.keptCard = document.querySelectorAll('.queued')[6]; window.keptButton = keptCard.querySelector('button:last-child'); keptButton.focus(); keptCard.scrollIntoView({block:'center'}); window.keptTop = keptCard.getBoundingClientRect().top; window.firstId = queueData.entries[0].id")
                evaluate("queueAction(`/recados/${firstId}/lido`)")
                assert evaluate("keptCard === document.querySelector(`[data-id='${keptCard.dataset.id}']`) && document.activeElement === keptButton")
                assert evaluate("Math.abs(keptCard.getBoundingClientRect().top - keptTop) < 2")
                evaluate("queueAction(`/recados/${keptCard.dataset.id}/mover/cima`)")
                assert evaluate("document.activeElement === keptButton && keptButton.isConnected")
                evaluate("queueAction(`/recados/${keptCard.dataset.id}/editar`, {novo_texto:'Texto atualizado',version:keptCard.entry.version})")
                assert evaluate("keptCard.querySelector('p').textContent === 'Texto atualizado' && document.activeElement === keptButton")
                evaluate("window.otherPresenter = window.open('/teleprompter', 'presenter-test'); Boolean(otherPresenter)")
                wait_for("otherPresenter?.document.getElementById('mensagens')?.children.length === 12")
                wait_for("refreshQueue(true).then(() => queueData.delivery.some(client => client.current && client.overflow?.below))")
                assert evaluate("document.getElementById('delivery-status').textContent.includes('abaixo da área visível')")
                evaluate("otherPresenter.scrollTo(0, otherPresenter.document.documentElement.scrollHeight)")
                wait_for("refreshQueue(true).then(() => queueData.delivery.some(client => client.current && client.overflow?.above && !client.overflow?.below))")
                assert evaluate("document.getElementById('delivery-status').textContent.includes('acima da área visível')")
                for entry in server.queue.snapshot()["entries"][1:]:
                    server.queue.remove(entry["id"])
                server.queue.edit(server.queue.snapshot()["entries"][0]["id"], "Recado curto", 1)
                wait_for("refreshQueue(true).then(() => queueData.delivery.some(client => client.current && client.overflow && !client.overflow.above && !client.overflow.below))")
                assert evaluate("document.getElementById('delivery-status').textContent.includes('todos os recados cabem')")
                evaluate("otherPresenter.close()")
                assert not exceptions, exceptions
                print("OK no navegador: resposta perdida e reenvio sem duplicar, cartões e foco preservados, posição da fila estável, rolagem do apresentador informada ao operador.")
                return
            if refinements:
                wait_for("document.getElementById('panel-health')?.textContent === 'Painel conectado'")
                evaluate("document.getElementById('message').value = 'Rascunho A'; document.getElementById('message').dispatchEvent(new Event('input'))")
                evaluate("window.otherDraft = window.open('/editor', 'draft-test'); Boolean(window.otherDraft)")
                wait_for("otherDraft?.document.getElementById('panel-health')?.textContent === 'Painel conectado'")
                wait_for("sessionStorage.getItem('production-tab') !== otherDraft.sessionStorage.getItem('production-tab')")
                evaluate("otherDraft.document.getElementById('message').value = 'Rascunho B'; otherDraft.document.getElementById('message').dispatchEvent(new otherDraft.Event('input'))")
                evaluate("document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.querySelectorAll('.queued').length === 1")
                assert evaluate("JSON.parse(localStorage.getItem('production-draft:' + otherDraft.sessionStorage.getItem('production-tab'))).text === 'Rascunho B'")
                other_page = evaluate("otherDraft.performance.timeOrigin")
                evaluate("otherDraft.location.reload()")
                wait_for(f"otherDraft.performance.timeOrigin > {other_page} && otherDraft.document.getElementById('message')?.value === 'Rascunho B'")
                wait_for("document.getElementById('saved-drafts').options.length > 1")
                evaluate("document.getElementById('saved-drafts').selectedIndex = 1; document.getElementById('saved-drafts').dispatchEvent(new Event('change')); document.getElementById('restore-draft').click()")
                assert evaluate("document.getElementById('message').value === 'Rascunho B'")
                assert evaluate("otherDraft.document.getElementById('message').value === 'Rascunho B'")
                evaluate("document.getElementById('mode-manual').click()")
                assert evaluate("getComputedStyle(document.querySelector('.inbox')).display === 'none'")
                assert evaluate("document.getElementById('message').value === 'Rascunho B'")
                evaluate("document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.querySelectorAll('.queued').length === 2")
                evaluate("document.getElementById('message').value = 'Recado C'; document.getElementById('message').dispatchEvent(new Event('input')); document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.querySelectorAll('.queued').length === 3")
                expected = evaluate("[...document.querySelectorAll('.queued p')].map(p => p.textContent)")
                evaluate("window.confirm = () => true; document.getElementById('clear').click()")
                wait_for("document.querySelectorAll('.queued').length === 0 && !document.getElementById('undo-removal').disabled")
                evaluate("document.getElementById('undo-removal').click()")
                wait_for("document.querySelectorAll('.queued').length === 3")
                assert evaluate("[...document.querySelectorAll('.queued p')].map(p => p.textContent)") == expected
                evaluate("document.getElementById('clear').click()")
                wait_for("document.querySelectorAll('.queued').length === 0")
                evaluate("document.getElementById('history-details').open = true")
                for count in range(1, 4):
                    evaluate("document.querySelector('.history-item button').click()")
                    wait_for(f"document.querySelectorAll('.queued').length === {count}")
                assert evaluate("[...document.querySelectorAll('.queued p')].map(p => p.textContent)") == expected
                assert list(server.queue.backup_dir.glob('recados-*.json'))
                if os.environ.get("PANEL_PREVIEW"):
                    import base64
                    Path(os.environ["PANEL_PREVIEW"]).write_bytes(base64.b64decode(cdp("Page.captureScreenshot", format="png")["data"]))
                cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
                assert evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                evaluate("otherDraft.close()")
                assert not exceptions, exceptions
                print("OK no navegador: abas e aba duplicada com rascunhos independentes, recuperação de outro rascunho, modo manual, desfazer limpeza, restauração ordenada e layout móvel.")
                return
            if manual_only:
                wait_for("document.getElementById('panel-health')?.textContent === 'Painel conectado'")
                assert evaluate("document.querySelectorAll('.comment').length === 0")
                # Uma falha de envio precisa preservar o texto e liberar a repetição.
                evaluate("window.manualFetch = window.fetch; window.failNextManual = true; window.fetch = (path, options) => { if (path === '/adicionar' && window.failNextManual) { window.failNextManual = false; return Promise.resolve(new Response(JSON.stringify({error: 'Falha simulada no envio'}), {status: 503, headers: {'Content-Type': 'application/json'}})); } return window.manualFetch(path, options); }")
                evaluate("document.getElementById('message').value = 'Primeiro recado manual'; document.getElementById('message').dispatchEvent(new Event('input')); document.querySelector('#compose-form button[type=submit]').click()")
                wait_for("document.getElementById('notice').textContent === 'Falha simulada no envio'")
                assert evaluate("!document.querySelector('#compose-form button[type=submit]').disabled")
                assert evaluate("!document.getElementById('message').readOnly")
                assert evaluate("document.getElementById('message').value === 'Primeiro recado manual'")
                for index, text in enumerate(("Primeiro recado manual", "Segundo recado manual"), 1):
                    evaluate(f"document.getElementById('message').value = {json.dumps(text)}; document.getElementById('message').dispatchEvent(new Event('input')); document.querySelector('#compose-form button[type=submit]').click()")
                    wait_for(f"document.querySelectorAll('.queued').length === {index}")
                    wait_for("!document.querySelector('#compose-form button[type=submit]').disabled")
                assert evaluate("!document.getElementById('message').readOnly")
                cdp("Page.navigate", url=base + "/__test__/legacy")
                wait_for("document.getElementById('notice')?.textContent.includes('versão anterior')")
                evaluate("document.getElementById('message').value = 'Não enviar em uma versão incompatível'; document.querySelector('#compose-form button[type=submit]').click()")
                assert evaluate("!document.querySelector('#compose-form button[type=submit]').disabled")
                assert len(server.queue.snapshot()["entries"]) == 2
                assert not exceptions, exceptions
                print("OK no navegador: envio manual sem canais, recuperação após falha e aviso de servidor desatualizado sem bloquear o botão.")
                return
            wait_for("document.querySelectorAll('.comment').length === 1")
            assert evaluate("window.injetado === undefined")
            assert evaluate("document.querySelector('.comment p').textContent.includes('<script>')")
            evaluate("window.originalCard = document.querySelector('.comment'); window.originalTop = originalCard.getBoundingClientRect().top")
            evaluate("fetch('/__test__/comment', {method: 'POST', headers: {'X-CSRF-Token': token}}).then(r => r.json())")
            evaluate("refreshChats(true)")
            assert evaluate("document.querySelectorAll('.comment').length === 1")
            assert evaluate("originalCard === document.querySelector('.comment')")
            assert evaluate("originalTop === originalCard.getBoundingClientRect().top")
            assert evaluate("document.getElementById('new-comments').textContent.includes('1 novo')")
            evaluate("document.getElementById('new-comments').click()")
            wait_for("document.querySelectorAll('.comment').length === 2")
            if os.environ.get("PANEL_PREVIEW"):
                import base64
                screenshot = cdp("Page.captureScreenshot", format="png")
                Path(os.environ["PANEL_PREVIEW"]).write_bytes(base64.b64decode(screenshot["data"]))
            evaluate("document.querySelector('[data-id=\"abcdefghijk:m1\"] button').click()")
            assert evaluate("document.getElementById('message').value.startsWith('Maria:')")
            evaluate("document.getElementById('message').value = 'Rascunho salvo'; document.getElementById('message').dispatchEvent(new Event('input'))")
            previous_page = evaluate("performance.timeOrigin")
            cdp("Page.navigate", url=base + "/editor")
            wait_for(f"performance.timeOrigin > {previous_page} && document.getElementById('message')?.value === 'Rascunho salvo'")
            evaluate("document.getElementById('message').value = 'Maria pede um abraço'; document.getElementById('compose-form').requestSubmit(document.querySelector('#compose-form button[type=submit]'))")
            wait_for("document.querySelectorAll('.queued').length === 1")
            wait_for("document.querySelector('[data-id=\"abcdefghijk:m1\"] button')?.disabled")
            assert evaluate("document.querySelector('.queued p').textContent") == "Maria pede um abraço"
            evaluate("document.querySelector('.queued button:last-child').click()")
            assert evaluate("document.getElementById('edit-dialog').open")
            evaluate("document.getElementById('edit-text').value = 'Maria e família'; document.getElementById('edit-form').requestSubmit(document.querySelector('#edit-form button[type=submit]'))")
            wait_for("document.querySelector('.queued p')?.textContent === 'Maria e família'")
            evaluate("document.querySelector('.queued button').click()")
            wait_for("document.querySelectorAll('.queued').length === 0")
            evaluate("document.getElementById('history-details').open = true; document.querySelector('.history-item button').click()")
            wait_for("document.querySelectorAll('.queued').length === 1")
            assert evaluate("document.querySelector('.queued p').textContent") == "Maria e família"
            evaluate("document.querySelector('.queued button').click()")
            wait_for("document.querySelectorAll('.queued').length === 0")
            evaluate("document.getElementById('message').value = 'Recado manual'; document.getElementById('compose-form').requestSubmit(document.querySelector('#compose-form button[type=submit]'))")
            wait_for("document.querySelectorAll('.queued').length === 1")
            evaluate("document.querySelector('.source[data-slot=\"1\"] .actions button').click()")
            wait_for("!document.querySelector('.source[data-slot=\"1\"] .actions button').disabled")
            evaluate("refreshChats(true)")
            assert evaluate("document.querySelector('[data-id=\"abcdefghijk:m1\"] button').disabled")
            assert evaluate("latest.some(c => c.slot === 2)")
            cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
            assert evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            cdp("Page.navigate", url=base + "/teleprompter")
            wait_for("document.getElementById('mensagens')?.textContent === 'Recado manual'")
            wait_for("fetch('/recados').then(r => r.json()).then(d => d.delivery.some(v => v.kind === 'navegador' && v.current))")
            assert not exceptions, exceptions
            print("OK no navegador: lista estável, novidades sob controle, rascunho recuperado, edição interna, envio, histórico, restauração, reconexão por canal, confirmação de entrega, largura móvel e texto seguro.")
    finally:
        close_browser(process, folder)


def main():
    manual_only = "--manual-only" in sys.argv
    refinements = "--refinements" in sys.argv
    browsers = [Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]
    browser = next((p for p in browsers if p.exists()), None)
    if browser is None:
        raise SystemExit("Chrome ou Edge não encontrado para o teste opcional.")
    with browser_workspace() as folder:
        server.queue = Recados(Path(folder) / "mensagens.json")
        current = {"slot": 1, "video_id": "abcdefghijk", "channel": "Canal de teste",
                   "title": "Live de teste", "state": "conectado", "detail": "Simulação",
                   "updated_at": None, "stop": threading.Event(), "interval": 30, "_key": "fake-test-key"}
        server.youtube.slots[1] = current
        second = dict(current, slot=2, video_id="12345678901", channel="Segundo canal", stop=threading.Event())
        server.youtube.slots[2] = second
        server.youtube._worker = lambda source, key: server.youtube._update(source, state="conectado", detail="Simulação")
        server.youtube._ingest(current, [{"id": "m1", "authorDetails": {"displayName": "Maria"},
            "snippet": {"displayMessage": "Um abraço! <script>window.injetado = true</script>",
                        "publishedAt": "2026-10-30T12:00:00Z"}}])

        def add_test_comment():
            server.youtube._ingest(second, [{"id": "m2", "authorDetails": {"displayName": "João"},
                "snippet": {"displayMessage": "Boa tarde a toda a equipe!", "publishedAt": "2026-10-30T12:01:00Z"}}])
            return jsonify(ok=True)

        server.app.add_url_rule("/__test__/comment", "test_comment", add_test_comment, methods=["POST"])
        server.app.add_url_rule("/__test__/legacy", "test_legacy", lambda: server.editor().replace('name="panel-version"', 'name="old-panel-version"').replace('id="new-comments"', 'id="old-new-comments"'))
        if manual_only or refinements:
            server.youtube.slots.clear()
            server.youtube.comments.clear()
        if "--readme" in sys.argv:
            server.youtube.comments.clear()
            server.youtube.seen.clear()
            current.update(channel="Canal principal", title="Encontro da comunidade", detail="Demonstração com dados fictícios")
            second.update(channel="Canal secundário", title="Transmissão simultânea", detail="Demonstração com dados fictícios")
            for source, ident, author, text, stamp in (
                (current, "demo1", "Marina Costa", "Boa noite! Um abraço para todos que estão acompanhando.", "18:32:10"),
                (second, "demo2", "Rafael Lima", "Acompanhando de Fortaleza. Parabéns pela transmissão!", "18:32:25"),
                (current, "demo3", "Ana Souza", "Mandem um abraço para a nossa família em Recife!", "18:32:40")):
                server.youtube._ingest(source, [{"id": ident, "authorDetails": {"displayName": author},
                    "snippet": {"displayMessage": text, "publishedAt": f"2026-11-05T{stamp}-03:00"}}])
            server.queue.add("Marina, um abraço para você e todos que estão acompanhando!")
            server.queue.add("Ana e família, em Recife, recebam nosso abraço!")
        httpd = make_server("127.0.0.1", 0, server.app, threaded=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            check_browser(browser, folder, f"http://127.0.0.1:{httpd.server_port}", manual_only=manual_only, refinements=refinements)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        os.environ["PANEL_PREVIEW"] = sys.argv[1]
    main()
