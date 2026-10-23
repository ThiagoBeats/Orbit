/* Tela "Log de ações" (spec de backup §7): só leitura, com filtros e selo de integridade.
 * Não existe nenhum botão para editar ou apagar linhas. */

const ROTULOS_ACAO = {
  revisao_enviada: 'Revisão enviada', status_alterado: 'Status alterado',
  importacao: 'Importação', email_preparado: 'E-mail preparado',
  nao_se_aplica_alterado: '"Não se aplica" alterado', dados_alterados: 'Dados alterados',
  arquivo_registrado: 'Arquivo registrado', cliente_criado: 'Cliente criado',
  cliente_alterado: 'Cliente alterado', projeto_criado: 'Projeto criado',
  maquina_criada: 'Máquina criada', configuracao_alterada: 'Configurações alteradas',
  trava_liberada: 'Trava liberada', sincronizacao: 'Sincronização',
  arquivo_restaurado: 'Arquivo restaurado', divergencia_resolvida: 'Divergência resolvida',
  recuperacao: 'Recuperação', adulteracao_detectada: 'Adulteração detectada',
};

function _resumoDetalhes(acao, d) {
  const partes = [];
  if (d.cliente_nome) partes.push(d.cliente_nome);
  if (d.container_nome) partes.push(d.container_nome);
  if (d.tipo_id) partes.push(d.tipo_id);
  if (d.numero !== undefined && d.numero !== null) partes.push(`Rev${String(d.numero).padStart(2, '0')}`);
  if (acao === 'status_alterado' && d.para) partes.push(`${d.de || '—'} → ${d.para}`);
  if (d.motivo) partes.push(d.motivo);
  if (d.arquivo) partes.push(d.arquivo);
  if (acao === 'sincronizacao') partes.push(`${d.enviados || 0} enviados, ${d.recebidos || 0} recebidos, ${d.divergencias || 0} divergências`);
  if (acao === 'divergencia_resolvida') partes.push(`${d.chave || d.caminho || ''}: ${d.escolha}`);
  if (acao === 'adulteracao_detectada') partes.push(d.descricao || '');
  return partes.filter(Boolean).join(' · ');
}

function _seloIntegridade(integ) {
  if (!integ) return '';
  if (integ.integro) return '<span class="chip ok">Íntegro</span>';
  const det = (integ.problemas || []).map(p => esc(p.descricao)).join('<br>');
  return `<span class="chip pend">Alterado fora do Orbit</span><div class="texto-sec">${det}</div>`;
}

Orbit.views.log = async (el, _id, aindaAtual) => {
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Log de ações</h1>
    <div class="pagina">
      <div id="log-selo" class="bloco"></div>
      <div class="barra">
        <input type="date" id="log-de" title="De">
        <input type="date" id="log-ate" title="Até">
        <input type="text" id="log-usuario" placeholder="Usuário" style="width:140px">
        <select id="log-acao"><option value="">Todas as ações</option>${Object.entries(ROTULOS_ACAO)
          .map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select>
        <input type="search" id="log-busca" class="busca" placeholder="Buscar…">
      </div>
      <table class="tabela" id="log-tabela"></table>
      <div class="linha-cfg" id="log-paginas"></div>
    </div>`;
  let pagina = 1;
  let seq = 0;
  const valor = id => el.querySelector(id).value.trim();

  async function carregar() {
    const minha = ++seq;
    const r = await api('ler_log', {
      de: valor('#log-de'), ate: valor('#log-ate'), usuario: valor('#log-usuario'),
      acao: valor('#log-acao'), texto: valor('#log-busca'), pagina,
    });
    if (minha !== seq || !aindaAtual()) return;
    el.querySelector('#log-selo').innerHTML = _seloIntegridade(r.integridade);
    el.querySelector('#log-tabela').innerHTML = r.linhas.length ? `
      <tr><th>Data e hora</th><th>Usuário</th><th>Computador</th><th>Ação</th><th>Detalhes</th></tr>
      ${r.linhas.map(l => `<tr class="${l.acao === 'adulteracao_detectada' ? 'linha-alerta' : ''}">
        <td>${esc(formatarDataHora(l.data_hora))}</td><td>${esc(l.usuario)}</td>
        <td>${esc(l.computador)}</td><td>${esc(ROTULOS_ACAO[l.acao] || l.acao)}</td>
        <td>${esc(_resumoDetalhes(l.acao, l.detalhes || {}))}</td></tr>`).join('')}`
      : '<tr><td class="texto-sec">Nenhuma ação encontrada.</td></tr>';
    el.querySelector('#log-paginas').innerHTML = r.paginas > 1 ? `
      <button type="button" class="btn pequeno" id="log-ant" ${r.pagina <= 1 ? 'disabled' : ''}>Anterior</button>
      <span class="texto-sec">Página ${esc(r.pagina)} de ${esc(r.paginas)} · ${esc(r.total)} ações</span>
      <button type="button" class="btn pequeno" id="log-prox" ${r.pagina >= r.paginas ? 'disabled' : ''}>Próxima</button>`
      : `<span class="texto-sec">${esc(r.total)} ações</span>`;
    const ant = el.querySelector('#log-ant');
    const prox = el.querySelector('#log-prox');
    if (ant) ant.addEventListener('click', () => { pagina--; carregar().catch(() => {}); });
    if (prox) prox.addEventListener('click', () => { pagina++; carregar().catch(() => {}); });
  }

  let timer = null;
  const recarregarFiltros = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { pagina = 1; carregar().catch(() => {}); }, 250);
  };
  ['#log-de', '#log-ate', '#log-usuario', '#log-acao', '#log-busca'].forEach(id => {
    el.querySelector(id).addEventListener('input', recarregarFiltros);
    el.querySelector(id).addEventListener('change', recarregarFiltros);
  });
  await carregar();
};

/* Na abertura: confere o log e avisa se foi alterado fora do Orbit. */
async function verificarLogNaAbertura() {
  const r = await _apiQuieta('verificar_log');
  if (!r || !r.ok || r.dados.integro) return;
  const det = (r.dados.problemas || []).map(p =>
    `<p>${esc(p.descricao)} (a partir da linha nº ${esc(p.a_partir_de_n)} de ${esc(p.computador)})</p>`).join('');
  abrirPopup({
    titulo: 'Log de ações alterado',
    corpoHtml: `<p>O log de ações foi alterado fora do Orbit.</p>${det}
      <p class="texto-sec">O alerta foi registrado no próprio log. As linhas antigas não foram corrigidas nem apagadas.</p>`,
    botoes: [{ texto: 'Fechar' }, { texto: 'Ver log', primario: true, acao: () => { irPara('#/log'); } }],
    classe: 'erro',
  });
}
