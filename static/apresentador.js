let clientId;
try {
  clientId = sessionStorage.getItem('presenter-client') || crypto.randomUUID();
  sessionStorage.setItem('presenter-client', clientId);
} catch { clientId = crypto.randomUUID(); }

async function timedFetch(path, options = {}, readJSON = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    if (readJSON) return {response, data: await response.json()};
    await response.arrayBuffer();
    return response;
  }
  finally { clearTimeout(timeout); }
}

async function atualizar() {
  try {
    const {response, data} = await timedFetch('/mensagens', {cache: 'no-store'}, true);
    if (!response.ok) throw new Error('Sem conexão');
    if (!Array.isArray(data.mensagens) || data.mensagens.some(m => typeof m !== 'string')) throw new Error('Dados inválidos');
    const container = document.getElementById('mensagens');
    if (container.dataset.last !== JSON.stringify(data.mensagens)) {
      container.replaceChildren(...data.mensagens.map(m => {
        const line = document.createElement('div');
        line.textContent = m;
        return line;
      }));
      container.dataset.last = JSON.stringify(data.mensagens);
    }
    document.getElementById('connection-status').hidden = true;
    // Confirma somente depois de aplicar os textos. O estado da aba é informado separadamente.
    if (data.revision && data.delivery_token) {
      if (!document.hidden) await new Promise(resolve => requestAnimationFrame(resolve));
      const bounds = container.getBoundingClientRect();
      const overflow = {above: data.mensagens.length > 0 && bounds.top < -1,
        below: data.mensagens.length > 0 && bounds.bottom > window.innerHeight + 1};
      await timedFetch('/apresentador/confirmar', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Delivery-Token': data.delivery_token},
        body: JSON.stringify({client_id: clientId, kind: 'navegador', active: !document.hidden, revision: data.revision, overflow}),
      }).catch(() => {});
    }
  } catch {
    document.getElementById('connection-status').hidden = false;
  } finally { setTimeout(atualizar, 1000); }
}
atualizar();
