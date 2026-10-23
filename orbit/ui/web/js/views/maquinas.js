/* Máquinas Padrão: cartões de máquina e popup de dados da máquina.
 *
 * popupDadosMaquina({maquina?}) -> Promise<{id} | null>
 *   sem "maquina": cria; com "maquina" (container do obter_painel): edita.
 * Abrir uma máquina leva ao painel (#/maquina/<id>, js/views/painel.js).
 */

function popupDadosMaquina({ maquina = null } = {}) {
  return new Promise(resolve => {
    let salvo = null;
    const m = maquina || {};
    const popup = abrirPopup({
      titulo: maquina ? 'Dados da máquina' : 'Nova máquina',
      subtitulo: maquina ? 'Alterar o nome não renomeia a pasta já criada.' : '',
      classe: 'largo',
      corpoHtml: _campo('Código', 'dm-codigo', m.codigo) + _campo('Nome', 'dm-nome', m.nome)
        + `<div class="field"><label for="dm-desc">Descrição</label>
           <textarea id="dm-desc" rows="3">${esc(m.descricao)}</textarea></div>`,
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Salvar', primario: true, acao: async p => {
          const el = p.elemento;
          const dados = {
            codigo: el.querySelector('#dm-codigo').value.trim(),
            nome: el.querySelector('#dm-nome').value.trim(),
            descricao: el.querySelector('#dm-desc').value.trim(),
          };
          if (maquina) {
            await api('atualizar_maquina', maquina.id, dados);
            salvo = { id: maquina.id };
          } else {
            salvo = await api('criar_maquina', dados);
          }
        } },
      ],
    });
    popup._aoFechar = () => resolve(salvo);
  });
}

Orbit.views.maquinas = async (el, _id, aindaAtual) => {
  const lista = await api('listar_maquinas');
  if (!aindaAtual()) return;
  const cartao = m => {
    if (m.erro) {
      return `<div class="card erro-card"><div class="t">${esc(m.nome)}</div>
        <div class="m">${esc(m.erro)}</div></div>`;
    }
    return `<a class="card cartao-link" href="#/maquina/${encodeURIComponent(m.id)}">
      ${m.codigo ? `<div class="m" style="margin:0">${esc(m.codigo)}</div>` : ''}
      <div class="t" style="margin-top:4px">${esc(m.nome)}</div>
      <div class="m"><span>Emitidos ${esc(m.emitidos)}/${esc(m.aplicaveis)}</span></div>
      <div class="m">Última emissão: ${esc(formatarDataCurta(m.ultima_emissao))}</div>
    </a>`;
  };
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Máquinas Padrão</h1>
    <div class="barra">
      <div></div>
      <div class="barra-botoes"><button type="button" class="btn solid" id="mq-nova">Nova máquina</button></div>
    </div>
    <div class="pagina"><div class="grid-cartoes">${lista.length ? lista.map(cartao).join('')
      : '<p class="texto-sec">Nenhuma máquina padrão ainda. Use "Nova máquina" para começar.</p>'}</div></div>`;
  el.querySelector('#mq-nova').addEventListener('click', async () => {
    const m = await popupDadosMaquina();
    if (m) irPara(`#/maquina/${encodeURIComponent(m.id)}`);
  });
};
