/* Produção (spec Produção §5): Fila, Meu trabalho (bancada) e Gestão.
 *
 * Rotas: #/producao (fila)  #/producao/trabalho  #/producao/gestao  #/op/<id> (op.js)
 * Também define: seletor de operador, formulário genérico, Nova OP, importação de
 * planilha com mapeamento de colunas, a seção "Produção" do painel do projeto e
 * Configurações → Produção.
 *
 * O operador escolhido fica em Orbit.prod.operador; a Api guarda o último usado
 * nesta máquina e o devolve em prod_config().ultimo_operador.
 */

const Prod = Orbit.prod = { cfg: null, operador: null };

async function prodCfg(forcar = false) {
  if (!Prod.cfg || forcar) {
    Prod.cfg = await api('prod_config');
    if (Prod.operador === null) Prod.operador = Prod.cfg.ultimo_operador || '';
  }
  return Prod.cfg;
}

function prodNomeEtapa(id) {
  const e = Prod.cfg && Prod.cfg.etapas.find(x => x.id === id);
  return e ? e.nome : id;
}

function prodHoras(h) {
  const min = Math.round((h || 0) * 60);
  if (min < 60) return `${min} min`;
  const hh = Math.floor(min / 60), mm = min % 60;
  return mm ? `${hh} h ${String(mm).padStart(2, '0')}` : `${hh} h`;
}

function prodDesde(isoInicio, isoAgora) {
  const a = Date.parse(isoInicio), b = Date.parse(isoAgora);
  if (Number.isNaN(a) || Number.isNaN(b)) return '';
  return prodHoras(Math.max(0, b - a) / 3600000);
}

/* ---- operador ---------------------------------------------------------- */

function prodSeletorOperador(id = 'prod-operador') {
  const nomes = (Prod.cfg.operadores || []).map(o => o.nome);
  const atual = Prod.operador || '';
  if (atual && !nomes.includes(atual)) nomes.push(atual);
  return `<label class="sel-operador"><span>Operador</span>
    <select id="${id}"><option value="">— escolha —</option>
      ${nomes.map(n => `<option${n === atual ? ' selected' : ''}>${esc(n)}</option>`).join('')}
      <option value="__outro">Outro…</option></select></label>`;
}

function prodLigarSeletor(raiz, aoMudar, id = 'prod-operador') {
  const sel = raiz.querySelector(`#${id}`);
  if (!sel) return;
  sel.addEventListener('change', async () => {
    if (sel.value === '__outro') {
      const r = await prodFormulario({ titulo: 'Operador', botao: 'OK',
        campos: [{ id: 'nome', rotulo: 'Nome', obrigatorio: true }] });
      if (r) Prod.operador = r.nome;
    } else {
      Prod.operador = sel.value;
    }
    if (aoMudar) aoMudar();
  });
}

function prodExigirOperador() {
  if (Prod.operador) return Prod.operador;
  mostrarErro('Escolha o operador no topo da tela.');
  throw new ErroApi('sem operador');
}

/* ---- formulário genérico ---------------------------------------------- */
/* campos: [{id, rotulo, tipo:'text'|'textarea'|'select'|'numero'|'date'|'datetime'|'checkbox',
 *           opcoes:[{valor,texto}|string], valor, obrigatorio, dica}] -> Promise<obj|null> */
function prodFormulario({ titulo, subtitulo = '', campos, botao = 'Salvar', classe = '', intro = '' }) {
  return new Promise(resolve => {
    let res = null;
    const campo = c => {
      const v = c.valor ?? '';
      let input;
      if (c.tipo === 'textarea') input = `<textarea data-campo="${c.id}" rows="${c.linhas || 3}">${esc(v)}</textarea>`;
      else if (c.tipo === 'select') input = `<select data-campo="${c.id}">${c.opcoes.map(o => {
        const val = typeof o === 'string' ? o : o.valor, txt = typeof o === 'string' ? o : o.texto;
        return `<option value="${esc(val)}"${String(val) === String(v) ? ' selected' : ''}>${esc(txt)}</option>`;
      }).join('')}</select>`;
      else if (c.tipo === 'checkbox') return `<div class="field"><label class="ativo-cfg"><input type="checkbox" data-campo="${c.id}"${v ? ' checked' : ''}> ${esc(c.rotulo)}</label></div>`;
      else {
        const tipo = c.tipo === 'date' ? 'date' : c.tipo === 'datetime' ? 'datetime-local' : 'text';
        const extra = c.tipo === 'numero' ? ' inputmode="decimal"' : '';
        input = `<input type="${tipo}" data-campo="${c.id}" value="${esc(v)}"${extra} maxlength="300">`;
      }
      return `<div class="field"><label>${esc(c.rotulo)}${c.obrigatorio ? ' *' : ''}</label>${input}${
        c.dica ? `<div class="dica">${esc(c.dica)}</div>` : ''}</div>`;
    };
    const p = abrirPopup({
      titulo, subtitulo, classe,
      corpoHtml: (intro ? `<p class="texto-sec">${intro}</p>` : '') + campos.map(campo).join(''),
      botoes: [{ texto: 'Cancelar' }, { texto: botao, primario: true, acao: popup => {
        const v = {};
        for (const c of campos) {
          const e = popup.elemento.querySelector(`[data-campo="${c.id}"]`);
          let x = c.tipo === 'checkbox' ? e.checked : e.value.trim();
          if (c.tipo === 'numero') x = x === '' ? null : Number(x.replace(/\./g, x.includes(',') ? '' : '.').replace(',', '.'));
          if (c.tipo === 'numero' && x !== null && Number.isNaN(x)) {
            mostrarErro(`Número inválido em "${c.rotulo}".`); return false;
          }
          if (c.obrigatorio && (x === '' || x === null)) { mostrarErro(`Preencha "${c.rotulo}".`); return false; }
          v[c.id] = x;
        }
        res = v;
        return undefined;
      } }],
    });
    p._aoFechar = () => resolve(res);
  });
}

/* ---- cartão de OP ------------------------------------------------------ */

function prodChipsOp(c) {
  const chips = [];
  if (c.bloqueio) chips.push(`<span class="chip pend" title="${esc(c.bloqueio.motivo)}">Bloqueada</span>`);
  if (c.atrasada) chips.push(`<span class="chip pend">Atrasada</span>`);
  if (c.prioridade === 'urgente') chips.push('<span class="chip pend">Urgente</span>');
  else if (c.prioridade === 'alta') chips.push('<span class="chip warn">Alta</span>');
  if (c.revisao_nova) chips.push('<span class="chip warn">Revisão nova</span>');
  if (c.faltas) chips.push(`<span class="chip pend">Falta de material (${esc(c.faltas)})</span>`);
  if (c.ncs_abertas) chips.push(`<span class="chip warn">${esc(c.ncs_abertas)} NC</span>`);
  return chips.join('');
}

function prodCartaoOp(c, { etapa = false, projeto = true } = {}) {
  const quem = c.trabalhando.length ? `<div class="op-quem cor-ok">● ${esc(c.trabalhando.join(', '))}</div>`
    : c.parados.length ? `<div class="op-quem cor-warn">❚❚ ${esc(c.parados.join(', '))}</div>` : '';
  return `<a class="card cartao-op prio-${esc(c.prioridade)}" href="#/op/${encodeURIComponent(c.id)}">
    <div class="op-num">${esc(c.numero)}${etapa ? ` · ${esc(c.nome_etapa)}` : ''}</div>
    <div class="op-painel">${esc(c.painel)}${c.quantidade > 1 ? ` <span class="texto-sec">×${esc(c.quantidade)}</span>` : ''}</div>
    ${projeto ? `<div class="op-proj">${esc([c.cliente_nome, c.container_nome].filter(Boolean).join(' · '))}</div>` : ''}
    <div class="op-prazo">${c.prazo ? `Prazo ${esc(formatarDataCurta(c.prazo))}` : 'Sem prazo'}</div>
    <div class="chips">${prodChipsOp(c)}</div>${quem}</a>`;
}

/* ---- barras simples (uma série, rótulo e valor em texto) ---------------- */

function prodBarras(itens, formatar = v => v) {
  if (!itens.length) return '<p class="texto-sec">Sem dados.</p>';
  const max = Math.max(...itens.map(i => i.valor), 0) || 1;
  return `<div class="barras">${itens.map(i => `
    <div class="barra-linha" title="${esc(i.rotulo)}: ${esc(formatar(i.valor))}">
      <span class="barra-rot">${esc(i.rotulo)}</span>
      <span class="barra-trilho"><span class="barra-val" style="width:${i.valor ? Math.max(2, i.valor / max * 100).toFixed(1) : 0}%"></span></span>
      <span class="barra-num">${esc(formatar(i.valor))}</span></div>`).join('')}</div>`;
}

/* ---- Nova OP ----------------------------------------------------------- */

async function popupNovaOp(containerId) {
  const cfg = await prodCfg();
  const r = await prodFormulario({
    titulo: 'Nova ordem de produção', botao: 'Criar OP',
    campos: [
      { id: 'painel', rotulo: 'Painel (tag/nome)', obrigatorio: true, dica: 'Ex.: QGBT-01, CCM-02' },
      { id: 'descricao', rotulo: 'Descrição' },
      { id: 'quantidade', rotulo: 'Quantidade', tipo: 'numero', valor: 1 },
      { id: 'prioridade', rotulo: 'Prioridade', tipo: 'select', valor: 'normal',
        opcoes: cfg.prioridades.map(p => ({ valor: p, texto: p[0].toUpperCase() + p.slice(1) })) },
      { id: 'prazo', rotulo: 'Prazo', tipo: 'date' },
      { id: 'responsavel', rotulo: 'Responsável', valor: cfg.usuario },
    ],
  });
  if (!r) return null;
  r.quantidade = r.quantidade || 1;
  r.prazo = r.prazo || null;
  const op = await api('prod_criar_op', containerId, r);
  irPara(`#/op/${encodeURIComponent(op.id)}`);
  return op;
}

/* ---- importação de planilha com mapeamento ----------------------------- */

const _TITULO_IMPORT = { materiais: 'Lista de materiais', ponto_a_ponto: 'Lista de conexões (ponto a ponto)',
  io: 'Lista de entradas e saídas' };

async function prodImportarPlanilha(opId, destino, jaTem) {
  const info = await api('prod_escolher_planilha', destino);
  if (!info) return null;
  return new Promise(resolve => {
    let total = null;
    const colunas = info.cabecalho.map((h, i) => ({ valor: i, texto: `${String.fromCharCode(65 + (i % 26))}${i >= 26 ? Math.floor(i / 26) : ''} · ${h || '(sem título)'}` }));
    const sel = c => `<div class="field"><label>${esc(c.nome)}${c.obrigatorio ? ' *' : ''}</label>
      <select data-col="${esc(c.id)}"><option value="">— não usar —</option>${colunas.map(o =>
        `<option value="${o.valor}"${info.sugestao[c.id] === o.valor ? ' selected' : ''}>${esc(o.texto)}</option>`).join('')}</select></div>`;
    const previa = `<div class="tabela-rolagem"><table class="tabela tabela-previa"><tr>${info.cabecalho.map(h => `<th>${esc(h)}</th>`).join('')}</tr>
      ${info.amostra.map(l => `<tr>${l.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</table></div>`;
    const p = abrirPopup({
      titulo: _TITULO_IMPORT[destino], subtitulo: `${info.nome} · ${info.total} linhas`, classe: 'largo',
      corpoHtml: `<p class="texto-sec">Escolha qual coluna da planilha corresponde a cada campo. O Orbit já sugeriu pelo título das colunas.</p>
        <div class="grade-campos">${info.campos.map(sel).join('')}</div>
        <div class="secao-sub">Primeiras linhas</div>${previa}
        ${jaTem ? `<div class="field"><label class="ativo-cfg"><input type="checkbox" id="imp-subst"> Substituir a lista atual (a anterior fica guardada no histórico)</label></div>` : ''}`,
      botoes: [{ texto: 'Cancelar' }, { texto: 'Importar', primario: true, acao: async popup => {
        const mapa = {};
        popup.elemento.querySelectorAll('[data-col]').forEach(s => {
          mapa[s.dataset.col] = s.value === '' ? null : Number(s.value);
        });
        const subst = !!(popup.elemento.querySelector('#imp-subst') || {}).checked;
        total = await api('prod_importar_planilha', opId, destino, info.caminho, mapa, subst);
      } }],
    });
    p._aoFechar = () => resolve(total);
  });
}

/* ---- tela Produção ----------------------------------------------------- */

Orbit.views.producao = async (conteudo, aba, aindaAtual) => {
  aba = ['trabalho', 'gestao'].includes(aba) ? aba : 'fila';
  await prodCfg(true);
  if (!aindaAtual()) return;
  const el = document.createElement('div');
  conteudo.appendChild(el);
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <div class="titulo-painel"><h1>Produção</h1>${aba === 'trabalho' ? prodSeletorOperador() : ''}</div>
    <div class="abas">
      <a href="#/producao" class="${aba === 'fila' ? 'on' : ''}">Fila</a>
      <a href="#/producao/trabalho" class="${aba === 'trabalho' ? 'on' : ''}">Meu trabalho</a>
      <a href="#/producao/gestao" class="${aba === 'gestao' ? 'on' : ''}">Gestão</a>
    </div>
    <div id="prod-corpo"></div>`;
  const corpo = el.querySelector('#prod-corpo');
  if (aba === 'fila') await _prodFila(corpo, aindaAtual);
  else if (aba === 'trabalho') {
    prodLigarSeletor(el, () => _prodTrabalho(corpo, aindaAtual));
    await _prodTrabalho(corpo, aindaAtual);
  } else await _prodGestao(corpo, aindaAtual);
};

let _prodExpedidas = false;

async function _prodFila(corpo, aindaAtual) {
  const cards = await api('prod_fila', _prodExpedidas);
  if (!aindaAtual()) return;
  const etapas = Prod.cfg.etapas.filter(e => _prodExpedidas || e.id !== 'expedida');
  corpo.innerHTML = `
    <div class="barra"><span class="texto-sec">${cards.length} OP${cards.length === 1 ? '' : 's'} · ordenadas por prioridade e prazo. Para criar uma OP, abra o projeto e use "Nova OP".</span>
      <label class="ativo-cfg"><input type="checkbox" id="pf-exp"${_prodExpedidas ? ' checked' : ''}> Mostrar expedidas</label></div>
    <div class="kanban">${etapas.map(e => {
      const doEstagio = cards.filter(c => c.etapa === e.id);
      return `<div class="kanban-col"><div class="kanban-cab">${esc(e.nome)} <span>${doEstagio.length}</span></div>
        ${doEstagio.map(c => prodCartaoOp(c)).join('') || '<div class="kanban-vazio">—</div>'}</div>`;
    }).join('')}</div>`;
  corpo.querySelector('#pf-exp').addEventListener('change', e => {
    _prodExpedidas = e.target.checked;
    _prodFila(corpo, aindaAtual);
  });
}

let _prodTimer = null;

async function _prodTrabalho(corpo, aindaAtual) {
  if (_prodTimer) { clearInterval(_prodTimer); _prodTimer = null; }
  const op = Prod.operador;
  const d = await api('prod_meu_trabalho', op || null);
  if (!aindaAtual()) return;
  const ab = d.aberto;
  let topo;
  if (!op) {
    topo = '<div class="bloco bancada"><p class="texto-sec">Escolha seu nome no topo (Operador) para começar.</p></div>';
  } else if (ab) {
    const a = ab.apontamento, parado = a.tipo === 'parada';
    topo = `<div class="bloco bancada ${parado ? 'parado' : 'trabalhando'}">
      <div class="bancada-estado">${parado ? `PARADO · ${esc(a.motivo)}` : 'TRABALHANDO'}</div>
      <div class="bancada-op"><a href="#/op/${encodeURIComponent(ab.op.id)}">${esc(ab.op.numero)} · ${esc(ab.op.painel)}</a>
        <span class="texto-sec">${esc(prodNomeEtapa(a.etapa))} · desde ${esc(formatarDataHora(a.inicio).slice(-5))}
        (<span id="bt-tempo">${esc(prodDesde(a.inicio, d.agora))}</span>)</span></div>
      ${a.obs ? `<div class="texto-sec">${esc(a.obs)}</div>` : ''}
      <div class="bancada-botoes">
        ${parado ? '<button type="button" class="btn grande solid" id="bt-retomar">Retomar</button>'
          : '<button type="button" class="btn grande" id="bt-pausar">Pausar com motivo</button>'}
        <button type="button" class="btn grande" id="bt-encerrar">Encerrar</button>
        <a class="btn grande" href="#/op/${encodeURIComponent(ab.op.id)}">Abrir OP</a></div></div>`;
  } else {
    topo = `<div class="bloco bancada"><div class="bancada-estado">SEM APONTAMENTO ABERTO</div>
      <p class="texto-sec">Escolha uma OP abaixo e toque em "Iniciar".</p></div>`;
  }
  const hoje = d.hoje ? `<div class="stats sem-pad">
      <div class="stat"><div class="v">${esc(prodHoras(d.hoje.trabalho_h))}</div><div class="l">Trabalho hoje</div></div>
      <div class="stat"><div class="v">${esc(prodHoras(d.hoje.parada_h))}</div><div class="l">Paradas hoje</div></div></div>` : '';
  corpo.innerHTML = `<div class="pagina">${topo}${hoje}
    <div class="secao-titulo">OPs na produção</div>
    <div class="grid-cartoes">${d.disponiveis.map(c => `<div class="cartao-iniciar">${prodCartaoOp(c, { etapa: true })}
      ${ab && ab.op.id === c.id ? '<div class="texto-sec centro">Em andamento</div>'
        : `<button type="button" class="btn grande solid" data-iniciar="${esc(c.id)}"${op ? '' : ' disabled'}>Iniciar</button>`}</div>`).join('')
      || '<p class="texto-sec">Nenhuma OP liberada para a produção.</p>'}</div></div>`;
  const rec = () => _prodTrabalho(corpo, aindaAtual);
  corpo.querySelectorAll('[data-iniciar]').forEach(b => b.addEventListener('click', async () => {
    await api('prod_iniciar', b.dataset.iniciar, prodExigirOperador(), '');
    rec();
  }));
  const pausar = corpo.querySelector('#bt-pausar');
  if (pausar) pausar.addEventListener('click', async () => {
    const r = await prodFormulario({ titulo: 'Pausar com motivo', botao: 'Pausar',
      campos: [{ id: 'motivo', rotulo: 'Motivo', tipo: 'select', opcoes: Prod.cfg.motivos_parada, valor: Prod.cfg.motivos_parada[0] },
        { id: 'obs', rotulo: 'Observação', dica: 'Ex.: qual material falta, o que está aguardando' }] });
    if (!r) return;
    await api('prod_pausar', op, r.motivo, r.obs);
    rec();
  });
  const retomar = corpo.querySelector('#bt-retomar');
  if (retomar) retomar.addEventListener('click', async () => { await api('prod_retomar', op); rec(); });
  const enc = corpo.querySelector('#bt-encerrar');
  if (enc) enc.addEventListener('click', async () => {
    const r = await prodFormulario({ titulo: 'Encerrar apontamento', botao: 'Encerrar',
      campos: [{ id: 'obs', rotulo: 'Observação (opcional)' }] });
    if (!r) return;
    await api('prod_encerrar', op, r.obs);
    rec();
  });
  if (ab) {
    const inicio = Date.parse(ab.apontamento.inicio), base = Date.now() - (Date.parse(d.agora) - inicio);
    _prodTimer = setInterval(() => {
      const t = document.getElementById('bt-tempo');
      if (!aindaAtual() || !t) { clearInterval(_prodTimer); _prodTimer = null; return; }
      t.textContent = prodHoras((Date.now() - base) / 3600000);
    }, 30000);
  }
}

async function _prodGestao(corpo, aindaAtual) {
  const g = await api('prod_gestao');
  if (!aindaAtual()) return;
  const ativas = g.por_etapa.filter(e => e.etapa !== 'expedida').reduce((s, e) => s + e.n, 0);
  const sem = g.semana;
  const ops = Object.entries(sem.por_operador).map(([nome, v]) => ({ nome, ...v }))
    .sort((a, b) => b.trabalho_h - a.trabalho_h);
  const refOp = o => `<a href="#/op/${encodeURIComponent(o.id || o.op_id)}">${esc(o.numero || o.op_numero)}</a> · ${esc(o.painel)}`;
  corpo.innerHTML = `
    <div class="stats">
      <div class="stat"><div class="v">${ativas}</div><div class="l">OPs abertas</div></div>
      <div class="stat"><div class="v ${g.atrasadas.length ? 'cor-pend' : ''}">${g.atrasadas.length}</div><div class="l">Atrasadas</div></div>
      <div class="stat"><div class="v">${esc(prodHoras(sem.trabalho_h))}</div><div class="l">Trabalho na semana</div></div>
      <div class="stat"><div class="v ${sem.parada_h ? 'cor-warn' : ''}">${esc(prodHoras(sem.parada_h))}</div><div class="l">Paradas na semana</div></div>
      <div class="stat"><div class="v ${g.ncs_abertas ? 'cor-warn' : ''}">${g.ncs_abertas}</div><div class="l">NCs abertas</div></div>
      <div class="stat"><div class="v ${g.faltas.length ? 'cor-pend' : ''}">${g.faltas.length}</div><div class="l">Itens em falta</div></div>
    </div>
    <main class="gestao">
      <div class="bloco"><div class="cab-painel"><span>OPs por etapa</span></div>
        ${prodBarras(g.por_etapa.map(e => ({ rotulo: e.nome, valor: e.n })))}</div>
      <div class="bloco"><div class="cab-painel"><span>Paradas na semana por motivo</span></div>
        ${prodBarras(Object.entries(sem.por_motivo).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ rotulo: k, valor: v })), prodHoras)}</div>
      <div class="bloco"><div class="cab-painel"><span>Não conformidades por tipo (Pareto)</span></div>
        ${prodBarras(g.pareto_nc.map(x => ({ rotulo: x.tipo, valor: x.n })))}</div>
      <div class="bloco"><div class="cab-painel"><span>Horas por operador (semana)</span></div>
        ${ops.length ? `<table class="tabela"><tr><th>Operador</th><th>Trabalho</th><th>Paradas</th><th>Ociosidade</th></tr>
          ${ops.map(o => `<tr><td>${esc(o.nome)}</td><td>${esc(prodHoras(o.trabalho_h))}</td><td>${esc(prodHoras(o.parada_h))}</td>
            <td>${o.trabalho_h + o.parada_h ? Math.round(o.parada_h / (o.trabalho_h + o.parada_h) * 100) : 0}%</td></tr>`).join('')}</table>`
          : '<p class="texto-sec">Sem apontamentos nesta semana.</p>'}</div>
      <div class="bloco largo"><div class="cab-painel"><span>Apontamentos abertos há mais de 10 h</span></div>
        ${g.esquecidos.length ? `<table class="tabela"><tr><th>Operador</th><th>OP</th><th>Desde</th><th>Aberto há</th><th></th></tr>
          ${g.esquecidos.map((a, i) => `<tr class="linha-alerta"><td>${esc(a.operador)}</td><td>${refOp(a)}</td>
            <td>${esc(formatarDataHora(a.inicio))}</td><td>${esc(prodHoras(a.aberto_h))}</td>
            <td><button type="button" class="btn pequeno" data-corrigir="${i}">Corrigir</button></td></tr>`).join('')}</table>`
          : '<p class="texto-sec">Nenhum.</p>'}</div>
      <div class="bloco largo"><div class="cab-painel"><span>Faltas de material</span></div>
        ${g.faltas.length ? `<table class="tabela"><tr><th>OP</th><th>Item</th><th>Qtd</th><th>Obs.</th><th>Previsão</th></tr>
          ${g.faltas.map(f => `<tr><td>${refOp(f)}</td><td>${esc([f.item.codigo, f.item.descricao].filter(Boolean).join(' — '))}</td>
            <td>${esc(f.item.quantidade)} ${esc(f.item.unidade)}</td><td>${esc(f.item.obs)}</td>
            <td>${esc(f.item.previsao ? formatarDataCurta(f.item.previsao) : '—')}</td></tr>`).join('')}</table>`
          : '<p class="texto-sec">Nenhuma falta registrada.</p>'}</div>
      <div class="bloco"><div class="cab-painel"><span>Atrasadas</span></div>
        ${g.atrasadas.map(o => `<div class="linha-lista">${refOp(o)} <span class="texto-sec">· ${esc(o.nome_etapa)} · prazo ${esc(formatarDataCurta(o.prazo))}</span></div>`).join('') || '<p class="texto-sec">Nenhuma.</p>'}</div>
      <div class="bloco"><div class="cab-painel"><span>Bloqueadas</span></div>
        ${g.bloqueadas.map(o => `<div class="linha-lista">${refOp(o)} <span class="texto-sec">· ${esc(o.bloqueio.motivo)}</span></div>`).join('') || '<p class="texto-sec">Nenhuma.</p>'}</div>
      <div class="bloco largo"><div class="cab-painel"><span>Agora na produção</span></div>
        ${g.em_andamento.map(a => `<div class="linha-lista"><b>${esc(a.operador)}</b> · ${refOp(a)} ·
          <span class="${a.tipo === 'parada' ? 'cor-warn' : 'cor-ok'}">${a.tipo === 'parada' ? `parado (${esc(a.motivo)})` : 'trabalhando'}</span>
          <span class="texto-sec">desde ${esc(formatarDataHora(a.inicio))}</span></div>`).join('') || '<p class="texto-sec">Ninguém com apontamento aberto.</p>'}</div>
    </main>`;
  corpo.querySelectorAll('[data-corrigir]').forEach(b => b.addEventListener('click', async () => {
    const a = g.esquecidos[+b.dataset.corrigir];
    if (await prodCorrigirApontamento(a.op_id, a)) _prodGestao(corpo, aindaAtual);
  }));
}

async function prodCorrigirApontamento(opId, a) {
  const r = await prodFormulario({
    titulo: 'Corrigir apontamento', subtitulo: `${a.operador} · ${a.tipo === 'parada' ? `parada (${a.motivo})` : 'trabalho'}`,
    intro: 'Fica registrado quem corrigiu e os horários anteriores.', botao: 'Salvar',
    campos: [{ id: 'inicio', rotulo: 'Início', tipo: 'datetime', valor: (a.inicio || '').slice(0, 16), obrigatorio: true },
      { id: 'fim', rotulo: 'Fim', tipo: 'datetime', valor: (a.fim || '').slice(0, 16), dica: 'Vazio = continua aberto' }],
  });
  if (!r) return false;
  const seg = v => v ? (v.length === 16 ? `${v}:00` : v) : null;
  await api('prod_editar_apontamento', opId, a.id, seg(r.inicio), seg(r.fim));
  return true;
}

/* ---- seção "Produção" no painel do projeto ------------------------------ */

async function montarProducaoProjeto(caixa, containerId) {
  const cards = await api('prod_ops_projeto', containerId).catch(() => null);
  if (cards === null) return;
  await prodCfg();
  caixa.innerHTML = `
    <div class="secao-titulo">Produção</div>
    <div class="bloco">
      <div class="linha-cfg"><span class="texto-sec" style="flex:1">Ordens de produção dos painéis deste projeto: documentos liberados para a bancada, materiais, testes e horas.</span>
        <button type="button" class="btn solid" id="pp-nova">Nova OP</button></div>
      ${cards.length ? `<div class="grid-cartoes">${cards.map(c => prodCartaoOp(c, { etapa: true, projeto: false })).join('')}</div>`
        : '<p class="texto-sec">Nenhuma OP ainda.</p>'}
    </div>`;
  caixa.querySelector('#pp-nova').addEventListener('click', () => popupNovaOp(containerId).catch(() => {}));
}

/* ---- Configurações → Produção ------------------------------------------ */

async function montarConfigProducao(pagina) {
  const cfg = await prodCfg(true).catch(() => null);
  if (!cfg) return;
  const sec = document.createElement('div');
  pagina.appendChild(sec);
  let operadores = cfg.operadores.map(o => ({ ...o }));
  const linhas = l => l.join('\n');
  sec.innerHTML = `
    <div class="secao-titulo">Produção</div>
    <div class="bloco">
      <div class="secao-sub">Operadores</div>
      <div class="texto-sec">Quem aponta horas e faz testes na bancada. Só quem tem "Faz verificação final" pode conferir a amostragem (e nunca a mesma pessoa que fez o ponto a ponto).</div>
      <div id="cp-ops" class="lista-cfg"></div>
      <div class="linha-cfg"><input type="text" id="cp-op-novo" maxlength="60" placeholder="Nome do operador">
        <button type="button" class="btn pequeno" id="cp-op-add">Adicionar</button></div>
      <div class="grade-campos">
        <div class="field"><label>Motivos de parada (um por linha)</label><textarea id="cp-motivos" rows="6">${esc(linhas(cfg.motivos_parada))}</textarea></div>
        <div class="field"><label>Tipos de não conformidade (um por linha)</label><textarea id="cp-tipos" rows="6">${esc(linhas(cfg.tipos_nc))}</textarea></div>
      </div>
      <div class="field"><label>Checklist de inspeção — IEC 61439-1 §11 (uma linha por item: referência | texto)</label>
        <textarea id="cp-check" rows="8">${esc(cfg.checklist_iec.map(i => `${i.ref} | ${i.texto}`).join('\n'))}</textarea>
        <div class="dica">Vale para OPs novas (ou que ainda não abriram a inspeção).</div></div>
      <div class="field"><label>Passos da energização (um por linha)</label><textarea id="cp-passos" rows="5">${esc(linhas(cfg.passos_energizacao))}</textarea></div>
      <div class="grade-campos cinco">
        <div class="field"><label>Isolação mínima (MΩ)</label><input type="text" inputmode="decimal" id="cp-iso" value="${esc(cfg.isolacao_min_mohm)}"></div>
        <div class="field"><label>Tensão de ensaio (V)</label><input type="text" inputmode="numeric" id="cp-isov" value="${esc(cfg.isolacao_tensao_v)}"></div>
        <div class="field"><label>Tolerância de tensão (±%)</label><input type="text" inputmode="decimal" id="cp-tol" value="${esc(cfg.tolerancia_tensao_pct)}"></div>
        <div class="field"><label>Amostragem (%)</label><input type="text" inputmode="decimal" id="cp-amo" value="${esc(cfg.amostragem_pct)}"></div>
        <div class="field"><label>Mínimo de ligações</label><input type="text" inputmode="numeric" id="cp-amomin" value="${esc(cfg.amostragem_min)}"></div>
      </div>
      <button type="button" class="btn solid" id="cp-salvar">Salvar produção</button>
    </div>`;
  const desenharOps = () => {
    sec.querySelector('#cp-ops').innerHTML = operadores.map((o, i) => `
      <div class="linha-cfg" data-i="${i}"><input type="text" class="cp-nome" maxlength="60" value="${esc(o.nome)}">
        <label class="ativo-cfg"><input type="checkbox" class="cp-ver"${o.verifica ? ' checked' : ''}> Faz verificação final</label>
        <button type="button" class="btn pequeno cp-rem">Remover</button></div>`).join('')
      || '<p class="texto-sec">Nenhum operador cadastrado (dá para digitar o nome na hora).</p>';
    sec.querySelectorAll('#cp-ops .linha-cfg').forEach(l => {
      const o = operadores[+l.dataset.i];
      l.querySelector('.cp-nome').addEventListener('input', e => { o.nome = e.target.value; });
      l.querySelector('.cp-ver').addEventListener('change', e => { o.verifica = e.target.checked; });
      l.querySelector('.cp-rem').addEventListener('click', () => { operadores.splice(+l.dataset.i, 1); desenharOps(); });
    });
  };
  desenharOps();
  sec.querySelector('#cp-op-add').addEventListener('click', () => {
    const c = sec.querySelector('#cp-op-novo');
    if (!c.value.trim()) return;
    operadores.push({ nome: c.value.trim(), verifica: false });
    c.value = '';
    desenharOps();
  });
  const lista = id => sec.querySelector(id).value.split('\n').map(x => x.trim()).filter(Boolean);
  const num = id => Number(sec.querySelector(id).value.trim().replace(',', '.'));
  sec.querySelector('#cp-salvar').addEventListener('click', async () => {
    const dados = {
      operadores, motivos_parada: lista('#cp-motivos'), tipos_nc: lista('#cp-tipos'),
      passos_energizacao: lista('#cp-passos'),
      checklist_iec: lista('#cp-check').map(l => {
        const i = l.indexOf('|');
        return i >= 0 ? { ref: l.slice(0, i).trim(), texto: l.slice(i + 1).trim() } : { ref: '—', texto: l };
      }),
      isolacao_min_mohm: num('#cp-iso'), isolacao_tensao_v: Math.round(num('#cp-isov')),
      tolerancia_tensao_pct: num('#cp-tol'), amostragem_pct: num('#cp-amo'),
      amostragem_min: Math.round(num('#cp-amomin')),
    };
    Prod.cfg = await api('prod_salvar_config', dados);
    operadores = Prod.cfg.operadores.map(o => ({ ...o }));
    desenharOps();
    abrirPopup({ titulo: 'Produção', corpoHtml: '<p>Configurações da produção salvas.</p>', botoes: [{ texto: 'OK', primario: true }] });
  });
}
