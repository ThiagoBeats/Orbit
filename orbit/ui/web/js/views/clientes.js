/* Tela inicial: cartões de clientes com busca. */

function formatarDataCurta(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[3]}/${m[2]}/${m[1].slice(2)}` : '—';
}

Orbit.views.clientes = async (el, _id, aindaAtual) => {
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Clientes</h1>
    <div class="barra">
      <input type="search" id="cli-busca" class="busca" placeholder="Buscar cliente ou projeto…" autocomplete="off">
      <div class="barra-botoes">
        <button type="button" class="btn" id="cli-novo-projeto">Novo projeto</button>
        <button type="button" class="btn solid" id="cli-novo">Novo cliente</button>
      </div>
    </div>
    <div class="pagina"><div class="grid-cartoes" id="cli-lista"></div></div>`;
  const lista = el.querySelector('#cli-lista');
  const campo = el.querySelector('#cli-busca');
  let seq = 0;

  async function carregar() {
    const minha = ++seq;
    const clientes = await api('listar_clientes', campo.value);
    if (minha !== seq || !aindaAtual()) return;
    if (!clientes.length) {
      lista.innerHTML = `<p class="texto-sec">${campo.value.trim()
        ? 'Nenhum cliente ou projeto encontrado.'
        : 'Nenhum cliente ainda. Use "Novo cliente" para começar.'}</p>`;
      return;
    }
    lista.innerHTML = clientes.map(c => c.erro ? `
      <div class="card erro-card"><div class="t">${esc(c.nome)}</div>
        <div class="m">${esc(c.erro)}</div></div>` : `
      <a class="card cartao-link" href="#/cliente/${encodeURIComponent(c.id)}">
        <div class="t">${esc(c.nome)}</div>
        <div class="m">${c.projetos_ativos} ${c.projetos_ativos === 1 ? 'projeto ativo' : 'projetos ativos'}</div>
        <div class="m">Última emissão: ${esc(formatarDataCurta(c.ultima_emissao))}</div>
      </a>`).join('');
  }

  let timer = null;
  campo.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => carregar().catch(() => {}), 200);
  });

  el.querySelector('#cli-novo').addEventListener('click', async () => {
    const c = await popupDadosCliente();
    if (c) await carregar();
  });
  el.querySelector('#cli-novo-projeto').addEventListener('click', async () => {
    const todos = (await api('listar_clientes', '')).filter(c => !c.erro && c.id);
    if (!todos.length) { mostrarErro('Crie um cliente antes de criar um projeto.'); return; }
    const p = await popupDadosProjeto({ clientes: todos });
    if (p) await carregar();
  });

  await carregar();
  campo.focus();
};
