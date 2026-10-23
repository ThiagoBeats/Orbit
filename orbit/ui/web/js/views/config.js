/* Tela Configurações: pasta base, tema, tipos de documento, status e logo da empresa.
 * Inclui o botão de teste de conexão (spec §9, §12). */

Orbit.views.config = async el => {
  const s = Orbit.settings;
  // estado editável das listas (cópia: só vira "salvo" depois da resposta da Api)
  let tipos = Orbit.config.tipos.map(t => ({ ...t }));
  let status = Orbit.config.status.map(nome => ({ original: nome, nome }));

  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Configurações</h1>
    <div class="pagina">
      <div class="secao-titulo">Pasta base</div>
      <div class="bloco">
        <div class="caminho">${esc(s.pasta_base)}</div>
        <button type="button" class="btn" id="cfg-pasta">Trocar</button>
        <button type="button" class="btn" id="cfg-conexao">Testar conexão</button>
      </div>

      <div class="secao-titulo">Tema</div>
      <div class="opcoes" id="cfg-tema">
        <div class="opcao" data-tema="escuro"><div class="t">Escuro suave</div><div class="d">Padrão</div></div>
        <div class="opcao" data-tema="claro"><div class="t">Claro suave</div><div class="d">Fundo claro</div></div>
      </div>

      <div class="secao-titulo">Logo da empresa</div>
      <div class="bloco linha-logo">
        <div class="previa-logo" id="cfg-logo-previa"></div>
        <div>
          <div class="texto-sec">Aparece no cabeçalho, ao lado do Orbit. Formatos: PNG, JPG, SVG ou WEBP.
            O Orbit guarda uma cópia na pasta base; o arquivo original não é alterado.</div>
          <button type="button" class="btn" id="cfg-logo">Escolher imagem</button>
        </div>
      </div>

      <div class="secao-titulo">Tipos de documento</div>
      <div class="bloco">
        <div class="texto-sec">Renomear muda só o nome mostrado; as pastas existentes não mudam.
          Tipos não são apagados: desative para esconder de projetos novos
          (projetos que já têm revisão continuam mostrando).</div>
        <div id="cfg-tipos" class="lista-cfg"></div>
        <div class="linha-cfg">
          <input type="text" id="cfg-tipo-novo" maxlength="80" placeholder="Novo tipo de documento">
          <button type="button" class="btn pequeno" id="cfg-tipo-add">Adicionar</button>
        </div>
        <button type="button" class="btn solid" id="cfg-tipos-salvar">Salvar tipos</button>
      </div>

      <div class="secao-titulo">Status</div>
      <div class="bloco">
        <div class="texto-sec">Um status que está na revisão atual de algum documento não pode ser
          removido nem renomeado.</div>
        <div id="cfg-status" class="lista-cfg"></div>
        <div class="linha-cfg">
          <input type="text" id="cfg-status-novo" maxlength="60" placeholder="Novo status">
          <button type="button" class="btn pequeno" id="cfg-status-add">Adicionar</button>
        </div>
        <button type="button" class="btn solid" id="cfg-status-salvar">Salvar status</button>
      </div>
    </div>`;

  montarSecaoBackup(el);

  /* ---- tema ---- */
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

  /* ---- pasta base ---- */
  el.querySelector('#cfg-pasta').addEventListener('click', async () => {
    const settings = await api('trocar_pasta_base');
    if (settings) await recarregar();
  });

  el.querySelector('#cfg-conexao').addEventListener('click',
    () => testarConexao({ detalhe: true }));

  /* ---- logo ---- */
  function mostrarPrevia() {
    const box = el.querySelector('#cfg-logo-previa');
    box.innerHTML = Orbit.config.logo_url
      ? `<img src="${esc(Orbit.config.logo_url)}" alt="Logo da empresa">`
      : '<span>Sem logo</span>';
  }
  mostrarPrevia();
  el.querySelector('#cfg-logo').addEventListener('click', async () => {
    const r = await api('definir_logo_empresa');
    if (!r) return; // cancelado
    Orbit.config = await api('get_config');
    atualizarLogoEmpresa();
    mostrarPrevia();
  });

  /* ---- tipos ---- */
  function desenharTipos() {
    el.querySelector('#cfg-tipos').innerHTML = tipos.map((t, i) => `
      <div class="linha-cfg" data-i="${i}">
        <input type="text" class="cfg-nome" maxlength="80" value="${esc(t.nome)}" aria-label="Nome do tipo">
        <label class="ativo-cfg"><input type="checkbox" class="cfg-ativo" ${t.ativo ? 'checked' : ''}> Ativo</label>
      </div>`).join('');
    el.querySelectorAll('#cfg-tipos .linha-cfg').forEach(l => {
      const t = tipos[+l.dataset.i];
      l.querySelector('.cfg-nome').addEventListener('input', e => { t.nome = e.target.value; });
      l.querySelector('.cfg-ativo').addEventListener('change', e => { t.ativo = e.target.checked; });
    });
  }
  desenharTipos();

  el.querySelector('#cfg-tipo-add').addEventListener('click', () => {
    const campo = el.querySelector('#cfg-tipo-novo');
    const nome = campo.value.trim();
    if (!nome) return;
    tipos.push({ id: null, nome, ativo: true });
    campo.value = '';
    desenharTipos();
  });
  el.querySelector('#cfg-tipos-salvar').addEventListener('click', async () => {
    const dados = await api('salvar_tipos',
      tipos.map(t => ({ id: t.id, nome: t.nome, ativo: t.ativo })));
    Orbit.config = dados;
    tipos = dados.tipos.map(t => ({ ...t }));
    desenharTipos();
  });

  /* ---- status ---- */
  function desenharStatus() {
    el.querySelector('#cfg-status').innerHTML = status.map((st, i) => `
      <div class="linha-cfg" data-i="${i}">
        <input type="text" class="cfg-nome" maxlength="60" value="${esc(st.nome)}" aria-label="Nome do status">
        <button type="button" class="btn pequeno cfg-remover">Remover</button>
      </div>`).join('');
    el.querySelectorAll('#cfg-status .linha-cfg').forEach(l => {
      const i = +l.dataset.i;
      l.querySelector('.cfg-nome').addEventListener('input', e => { status[i].nome = e.target.value; });
      l.querySelector('.cfg-remover').addEventListener('click', () => {
        status.splice(i, 1);
        desenharStatus();
      });
    });
  }
  desenharStatus();

  el.querySelector('#cfg-status-add').addEventListener('click', () => {
    const campo = el.querySelector('#cfg-status-novo');
    const nome = campo.value.trim();
    if (!nome) return;
    status.push({ original: null, nome });
    campo.value = '';
    desenharStatus();
  });
  el.querySelector('#cfg-status-salvar').addEventListener('click', async () => {
    const dados = await api('salvar_status', status.map(st => st.nome));
    Orbit.config = dados;
    status = dados.status.map(nome => ({ original: nome, nome }));
    desenharStatus();
  });
};
