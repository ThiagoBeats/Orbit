/* Tela Início: dashboard do dia e das empresas (spec Meu dia §6; rascunho aprovado
 * .superpowers/brainstorm/844-1792756537/content/dashboard-dia.html). */

const _DIAS_SEMANA = ['domingo', 'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
  'sexta-feira', 'sábado'];
const _MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto',
  'setembro', 'outubro', 'novembro', 'dezembro'];
let _timerMeiaNoite = null;

function _dataPorExtenso(iso) {
  const [a, m, d] = iso.split('-').map(Number);
  const dt = new Date(a, m - 1, d);
  const sem = _DIAS_SEMANA[dt.getDay()];
  return `${sem.charAt(0).toUpperCase()}${sem.slice(1)}, ${d} de ${_MESES[m - 1]}`;
}

function _somarDias(iso, n) {
  const [a, m, d] = iso.split('-').map(Number);
  const dt = new Date(a, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

function _saudacao() {
  const h = new Date().getHours();
  return h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
}

function _agendarMeiaNoite() {
  if (_timerMeiaNoite) clearTimeout(_timerMeiaNoite);
  const agora = new Date();
  const amanha = new Date(agora.getFullYear(), agora.getMonth(), agora.getDate() + 1, 0, 0, 5);
  _timerMeiaNoite = setTimeout(() => {
    if (lerRota().nome === 'inicio') renderizar();
    _agendarMeiaNoite();
  }, amanha - agora);
}

Orbit.views.inicio = async (conteudo, _id, aindaAtual) => {
  // contêiner próprio a cada visita: os ouvintes de clique não se acumulam em #conteudo
  const el = document.createElement('div');
  conteudo.appendChild(el);
  let dia = null; // null = hoje
  const projetos = await opcoesProjetos(true);
  if (!aindaAtual()) return;

  async function desenhar() {
    const d = await api('dashboard', dia);
    if (!aindaAtual()) return;
    const ehHoje = d.dia === d.hoje;
    const b = Orbit.backup;
    const backup = !b || !b.caminho ? ['—', 'Sem backup']
      : b.estado === 'em_dia' ? ['●', 'Backup em dia']
      : b.estado === 'inacessivel' ? ['●', 'Backup inacessível'] : ['●', 'Backup diferente'];
    const corBackup = !b || !b.caminho ? '' : b.estado === 'em_dia' ? 'ok' : b.estado === 'inacessivel' ? 'pend' : 'warn';
    el.innerHTML = `
      <div class="topo-inicio">
        <div><h1>${esc(_saudacao())}, ${esc(d.usuario)}</h1>
          <div class="sub">${esc(_dataPorExtenso(d.hoje))}</div></div>
        <div class="stats">
          <div class="stat"><div class="v">${esc(d.numeros.abertas_hoje)}</div><div class="l">Abertas hoje</div></div>
          <div class="stat"><div class="v">${esc(d.numeros.projetos_ativos)}</div><div class="l">Projetos ativos</div></div>
          <div class="stat"><div class="v">${esc(d.numeros.docs_pendentes)}</div><div class="l">Docs pendentes</div></div>
          <div class="stat"><div class="v cor-${corBackup}">${esc(backup[0])}</div><div class="l">${esc(backup[1])}</div></div>
        </div>
      </div>
      <main class="inicio">
        <div>
          <div class="bloco painel-inicio">
            <div class="cab-painel"><span>Meu dia${ehHoje ? '' : ` · ${esc(formatarDataCurta(d.dia))}`}</span>
              <span class="nav-dia"><button type="button" class="btn pequeno" id="in-ant" title="Dia anterior">‹</button>
                ${ehHoje ? '' : '<button type="button" class="btn pequeno" id="in-hoje">Hoje</button>'}
                <button type="button" class="btn pequeno" id="in-prox" title="Próximo dia">›</button></span></div>
            ${d.erro_meu_dia ? `<p class="aviso">${esc(d.erro_meu_dia)}</p>` : `
            <div class="add-item">
              <input type="text" id="in-texto" maxlength="500" placeholder="O que você vai fazer? (Enter adiciona)">
              <select id="in-tipo">${_optionsTipos('atividade')}</select>
              <select id="in-proj">${_optionsProjetos(projetos, null)}</select>
            </div>`}
            <div id="in-itens">${d.itens.length ? d.itens.map(i => htmlItem(i)).join('')
              : '<p class="texto-sec">Nada por aqui. Escreva acima e aperte Enter.</p>'}</div>
          </div>
          <div class="bloco painel-inicio">
            <div class="cab-painel"><span>Lembretes</span>
              <button type="button" class="btn pequeno" id="in-lembrete">+ Lembrete</button></div>
            ${d.lembretes.length ? d.lembretes.map(l => `<div class="lembrete" data-lembrete="${esc(l.id)}">
              <span class="hora">${esc(formatarDataHora(l.adiado_ate || l.quando))}</span>
              <span class="txt">${esc(l.texto)}${l.container_nome ? ` <span class="proj">· ${esc(l.container_nome)}</span>` : ''}
                ${l.recorrencia && l.recorrencia.tipo !== 'nenhuma' ? '<span class="tag">repete</span>' : ''}</span></div>`).join('')
              : '<p class="texto-sec">Nenhum lembrete agendado.</p>'}
          </div>
        </div>
        <div>
          <div class="bloco painel-inicio">
            <div class="cab-painel"><span>Onde parei</span></div>
            ${d.onde_parei.length ? d.onde_parei.map(x => `<a class="projcard" href="#/projeto/${encodeURIComponent(x.container_id)}">
              <div class="n">${esc(x.container_nome)}${x.cliente_nome ? ` <span class="proj">· ${esc(x.cliente_nome)}</span>` : ''}</div>
              <div class="p">${esc(x.item.texto)} · ${esc(formatarDataHora(x.item.alterado_em))}</div></a>`).join('')
              : '<p class="texto-sec">Anote "Onde parei" num projeto para ver aqui onde você estava.</p>'}
          </div>
          <div class="bloco painel-inicio">
            <div class="cab-painel"><span>Ideias para replicar</span></div>
            ${d.ideias.length ? d.ideias.map(x => `<div class="ideia"><div>${esc(x.item.texto)}</div>
              <div class="proj">de ${esc(x.container_nome)} · ${esc(x.item.usuario)}</div></div>`).join('')
              : '<p class="texto-sec">Os insights dos projetos aparecem aqui.</p>'}
          </div>
        </div>
      </main>`;
    const campo = el.querySelector('#in-texto');
    if (campo) {
      campo.addEventListener('keydown', async e => {
        if (e.key !== 'Enter' || !campo.value.trim()) return;
        await api('adicionar_item', { texto: campo.value, tipo: el.querySelector('#in-tipo').value,
          container_id: el.querySelector('#in-proj').value || null, dia }).catch(() => {});
        await desenhar();
        const novo = el.querySelector('#in-texto');
        if (novo) novo.focus();
      });
    }
    el.querySelector('#in-ant').addEventListener('click', () => { dia = _somarDias(d.dia, -1); desenhar(); });
    el.querySelector('#in-prox').addEventListener('click', () => { dia = _somarDias(d.dia, 1); desenhar(); });
    const hoje = el.querySelector('#in-hoje');
    if (hoje) hoje.addEventListener('click', () => { dia = null; desenhar(); });
    el.querySelector('#in-lembrete').addEventListener('click', () => popupLembrete(null, desenhar));
    el.querySelectorAll('[data-lembrete]').forEach(x => x.addEventListener('click', () => {
      const l = d.lembretes.find(y => y.id === x.dataset.lembrete);
      popupLembrete(l, desenhar);
    }));
  }

  ligarItens(el, () => desenhar());
  _agendarMeiaNoite();
  Orbit.recarregarInicio = desenhar;
  await desenhar();
};
