/* Backup e sincronização (spec de backup §4, §5, §6, §8).
 *
 * - Indicador no cabeçalho (#backup-ind), só com backup configurado:
 *   "Backup em dia" / "Backup diferente (N)" / "Backup inacessível" / "Sincronizando…".
 *   Clique: popup de resumo com "Sincronizar agora".
 * - Timer: status_backup a cada "intervalo" minutos (a comparação de verdade
 *   também é limitada pelo Python).
 * - sincronizarAgora(): inicia o job e acompanha com um popup de progresso
 *   (Cancelar); no fim mostra o resumo e abre as divergências, se houver.
 * - montarSecaoBackup(el): seção "Backup" da tela Configurações.
 * - restaurarPcNovo(): fluxo de recuperação num PC novo (também na boas-vindas).
 */

Orbit.backup = null; // último status_backup

const _ROTULO_BACKUP = {
  em_dia: ['ok', 'Backup em dia'],
  diferente: ['aviso', 'Backup diferente'],
  inacessivel: ['falha', 'Backup inacessível'],
  sincronizando: ['info', 'Sincronizando…'],
};

let _timerBackup = null;

function _pintarBackup(st) {
  const box = document.getElementById('backup-ind');
  if (!box) return;
  if (!st || st.estado === 'desativado' || !st.caminho) { box.innerHTML = ''; return; }
  const [cls, texto] = _ROTULO_BACKUP[st.estado] || ['', st.estado];
  const n = st.estado === 'diferente' ? ` (${esc(st.pendentes + st.divergencias)})` : '';
  box.innerHTML = `<button type="button" class="ind ${cls}" id="btn-backup" title="${esc(st.caminho)}"><span class="ponto"></span>${esc(texto)}${n}</button>`;
  box.querySelector('#btn-backup').addEventListener('click', () => popupResumoBackup());
}

async function atualizarIndicadorBackup(forcar = false) {
  const r = await _apiQuieta('status_backup', forcar);
  if (!r || !r.ok) return null;
  Orbit.backup = r.dados;
  _pintarBackup(r.dados);
  _agendarBackup(r.dados);
  const botao = document.getElementById('cli-sincronizar');
  if (botao) botao.hidden = !r.dados.caminho;
  return r.dados;
}

function _agendarBackup(st) {
  if (_timerBackup) clearInterval(_timerBackup);
  _timerBackup = null;
  if (!st || !st.caminho) return;
  const ms = Math.max(1, st.intervalo || 10) * 60000;
  _timerBackup = setInterval(() => atualizarIndicadorBackup(false), ms);
}

async function popupResumoBackup() {
  const st = await atualizarIndicadorBackup(true);
  if (!st) return;
  const linhas = [
    ['Pasta de backup', esc(st.caminho)],
    ['Situação', esc((_ROTULO_BACKUP[st.estado] || ['', st.estado])[1])],
    ['Alterações pendentes', esc(st.pendentes)],
    ['Divergências', esc(st.divergencias)],
    ['Última sincronização', esc(formatarDataHora(st.ultima_sync))],
  ];
  if (st.erro) linhas.push(['Erro', esc(st.erro)]);
  abrirPopup({
    titulo: 'Backup',
    corpoHtml: `<table class="detalhe-conexao">${linhas.map(([a, b]) =>
      `<tr><td>${a}</td><td>${b}</td></tr>`).join('')}</table>`,
    botoes: [
      { texto: 'Fechar' },
      ...(st.divergencias ? [{ texto: 'Ver divergências', acao: () => { abrirDivergencias(); } }] : []),
      { texto: 'Sincronizar agora', primario: true, acao: () => { sincronizarAgora(); } },
    ],
  });
}

function formatarDataHora(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
  return m ? `${m[3]}/${m[2]}/${m[1].slice(2)} ${m[4]}:${m[5]}` : '—';
}

/* Acompanha o job atual (sincronização, configuração ou recuperação). */
function acompanharJob(titulo) {
  return new Promise(resolve => {
    let parar = false;
    const popup = abrirPopup({
      titulo,
      corpoHtml: `<p id="job-fase" class="texto-sec">Preparando…</p>
        <div class="barra-progresso"><div id="job-barra"></div></div>`,
      botoes: [{ texto: 'Cancelar', acao: async () => {
        await _apiQuieta('cancelar_sincronizacao');
        return false; // fecha quando o job terminar
      } }],
    });
    popup._aoFechar = () => { parar = true; };
    const passo = async () => {
      if (parar) return;
      const r = await _apiQuieta('progresso_backup');
      if (!r || !r.ok) { popup.fechar(); resolve(null); return; }
      const p = r.dados;
      const fase = popup.elemento.querySelector('#job-fase');
      const barra = popup.elemento.querySelector('#job-barra');
      if (fase) fase.textContent = p.total ? `${p.fase} ${p.atual} de ${p.total}` : p.fase;
      if (barra) barra.style.width = p.total ? `${Math.round(100 * p.atual / p.total)}%` : '0%';
      if (p.rodando) { setTimeout(passo, 400); return; }
      parar = true;
      popup.fechar();
      resolve(p.resultado);
    };
    setTimeout(passo, 200);
  });
}

function _resumoResultado(res) {
  if (!res) return '<p>Sem resultado.</p>';
  if (res.erro) return `<p class="aviso">${esc(res.erro)}</p>`;
  const itens = [
    `${esc(res.enviados || 0)} arquivo(s) enviados ao backup`,
    `${esc(res.recebidos || 0)} arquivo(s) trazidos do backup`,
  ];
  if (res.restaurados) itens.push(`${esc(res.restaurados)} arquivo(s) restaurados (tinham sumido de um dos lados)`);
  if (res.divergencias && res.divergencias.length) itens.push(`${esc(res.divergencias.length)} divergência(s) para você decidir`);
  let html = `${res.cancelado ? '<p class="aviso">Sincronização cancelada.</p>' : ''}<ul>${itens.map(i => `<li>${i}</li>`).join('')}</ul>`;
  if (res.pulados && res.pulados.length) {
    html += `<p class="texto-sec">Ficaram para a próxima sincronização:</p><ul>${res.pulados.slice(0, 10).map(p => `<li>${esc(p)}</li>`).join('')}</ul>`;
  }
  return html;
}

async function _depoisDoJob(titulo, res) {
  await atualizarIndicadorBackup(true);
  if (res && !res.erro && res.divergencias && res.divergencias.length) {
    abrirDivergencias();
    return;
  }
  abrirPopup({ titulo, corpoHtml: _resumoResultado(res),
    botoes: [{ texto: 'OK', primario: true }], classe: res && res.erro ? 'erro' : '' });
}

async function sincronizarAgora() {
  await api('sincronizar_backup');
  _pintarBackup({ ...(Orbit.backup || {}), estado: 'sincronizando' });
  const res = await acompanharJob('Sincronizando com o backup');
  await _depoisDoJob('Sincronização', res);
  renderizar();
}

/* ---- Configurações: seção Backup ---------------------------------------- */

function montarSecaoBackup(el) {
  const caixa = document.createElement('div');
  caixa.innerHTML = `
    <div class="secao-titulo">Backup</div>
    <div class="bloco" id="cfg-backup"><p class="texto-sec">Carregando…</p></div>`;
  el.querySelector('.pagina').appendChild(caixa);
  _desenharSecaoBackup(caixa.querySelector('#cfg-backup'));
}

async function _desenharSecaoBackup(box) {
  const st = await atualizarIndicadorBackup(false);
  if (!st) return;
  const configurado = !!st.caminho;
  box.innerHTML = `
    ${configurado
      ? `<div class="caminho">${esc(st.caminho)}</div>
         <div class="texto-sec">Última sincronização: ${esc(formatarDataHora(st.ultima_sync))}</div>`
      : `<div class="texto-sec">Nenhum backup configurado. Escolha uma pasta no servidor, num HD
           externo ou numa pasta de nuvem. Cada alteração feita no Orbit também é copiada
           para lá, e o botão Sincronizar junta as alterações dos dois lados.</div>`}
    ${st.aviso_nuvem ? `<p class="aviso-ambar">${esc(st.aviso_nuvem)}</p>` : ''}
    <div class="linha-cfg">
      <button type="button" class="btn" id="bk-escolher">${configurado ? 'Trocar pasta' : 'Escolher pasta'}</button>
      ${configurado ? `<button type="button" class="btn solid" id="bk-sync">Sincronizar agora</button>
      <button type="button" class="btn" id="bk-desativar">Desativar</button>` : ''}
    </div>
    ${configurado ? `<div class="linha-cfg"><label for="bk-intervalo">Verificar a cada</label>
      <input type="number" id="bk-intervalo" min="1" max="1440" value="${esc(st.intervalo)}" style="width:90px"> minutos
      <button type="button" class="btn pequeno" id="bk-intervalo-salvar">Salvar</button></div>` : ''}
    <div class="secao-sub">Recuperar backup</div>
    <div class="texto-sec">Juntar traz o que falta de um backup para a pasta base atual (e envia para ele o que só existe aqui).
      Para montar tudo do zero num computador novo, use "Restaurar num PC novo".</div>
    <div class="linha-cfg">
      <button type="button" class="btn" id="bk-juntar">Juntar com a pasta base</button>
      <button type="button" class="btn" id="bk-restaurar">Restaurar num PC novo</button>
    </div>`;
  const on = (id, fn) => { const b = box.querySelector(id); if (b) b.addEventListener('click', fn); };
  on('#bk-escolher', async () => {
    const r = await api('escolher_backup');
    if (!r) return;
    if (r.analise === 'estranho') {
      mostrarErro('A pasta escolhida tem arquivos que não são do Orbit. Escolha uma pasta vazia ou um backup do Orbit.');
      return;
    }
    const msg = r.analise === 'orbit'
      ? 'Esta pasta já tem um backup do Orbit. Nada será sobrescrito: o Orbit vai juntar os dados dos dois lados (o que só existe aqui vai para o backup, e o que só existe lá vem para cá). Continuar?'
      : 'O Orbit vai fazer a primeira cópia completa da pasta base para esta pasta. Continuar?';
    if (r.aviso_nuvem && !(await confirmar(r.aviso_nuvem))) return;
    if (!(await confirmar(msg))) return;
    await api('configurar_backup', r.caminho);
    const res = await acompanharJob(r.analise === 'orbit' ? 'Juntando com o backup' : 'Primeira cópia do backup');
    await _depoisDoJob('Backup configurado', res);
    _desenharSecaoBackup(box);
  });
  on('#bk-sync', async () => { await sincronizarAgora(); _desenharSecaoBackup(box); });
  on('#bk-desativar', async () => {
    if (!(await confirmar('Desativar o backup? Os arquivos que já estão lá não são apagados.'))) return;
    await api('desativar_backup');
    await atualizarIndicadorBackup(true);
    _desenharSecaoBackup(box);
  });
  on('#bk-intervalo-salvar', async () => {
    const v = box.querySelector('#bk-intervalo').value;
    const min = await api('definir_intervalo_backup', Number(v));
    box.querySelector('#bk-intervalo').value = min;
    await atualizarIndicadorBackup(false);
  });
  on('#bk-juntar', async () => {
    const r = await api('recuperar_juntando');
    if (!r) return;
    const res = await acompanharJob('Juntando com o backup');
    await _depoisDoJob('Recuperação concluída', res);
  });
  on('#bk-restaurar', restaurarPcNovo);
}

/* ---- Restaurar num PC novo (Configurações e boas-vindas) ----------------- */

async function restaurarPcNovo() {
  if (!(await confirmar('Escolha primeiro a pasta do backup e, depois, uma pasta VAZIA onde a nova pasta base será montada.'))) return;
  const r = await api('restaurar_pc_novo');
  if (!r) return;
  const res = await acompanharJob('Restaurando do backup');
  if (!res || res.erro && !res.nova_base) {
    abrirPopup({ titulo: 'Restauração', corpoHtml: _resumoResultado(res),
      botoes: [{ texto: 'OK', primario: true }], classe: 'erro' });
    return;
  }
  const usar = await confirmar(`Restauração concluída (${res.recebidos || 0} arquivo(s)). `
    + `Usar ${res.caminho_backup} como o backup deste computador?`);
  await api('concluir_restauracao', res.nova_base, res.caminho_backup, usar);
  if (res.erro) mostrarErro(res.erro);
  await recarregar();
}
