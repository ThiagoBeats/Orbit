/* Itens do Meu dia e anotações de projeto: desenho e ações compartilhados
 * entre a tela Início e o painel do projeto (spec Meu dia §3 e §6).
 *
 * htmlItem(it, {projeto})   linha de um item (caixinha de OK só nos tipos com OK)
 * ligarItens(raiz, recarregar)  OK, edição na linha, menu ⋯ e link do projeto
 * opcoesProjetos()          [{id, nome}] de projetos e máquinas (para os seletores)
 * montarAnotacoesProjeto(caixa, containerId)  seção "Anotações" do painel
 */

const TIPOS_ITEM = {
  atividade: 'Atividade', pesquisar: 'Pesquisar depois', definicao: 'Definição futura',
  insight: 'Insight', onde_parei: 'Onde parei',
};
const TIPOS_COM_OK = new Set(['atividade', 'pesquisar', 'definicao']);
const _CLASSE_TIPO = { pesquisar: 't-pesq', definicao: 't-def', insight: 't-ins', onde_parei: 't-par' };

function htmlItem(it, { projeto = true, autor = false } = {}) {
  const ok = TIPOS_COM_OK.has(it.tipo);
  const feito = !!it.feito_em;
  const tag = it.tipo === 'atividade' ? ''
    : `<span class="tag ${_CLASSE_TIPO[it.tipo] || ''}">${esc(TIPOS_ITEM[it.tipo])}</span>`;
  const proj = projeto && it.container_id
    ? `<a class="proj" href="${it.container_nome ? '#/projeto/' + encodeURIComponent(it.container_id) : '#'}" data-proj="${esc(it.container_id)}">${esc(it.container_nome || 'projeto')}</a>`
    : '';
  return `<div class="item${feito ? ' feito' : ''}" data-item="${esc(it.id)}" data-tipo="${esc(it.tipo)}" data-cid="${esc(it.container_id || '')}">
    ${ok ? `<button type="button" class="chk" data-ok title="${feito ? 'Desmarcar' : 'Marcar como feito'}">${feito ? '✓' : ''}</button>` : '<span class="chk vazio"></span>'}
    <div class="txt"><span class="texto" data-editar title="Clique para editar">${esc(it.texto)}</span>${tag}${proj ? `<div>${proj}</div>` : ''}${
      autor ? `<div class="texto-sec autor">${esc(it.usuario)} · ${esc(formatarDataHora(it.alterado_em))}</div>` : ''}</div>
    <button type="button" class="menu-btn" data-menu-item title="Mais ações">⋯</button>
  </div>`;
}

let _cacheProjetos = null;
async function opcoesProjetos(forcar = false) {
  if (_cacheProjetos && !forcar) return _cacheProjetos;
  const lista = [];
  for (const c of (await api('listar_clientes', '')).filter(c => !c.erro && c.id)) {
    const d = await api('obter_cliente', c.id);
    for (const p of d.projetos) if (p.id && !p.erro) lista.push({ id: p.id, nome: `${p.nome} · ${c.nome}` });
  }
  for (const m of await api('listar_maquinas')) if (m.id && !m.erro) lista.push({ id: m.id, nome: `${m.nome} · Máquina padrão` });
  _cacheProjetos = lista.sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'));
  return _cacheProjetos;
}

function _optionsProjetos(lista, selecionado) {
  return `<option value="">Sem projeto</option>` + lista.map(p =>
    `<option value="${esc(p.id)}"${p.id === selecionado ? ' selected' : ''}>${esc(p.nome)}</option>`).join('');
}

function _optionsTipos(selecionado) {
  return Object.entries(TIPOS_ITEM).map(([k, v]) =>
    `<option value="${esc(k)}"${k === selecionado ? ' selected' : ''}>${esc(v)}</option>`).join('');
}

function ligarItens(raiz, recarregar) {
  raiz.addEventListener('click', async e => {
    const linha = e.target.closest('[data-item]');
    if (!linha || !raiz.contains(linha)) return;
    const id = linha.dataset.item;
    if (e.target.closest('[data-ok]')) {
      await api('marcar_item', id, !linha.classList.contains('feito')).catch(() => {});
      recarregar();
    } else if (e.target.closest('[data-editar]')) {
      _editarNaLinha(linha, recarregar);
    } else if (e.target.closest('[data-menu-item]')) {
      _menuItem(id, linha.dataset.tipo, linha.dataset.cid || null, recarregar);
    }
  });
}

function _editarNaLinha(linha, recarregar) {
  const span = linha.querySelector('[data-editar]');
  if (!span || linha.querySelector('input.edicao')) return;
  const original = span.textContent;
  const campo = document.createElement('input');
  campo.className = 'edicao';
  campo.value = original;
  span.replaceWith(campo);
  campo.focus();
  let terminado = false;
  const terminar = async salvar => {
    if (terminado) return;
    terminado = true;
    if (salvar && campo.value.trim() && campo.value.trim() !== original) {
      await api('editar_item', linha.dataset.item, { texto: campo.value }).catch(() => {});
    }
    recarregar();
  };
  campo.addEventListener('keydown', e => {
    if (e.key === 'Enter') terminar(true);
    if (e.key === 'Escape') { e.stopPropagation(); terminar(false); }
  });
  campo.addEventListener('blur', () => terminar(true));
}

async function _menuItem(id, tipo, cid, recarregar) {
  const projetos = await opcoesProjetos();
  abrirPopup({
    titulo: 'Anotação',
    corpoHtml: `<div class="field"><label>Tipo</label><select id="mi-tipo">${_optionsTipos(tipo)}</select></div>
      <div class="field"><label>Projeto</label><select id="mi-proj">${_optionsProjetos(projetos, cid)}</select></div>
      <p class="texto-sec">Atividades são sempre suas. Anotações com projeto ficam visíveis para quem abrir o projeto.</p>`,
    botoes: [
      { texto: 'Excluir', acao: async () => {
        if (!(await confirmar('Excluir esta anotação?'))) return false;
        await api('excluir_item', id); recarregar();
      } },
      { texto: 'Cancelar' },
      { texto: 'Salvar', primario: true, acao: async popup => {
        const t = popup.elemento.querySelector('#mi-tipo').value;
        const p = popup.elemento.querySelector('#mi-proj').value || null;
        const dados = {};
        if (t !== tipo) dados.tipo = t;
        if (p !== cid) dados.container_id = p; // só manda o projeto se ele mudou
        if (Object.keys(dados).length) await api('editar_item', id, dados);
        recarregar();
      } },
    ],
  });
}

/* ---- Painel do projeto: faixa "Onde parei" + seção Anotações ---------------- */

async function montarAnotacoesProjeto(caixaFaixa, caixa, containerId) {
  const desenhar = async () => {
    const r = await api('anotacoes_projeto', containerId).catch(() => null);
    if (!r) return;
    const op = r.onde_parei;
    caixaFaixa.innerHTML = op ? `<div class="faixa-parei"><b>Onde parei:</b> ${esc(op.texto)}
      <span class="texto-sec">— ${esc(op.usuario)}, ${esc(formatarDataHora(op.alterado_em))}</span></div>` : '';
    const grupos = Object.keys(TIPOS_ITEM).filter(t => t !== 'atividade')
      .map(t => [t, r.anotacoes.filter(a => a.tipo === t)]).filter(([, l]) => l.length);
    caixa.innerHTML = `
      <div class="secao-titulo">Anotações</div>
      <div class="bloco">
        <div class="add-item">
          <input type="text" id="an-texto" maxlength="500" placeholder="Anotar sobre este projeto (Enter adiciona)">
          <select id="an-tipo">${Object.entries(TIPOS_ITEM).filter(([k]) => k !== 'atividade').map(([k, v]) =>
            `<option value="${esc(k)}"${k === 'onde_parei' ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>
        </div>
        ${grupos.length ? grupos.map(([t, lista]) => `<div class="grupo-anot"><div class="secao-sub">${esc(TIPOS_ITEM[t])}</div>
          ${lista.map(a => htmlItem(a, { projeto: false, autor: true })).join('')}</div>`).join('')
          : '<p class="texto-sec">Nenhuma anotação ainda.</p>'}
      </div>`;
    const campo = caixa.querySelector('#an-texto');
    campo.addEventListener('keydown', async e => {
      if (e.key !== 'Enter' || !campo.value.trim()) return;
      await api('adicionar_item', { texto: campo.value, tipo: caixa.querySelector('#an-tipo').value,
        container_id: containerId }).catch(() => {});
      desenhar();
    });
  };
  ligarItens(caixa, desenhar);
  await desenhar();
}
