/* Painel do projeto / máquina padrão (layout B, spec §9).
 *
 * Rotas #/projeto/<id> e #/maquina/<id>.
 * Estado da tela em Orbit.painel (null fora do painel):
 *   {id, dados (obter_painel), sel (tipo_id no visualizador), ver (nº da revisão vista),
 *    marcados (Set de tipo_id para envio múltiplo), recarregar(), aindaAtual()}
 * Arrastar e soltar: o Python chama window.orbitDrop(caminhos) depois do drop
 * (ver orbit/ui/app.py); o cartão alvo é o que estava sob o mouse no drop.
 */

function _formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1).replace('.', ',')} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
}

function _emBreve(oque) {
  abrirPopup({
    titulo: oque,
    corpoHtml: '<p class="texto-sec">Esta função chega numa próxima etapa do Orbit.</p>',
    botoes: [{ texto: 'OK', primario: true }],
  });
}

function _cartaoDoc(d, P) {
  const a = d.atual;
  const pend = !a && !d.nao_se_aplica;
  const cls = ['card', 'doc', d.tipo_id === P.sel ? 'sel' : '', pend ? 'pend' : '', d.nao_se_aplica ? 'na' : '']
    .filter(Boolean).join(' ');
  let meta;
  if (d.nao_se_aplica) meta = 'Não se aplica';
  else if (a) meta = `${pilulaStatus(a.status)}<span>${esc(formatarDataCurta(a.data))}</span>`;
  else meta = '<span class="chip pend">Pendente</span><span>arraste o arquivo</span>';
  const marcar = a ? `<input type="checkbox" class="marcar" data-marcar title="Selecionar para enviar por e-mail"${
    P.marcados.has(d.tipo_id) ? ' checked' : ''}>` : '';
  return `<div class="${cls}" data-tipo="${esc(d.tipo_id)}">
    <div class="card-topo">${marcar}<div class="t">${esc(d.nome)}</div>
      <button type="button" class="menu-btn" data-menu title="Mais ações">⋯</button></div>
    <div class="rev">${a ? esc(`REV ${String(a.numero).padStart(2, '0')}`) : '—'}</div>
    <div class="m">${meta}</div>
  </div>`;
}

function _menuCartao(d) {
  const itens = [];
  if (d.atual) itens.push(['status', 'Mudar status']);
  itens.push(['na', d.nao_se_aplica ? 'Aplica-se' : 'Não se aplica']);
  itens.push(['pasta', 'Abrir pasta']);
  return `<div class="menu-cartao">${itens.map(([k, t]) =>
    `<button type="button" data-acao="${k}">${esc(t)}</button>`).join('')}</div>`;
}

Orbit.views.projeto = Orbit.views.maquina = async (el, id, aindaAtual) => {
  const P = {
    id, dados: null, sel: null, ver: null, marcados: new Set(), aindaAtual,
    recarregar: () => carregar(),
  };
  Orbit.painel = P;
  const doc = tipo => P.dados.documentos.find(d => d.tipo_id === tipo);
  const nomesTipos = () => Object.fromEntries(P.dados.documentos.map(d => [d.tipo_id, d.nome]));

  async function carregar() {
    const dados = await api('obter_painel', id);
    if (!aindaAtual()) return;
    P.dados = dados;
    for (const t of [...P.marcados]) {
      const d = doc(t);
      if (!d || !d.atual) P.marcados.delete(t);
    }
    if (!P.sel || !doc(P.sel)) {
      const primeiro = dados.documentos.find(d => d.atual && !d.nao_se_aplica) || dados.documentos[0];
      P.sel = primeiro ? primeiro.tipo_id : null;
      P.ver = null;
    }
    desenhar();
  }

  function desenhar() {
    const { container: c, resumo: r } = P.dados;
    const maquina = c.tipo === 'maquina';
    const crumb = maquina
      ? `<a href="#/maquinas">Máquinas Padrão</a> / ${esc(c.codigo || c.nome)}`
      : `<a href="#/clientes">Clientes</a> / <a href="#/cliente/${encodeURIComponent(c.cliente_id)}">${
          esc(P.dados.cliente_nome)}</a> / ${esc(c.codigo)}`;
    const ult = r.ultimo_emitido;
    const n = P.dados.nao_registrados;
    el.innerHTML = `
      <div class="crumb">${crumb}</div>
      <div class="titulo-painel"><h1>${esc(c.nome)}</h1>
        ${maquina ? '' : '<button type="button" class="btn" id="pn-dados">Dados do projeto</button>'}</div>
      ${n > 0 ? `<div class="faixa-aviso"><span>${n} ${n === 1 ? 'arquivo na pasta não está registrado'
        : 'arquivos na pasta não estão registrados'}</span>
        <button type="button" class="btn pequeno" id="pn-revisar">Revisar</button></div>` : ''}
      <div class="stats">
        <div class="stat"><div class="v">${r.emitidos}/${r.aplicaveis}</div><div class="l">Emitidos</div></div>
        <div class="stat"><div class="v">${esc(formatarDataCurta(r.ultima_atualizacao))}</div><div class="l">Última atualização</div></div>
        <div class="stat"><div class="v">${ult ? `${esc(ult.nome)} ${formatarRev(ult.numero)}` : '—'}</div><div class="l">Último emitido</div></div>
      </div>
      <main class="painel">
        <div class="coluna-cartoes">
          <div class="barra-selecao${P.marcados.size ? '' : ' oculto'}">
            <span id="pn-qtd"></span>
            <button type="button" class="btn pequeno solid" id="pn-email-varios">Enviar por e-mail</button>
            <button type="button" class="btn pequeno" id="pn-limpar">Limpar seleção</button>
          </div>
          <div class="grid">${P.dados.documentos.map(d => _cartaoDoc(d, P)).join('')}</div>
        </div>
        <div class="viewer" id="pn-viewer"></div>
      </main>`;
    atualizarSelecao();
    ligar();
    desenharViewer();
  }

  function atualizarSelecao() {
    const barra = el.querySelector('.barra-selecao');
    barra.classList.toggle('oculto', !P.marcados.size);
    el.querySelector('#pn-qtd').textContent =
      `${P.marcados.size} ${P.marcados.size === 1 ? 'documento selecionado' : 'documentos selecionados'}`;
  }

  /* ---- visualizador ---- */
  let seqViewer = 0;
  async function desenharViewer() {
    const v = el.querySelector('#pn-viewer');
    const d = P.sel && doc(P.sel);
    if (!d) { v.innerHTML = '<p class="texto-sec">Nenhum tipo de documento.</p>'; return; }
    const rev = d.revisoes.find(x => x.numero === P.ver) || d.atual || d.revisoes[0];
    const botoes = `<div class="acoes">
        ${rev ? '<button type="button" class="btn solid" data-v="email">Enviar por e-mail</button>' : ''}
        <button type="button" class="btn${rev ? '' : ' solid'}" data-v="nova">Nova revisão</button>
        <button type="button" class="btn" data-v="hist">Histórico</button>
        <button type="button" class="btn" data-v="pasta">Abrir pasta</button></div>`;
    if (!rev) {
      v.innerHTML = `<div class="viewer-titulo"><b>${esc(d.nome)}</b></div>
        <div class="pdf vazio">${d.nao_se_aplica ? 'Não se aplica' : 'Nenhuma revisão enviada'}</div>
        <p class="texto-sec" style="margin-top:10px">Arraste o arquivo para o cartão ou use "Nova revisão".</p>${botoes}`;
      return;
    }
    const antiga = rev.arquivada || (d.atual && rev.numero !== d.atual.numero);
    const curtos = d.revisoes.slice(0, 3).map(x => `
      <div class="hist-item${x.numero === rev.numero ? ' on' : ''}" data-rev="${esc(x.numero)}">
        <b>${formatarRev(x.numero)}</b> · ${esc(formatarDataCurta(x.data))}${x.motivo ? ` · ${esc(x.motivo)}` : ''}</div>`).join('');
    v.innerHTML = `
      <div class="viewer-titulo"><b>${esc(d.nome)} · ${formatarRev(rev.numero)}</b> ${pilulaStatus(rev.status)}
        ${antiga ? '<span class="chip">Revisão antiga</span>' : ''}</div>
      <div id="pn-arquivo"><div class="pdf vazio">Carregando…</div></div>
      ${rev.editaveis.length ? `<div class="editaveis"><div class="secao-titulo">Editáveis</div>${
        rev.editaveis.map(nm => `<div class="linha-editavel"><span title="${esc(nm)}">${esc(nm)}</span>
          <button type="button" class="btn pequeno" data-abrir="${esc(nm)}">Abrir</button></div>`).join('')}</div>` : ''}
      ${botoes}
      <div class="hist">${curtos}</div>`;
    v.querySelectorAll('[data-abrir]').forEach(b => b.addEventListener('click', () =>
      api('abrir_no_programa', id, d.tipo_id, rev.numero, b.dataset.abrir).catch(() => {})));
    v.querySelectorAll('[data-rev]').forEach(x => x.addEventListener('click', () => {
      P.ver = Number(x.dataset.rev);
      desenharViewer();
    }));

    const minha = ++seqViewer;
    const r = await apiSilenciosa('url_arquivo', id, d.tipo_id, rev.numero, rev.principal);
    const alvo = el.querySelector('#pn-arquivo');
    if (minha !== seqViewer || !aindaAtual() || !alvo) return;
    if (!r.ok) { alvo.innerHTML = `<div class="pdf vazio erro">${esc(r.erro)}</div>`; return; }
    const f = r.dados;
    const ext = f.nome.split('.').pop().toLowerCase();
    if (f.visualizavel && ext === 'pdf') {
      alvo.innerHTML = `<iframe class="visualizador" src="${esc(f.url)}" title="${esc(f.nome)}"></iframe>`;
    } else if (f.visualizavel) {
      alvo.innerHTML = `<div class="visualizador img"><img src="${esc(f.url)}" alt="${esc(f.nome)}"></div>`;
    } else {
      alvo.innerHTML = `<div class="cartao-arquivo">
        <div class="t">${esc(f.nome)}</div>
        <div class="texto-sec">${_formatarTamanho(f.tamanho)} · modificado em ${esc(formatarDataCurta(f.modificado))}</div>
        <div class="texto-sec">Este formato não abre dentro do Orbit.</div>
        <button type="button" class="btn solid" id="pn-abrir-prog">Abrir no programa padrão</button></div>`;
      alvo.querySelector('#pn-abrir-prog').addEventListener('click', () =>
        api('abrir_no_programa', id, d.tipo_id, rev.numero, rev.principal).catch(() => {}));
    }
    if (f.visualizavel) {
      alvo.insertAdjacentHTML('beforeend', `<div class="nome-arquivo"><span title="${esc(f.nome)}">${esc(f.nome)}</span>
        <button type="button" class="link" id="pn-abrir-fora">Abrir no programa padrão</button></div>`);
      alvo.querySelector('#pn-abrir-fora').addEventListener('click', () =>
        api('abrir_no_programa', id, d.tipo_id, rev.numero, rev.principal).catch(() => {}));
    }
  }

  /* ---- ações ---- */
  async function novaRevisao(tipo, arquivos = []) {
    const d = doc(tipo);
    const c = P.dados.container;
    const rev = await popupNovaRevisao({
      containerId: id, doc: d, arquivos,
      subtitulo: `${d.nome} · ${c.codigo ? `${c.codigo} · ` : ''}${c.nome}`,
    });
    if (rev) { P.sel = tipo; P.ver = null; await carregar(); }
  }
  P.novaRevisao = novaRevisao;

  async function acaoMenu(acao, d) {
    if (acao === 'status') {
      if (await popupStatus({ containerId: id, doc: d })) await carregar();
    } else if (acao === 'na') {
      const valor = !d.nao_se_aplica;
      if (valor && d.atual && !await confirmar(
        `Marcar "${d.nome}" como "não se aplica"? A revisão atual e os arquivos continuam onde estão.`)) return;
      await api('definir_nao_se_aplica', id, d.tipo_id, valor);
      await carregar();
    } else if (acao === 'pasta') {
      await api('abrir_pasta', id, d.tipo_id);
    }
  }

  function fecharMenus() {
    el.querySelectorAll('.menu-cartao').forEach(m => m.remove());
  }

  function ligar() {
    const grid = el.querySelector('.grid');
    grid.addEventListener('click', e => {
      const cartao = e.target.closest('.card.doc');
      if (!cartao) return;
      const d = doc(cartao.dataset.tipo);
      const item = e.target.closest('[data-acao]');
      if (item) { fecharMenus(); acaoMenu(item.dataset.acao, d); return; }
      if (e.target.closest('[data-menu]')) {
        const aberto = cartao.querySelector('.menu-cartao');
        fecharMenus();
        if (!aberto) cartao.insertAdjacentHTML('beforeend', _menuCartao(d));
        return;
      }
      if (e.target.closest('[data-marcar]')) return; // tratado no "change"
      fecharMenus();
      if (P.sel === d.tipo_id && P.ver === null) return;
      P.sel = d.tipo_id;
      P.ver = null;
      grid.querySelectorAll('.card.doc').forEach(x => x.classList.toggle('sel', x === cartao));
      desenharViewer();
    });
    grid.addEventListener('change', e => {
      const cb = e.target.closest('[data-marcar]');
      if (!cb) return;
      const tipo = cb.closest('.card.doc').dataset.tipo;
      if (cb.checked) P.marcados.add(tipo); else P.marcados.delete(tipo);
      atualizarSelecao();
    });
    el.querySelector('#pn-viewer').addEventListener('click', e => {
      const b = e.target.closest('[data-v]');
      if (!b) return;
      const d = doc(P.sel);
      if (b.dataset.v === 'nova') novaRevisao(d.tipo_id);
      else if (b.dataset.v === 'hist') popupHistorico({ containerId: id, nomesTipos: nomesTipos() }).catch(() => {});
      else if (b.dataset.v === 'pasta') api('abrir_pasta', id, d.tipo_id).catch(() => {});
      else if (b.dataset.v === 'email') _emBreve('Enviar por e-mail');
    });
    el.querySelector('#pn-email-varios').addEventListener('click', () => _emBreve('Enviar por e-mail'));
    el.querySelector('#pn-limpar').addEventListener('click', () => {
      P.marcados.clear();
      el.querySelectorAll('[data-marcar]').forEach(cb => { cb.checked = false; });
      atualizarSelecao();
    });
    const revisar = el.querySelector('#pn-revisar');
    if (revisar) revisar.addEventListener('click', () => _emBreve('Arquivos não registrados'));
    const dados = el.querySelector('#pn-dados');
    if (dados) dados.addEventListener('click', async () => {
      if (await popupDadosProjeto({ projeto: P.dados.container })) await carregar();
    });
  }

  await carregar();
};

/* ---- Arrastar e soltar (registrado uma vez) ---------------------------- */

(() => {
  let alvoDrop = null; // tipo_id do cartão sob o mouse no último drop
  const temArquivos = e => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  const cartaoEm = e => {
    const P = Orbit.painel;
    if (!P || !P.aindaAtual() || Orbit.uploadAberto) return null;
    const c = e.target.closest && e.target.closest('.card.doc');
    return c || null;
  };
  const limpar = () => document.querySelectorAll('.card.doc.alvo').forEach(x => x.classList.remove('alvo'));

  document.addEventListener('dragover', e => {
    if (!temArquivos(e)) return;
    e.preventDefault(); // sem isto o drop não acontece
    const c = cartaoEm(e);
    e.dataTransfer.dropEffect = c || Orbit.uploadAberto ? 'copy' : 'none';
    document.querySelectorAll('.card.doc.alvo').forEach(x => { if (x !== c) x.classList.remove('alvo'); });
    if (c) c.classList.add('alvo');
  });
  document.addEventListener('dragleave', e => {
    if (!e.relatedTarget) limpar(); // saiu da janela
  });
  document.addEventListener('drop', e => {
    e.preventDefault(); // nunca deixa o WebView abrir o arquivo
    const c = cartaoEm(e);
    alvoDrop = c ? c.dataset.tipo : null;
    limpar();
  });

  /* Chamada pelo Python (app.py) com os caminhos completos dos arquivos soltos. */
  window.orbitDrop = caminhos => {
    const alvo = alvoDrop;
    alvoDrop = null;
    if (Orbit.uploadAberto) {
      if (caminhos.length) Orbit.uploadAberto.adicionar(caminhos);
      return;
    }
    const P = Orbit.painel;
    if (!alvo || !P || !P.aindaAtual()) return;
    if (!caminhos.length) {
      mostrarErro('Não foi possível ler o caminho do arquivo arrastado. Use "Nova revisão" e escolha o arquivo.');
      return;
    }
    P.novaRevisao(alvo, caminhos);
  };
})();
