/* Tela Configurações (base desta tarefa: pasta base e tema).
 * Tipos de documento, status, logo da empresa e teste de conexão entram nas próximas tarefas. */

Orbit.views.config = async el => {
  const s = Orbit.settings;
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Configurações</h1>
    <div class="pagina">
      <div class="secao-titulo">Pasta base</div>
      <div class="bloco">
        <div class="caminho">${esc(s.pasta_base)}</div>
        <button type="button" class="btn" id="cfg-pasta">Alterar pasta base</button>
      </div>
      <div class="secao-titulo">Tema</div>
      <div class="opcoes" id="cfg-tema">
        <div class="opcao" data-tema="escuro"><div class="t">Escuro suave</div><div class="d">Padrão</div></div>
        <div class="opcao" data-tema="claro"><div class="t">Claro suave</div><div class="d">Fundo claro</div></div>
      </div>
    </div>`;

  const marcar = tema => el.querySelectorAll('#cfg-tema .opcao').forEach(o =>
    o.classList.toggle('on', o.dataset.tema === tema));
  marcar(s.tema);

  el.querySelectorAll('#cfg-tema .opcao').forEach(o => o.addEventListener('click', async () => {
    const tema = o.dataset.tema;
    if (tema === Orbit.settings.tema) return;
    Orbit.settings = await api('set_tema', tema);
    aplicarTema(Orbit.settings.tema);
    marcar(Orbit.settings.tema);
  }));

  el.querySelector('#cfg-pasta').addEventListener('click', async () => {
    const settings = await api('escolher_pasta_base');
    if (settings) await recarregar();
  });
};
