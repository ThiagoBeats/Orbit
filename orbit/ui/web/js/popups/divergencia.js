/* Popups de divergência da sincronização (spec de backup §5).
 *
 * abrirDivergencias(): busca a lista pendente e mostra uma por vez
 * ("Divergência 2 de 5"), com os dois lados lado a lado e só as ações
 * possíveis. "Resolver depois" fecha sem decidir (continua pendente).
 */

const _ACOES_DIV = {
  local: 'Manter o desta máquina',
  backup: 'Manter o do backup',
  ambos: 'Manter os dois',
  juntar: 'Juntar num só',
  ciente: 'Ciente',
};

const _TITULOS_DIV = {
  campo: 'Valores diferentes',
  revisao: 'Revisão diferente nos dois lados',
  arquivo: 'Arquivo alterado nos dois lados',
  pasta_id: 'Dois cadastros na mesma pasta',
  log: 'Log de ações diferente',
};

function _valorDiv(v) {
  if (v === null || v === undefined || v === '') return '<span class="texto-sec">(vazio)</span>';
  if (v === true) return 'Sim';
  if (v === false) return 'Não';
  if (Array.isArray(v)) {
    return v.length ? v.map(x => esc(x && typeof x === 'object'
      ? [x.nome, x.email].filter(Boolean).join(' — ') : x)).join('<br>')
      : '<span class="texto-sec">(nenhum)</span>';
  }
  return esc(v);
}

function _ladoDiv(div, lado) {
  const d = div[lado] || {};
  const partes = [];
  if (div.tipo === 'campo') partes.push(`<div class="valor">${_valorDiv(d.valor)}</div>`);
  if (div.tipo === 'revisao' && d.revisao) {
    const r = d.revisao;
    partes.push(`<div class="valor">Rev${esc(String(r.numero).padStart(2, '0'))} — ${esc(r.status)}</div>`);
    partes.push(`<div class="texto-sec">${(r.arquivos || []).map(a => esc(a.nome)).join('<br>')}</div>`);
  }
  if (div.tipo === 'arquivo') partes.push(`<div class="valor">${esc(d.tamanho)} bytes</div>`);
  if (div.tipo === 'pasta_id') partes.push(`<div class="texto-sec">Cadastro ${esc((d.id || '').slice(0, 8))}…</div>`);
  if (d.usuario || d.computador || d.data_hora) {
    partes.push(`<div class="texto-sec">${esc(d.usuario || '')}${d.computador ? ` (${esc(d.computador)})` : ''}${d.data_hora ? ` · ${esc(d.data_hora)}` : ''}</div>`);
  }
  const abre = div.tipo === 'arquivo' || div.tipo === 'revisao';
  return `<div class="card div-lado">
    <div class="t">${lado === 'local' ? 'Nesta máquina' : 'No backup'}</div>
    ${partes.join('')}
    ${abre ? `<button type="button" class="btn pequeno" data-abrir="${lado}">Abrir</button>` : ''}
  </div>`;
}

async function abrirDivergencias(indice = 0) {
  const lista = await api('listar_divergencias');
  if (!lista.length) {
    abrirPopup({ titulo: 'Divergências', corpoHtml: '<p>Nenhuma divergência pendente.</p>',
      botoes: [{ texto: 'OK', primario: true }] });
    return;
  }
  const i = Math.min(indice, lista.length - 1);
  const div = lista[i];
  const botoes = [{ texto: 'Resolver depois' }];
  for (const acao of div.acoes) {
    botoes.push({ texto: _ACOES_DIV[acao] || acao, primario: acao === 'local', acao: async () => {
      await api('resolver_divergencia', div.id, acao);
      atualizarIndicadorBackup(true);
      const restantes = await api('listar_divergencias');
      if (restantes.length) setTimeout(() => abrirDivergencias(Math.min(i, restantes.length - 1)), 0);
      else renderizar();
    } });
  }
  const p = abrirPopup({
    titulo: `${_TITULOS_DIV[div.tipo] || 'Divergência'}`,
    subtitulo: `Divergência ${i + 1} de ${lista.length}`,
    corpoHtml: `<p>${esc(div.descricao)}</p>
      ${div.caminho ? `<p class="texto-sec">${esc(div.caminho)}</p>` : ''}
      <div class="div-lados">${_ladoDiv(div, 'local')}${_ladoDiv(div, 'backup')}</div>
      <p class="texto-sec">Nada é apagado: a versão descartada fica guardada na pasta _Divergências.</p>`,
    botoes,
  });
  p.elemento.querySelectorAll('[data-abrir]').forEach(b => b.addEventListener('click', () =>
    api('abrir_arquivo_divergencia', div.id, b.dataset.abrir).catch(() => {})));
}
