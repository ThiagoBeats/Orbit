/* Popups de status e de histórico do painel.
 *
 * classeStatus(status) -> 'ok' | 'warn' | 'info' | ''   (cor da pílula)
 * pilulaStatus(status) -> HTML da pílula
 * popupStatus({containerId, doc})          -> Promise<bool>  (true = status mudou)
 * popupHistorico({containerId, nomesTipos}) -> Promise<void>
 *     nomesTipos: {tipo_id: nome de exibição}
 */

const _CLASSE_STATUS = {
  'Aprovado': 'ok',
  'Para aprovação': 'warn',
  'Liberado para fabricação': 'info',
};

function classeStatus(status) {
  return _CLASSE_STATUS[status] || '';
}

function pilulaStatus(status) {
  return `<span class="chip ${classeStatus(status)}">${esc(status)}</span>`;
}

function formatarRev(n) {
  return esc(`Rev${String(n).padStart(2, '0')}`); // número vem do JSON compartilhado
}

function popupStatus({ containerId, doc }) {
  return new Promise(resolve => {
    let mudou = false;
    const atual = doc.atual;
    let escolhido = atual.status;
    const lista = (Orbit.config.status || []).slice();
    if (!lista.includes(atual.status)) lista.push(atual.status); // status removido da config
    const popup = abrirPopup({
      titulo: 'Mudar status',
      subtitulo: `${doc.nome} · ${formatarRev(atual.numero)}`,
      corpoHtml: `<p class="texto-sec">A revisão e os arquivos não mudam. A mudança fica no histórico.</p>
        <div class="lista-status">${lista.map(s => `
          <button type="button" class="opcao${s === escolhido ? ' on' : ''}" data-status="${esc(s)}">
            ${pilulaStatus(s)}</button>`).join('')}</div>`,
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Salvar', primario: true, acao: async () => {
          if (escolhido === atual.status) return;
          await api('alterar_status', containerId, doc.tipo_id, escolhido);
          mudou = true;
        } },
      ],
    });
    popup.elemento.querySelector('.lista-status').addEventListener('click', e => {
      const b = e.target.closest('[data-status]');
      if (!b) return;
      escolhido = b.dataset.status;
      popup.elemento.querySelectorAll('[data-status]').forEach(x =>
        x.classList.toggle('on', x === b));
    });
    popup._aoFechar = () => resolve(mudou);
  });
}

function _descreverEvento(e, nomesTipos) {
  const d = e.dados || {};
  const tipo = id => esc(nomesTipos[id] || id || '');
  const revs = lista => (lista || []).map(r => `${tipo(r.tipo_id)} ${formatarRev(r.numero)}`).join(', ');
  switch (e.tipo) {
    case 'revisao_enviada':
      return `<b>Nova revisão</b> · ${tipo(d.tipo_id)} ${formatarRev(d.numero)}`
        + (d.motivo ? ` · ${esc(d.motivo)}` : '');
    case 'status_alterado':
      return `<b>Status alterado</b> · ${tipo(d.tipo_id)}: ${esc(d.de)} → ${esc(d.para)}`;
    case 'nao_se_aplica_alterado':
      return `<b>${d.valor ? 'Marcado como "não se aplica"' : 'Voltou a se aplicar'}</b> · ${tipo(d.tipo_id)}`;
    case 'importacao':
      return `<b>Importação</b> · ${revs(d.revisoes)}`;
    case 'email_preparado':
      return `<b>E-mail preparado</b> · ${esc((d.destinatarios || []).join(', '))}`
        + (d.itens ? ` · ${revs(d.itens)}` : '');
    case 'dados_alterados':
      return `<b>Dados alterados</b> · ${esc(Object.keys(d.alterados || {}).join(', '))}`;
    case 'arquivo_registrado':
      return `<b>Arquivos registrados</b> · ${revs(d.registros)}`;
    default:
      return `<b>${esc(e.tipo)}</b>`;
  }
}

function _formatarDataHora(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
  return m ? `${m[3]}/${m[2]}/${m[1].slice(2)} ${m[4]}:${m[5]}` : esc(iso);
}

async function popupHistorico({ containerId, nomesTipos, documentos = [], aoEnviar = null }) {
  const eventos = await api('obter_historico', containerId);
  const linhas = eventos.length ? eventos.map(e => `
    <div class="evento">
      <div class="quando">${_formatarDataHora(e.data_hora)}</div>
      <div class="oque">${_descreverEvento(e, nomesTipos)}
        <div class="quem">${esc(e.usuario)}${e.computador ? ` · ${esc(e.computador)}` : ''}</div></div>
    </div>`).join('') : '<p class="texto-sec">Nenhum evento registrado.</p>';
  const antigas = aoEnviar ? documentos.flatMap(d => d.revisoes.filter(r => r.arquivada)
    .map(r => ({ tipo_id: d.tipo_id, nome: d.nome, ...r }))) : [];
  const secaoAntigas = antigas.length ? `<div class="secao-revisoes">
    <div class="secao-titulo">Revisões antigas</div>${antigas.map((r, i) => `
    <div class="rev-antiga"><span>${esc(r.nome)} · ${formatarRev(r.numero)} · ${esc(formatarDataCurta(r.data))}</span>
      <button type="button" class="btn pequeno" data-enviar="${i}">Enviar</button></div>`).join('')}</div>` : '';
  return new Promise(resolve => {
    const popup = abrirPopup({
      titulo: 'Histórico',
      subtitulo: 'Do mais recente para o mais antigo.',
      classe: 'largo',
      corpoHtml: `${secaoAntigas}<div class="lista-eventos">${linhas}</div>`,
      botoes: [{ texto: 'Fechar', primario: true }],
    });
    popup.elemento.querySelectorAll('[data-enviar]').forEach(b => b.addEventListener('click', () => {
      const r = antigas[Number(b.dataset.enviar)];
      popup.fechar();
      aoEnviar(r.tipo_id, r.numero);
    }));
    popup._aoFechar = () => resolve();
  });
}
