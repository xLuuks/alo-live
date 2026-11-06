const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
const uid = () => crypto.randomUUID();
let latest = [];
let displayed = [];
let receivedOnce = false;
let selected = null;
let sending = false;
let requestId = uid();
let queueData = {entries: [], history: [], revision: ''};
let editing = null;
let queueSignature = '';
let sourcesSignature = '';
let noticeTimer;
let chatsPromise = null;
let queuePromise = null;
let panelWasOffline = false;
const commentNodes = new Map();
const queueNodes = new Map();
const historyNodes = new Map();
const sourceVideos = new Map();
const draftPrefix = 'production-draft:';
let draftKey;
let draftTab;
let draftChannel;
let panelMode = 'youtube';

async function prepareDraftScope() {
  let inherited = null;
  let forked = false;
  try {
    draftTab = sessionStorage.getItem('production-tab') || uid();
    sessionStorage.setItem('production-tab', draftTab);
  } catch { draftTab = uid(); }
  draftKey = draftPrefix + draftTab;
  // Uma aba duplicada pode herdar sessionStorage. A aba já aberta conserva sua chave.
  try {
  if (typeof BroadcastChannel !== 'undefined') {
    const page = uid();
    draftChannel = new BroadcastChannel('production-draft-owners');
    draftChannel.onmessage = event => {
      const data = event.data;
      if (data.type === 'claim' && data.tab === draftTab && data.page !== page) {
        draftChannel.postMessage({type: 'occupied', target: data.page});
      } else if (data.type === 'occupied' && data.target === page && !forked) {
        forked = true;
        try { inherited = localStorage.getItem(draftKey); } catch {}
        draftTab = uid();
        draftKey = draftPrefix + draftTab;
        try { sessionStorage.setItem('production-tab', draftTab); } catch {}
      }
    };
    draftChannel.postMessage({type: 'claim', tab: draftTab, page});
    await new Promise(resolve => setTimeout(resolve, 100));
    window.addEventListener('pagehide', () => draftChannel.close(), {once: true});
  }
  } catch {
    // Bloqueios de comunicação entre abas não podem impedir o envio manual.
    try { inherited = localStorage.getItem(draftKey); } catch {}
    draftTab = uid();
    draftKey = draftPrefix + draftTab;
    try { sessionStorage.setItem('production-tab', draftTab); } catch {}
  }
  try {
    const own = localStorage.getItem(draftKey);
    const legacy = localStorage.getItem('production-draft');
    if (!own && (inherited || legacy)) localStorage.setItem(draftKey, inherited || legacy);
    if (legacy && localStorage.getItem('production-draft') === legacy) localStorage.removeItem('production-draft');
  } catch {}
}

function refreshDraftList() {
  const select = $('saved-drafts');
  const previous = select.value;
  const items = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith(draftPrefix) || key === draftKey) continue;
      try {
        const draft = JSON.parse(localStorage.getItem(key));
        if (typeof draft?.text === 'string' && draft.text.trim()) items.push({key, ...draft});
      } catch {}
    }
  } catch {}
  items.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  select.replaceChildren(node('option', items.length ? 'Selecione um rascunho salvo' : 'Nenhum outro rascunho salvo'));
  select.firstChild.value = '';
  for (const draft of items) {
    const option = node('option', draft.text.replace(/\s+/g, ' ').slice(0, 70));
    option.value = draft.key;
    select.append(option);
  }
  select.value = items.some(item => item.key === previous) ? previous : '';
  $('restore-draft').disabled = !select.value;
}

function setPanelMode(mode) {
  panelMode = mode === 'manual' ? 'manual' : 'youtube';
  document.body.dataset.mode = panelMode;
  $('mode-manual').setAttribute('aria-pressed', String(panelMode === 'manual'));
  $('mode-youtube').setAttribute('aria-pressed', String(panelMode === 'youtube'));
  if (panelMode === 'manual' && selected) {
    selected = null; requestId = uid(); showSelection(); saveDraft(); renderComments();
  }
  try { localStorage.setItem('production-mode', panelMode); } catch {}
  $('mode-note').hidden = panelMode !== 'manual';
  $('mode-note').textContent = 'Modo manual: prepare e envie seus recados. Chats já conectados continuam recebendo comentários; use o modo YouTube para desconectá-los.';
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function notice(text, error = false) {
  clearTimeout(noticeTimer);
  $('notice').textContent = text;
  $('notice').className = error ? 'error' : '';
  $('notice').hidden = false;
  if (!error) noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 6000);
}

async function api(path, data) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const options = {cache: 'no-store', signal: controller.signal};
    if (data !== undefined) {
      options.method = 'POST';
      options.headers = {'X-CSRF-Token': token};
      options.body = data instanceof FormData ? data : new URLSearchParams(data);
    }
    const response = await fetch(path, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Não foi possível concluir a operação.');
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('O painel demorou a responder. Confira a fila antes de repetir o envio.');
    throw error;
  } finally { clearTimeout(timeout); }
}

function action(text, handler, disabled = false) {
  const button = node('button', text);
  button.type = 'button';
  button.disabled = disabled;
  button.addEventListener('click', async () => {
    button.busy = true;
    button.disabled = true;
    try { await handler(); }
    catch (error) { notice(error.message, true); }
    finally { button.busy = false; if (button.isConnected) button.disabled = button.unavailable ?? disabled; }
  });
  return button;
}

function reconcile(container, desired) {
  const focused = container.contains(document.activeElement) ? document.activeElement : null;
  const keep = new Set(desired);
  for (const child of [...container.children]) if (!keep.has(child)) child.remove();
  desired.forEach((element, index) => {
    if (container.children[index] !== element) container.insertBefore(element, container.children[index] || null);
  });
  if (focused?.isConnected && document.activeElement !== focused && !focused.disabled) focused.focus({preventScroll: true});
}

function updateDraftStatus() {
  $('character-count').textContent = `${$('message').value.length.toLocaleString('pt-BR')} / 5.000`;
  $('convert-manual').hidden = !selected;
}

function saveDraft() {
  updateDraftStatus();
  try {
    if ($('message').value || selected) {
      localStorage.setItem(draftKey, JSON.stringify({text: $('message').value, selected, requestId, updated_at: Date.now()}));
    } else localStorage.removeItem(draftKey);
    $('draft-status').textContent = 'Rascunho desta aba salvo no navegador.';
    refreshDraftList();
  } catch {
    $('draft-status').textContent = 'O navegador não permitiu salvar o rascunho.';
  }
}

function showSelection() {
  $('selection').textContent = selected
    ? `${selected.author} · ${selected.channel} · Transmissão ${selected.slot}`
    : 'Recado manual. Escreva o texto que deseja enviar.';
  updateDraftStatus();
}

function resetCompose() {
  selected = null;
  requestId = uid();
  $('message').value = '';
  showSelection();
  saveDraft();
  renderComments();
}

function choose(comment) {
  if (sending || comment.sent) return;
  if ($('message').value.trim() && selected?.id !== comment.id && !confirm('Substituir o recado em preparação?')) return;
  if (selected?.id === comment.id) { $('message').focus(); return; }
  selected = {id: comment.id, author: comment.author, channel: comment.channel, slot: comment.slot};
  requestId = uid();
  $('message').value = `${comment.author}: ${comment.text}`;
  showSelection();
  saveDraft();
  renderComments();
  $('message').focus();
}

function updateNewButton() {
  const shown = new Set(displayed.map(c => c.id));
  const count = latest.filter(c => !shown.has(c.id)).length;
  $('new-comments').disabled = !count || $('pause').checked;
  $('new-comments').textContent = $('pause').checked
    ? `Lista pausada · ${count} novos`
    : count ? `Atualizar lista · ${count} ${count === 1 ? 'novo comentário' : 'novos comentários'}` : 'Lista atualizada';
}

function createComment() {
  const card = node('article', undefined, 'comment');
  const meta = node('div', undefined, 'comment-meta');
  card.author = node('strong');
  card.source = node('span', undefined, 'source-label');
  card.time = node('time');
  card.text = node('p');
  card.button = action('Preparar recado', () => choose(card.comment));
  meta.append(card.author, card.source, card.time);
  card.append(meta, card.text, card.button);
  return card;
}

function renderComments() {
  const search = $('search').value.trim().toLocaleLowerCase('pt-BR');
  const source = $('source-filter').value;
  const visible = displayed.filter(c => (!source || String(c.slot) === source)
    && (!$('hide-sent').checked || !c.sent)
    && `${c.author} ${c.text}`.toLocaleLowerCase('pt-BR').includes(search));
  const cards = visible.map(comment => {
    let card = commentNodes.get(comment.id);
    if (!card) { card = createComment(); commentNodes.set(comment.id, card); }
    card.comment = comment;
    card.dataset.id = comment.id;
    card.dataset.slot = comment.slot;
    card.className = `comment${comment.sent ? ' sent' : ''}${selected?.id === comment.id ? ' selected' : ''}`;
    card.author.textContent = comment.author;
    card.source.textContent = `${comment.channel} · ${comment.slot}`;
    const time = new Date(comment.published_at);
    card.time.textContent = Number.isNaN(time.getTime()) ? '' : time.toLocaleTimeString('pt-BR');
    card.text.textContent = comment.text;
    card.button.textContent = comment.sent ? 'Enviado ✓' : selected?.id === comment.id ? 'Em preparação' : 'Preparar recado';
    card.button.disabled = comment.sent || sending;
    return card;
  });
  $('comment-count').textContent = `${visible.length} / ${displayed.length}`;
  if (!cards.length) cards.push(node('p', displayed.length ? 'Nenhum comentário corresponde aos filtros.' : 'Aguardando comentários. Conecte uma live com chat ativo.', 'empty'));
  reconcile($('comments'), cards);
  const retained = new Set(displayed.map(c => c.id));
  for (const id of commentNodes.keys()) if (!retained.has(id)) commentNodes.delete(id);
  updateNewButton();
}

function applyLatest() {
  if ($('pause').checked) return;
  displayed = latest.map(c => ({...c}));
  renderComments();
  $('comments').scrollTop = 0;
}

function connectionFormData() {
  const form = $('connection-form');
  return {api_key: form.elements.api_key.value, interval: form.elements.interval.value};
}

function renderSources(sources) {
  const signature = JSON.stringify(sources);
  if (sourcesSignature === signature) return;
  sourcesSignature = signature;
  const cards = [1, 2].map(number => {
    const source = sources.find(s => s.slot === number);
    if (source && sourceVideos.has(number) && sourceVideos.get(number) !== source.video_id) {
      displayed = displayed.filter(comment => comment.slot !== number);
    }
    if (source) sourceVideos.set(number, source.video_id);
    const card = node('article', undefined, 'source');
    card.dataset.slot = number;
    const heading = node('div', undefined, 'source-header');
    const state = node('span', source?.state || 'não conectado', 'state');
    state.dataset.state = source?.state || 'desconectado';
    heading.append(node('strong', `Transmissão ${number} · ${source?.channel || 'YouTube'}`), state);
    card.append(heading);
    if (source?.title) card.append(node('p', source.title));
    card.append(node('p', source?.detail || 'Configure o link desta transmissão para começar.'));
    if (source?.updated_at) card.append(node('p', `Última consulta: ${new Date(source.updated_at).toLocaleTimeString('pt-BR')}`, 'muted'));
    const actions = node('div', undefined, 'actions');
    actions.append(action(source ? 'Reconectar este canal' : 'Conectar este canal', async () => {
      const form = $('connection-form');
      const url = form.elements[`live${number}`].value;
      if (source && url.trim() && !url.includes(source.video_id) && !confirm('Trocar o vídeo deste canal? Os comentários anteriores deste canal sairão da lista.')) return;
      await api(`/youtube/${number}/reconectar`, {...connectionFormData(), url});
      saveLinks();
      await refreshChats(true);
      notice(`Conexão da transmissão ${number} iniciada. O outro canal foi preservado.`);
    }));
    if (source) actions.append(action('Desconectar', async () => {
      await api(`/youtube/${number}/desconectar`, {});
      await refreshChats(true);
    }, source.state === 'desconectado'));
    actions.append(action('Configurar', () => {
      $('connection-settings').open = true;
      $('connection-form').elements[`live${number}`].focus();
    }));
    card.append(actions);
    return card;
  });
  $('sources').replaceChildren(...cards);
  for (const source of sources) {
    const option = $('source-filter').querySelector(`option[value="${source.slot}"]`);
    if (option) option.textContent = `${source.slot} · ${source.channel}`;
    const field = $('connection-form').elements[`live${source.slot}`];
    if (!field.value) field.value = `https://www.youtube.com/watch?v=${source.video_id}`;
  }
}

async function refreshChats(force = false) {
  if (chatsPromise) { await chatsPromise; if (!force) return; }
  chatsPromise = (async () => {
    const data = await api('/youtube/estado');
    renderSources(data.sources);
    latest = data.comments;
    if (!receivedOnce) {
      receivedOnce = true;
      displayed = latest.map(c => ({...c}));
      if (data.sources.some(s => s.state === 'conectado')) $('connection-settings').open = false;
    } else if (!$('pause').checked) {
      const byId = new Map(latest.map(c => [c.id, c]));
      // As posições ficam intactas; apenas o conteúdo dos cartões existentes é atualizado.
      displayed = displayed.map(c => byId.get(c.id) || c);
    }
    renderComments();
  })();
  try { await chatsPromise; } finally { chatsPromise = null; }
}

function renderDelivery(delivery) {
  const recent = delivery.filter(client => client.age <= 8);
  const current = recent.filter(client => client.current);
  const element = $('delivery-status');
  element.dataset.state = current.length === recent.length && recent.length ? 'current' : 'waiting';
  if (!recent.length) element.textContent = 'Sem confirmação recente. Abra a janela ou a tela do apresentador.';
  else element.textContent = recent.map(client => {
    let text = `${client.kind === 'janela' ? 'Janela' : 'Navegador'}: ${client.current ? 'atualização recebida' : 'aguardando atualização'}${client.active ? '' : ' (minimizado ou em segundo plano)'}`;
    if (client.current && client.active && client.overflow) {
      const {above, below} = client.overflow;
      text += above || below ? ` — há recados ${above && below ? 'acima e abaixo' : above ? 'acima' : 'abaixo'} da área visível` : ' — todos os recados cabem na tela';
    }
    return text;
  }).join(' · ');
  element.title = 'Confirma que a tela recebeu os textos. Não confirma que o apresentador leu. Uma desconexão pode levar até 8 segundos para aparecer aqui.';
}

async function queueAction(path, data = {}, success = '') {
  try {
    await api(path, data);
  } catch (error) {
    await refreshQueue(true).catch(() => {});
    throw error;
  }
  if (success) notice(success);
  await refreshQueue(true).catch(() => notice('Alteração salva. Aguardando conexão para atualizar a fila.', true));
}

function editEntry(entry) {
  editing = {id: entry.id, version: entry.version};
  $('edit-text').value = entry.text;
  $('edit-error').hidden = true;
  $('reload-edit').hidden = true;
  $('edit-dialog').showModal();
  $('edit-text').focus();
}

function createQueuedCard() {
  const card = node('article', undefined, 'queued');
  card.text = node('p');
  const actions = node('div', undefined, 'actions');
  card.read = action('Lido ✓', () => queueAction(`/recados/${card.entry.id}/lido`, {}, 'Recado retirado. Você pode restaurá-lo no histórico.'));
  card.up = action('↑', () => queueAction(`/recados/${card.entry.id}/mover/cima`));
  card.down = action('↓', () => queueAction(`/recados/${card.entry.id}/mover/baixo`));
  card.edit = action('Editar', () => editEntry(card.entry));
  card.up.setAttribute('aria-label', 'Subir recado');
  card.down.setAttribute('aria-label', 'Descer recado');
  actions.append(card.read, card.up, card.down, card.edit);
  card.append(card.text, actions);
  return card;
}

function renderQueue() {
  const oldCards = [...$('queue').querySelectorAll('.queued')];
  const focused = document.activeElement;
  const focusedCard = focused?.closest('.queued');
  const focusedIndex = oldCards.indexOf(focusedCard);
  const ids = new Set(queueData.entries.map(entry => entry.id));
  // Conserva a posição de um recado visível que sobreviva à atualização.
  const anchor = oldCards.find(card => ids.has(card.dataset.id) && card.getBoundingClientRect().bottom > 0 && card.getBoundingClientRect().top < innerHeight);
  const anchorTop = anchor?.getBoundingClientRect().top;
  const cards = queueData.entries.map((entry, index) => {
    let card = queueNodes.get(entry.id);
    if (!card) { card = createQueuedCard(); queueNodes.set(entry.id, card); }
    card.entry = entry;
    card.dataset.id = entry.id;
    if (card.text.textContent !== entry.text) card.text.textContent = entry.text;
    for (const [button, unavailable] of [[card.up, index === 0], [card.down, index === queueData.entries.length - 1]]) {
      button.unavailable = unavailable;
      button.disabled = unavailable || Boolean(button.busy);
    }
    return card;
  });
  reconcile($('queue'), cards.length ? cards : [node('p', 'Nenhum recado aguardando na tela.', 'empty')]);
  if (focusedIndex >= 0 && !focused.isConnected && cards.length) cards[Math.min(focusedIndex, cards.length - 1)].read.focus({preventScroll: true});
  if (anchor?.isConnected) window.scrollBy(0, anchor.getBoundingClientRect().top - anchorTop);
  for (const id of queueNodes.keys()) if (!ids.has(id)) queueNodes.delete(id);
  $('queue-count').textContent = cards.length;
  $('clear').disabled = !cards.length;
  const historyCards = queueData.history.map(history => {
    let card = historyNodes.get(history.id);
    if (!card) {
      card = node('article', undefined, 'history-item');
      card.append(node('time', new Date(history.removed_at).toLocaleString('pt-BR'), 'muted'), node('p', history.entry.text),
        action('Restaurar na tela ↩', () => queueAction(`/historico/${history.id}/restaurar`, {}, 'Recado restaurado na fila do apresentador.')));
      historyNodes.set(history.id, card);
    }
    return card;
  });
  $('history-count').textContent = historyCards.length;
  reconcile($('history'), historyCards.length ? historyCards : [node('p', 'Os recados retirados aparecerão aqui.', 'empty')]);
  const historyIds = new Set(queueData.history.map(history => history.id));
  for (const id of historyNodes.keys()) if (!historyIds.has(id)) historyNodes.delete(id);
}

async function refreshQueue(force = false) {
  if (queuePromise) { await queuePromise; if (!force) return; }
  queuePromise = (async () => {
    const data = await api('/recados');
    queueData = data;
    $('undo-removal').disabled = !data.undo;
    $('undo-removal').textContent = data.undo ? `Desfazer última retirada (${data.undo.count})` : 'Desfazer última retirada';
    const storageMessages = [data.storage?.recovery_notice,
      data.storage?.backup_error ? 'Os recados foram salvos, mas não foi possível atualizar a cópia de segurança. Consulte o registro de erros.' : ''].filter(Boolean);
    $('storage-status').hidden = !storageMessages.length;
    $('storage-status').textContent = storageMessages.join(' ');
    renderDelivery(data.delivery);
    if (queueSignature !== data.revision) { queueSignature = data.revision; renderQueue(); }
  })();
  try { await queuePromise; } finally { queuePromise = null; }
}

function saveLinks() {
  try {
    const form = $('connection-form');
    localStorage.setItem('youtube-live-links', JSON.stringify({live1: form.elements.live1.value, live2: form.elements.live2.value, interval: form.elements.interval.value}));
  } catch { /* O armazenamento dos links é opcional. */ }
}

async function initializePanel() {
  const required = ['connection-form', 'connection-settings', 'disconnect', 'sources',
    'compose-form', 'message', 'selection', 'character-count', 'draft-status', 'manual',
    'convert-manual', 'new-comments', 'search', 'source-filter', 'hide-sent', 'pause',
    'comments', 'comment-count', 'delivery-status', 'queue', 'queue-count', 'clear',
    'history', 'history-count', 'edit-dialog', 'edit-form', 'edit-text', 'edit-error',
    'cancel-edit', 'reload-edit', 'panel-health', 'mode-manual', 'mode-youtube',
    'saved-drafts', 'restore-draft', 'undo-removal', 'storage-status'];
  if (!token || document.querySelector('meta[name="panel-version"]')?.content !== '5'
      || required.some(id => !$(id))) {
    const message = 'O servidor está executando uma versão anterior do painel. Feche o servidor antigo (Ctrl+C no terminal), abra Iniciar.pyw e atualize esta página com Ctrl+F5. Seus recados salvos serão mantidos.';
    const banner = $('notice') || node('div', undefined, 'error');
    banner.id = 'notice';
    banner.className = 'error';
    banner.setAttribute('role', 'alert');
    banner.textContent = message;
    banner.hidden = false;
    if (!banner.isConnected) document.body.prepend(banner);
    for (const form of document.querySelectorAll('form')) {
      form.addEventListener('submit', event => { event.preventDefault(); banner.hidden = false; });
    }
    const submit = document.querySelector('#compose-form button[type="submit"]');
    if (submit) submit.disabled = false;
    if ($('message')) $('message').readOnly = false;
    return;
  }
  await prepareDraftScope();

$('mode-manual').addEventListener('click', () => setPanelMode('manual'));
$('mode-youtube').addEventListener('click', () => setPanelMode('youtube'));
$('saved-drafts').addEventListener('change', () => { $('restore-draft').disabled = !$('saved-drafts').value; });
$('restore-draft').addEventListener('click', () => {
  if (sending || !$('saved-drafts').value) return;
  if ($('message').value.trim() && !confirm('Substituir o texto em preparação pelo rascunho selecionado?')) return;
  try {
    const draft = JSON.parse(localStorage.getItem($('saved-drafts').value));
    if (typeof draft?.text !== 'string') throw new Error('Este rascunho não está mais disponível.');
    $('message').value = draft.text;
    selected = panelMode === 'manual' ? null : draft.selected || null;
    requestId = uid(); showSelection(); saveDraft(); renderComments();
    notice('Rascunho copiado para esta aba. O original foi preservado.');
  } catch (error) { notice(error.message, true); refreshDraftList(); }
});
window.addEventListener('storage', event => { if (event.key?.startsWith(draftPrefix)) refreshDraftList(); });
$('undo-removal').addEventListener('click', async () => {
  if (!queueData.undo) return;
  try { await queueAction('/historico/desfazer', {batch_id: queueData.undo.id}, 'Última retirada desfeita. A ordem dos recados foi preservada.'); }
  catch (error) { notice(error.message, true); }
});

$('connection-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter || event.target.querySelector('[type=submit]');
  button.disabled = true;
  try {
    await api('/youtube/conectar', new FormData(event.target));
    saveLinks();
    $('connection-settings').open = false;
    await refreshChats(true);
    if (!displayed.length) applyLatest();
    notice('Conexões iniciadas. Acompanhe o estado de cada canal.');
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});

$('disconnect').addEventListener('click', async () => {
  try { await api('/youtube/desconectar', {}); await refreshChats(true); notice('Coleta interrompida. Os comentários recebidos foram mantidos.'); }
  catch (error) { notice(error.message, true); }
});

$('compose-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (sending) return;
  const button = event.submitter || event.target.querySelector('[type=submit]');
  const label = button.textContent;
  let saved = false;
  try {
    sending = true;
    button.disabled = true;
    button.textContent = 'Enviando…';
    $('message').readOnly = true;
    for (const card of commentNodes.values()) card.button.disabled = true;
    const sentId = selected?.id;
    await api(sentId ? '/youtube/enviar' : '/adicionar', {id: sentId || '', mensagem: $('message').value, request_id: requestId});
    saved = true;
    for (const list of [latest, displayed]) for (const c of list) if (c.id === sentId) c.sent = true;
    resetCompose();
    notice('Recado salvo e enviado. A entrega à tela é confirmada na coluna ao lado.');
  } catch (error) { notice(error.message, true); }
  finally {
    sending = false;
    button.disabled = false;
    button.textContent = label;
    $('message').readOnly = false;
    for (const card of commentNodes.values()) card.button.disabled = card.comment.sent;
  }
  // A atualização da fila não mantém o editor bloqueado após o servidor confirmar o envio.
  if (saved) await refreshQueue(true).catch(() => notice('Recado salvo. Aguardando conexão para atualizar a fila.', true));
});

$('message').addEventListener('input', () => { requestId = uid(); saveDraft(); });
$('manual').addEventListener('click', () => {
  if (sending || ($('message').value.trim() && !confirm('Descartar o rascunho atual e começar um recado manual?'))) return;
  resetCompose(); $('message').focus();
});
$('convert-manual').addEventListener('click', () => {
  if (sending) return;
  selected = null; requestId = uid(); showSelection(); saveDraft(); renderComments(); $('message').focus();
});
$('new-comments').addEventListener('click', applyLatest);
for (const id of ['search', 'source-filter', 'hide-sent']) $(id).addEventListener('input', renderComments);
$('pause').addEventListener('change', () => {
  if (!$('pause').checked) {
    const byId = new Map(latest.map(c => [c.id, c]));
    displayed = displayed.map(c => byId.get(c.id) || c);
  }
  renderComments();
});
$('clear').addEventListener('click', async () => {
  if (!confirm('Retirar todos os recados da tela? Eles ficarão disponíveis no histórico.')) return;
  try { await queueAction('/limpar', {revision: queueData.revision}, 'Recados retirados. Você pode restaurá-los no histórico.'); }
  catch (error) { notice(error.message, true); }
});

$('cancel-edit').addEventListener('click', () => $('edit-dialog').close());
$('edit-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!editing) return;
  const button = event.submitter || event.target.querySelector('[type=submit]');
  button.disabled = true;
  try {
    await api(`/recados/${editing.id}/editar`, {novo_texto: $('edit-text').value, version: editing.version});
    $('edit-dialog').close();
    notice('Recado atualizado.');
    await refreshQueue(true).catch(() => notice('Alteração salva. Aguardando conexão para atualizar a fila.', true));
  } catch (error) {
    $('edit-error').textContent = error.message;
    $('edit-error').hidden = false;
    $('reload-edit').hidden = false;
    await refreshQueue(true).catch(() => {});
  } finally { button.disabled = false; }
});
$('reload-edit').addEventListener('click', () => {
  const current = queueData.entries.find(e => e.id === editing?.id);
  if (!current) { $('edit-error').textContent = 'Este recado já foi retirado da fila. Cancele a edição.'; return; }
  $('edit-text').value = current.text;
  editing.version = current.version;
  $('edit-error').hidden = true;
  $('reload-edit').hidden = true;
});

try {
  const links = JSON.parse(localStorage.getItem('youtube-live-links') || '{}');
  for (const key of ['live1', 'live2', 'interval']) if (links[key]) $('connection-form').elements[key].value = links[key];
  const draft = JSON.parse(localStorage.getItem(draftKey) || 'null');
  if (draft && typeof draft.text === 'string') {
    $('message').value = draft.text;
    selected = draft.selected && typeof draft.selected.id === 'string' ? draft.selected : null;
    requestId = typeof draft.requestId === 'string' ? draft.requestId : uid();
    showSelection();
    $('draft-status').textContent = 'Rascunho recuperado.';
  }
  setPanelMode(localStorage.getItem('production-mode'));
} catch { $('draft-status').textContent = 'Salvamento do rascunho indisponível neste navegador.'; }
updateDraftStatus();
refreshDraftList();
$('message').readOnly = false;
document.querySelector('#compose-form button[type=submit]').disabled = false;
refresh();
}

async function refresh() {
  const results = await Promise.allSettled([refreshChats(), refreshQueue()]);
  const offline = results.some(result => result.status === 'rejected');
  $('panel-health').textContent = offline ? 'Sem conexão · tentando novamente…' : 'Painel conectado';
  if (panelWasOffline && !offline) notice('Conexão com o painel restabelecida.');
  panelWasOffline = offline;
  setTimeout(refresh, 2000);
}
initializePanel();
