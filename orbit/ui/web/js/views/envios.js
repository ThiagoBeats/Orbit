/* Envios: e-mails preparados (registrados no histórico), com filtro por cliente. */

Orbit.views.envios = async (el, _id, aindaAtual) => {
  const clientes = await api('listar_clientes', '');
  if (!aindaAtual()) return;
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Envios</h1>
    <div class="barra">
      <select id="en-filtro" class="busca" style="max-width:320px">
        <option value="">Todos os clientes e máquinas</option>
        ${clientes.map(c => `<option value="${esc(c.id)}">${esc(c.nome)}</option>`).join('')}
      </select>
    </div>
    <div class="pagina" id="en-tabela"></div>`;
  const alvo = el.querySelector('#en-tabela');
  const nomesTipos = Object.fromEntries((Orbit.config.tipos || []).map(t => [t.id, t.nome]));
  let seq = 0;

  async function carregar() {
    const minha = ++seq;
    const filtro = el.querySelector('#en-filtro').value;
    const envios = await api('listar_envios', filtro || null);
    if (minha !== seq || !aindaAtual()) return;
    if (!envios.length) { alvo.innerHTML = '<p class="texto-sec">Nenhum envio registrado.</p>'; return; }
    alvo.innerHTML = `<table class="tabela">
      <thead><tr><th>Data/hora</th><th>Cliente / container</th><th>Destinatários</th>
        <th>Documentos e revisões</th></tr></thead>
      <tbody>${envios.map(e => `<tr>
        <td class="nowrap">${_formatarDataHora(e.data_hora)}</td>
        <td>${e.cliente_nome ? `${esc(e.cliente_nome)} / ` : '<span class="texto-sec">Máquina padrão</span> / '}${esc(e.container_nome)}</td>
        <td>${esc((e.destinatarios || []).join('; ')) || '<span class="texto-sec">—</span>'}</td>
        <td>${(e.itens || []).map(i =>
          `<div>${esc(nomesTipos[i.tipo_id] || i.tipo_id)} ${formatarRev(i.numero)}</div>`).join('')}</td>
      </tr>`).join('')}</tbody></table>`;
  }

  el.querySelector('#en-filtro').addEventListener('change', () => carregar().catch(() => {}));
  await carregar();
};
