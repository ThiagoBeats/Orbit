/* Página do cliente: dados, contatos e cartões de projeto. */

Orbit.views.cliente = async (el, id, aindaAtual) => {
  const d = await api('obter_cliente', id);
  if (!aindaAtual()) return;
  const c = d.cliente;
  const contatos = c.contatos.length
    ? c.contatos.map(x => `<div>${esc(x.nome)}${x.email ? ` &lt;${esc(x.email)}&gt;` : ''}</div>`).join('')
    : '<span class="texto-sec">Nenhum contato cadastrado.</span>';

  const cartao = p => {
    if (p.erro) {
      return `<div class="card erro-card"><div class="t">${esc(p.nome)}</div>
        <div class="m">${esc(p.erro)}</div></div>`;
    }
    const concl = p.situacao === 'concluido';
    return `<a class="card cartao-link" href="#/projeto/${encodeURIComponent(p.id)}">
      <div class="m" style="margin:0">${esc(p.codigo)}</div>
      <div class="t" style="margin-top:4px">${esc(p.nome)}</div>
      <div class="m"><span class="chip ${concl ? 'info' : 'ok'}">${concl ? 'Concluído' : 'Ativo'}</span>
        <span>Emitidos ${p.emitidos}/${p.aplicaveis}</span></div>
      <div class="m">Última emissão: ${esc(formatarDataCurta(p.ultima_emissao))}</div>
    </a>`;
  };

  el.innerHTML = `
    <div class="crumb"><a href="#/clientes">Clientes</a> / ${esc(c.nome)}</div>
    <h1>${esc(c.nome)}</h1>
    <div class="pagina">
      <div class="bloco">
        ${c.cnpj ? `<div class="texto-sec">CNPJ: ${esc(c.cnpj)}</div>` : ''}
        <div class="secao-titulo" style="margin-top:0">Contatos</div>
        ${contatos}
        <button type="button" class="btn" id="cl-editar">Editar</button>
      </div>
      <div class="secao-titulo">Projetos</div>
      <div class="barra-botoes"><button type="button" class="btn solid" id="cl-novo-proj">Novo projeto</button></div>
      <div class="grid-cartoes" style="margin-top:12px">
        ${d.projetos.length ? d.projetos.map(cartao).join('') : '<p class="texto-sec">Nenhum projeto ainda.</p>'}
      </div>
    </div>`;

  el.querySelector('#cl-editar').addEventListener('click', async () => {
    if (await popupDadosCliente({ cliente: c })) renderizar();
  });
  el.querySelector('#cl-novo-proj').addEventListener('click', async () => {
    if (await popupDadosProjeto({ clienteId: c.id })) renderizar();
  });
};
