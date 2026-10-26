/* Tela da OP (spec Produção §5): Resumo, Documentos, Materiais, Testes, NCs,
 * Apontamentos e Relatório. Rota #/op/<id>.
 *
 * Estado: O = {id, d (prod_obter_op), aba}. A aba escolhida fica guardada por OP
 * enquanto o Orbit está aberto. Marcações do ponto a ponto atualizam só a linha
 * (listas grandes); o resto recarrega a OP inteira.
 */

const _abaOp = {};
const _ABAS_OP = [['resumo', 'Resumo'], ['documentos', 'Documentos'], ['materiais', 'Materiais'],
  ['testes', 'Testes'], ['ncs', 'NCs'], ['apontamentos', 'Apontamentos'], ['relatorio', 'Relatório']];
const _RES = { ok: 'OK', nc: 'NC', na: 'N/A' };
const _ESTADO_BLOCO = { concluido: ['ok', 'Concluído'], em_andamento: ['warn', 'Em andamento'],
  nao_iniciado: ['', 'Não iniciado'] };
const _SIT_NC = { aberta: ['pend', 'Aberta'], corrigida: ['warn', 'Corrigida — aguarda reteste'],
  verificada: ['ok', 'Verificada'] };
const _COR_MAT = { pendente: '', solicitado: 'info', recebido: 'ok', separado: 'ok', falta: 'pend' };

function _seg(nome, atual, opcoes = ['ok', 'nc', 'na'], extra = '') {
  return `<span class="seg" data-seg="${esc(nome)}" ${extra}>${opcoes.map(o =>
    `<button type="button" data-val="${o}" class="${atual === o ? `on ${o}` : ''}">${_RES[o]}</button>`).join('')}</span>`;
}

function _chipEstado(st) {
  const [cls, txt] = _ESTADO_BLOCO[st.estado];
  return `<span class="chip ${cls}">${txt} · ${st.feitos}/${st.total}</span>${st.nc ? ` <span class="chip pend">${st.nc} NC</span>` : ''}`;
}

Orbit.views.op = async (conteudo, id, aindaAtual) => {
  await prodCfg(true);
  if (!aindaAtual()) return;
  const el = document.createElement('div');
  conteudo.appendChild(el);
  const O = { id, d: null, aba: _abaOp[id] || 'resumo', filtroPP: 'pendentes', buscaPP: '', filtroMat: '' };

  async function carregar() {
    const d = await api('prod_obter_op', id);
    if (!aindaAtual()) return;
    O.d = d;
    desenhar();
  }

  function desenhar() {
    const { op, cartao: c, container: ct } = O.d;
    const crumbProj = ct.tipo === 'maquina' ? `#/maquina/${encodeURIComponent(ct.id)}` : `#/projeto/${encodeURIComponent(ct.id)}`;
    el.innerHTML = `
      <div class="crumb"><a href="#/producao">Produção</a> / <a href="${crumbProj}">${esc([op.cliente_nome, ct.nome].filter(Boolean).join(' · '))}</a> / ${esc(op.numero)}</div>
      <div class="titulo-painel"><h1>${esc(op.numero)} · ${esc(op.painel)}</h1>${prodSeletorOperador('op-operador')}</div>
      <div class="etapas-op">${Prod.cfg.etapas.map((e, i) => {
        const atual = Prod.cfg.etapas.findIndex(x => x.id === op.etapa);
        return `<span class="etapa ${i < atual ? 'feita' : i === atual ? 'atual' : ''}">${esc(e.nome)}</span>`;
      }).join('')}</div>
      ${op.bloqueio ? `<div class="faixa-aviso erro"><span><b>Bloqueada:</b> ${esc(op.bloqueio.motivo)} · desde ${esc(formatarDataHora(op.bloqueio.desde))} (${esc(op.bloqueio.por)})</span>
        <button type="button" class="btn pequeno" id="op-desbloq">Desbloquear</button></div>` : ''}
      ${O.d.alertas.length ? `<div class="faixa-aviso"><span>Revisão nova no projeto: ${O.d.alertas.map(a =>
        `${esc(a.nome)} (liberada ${formatarRev(a.liberada)}, atual ${formatarRev(a.atual)})`).join('; ')}. A bancada continua vendo a revisão liberada.</span>
        <button type="button" class="btn pequeno" id="op-atualizar-pac">Atualizar pacote</button></div>` : ''}
      ${c.faltas ? `<div class="faixa-aviso erro"><span>Falta de material (${c.faltas} ${c.faltas === 1 ? 'item' : 'itens'})</span>
        <button type="button" class="btn pequeno" data-ir-aba="materiais">Ver materiais</button></div>` : ''}
      <div class="abas">${_ABAS_OP.map(([k, t]) => `<a href="#" data-aba="${k}" class="${O.aba === k ? 'on' : ''}">${t}${
        k === 'ncs' && c.ncs_abertas ? ` (${c.ncs_abertas})` : ''}</a>`).join('')}</div>
      <div class="pagina" id="op-corpo"></div>`;
    prodLigarSeletor(el, () => desenhar(), 'op-operador');
    el.querySelectorAll('[data-aba]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); irAba(a.dataset.aba); }));
    el.querySelectorAll('[data-ir-aba]').forEach(a => a.addEventListener('click', () => irAba(a.dataset.irAba)));
    const db = el.querySelector('#op-desbloq');
    if (db) db.addEventListener('click', async () => { await api('prod_desbloquear', id); carregar(); });
    const ap = el.querySelector('#op-atualizar-pac');
    if (ap) ap.addEventListener('click', atualizarPacote);
    const corpo = el.querySelector('#op-corpo');
    ({ resumo, documentos, materiais: abaMateriais, testes, ncs, apontamentos, relatorio })[O.aba](corpo);
  }

  function irAba(k) { O.aba = _abaOp[id] = k; desenhar(); }

  async function atualizarPacote() {
    if (!await confirmar('Trocar os documentos do pacote pelas revisões atuais do projeto? A troca fica no histórico da OP.')) return;
    await api('prod_atualizar_pacote', id);
    carregar();
  }

  /* ---------- Resumo ---------- */
  function resumo(corpo) {
    const { op, cartao: c, horas, pendencias: pend } = O.d;
    const i = Prod.cfg.etapas.findIndex(x => x.id === op.etapa);
    const prox = Prod.cfg.etapas[i + 1];
    corpo.innerHTML = `
      <div class="stats sem-pad">
        <div class="stat"><div class="v">${esc(prodNomeEtapa(op.etapa))}</div><div class="l">Etapa</div></div>
        <div class="stat"><div class="v ${c.atrasada ? 'cor-pend' : ''}">${esc(op.prazo ? formatarDataCurta(op.prazo) : '—')}</div><div class="l">Prazo</div></div>
        <div class="stat"><div class="v">${esc(op.prioridade)}</div><div class="l">Prioridade</div></div>
        <div class="stat"><div class="v">${esc(prodHoras(horas.trabalho_h))}</div><div class="l">Horas trabalhadas</div></div>
        <div class="stat"><div class="v ${horas.parada_h ? 'cor-warn' : ''}">${esc(prodHoras(horas.parada_h))}</div><div class="l">Paradas</div></div>
        <div class="stat"><div class="v ${c.ncs_abertas ? 'cor-warn' : ''}">${c.ncs_abertas}</div><div class="l">NCs abertas</div></div>
      </div>
      <div class="bloco">
        <table class="detalhe-op">
          <tr><td>Descrição</td><td>${esc(op.descricao || '—')}</td></tr>
          <tr><td>Quantidade</td><td>${esc(op.quantidade)}</td></tr>
          <tr><td>Responsável</td><td>${esc(op.responsavel || '—')}</td></tr>
          <tr><td>Criada</td><td>${esc(formatarDataHora(op.criada_em))} por ${esc(op.criada_por)}</td></tr>
          <tr><td>Pasta</td><td class="caminho">${esc(O.d.pasta)}</td></tr>
        </table>
        ${op.etapa === 'planejada' ? '<button type="button" class="btn solid" data-ir-aba="documentos">Liberar pacote de documentos</button>'
          : prox ? `<button type="button" class="btn solid" id="op-avancar">Avançar para ${esc(prox.nome)}</button>` : ''}
        ${i > 1 ? '<button type="button" class="btn" id="op-voltar">Voltar etapa</button>' : ''}
        ${op.bloqueio ? '' : '<button type="button" class="btn" id="op-bloquear">Bloquear</button>'}
        <button type="button" class="btn" id="op-editar">Editar dados</button>
        <button type="button" class="btn" id="op-pasta">Abrir pasta</button>
      </div>
      ${pend.length && ['em_montagem', 'em_teste'].includes(op.etapa) ? `<div class="secao-titulo">Falta para a verificação final</div>
        <div class="bloco">${pend.map(p => `<div class="linha-lista cor-warn">• ${esc(p)}</div>`).join('')}</div>` : ''}
      <div class="secao-titulo">Histórico</div>
      <div class="bloco lista-eventos">${op.historico.slice().reverse().slice(0, 60).map(h => `
        <div class="evento"><div class="quando">${esc(formatarDataHora(h.quando))}</div>
          <div class="oque"><b>${esc(_textoAcao(h))}</b><div class="quem">${esc(h.usuario)}</div></div></div>`).join('')}</div>`;
    corpo.querySelectorAll('[data-ir-aba]').forEach(a => a.addEventListener('click', () => irAba(a.dataset.irAba)));
    const av = corpo.querySelector('#op-avancar');
    if (av) av.addEventListener('click', async () => {
      if (!await confirmar(`Mandar ${op.numero} para "${prox.nome}"?`)) return;
      await api('prod_avancar', id, Prod.operador || null);
      carregar();
    });
    const vo = corpo.querySelector('#op-voltar');
    if (vo) vo.addEventListener('click', async () => {
      const ops = Prod.cfg.etapas.slice(1, i).map(e => ({ valor: e.id, texto: e.nome }));
      const r = await prodFormulario({ titulo: 'Voltar etapa', botao: 'Voltar', campos: [
        { id: 'destino', rotulo: 'Voltar para', tipo: 'select', opcoes: ops, valor: ops[ops.length - 1].valor },
        { id: 'motivo', rotulo: 'Motivo', obrigatorio: true }] });
      if (!r) return;
      await api('prod_voltar', id, r.destino, r.motivo, Prod.operador || null);
      carregar();
    });
    const bl = corpo.querySelector('#op-bloquear');
    if (bl) bl.addEventListener('click', async () => {
      const r = await prodFormulario({ titulo: 'Bloquear OP', botao: 'Bloquear', campos: [
        { id: 'motivo', rotulo: 'Motivo', tipo: 'select', opcoes: [...Prod.cfg.motivos_parada], valor: Prod.cfg.motivos_parada[0] },
        { id: 'obs', rotulo: 'Detalhe' }] });
      if (!r) return;
      await api('prod_bloquear', id, r.obs ? `${r.motivo}: ${r.obs}` : r.motivo);
      carregar();
    });
    corpo.querySelector('#op-editar').addEventListener('click', async () => {
      const r = await prodFormulario({ titulo: 'Dados da OP', campos: [
        { id: 'painel', rotulo: 'Painel', valor: op.painel, obrigatorio: true },
        { id: 'descricao', rotulo: 'Descrição', valor: op.descricao },
        { id: 'quantidade', rotulo: 'Quantidade', tipo: 'numero', valor: op.quantidade },
        { id: 'prioridade', rotulo: 'Prioridade', tipo: 'select', valor: op.prioridade, opcoes: Prod.cfg.prioridades },
        { id: 'prazo', rotulo: 'Prazo', tipo: 'date', valor: op.prazo || '' },
        { id: 'responsavel', rotulo: 'Responsável', valor: op.responsavel }] });
      if (!r) return;
      r.prazo = r.prazo || null;
      r.quantidade = r.quantidade || 1;
      await api('prod_editar_op', id, r);
      carregar();
    });
    corpo.querySelector('#op-pasta').addEventListener('click', () => api('prod_abrir_pasta_op', id).catch(() => {}));
  }

  /* ---------- Documentos ---------- */
  function documentos(corpo) {
    const { op, disponiveis } = O.d;
    if (op.etapa === 'planejada') {
      corpo.innerHTML = `<div class="bloco">
        <p class="texto-sec">Escolha os documentos que vão para a bancada. O Orbit congela a revisão atual de cada um:
          a produção abre exatamente esses arquivos, mesmo que o projeto ganhe revisão nova depois (aí aparece um alerta).</p>
        ${disponiveis.length ? `<table class="tabela"><tr><th></th><th>Documento</th><th>Revisão</th><th>Status</th><th>Arquivo</th></tr>
          ${disponiveis.map(d => `<tr><td><input type="checkbox" data-doc="${esc(d.tipo_id)}" ${/eletric/i.test(d.tipo_id) || /el[eé]tric/i.test(d.nome) ? 'checked' : ''}></td>
            <td>${esc(d.nome)}</td><td>${formatarRev(d.numero)}</td><td>${pilulaStatus(d.status)}</td><td>${esc(d.principal)}</td></tr>`).join('')}</table>
          <button type="button" class="btn solid" id="op-liberar">Liberar para a produção</button>`
          : '<p class="aviso">Nenhum documento emitido neste projeto. Envie o diagrama elétrico antes de liberar a OP.</p>'}</div>`;
      const lb = corpo.querySelector('#op-liberar');
      if (lb) lb.addEventListener('click', async () => {
        const tipos = [...corpo.querySelectorAll('[data-doc]:checked')].map(x => x.dataset.doc);
        if (!tipos.length) { mostrarErro('Marque ao menos um documento.'); return; }
        await api('prod_liberar', id, tipos);
        carregar();
      });
      return;
    }
    const alerta = Object.fromEntries(O.d.alertas.map(a => [a.tipo_id, a]));
    corpo.innerHTML = `<div class="bloco">
      <p class="texto-sec">Pacote liberado em ${esc(formatarDataHora(op.pacote_liberado_em))}. Estes são os arquivos que a bancada deve usar.</p>
      <table class="tabela"><tr><th>Documento</th><th>Revisão liberada</th><th>Arquivo</th><th></th></tr>
      ${op.pacote.map(d => `<tr class="${alerta[d.tipo_id] ? 'linha-aviso' : ''}"><td>${esc(d.nome)}</td>
        <td>${formatarRev(d.numero)}${alerta[d.tipo_id] ? ` <span class="chip warn">projeto já tem ${formatarRev(alerta[d.tipo_id].atual)}</span>` : ''}</td>
        <td>${esc(d.principal)}</td>
        <td><button type="button" class="btn pequeno solid" data-abrir-doc="${esc(d.tipo_id)}">Abrir</button></td></tr>`).join('')}</table>
      ${O.d.alertas.length ? '<button type="button" class="btn" id="op-atualizar">Atualizar pacote para as revisões atuais</button>' : ''}</div>`;
    corpo.querySelectorAll('[data-abrir-doc]').forEach(b => b.addEventListener('click', () =>
      api('prod_abrir_documento', id, b.dataset.abrirDoc).catch(() => {})));
    const at = corpo.querySelector('#op-atualizar');
    if (at) at.addEventListener('click', atualizarPacote);
  }

  /* ---------- Materiais ---------- */
  function abaMateriais(corpo) {
    const { op, materiais: rm } = O.d;
    const sits = Prod.cfg.situacoes_material;
    const lista = op.materiais.filter(m => !O.filtroMat || m.situacao === O.filtroMat);
    corpo.innerHTML = `
      <div class="linha-botoes">
        <button type="button" class="btn" id="mat-importar">Importar planilha</button>
        <button type="button" class="btn" id="mat-add">Adicionar item</button>
        <span class="chips">${sits.map(s => `<button type="button" class="chip filtro ${_COR_MAT[s.id]}${O.filtroMat === s.id ? ' on' : ''}" data-filtro="${s.id}">${esc(s.nome)}: ${rm[s.id]}</button>`).join('')}
          ${O.filtroMat ? '<button type="button" class="link" data-filtro="">mostrar todos</button>' : ''}</span>
      </div>
      ${op.materiais.length ? `<div class="barra-selecao" id="mat-barra">
          <label class="ativo-cfg"><input type="checkbox" id="mat-todos"> Todos</label>
          <span id="mat-qtd" class="texto-sec">0 selecionados</span>
          <select id="mat-sit">${sits.map(s => `<option value="${s.id}">${esc(s.nome)}</option>`).join('')}</select>
          <button type="button" class="btn pequeno solid" id="mat-aplicar">Aplicar aos selecionados</button></div>
        <div class="bloco sem-pad"><table class="tabela"><tr><th></th><th>Código</th><th>Descrição</th><th>Qtd</th><th>Fabricante</th><th>Situação</th><th>Obs. / previsão</th></tr>
        ${lista.map(m => `<tr><td><input type="checkbox" data-mat="${esc(m.id)}"></td><td>${esc(m.codigo)}</td><td>${esc(m.descricao)}</td>
          <td class="nowrap">${esc(m.quantidade)} ${esc(m.unidade)}</td><td>${esc(m.fabricante)}</td>
          <td><span class="chip ${_COR_MAT[m.situacao]}">${esc((sits.find(s => s.id === m.situacao) || {}).nome || m.situacao)}</span></td>
          <td>${esc(m.obs)}${m.previsao ? ` <span class="texto-sec">prev. ${esc(formatarDataCurta(m.previsao))}</span>` : ''}</td></tr>`).join('')}</table></div>`
        : '<div class="bloco"><p class="texto-sec">Nenhum material. Importe a lista (BOM) de uma planilha .xlsx/.csv ou adicione itens.</p></div>'}`;
    corpo.querySelectorAll('[data-filtro]').forEach(b => b.addEventListener('click', () => {
      O.filtroMat = O.filtroMat === b.dataset.filtro ? '' : b.dataset.filtro;
      abaMateriais(corpo);
    }));
    corpo.querySelector('#mat-importar').addEventListener('click', async () => {
      const n = await prodImportarPlanilha(id, 'materiais', op.materiais.length > 0);
      if (n !== null) carregar();
    });
    corpo.querySelector('#mat-add').addEventListener('click', async () => {
      const r = await prodFormulario({ titulo: 'Adicionar material', campos: [
        { id: 'codigo', rotulo: 'Código' }, { id: 'descricao', rotulo: 'Descrição', obrigatorio: true },
        { id: 'quantidade', rotulo: 'Quantidade', tipo: 'numero', valor: 1 }, { id: 'unidade', rotulo: 'Unidade', valor: 'pç' },
        { id: 'fabricante', rotulo: 'Fabricante' }] });
      if (!r) return;
      await api('prod_adicionar_material', id, r);
      carregar();
    });
    const sel = () => [...corpo.querySelectorAll('[data-mat]:checked')].map(x => x.dataset.mat);
    const qtd = () => { const q = corpo.querySelector('#mat-qtd'); if (q) q.textContent = `${sel().length} selecionados`; };
    corpo.querySelectorAll('[data-mat]').forEach(c => c.addEventListener('change', qtd));
    const todos = corpo.querySelector('#mat-todos');
    if (todos) todos.addEventListener('change', () => {
      corpo.querySelectorAll('[data-mat]').forEach(c => { c.checked = todos.checked; });
      qtd();
    });
    const ap = corpo.querySelector('#mat-aplicar');
    if (ap) ap.addEventListener('click', async () => {
      const ids = sel();
      if (!ids.length) { mostrarErro('Selecione os itens.'); return; }
      const sit = corpo.querySelector('#mat-sit').value;
      let obs = '', prev = null;
      if (sit === 'falta') {
        const r = await prodFormulario({ titulo: 'Falta de material', botao: 'Registrar falta', campos: [
          { id: 'obs', rotulo: 'Observação', dica: 'Ex.: sem estoque no fornecedor, pedido nº…' },
          { id: 'previsao', rotulo: 'Previsão de chegada', tipo: 'date' }] });
        if (!r) return;
        obs = r.obs; prev = r.previsao || null;
      }
      await api('prod_situacao_materiais', id, ids, sit, obs, prev);
      carregar();
    });
  }

  /* ---------- Testes ---------- */
  let testesProntos = false;
  async function testes(corpo) {
    if (!testesProntos) {
      corpo.innerHTML = '<p class="texto-sec">Carregando…</p>';
      O.d.op.testes = await api('prod_preparar_testes', id);
      testesProntos = true;
      if (!aindaAtual()) return;
    }
    const { op, situacao: st, pendencias: pend } = O.d;
    const t = op.testes;
    const cfg = Prod.cfg;
    const linhasPP = t.ponto_a_ponto.linhas.filter(l => {
      if (O.filtroPP === 'pendentes' && l.ligacao && l.aperto) return false;
      if (O.filtroPP === 'nc' && l.ligacao !== 'nc' && l.aperto !== 'nc') return false;
      const b = O.buscaPP.toLowerCase();
      return !b || [l.origem, l.destino, l.fio].some(x => (x || '').toLowerCase().includes(b));
    });
    const LIMITE = 400;
    const v = t.verificacao;
    const ppId = Object.fromEntries(t.ponto_a_ponto.linhas.map(l => [l.id, l]));
    corpo.innerHTML = `
      ${pend.length ? `<div class="bloco aviso-bloco"><b>Pendências para a verificação final:</b> ${pend.map(esc).join('; ')}</div>`
        : op.etapa === 'em_teste' ? '<div class="bloco ok-bloco">Testes obrigatórios completos e sem NC aberta. <button type="button" class="btn pequeno solid" id="ts-avancar">Avançar para verificação final</button></div>' : ''}

      <div class="secao-titulo">A. Inspeção de rotina — IEC 61439-1 §11 ${_chipEstado(st.inspecao)}</div>
      <div class="bloco sem-pad"><table class="tabela teste"><tr><th>Ref.</th><th>Item</th><th>Resultado</th><th>Obs.</th><th>Por</th></tr>
        ${t.inspecao.itens.map(i => `<tr data-item="${esc(i.id)}" data-bloco="inspecao"><td>${esc(i.ref)}</td><td>${esc(i.texto)}</td>
          <td>${_seg('resultado', i.resultado)}</td><td>${esc(i.obs)}</td><td class="texto-sec">${esc(i.por || '')}</td></tr>`).join('')}</table></div>

      <div class="secao-titulo">B. Ponto a ponto — ligação e aperto ${t.ponto_a_ponto.linhas.length ? _chipEstado(st.ponto_a_ponto) : '<span class="chip">Sem lista (opcional)</span>'}</div>
      <div class="bloco sem-pad">
        <div class="linha-botoes pad">
          <button type="button" class="btn pequeno" id="pp-importar">${t.ponto_a_ponto.linhas.length ? 'Substituir lista de conexões' : 'Importar lista de conexões'}</button>
          ${t.ponto_a_ponto.linhas.length ? `<select id="pp-filtro"><option value="pendentes"${O.filtroPP === 'pendentes' ? ' selected' : ''}>Pendentes</option>
            <option value="todas"${O.filtroPP === 'todas' ? ' selected' : ''}>Todas</option><option value="nc"${O.filtroPP === 'nc' ? ' selected' : ''}>Com NC</option></select>
            <input type="search" id="pp-busca" class="busca pequena" placeholder="Buscar borne, componente ou fio" value="${esc(O.buscaPP)}">
            <span class="texto-sec">${linhasPP.length} de ${t.ponto_a_ponto.linhas.length}${linhasPP.length > LIMITE ? ` (mostrando ${LIMITE}; use a busca)` : ''}</span>` : ''}
        </div>
        ${linhasPP.length ? `<table class="tabela teste" id="pp-tabela"><tr><th>Origem</th><th>Destino</th><th>Fio</th><th>Seção</th><th>Cor</th><th>Ligação</th><th>Aperto</th><th>Por</th></tr>
          ${linhasPP.slice(0, LIMITE).map(l => _linhaPP(l)).join('')}</table>` : ''}
      </div>

      <div class="secao-titulo">C. Resistência de isolação (≥ ${esc(cfg.isolacao_min_mohm)} MΩ) ${_chipEstado(st.isolacao)}</div>
      <div class="bloco sem-pad">
        <table class="tabela teste"><tr><th>Circuito</th><th>Tensão de ensaio</th><th>Medido (MΩ)</th><th>Resultado</th><th>Por</th></tr>
        ${t.isolacao.circuitos.map(x => `<tr data-item="${esc(x.id)}"><td>${esc(x.nome)}</td><td>${esc(x.tensao_v)} V</td>
          <td><input type="text" inputmode="decimal" class="med" data-medir="isolacao" value="${esc(x.medido_mohm ?? '')}"></td>
          <td>${x.resultado ? `<span class="chip ${x.resultado}">${_RES[x.resultado]}</span>` : '—'}</td><td class="texto-sec">${esc(x.por || '')}</td></tr>`).join('')}</table>
        <div class="linha-botoes pad"><button type="button" class="btn pequeno" id="iso-add">Adicionar circuito</button>
          <span class="texto-sec">Ex.: L1-L2-L3 × PE, comando 24 V × PE. Digite o valor e aperte Enter.</span></div>
      </div>

      <div class="secao-titulo">D. Energização (opcional, tolerância ±${esc(cfg.tolerancia_tensao_pct)}%) ${_chipEstado(st.energizacao)}</div>
      <div class="bloco sem-pad">
        <table class="tabela teste"><tr><th>Passo</th><th>Resultado</th><th>Obs.</th><th>Por</th></tr>
        ${t.energizacao.passos.map((p, n) => `<tr data-item="${esc(p.id)}" data-bloco="passo"><td>${n + 1}. ${esc(p.texto)}</td>
          <td>${_seg('resultado', p.resultado)}</td><td>${esc(p.obs)}</td><td class="texto-sec">${esc(p.por || '')}</td></tr>`).join('')}</table>
        <table class="tabela teste"><tr><th>Ponto de medição</th><th>Esperado</th><th>Medido (V)</th><th>Resultado</th><th>Por</th></tr>
        ${t.energizacao.pontos.map(x => `<tr data-item="${esc(x.id)}"><td>${esc(x.nome)}</td><td>${esc(x.esperado_v)} V</td>
          <td><input type="text" inputmode="decimal" class="med" data-medir="tensao" value="${esc(x.medido_v ?? '')}"></td>
          <td>${x.resultado ? `<span class="chip ${x.resultado}">${_RES[x.resultado]}</span>` : '—'}</td><td class="texto-sec">${esc(x.por || '')}</td></tr>`).join('')}</table>
        <div class="linha-botoes pad"><button type="button" class="btn pequeno" id="ten-add">Adicionar ponto de medição</button></div>
      </div>

      <div class="secao-titulo">E. Entradas e saídas ${t.io.sinais.length ? _chipEstado(st.io) : '<span class="chip">Sem lista (opcional)</span>'}</div>
      <div class="bloco sem-pad">
        <div class="linha-botoes pad"><button type="button" class="btn pequeno" id="io-importar">${t.io.sinais.length ? 'Substituir lista de tags' : 'Importar lista de tags'}</button></div>
        ${t.io.sinais.length ? `<table class="tabela teste"><tr><th>Tag</th><th>Descrição</th><th>Endereço</th><th>Tipo</th><th>Resultado</th><th>Por</th></tr>
          ${t.io.sinais.map(s => `<tr data-item="${esc(s.id)}" data-bloco="sinal"><td>${esc(s.tag)}</td><td>${esc(s.descricao)}</td><td>${esc(s.endereco)}</td>
            <td>${esc(s.tipo)}</td><td>${_seg('resultado', s.resultado)}</td><td class="texto-sec">${esc(s.por || '')}</td></tr>`).join('')}</table>` : ''}
      </div>

      <div class="secao-titulo">Verificação final por amostragem (outra pessoa)</div>
      <div class="bloco">${_verificacao(op, v, ppId)}</div>`;
    ligarTestes(corpo);
  }

  function _linhaPP(l) {
    return `<tr data-item="${esc(l.id)}" data-bloco="ponto_a_ponto"><td>${esc(l.origem)}</td><td>${esc(l.destino)}</td>
      <td>${esc(l.fio)}</td><td>${esc(l.secao)}</td><td>${esc(l.cor)}</td>
      <td>${_seg('ligacao', l.ligacao, ['ok', 'nc'])}</td><td>${_seg('aperto', l.aperto, ['ok', 'nc'])}</td>
      <td class="texto-sec">${esc(l.por || '')}</td></tr>`;
  }

  function _verificacao(op, v, ppId) {
    if (op.etapa !== 'verificacao_final' && !v.sorteadas.length) {
      return '<p class="texto-sec">Disponível quando a OP estiver na etapa "Verificação final". O Orbit sorteia ligações do ponto a ponto para outra pessoa conferir, mais um checklist final.</p>';
    }
    if (!v.sorteadas.length || (v.concluida && op.etapa === 'verificacao_final' && !v.aprovada)) {
      return `<p class="texto-sec">Quem verifica: o operador escolhido no topo (precisa ser diferente de quem fez o ponto a ponto).
        Serão sorteadas ${esc(Prod.cfg.amostragem_pct)}% das ligações (mínimo ${esc(Prod.cfg.amostragem_min)}).</p>
        <button type="button" class="btn solid" id="vf-sortear">Sortear amostra</button>`;
    }
    const res = v.aprovada === true ? '<span class="chip ok">Aprovada</span>' : v.aprovada === false ? '<span class="chip pend">Reprovada</span>' : '<span class="chip warn">Em andamento</span>';
    return `<p>Verificador: <b>${esc(v.verificador)}</b> · ${v.sorteadas.length} ligações sorteadas ${res}</p>
      <table class="tabela teste"><tr><th>Origem</th><th>Destino</th><th>Fio</th><th>Conferência</th><th>Obs.</th></tr>
      ${v.sorteadas.map(lid => { const l = ppId[lid] || {}; const r = v.resultados[lid] || {};
        return `<tr data-amostra="${esc(lid)}"><td>${esc(l.origem)}</td><td>${esc(l.destino)}</td><td>${esc(l.fio)}</td>
          <td>${v.concluida ? `<span class="chip ${r.resultado || ''}">${_RES[r.resultado] || '—'}</span>` : _seg('amostra', r.resultado, ['ok', 'nc'])}</td><td>${esc(r.obs || '')}</td></tr>`; }).join('')}</table>
      <div class="secao-sub">Checklist final</div>
      <table class="tabela teste">${v.checklist.map((c, i) => `<tr data-check="${i}"><td>${esc(c.texto)}</td>
        <td>${v.concluida ? `<span class="chip ${c.resultado || ''}">${_RES[c.resultado] || '—'}</span>` : _seg('check', c.resultado, ['ok', 'nc'])}</td></tr>`).join('')}</table>
      ${v.concluida ? (v.aprovada ? '<p class="cor-ok">Verificação aprovada. Avance a OP para "Aprovada" no Resumo.</p>'
        : '<p class="cor-pend">Verificação reprovada: a OP voltou para "Em teste" e o ponto a ponto foi zerado para revisão completa.</p>')
        : '<button type="button" class="btn solid" id="vf-concluir">Concluir verificação</button>'}`;
  }

  async function pedirNc(tipoPadrao, titulo) {
    return prodFormulario({ titulo: titulo || 'Não conformidade', botao: 'Registrar NC', campos: [
      { id: 'tipo', rotulo: 'Tipo', tipo: 'select', opcoes: Prod.cfg.tipos_nc, valor: tipoPadrao || Prod.cfg.tipos_nc[0] },
      { id: 'obs', rotulo: 'O que está errado', obrigatorio: true, dica: 'Ex.: X1:4 frouxo, fio 23 em K2 no lugar de K3' }] });
  }

  function ligarTestes(corpo) {
    const av = corpo.querySelector('#ts-avancar');
    if (av) av.addEventListener('click', async () => { await api('prod_avancar', id, Prod.operador || null); testesProntos = false; carregar(); });
    if (!corpo._segLigado) corpo.addEventListener('click', async e => {
      const b = e.target.closest('.seg button');
      if (!b) return;
      const seg = b.closest('.seg'), tr = b.closest('tr'), val = b.dataset.val, campo = seg.dataset.seg;
      try {
        if (tr.dataset.amostra || tr.dataset.check !== undefined) {
          const ver = prodExigirOperador();
          if (campo === 'amostra') {
            let obs = '';
            if (val === 'nc') { const r = await prodFormulario({ titulo: 'Ligação com falha', botao: 'Registrar', campos: [{ id: 'obs', rotulo: 'O que está errado', obrigatorio: true }] }); if (!r) return; obs = r.obs; }
            await api('prod_marcar_amostra', id, tr.dataset.amostra, val, ver, obs);
            const v = O.d.op.testes.verificacao; v.resultados[tr.dataset.amostra] = { resultado: val, obs };
          } else {
            await api('prod_marcar_checklist_final', id, Number(tr.dataset.check), val, ver);
            O.d.op.testes.verificacao.checklist[Number(tr.dataset.check)].resultado = val;
          }
          seg.querySelectorAll('button').forEach(x => { x.className = x.dataset.val === val ? `on ${val}` : ''; });
          return;
        }
        const operador = prodExigirOperador();
        const bloco = tr.dataset.bloco;
        const dados = { operador, obs: '' };
        if (bloco === 'ponto_a_ponto') {
          const l = O.d.op.testes.ponto_a_ponto.linhas.find(x => x.id === tr.dataset.item);
          dados.ligacao = campo === 'ligacao' ? val : l.ligacao;
          dados.aperto = campo === 'aperto' ? val : l.aperto;
          if (val === 'nc' && l[campo] !== 'nc' && l.ligacao !== 'nc' && l.aperto !== 'nc') {
            const r = await pedirNc(campo === 'aperto' ? 'Aperto/borne solto' : 'Fio/ligação trocada', `${l.origem} → ${l.destino}`);
            if (!r) return;
            dados.nc_tipo = r.tipo; dados.obs = r.obs;
          }
          const nova = await api('prod_marcar', id, bloco, tr.dataset.item, dados);
          Object.assign(l, nova);
          if (dados.nc_tipo) { carregar(); return; }
          tr.outerHTML = _linhaPP(l);
          return;
        }
        dados.resultado = val;
        const atual = (seg.querySelector('button.on') || {}).dataset;
        if (val === 'nc' && !(atual && atual.val === 'nc')) {
          const r = await pedirNc(bloco === 'sinal' ? 'Função/lógica' : null);
          if (!r) return;
          dados.nc_tipo = r.tipo; dados.obs = r.obs;
        }
        await api('prod_marcar', id, bloco, tr.dataset.item, dados);
        carregar();
      } catch (err) { if (!(err instanceof ErroApi)) console.error(err); }
    });
    corpo._segLigado = true;
    corpo.querySelectorAll('[data-medir]').forEach(inp => inp.addEventListener('keydown', async e => {
      if (e.key !== 'Enter') return;
      const valor = Number(inp.value.trim().replace(',', '.'));
      if (inp.value.trim() === '' || Number.isNaN(valor)) { mostrarErro('Digite um número.'); return; }
      try {
        await api('prod_marcar', id, inp.dataset.medir, inp.closest('tr').dataset.item,
          { valor, operador: prodExigirOperador() });
        carregar();
      } catch (err) { if (!(err instanceof ErroApi)) console.error(err); }
    }));
    const filtro = corpo.querySelector('#pp-filtro');
    if (filtro) filtro.addEventListener('change', () => { O.filtroPP = filtro.value; testes(corpo); });
    const busca = corpo.querySelector('#pp-busca');
    if (busca) {
      let tm = null;
      busca.addEventListener('input', () => {
        clearTimeout(tm);
        tm = setTimeout(() => {
          O.buscaPP = busca.value;
          testes(corpo).then(() => {
            const b2 = corpo.querySelector('#pp-busca');
            if (b2) { b2.focus(); b2.setSelectionRange(b2.value.length, b2.value.length); }
          });
        }, 250);
      });
    }
    const imp = (botao, destino, temLista) => {
      const b = corpo.querySelector(botao);
      if (b) b.addEventListener('click', async () => {
        const n = await prodImportarPlanilha(id, destino, temLista);
        if (n !== null) { testesProntos = false; carregar(); }
      });
    };
    const t = O.d.op.testes;
    imp('#pp-importar', 'ponto_a_ponto', t.ponto_a_ponto.linhas.length > 0);
    imp('#io-importar', 'io', t.io.sinais.length > 0);
    corpo.querySelector('#iso-add').addEventListener('click', async () => {
      const r = await prodFormulario({ titulo: 'Circuito de isolação', botao: 'Adicionar', campos: [
        { id: 'nome', rotulo: 'Circuito', obrigatorio: true, dica: 'Ex.: L1-L2-L3 × PE' },
        { id: 'tensao', rotulo: 'Tensão de ensaio (V)', tipo: 'numero', valor: Prod.cfg.isolacao_tensao_v, obrigatorio: true }] });
      if (!r) return;
      await api('prod_adicionar_circuito', id, r.nome, r.tensao);
      carregar();
    });
    corpo.querySelector('#ten-add').addEventListener('click', async () => {
      const r = await prodFormulario({ titulo: 'Ponto de medição', botao: 'Adicionar', campos: [
        { id: 'nome', rotulo: 'Ponto', obrigatorio: true, dica: 'Ex.: Entrada L1-L2, Fonte 24 Vcc' },
        { id: 'esperado', rotulo: 'Tensão esperada (V)', tipo: 'numero', obrigatorio: true }] });
      if (!r) return;
      await api('prod_adicionar_ponto_tensao', id, r.nome, r.esperado);
      carregar();
    });
    const sortear = corpo.querySelector('#vf-sortear');
    if (sortear) sortear.addEventListener('click', async () => {
      await api('prod_sortear_amostra', id, prodExigirOperador());
      carregar();
    });
    const concluir = corpo.querySelector('#vf-concluir');
    if (concluir) concluir.addEventListener('click', async () => {
      if (!await confirmar('Concluir a verificação final? Se houver falha, a OP volta para "Em teste" e o ponto a ponto é zerado.')) return;
      const op = await api('prod_concluir_verificacao', id, prodExigirOperador());
      testesProntos = false;
      await carregar();
      abrirPopup({ titulo: 'Verificação final', corpoHtml: op.testes.verificacao.aprovada
        ? '<p>Aprovada. Agora avance a OP para "Aprovada" no Resumo e gere o relatório de ensaio.</p>'
        : '<p>Reprovada. Foram abertas NCs, a OP voltou para "Em teste" e o ponto a ponto precisa ser refeito por completo.</p>',
        botoes: [{ texto: 'OK', primario: true }] });
    });
  }

  /* ---------- NCs ---------- */
  function ncs(corpo) {
    const { op } = O.d;
    const origem = n => n.origem && n.origem.bloco !== 'manual' ? (Prod.cfg.blocos[n.origem.bloco] || (n.origem.bloco === 'verificacao' ? 'Verificação final' : n.origem.bloco)) : 'Manual';
    corpo.innerHTML = `
      <div class="linha-botoes"><button type="button" class="btn" id="nc-nova">Abrir NC</button>
        <span class="texto-sec">NC só fecha depois do reteste (qualquer pessoa). NCs dos testes também nascem marcando "NC" na linha.</span></div>
      ${op.ncs.length ? `<div class="bloco sem-pad"><table class="tabela"><tr><th>Nº</th><th>Tipo</th><th>Descrição</th><th>Origem</th><th>Aberta</th><th>Correção</th><th>Situação</th><th></th></tr>
        ${op.ncs.slice().reverse().map(n => `<tr><td>${esc(n.numero)}</td><td>${esc(n.tipo)}</td><td>${esc(n.descricao)}</td><td>${esc(origem(n))}</td>
          <td>${esc(n.aberta_por)}<div class="texto-sec">${esc(formatarDataHora(n.aberta_em))}</div></td>
          <td>${esc(n.correcao || '')}${n.corrigida_por ? `<div class="texto-sec">${esc(n.corrigida_por)}</div>` : ''}${n.verificada_por ? `<div class="texto-sec">reteste: ${esc(n.verificada_por)}</div>` : ''}</td>
          <td><span class="chip ${(_SIT_NC[n.situacao] || [''])[0]}">${esc((_SIT_NC[n.situacao] || ['', n.situacao])[1])}</span></td>
          <td>${n.situacao === 'aberta' ? `<button type="button" class="btn pequeno" data-corrigir="${esc(n.id)}">Registrar correção</button>`
            : n.situacao === 'corrigida' ? `<button type="button" class="btn pequeno solid" data-reteste="${esc(n.id)}">Reteste OK</button>` : ''}</td></tr>`).join('')}</table></div>`
        : '<div class="bloco"><p class="texto-sec">Nenhuma não conformidade.</p></div>'}`;
    corpo.querySelector('#nc-nova').addEventListener('click', async () => {
      const r = await pedirNc(null, 'Nova não conformidade');
      if (!r) return;
      await api('prod_abrir_nc', id, r.tipo, r.obs, prodExigirOperador());
      carregar();
    });
    corpo.querySelectorAll('[data-corrigir]').forEach(b => b.addEventListener('click', async () => {
      const operador = prodExigirOperador();
      const r = await prodFormulario({ titulo: 'Correção', botao: 'Registrar', campos: [{ id: 'txt', rotulo: 'O que foi feito', obrigatorio: true }] });
      if (!r) return;
      await api('prod_corrigir_nc', id, b.dataset.corrigir, operador, r.txt);
      carregar();
    }));
    corpo.querySelectorAll('[data-reteste]').forEach(b => b.addEventListener('click', async () => {
      const operador = prodExigirOperador();
      if (!await confirmar('Confirmar que o reteste passou? A linha do teste de origem fica OK.')) return;
      await api('prod_verificar_nc', id, b.dataset.reteste, operador);
      carregar();
    }));
  }

  /* ---------- Apontamentos ---------- */
  function apontamentos(corpo) {
    const { op, horas } = O.d;
    const dur = a => prodDesde(a.inicio, a.fim);
    const porOp = Object.entries(horas.por_operador);
    corpo.innerHTML = `
      <div class="linha-botoes"><button type="button" class="btn solid" id="ap-iniciar">Iniciar trabalho nesta OP</button>
        <span class="texto-sec">Para pausar ou encerrar, use Produção → Meu trabalho.</span></div>
      <div class="stats sem-pad">
        <div class="stat"><div class="v">${esc(prodHoras(horas.trabalho_h))}</div><div class="l">Trabalho</div></div>
        <div class="stat"><div class="v">${esc(prodHoras(horas.parada_h))}</div><div class="l">Paradas</div></div>
        ${Object.entries(horas.por_etapa).map(([k, v]) => `<div class="stat"><div class="v">${esc(prodHoras(v))}</div><div class="l">${esc(prodNomeEtapa(k))}</div></div>`).join('')}
      </div>
      ${porOp.length ? `<div class="bloco"><table class="tabela"><tr><th>Operador</th><th>Trabalho</th><th>Paradas</th></tr>
        ${porOp.map(([n, v]) => `<tr><td>${esc(n)}</td><td>${esc(prodHoras(v.trabalho_h))}</td><td>${esc(prodHoras(v.parada_h))}</td></tr>`).join('')}</table></div>` : ''}
      <div class="secao-titulo">Apontamentos</div>
      <div class="bloco sem-pad">${op.apontamentos.length ? `<table class="tabela"><tr><th>Operador</th><th>Etapa</th><th>Tipo</th><th>Início</th><th>Fim</th><th>Duração</th><th>Obs.</th><th></th></tr>
        ${op.apontamentos.map((a, i) => `<tr><td>${esc(a.operador)}</td><td>${esc(prodNomeEtapa(a.etapa))}</td>
          <td>${a.tipo === 'parada' ? `<span class="cor-warn">Parada: ${esc(a.motivo)}</span>` : 'Trabalho'}</td>
          <td>${esc(formatarDataHora(a.inicio))}</td><td>${a.fim ? esc(formatarDataHora(a.fim)) : '<span class="chip ok">aberto</span>'}</td>
          <td>${a.fim ? esc(dur(a)) : ''}</td><td>${esc(a.obs)}${a.editado_por ? `<div class="texto-sec">corrigido por ${esc(a.editado_por)}</div>` : ''}</td>
          <td><button type="button" class="btn pequeno" data-ap="${i}">Corrigir</button></td></tr>`).reverse().join('')}</table>`
        : '<p class="texto-sec pad">Nenhum apontamento.</p>'}</div>`;
    corpo.querySelector('#ap-iniciar').addEventListener('click', async () => {
      await api('prod_iniciar', id, prodExigirOperador(), '');
      carregar();
    });
    corpo.querySelectorAll('[data-ap]').forEach(b => b.addEventListener('click', async () => {
      if (await prodCorrigirApontamento(id, op.apontamentos[+b.dataset.ap])) carregar();
    }));
  }

  /* ---------- Relatório ---------- */
  function relatorio(corpo) {
    corpo.innerHTML = `<div class="bloco">
      <p>O relatório de ensaio reúne identificação, documentos liberados (revisões), os resultados de cada bloco
        (inspeção IEC 61439-1 §11, ponto a ponto, isolação, energização, entradas e saídas) com quem fez e quando,
        as NCs com reteste, a verificação final e campos de assinatura.</p>
      <p class="texto-sec">Arquivo HTML na pasta da OP. Para PDF, use Imprimir → Salvar como PDF. Ele é regravado a cada geração (é sempre derivado dos dados).</p>
      <button type="button" class="btn solid" id="rel-gerar">Gerar e abrir relatório</button>
      <button type="button" class="btn" id="rel-pasta">Abrir pasta da OP</button></div>`;
    corpo.querySelector('#rel-gerar').addEventListener('click', () => api('prod_relatorio', id, true).catch(() => {}));
    corpo.querySelector('#rel-pasta').addEventListener('click', () => api('prod_abrir_pasta_op', id).catch(() => {}));
  }

  await carregar();
};

const _NOMES_ACAO = {
  op_criada: 'OP criada', pacote_liberado: 'Pacote de documentos liberado', pacote_atualizado: 'Pacote atualizado',
  etapa_avancada: 'Etapa avançada', etapa_voltada: 'Etapa voltada', op_bloqueada: 'OP bloqueada',
  op_desbloqueada: 'OP desbloqueada', op_editada: 'Dados alterados', nc_aberta: 'NC aberta', nc_corrigida: 'NC corrigida',
  nc_verificada: 'NC verificada (reteste)', ponto_a_ponto_carregado: 'Lista de conexões carregada',
  materiais_importados: 'Lista de materiais importada', material_em_falta: 'Material em falta',
  amostra_sorteada: 'Amostra sorteada', verificacao_aprovada: 'Verificação final aprovada',
  apontamento_editado: 'Apontamento corrigido',
};

function _textoAcao(h) {
  const d = h.detalhes || {};
  let t = _NOMES_ACAO[h.acao] || h.acao;
  if (d.para && h.acao.startsWith('etapa')) t += ` → ${prodNomeEtapa(d.para)}`;
  if (d.motivo) t += ` (${d.motivo})`;
  if (d.numero && h.acao.startsWith('nc')) t += ` nº ${d.numero}${d.tipo ? ` · ${d.tipo}` : ''}`;
  if (d.itens && typeof d.itens === 'number') t += ` (${d.itens} itens)`;
  if (d.linhas) t += ` (${d.linhas} ligações)`;
  return t;
}
