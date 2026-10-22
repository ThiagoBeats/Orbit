/* Orbit — núcleo da interface: chamada à Api, tema, cabeçalho e roteador por hash.
 *
 * api(nome, ...args)
 *   Chama window.pywebview.api[nome]. Em sucesso devolve "dados". Se a Api
 *   responder {ok:false}, mostra o popup de erro e lança ErroApi (que o resto
 *   do código pode ignorar: o usuário já foi avisado).
 *   Se a resposta trouxer "trava" (LockHeld: outra pessoa enviando revisão do
 *   mesmo documento), mostra o popup da trava, que oferece "Liberar trava"
 *   quando trava.abandonada é true (ver mostrarTrava).
 *
 * Presença (spec §12): ao entrar numa rota de container (#/projeto/<id> ou
 *   #/maquina/<id>) chama entrar_container e avisa se há outras pessoas; um
 *   timer de 30 s chama sinalizar_container; ao sair da rota chama
 *   sair_container. No fechamento da janela o Python (app.py) apaga a presença.
 *
 * Telas: cada arquivo em js/views/ registra Orbit.views[nome] = async (el, id) => {...}
 *   Rotas: #/clientes  #/cliente/<id>  #/projeto/<id>  #/maquinas  #/maquina/<id>
 *          #/envios  #/config
 */

const Orbit = window.Orbit = {
  views: {},
  settings: null,   // resposta de get_settings
  config: null,     // resposta de get_config (config compartilhada)
};

async function api(nome, ...args) {
  const ponte = window.pywebview && window.pywebview.api;
  if (!ponte || typeof ponte[nome] !== 'function') {
    mostrarErro(`Função indisponível na Api: ${nome}`);
    throw new ErroApi(nome);
  }
  let r;
  try {
    r = await ponte[nome](...args);
  } catch (e) {
    mostrarErro(`Falha de comunicação com o Orbit: ${e && e.message ? e.message : e}`);
    throw new ErroApi(String(e));
  }
  if (!r || !r.ok) {
    const msg = (r && r.erro) || 'Erro desconhecido.';
    if (r && r.trava) mostrarTrava(msg, r.trava); else mostrarErro(msg);
    throw new ErroApi(msg);
  }
  return r.dados;
}

/* Chamada à Api sem popup de erro (presença: é só um aviso, não atrapalha o uso). */
async function _apiQuieta(nome, ...args) {
  try {
    const ponte = window.pywebview && window.pywebview.api;
    return ponte && typeof ponte[nome] === 'function'
      ? await ponte[nome](...args) : { ok: false, erro: nome };
  } catch (e) {
    return { ok: false, erro: String(e) };
  }
}

/* Popup de LockHeld. Trava abandonada (mais de 10 min) pode ser liberada. */
function mostrarTrava(mensagem, trava) {
  const podeLiberar = trava.abandonada && trava.container_id && trava.tipo_id;
  return abrirPopup({
    titulo: 'Documento em uso',
    corpoHtml: `<p>${esc(mensagem)}</p>` + (podeLiberar
      ? '<p class="texto-sec">A trava tem mais de 10 minutos e parece abandonada (o envio pode ter sido interrompido). Se ninguém está enviando este documento agora, você pode liberá-la e tentar de novo.</p>'
      : '<p class="texto-sec">Aguarde o envio terminar e tente de novo.</p>'),
    botoes: podeLiberar
      ? [{ texto: 'Fechar' },
         { texto: 'Liberar trava', primario: true, acao: async () => {
           await api('liberar_trava', trava.container_id, trava.tipo_id);
           abrirPopup({ titulo: 'Trava liberada',
             corpoHtml: '<p>A trava foi liberada. Tente enviar de novo.</p>',
             botoes: [{ texto: 'OK', primario: true }] });
         } }]
      : [{ texto: 'OK', primario: true }],
    classe: 'erro',
  });
}

/* ---- Presença no container --------------------------------------------- */

const SINAL_PRESENCA_MS = 30000;
const _presenca = { id: null, timer: null };

function sairPresenca() {
  if (_presenca.timer) clearInterval(_presenca.timer);
  const id = _presenca.id;
  _presenca.id = null;
  _presenca.timer = null;
  if (id) _apiQuieta('sair_container', id);
}

async function atualizarPresenca(nome, id) {
  const novo = (nome === 'projeto' || nome === 'maquina') && id ? id : null;
  if (novo === _presenca.id) return; // re-renderização da mesma tela
  sairPresenca();
  if (!novo) return;
  _presenca.id = novo;
  _presenca.timer = setInterval(() => _apiQuieta('sinalizar_container', novo),
    SINAL_PRESENCA_MS);
  const r = await _apiQuieta('entrar_container', novo);
  if (_presenca.id !== novo || !r || !r.ok || !r.dados.length) return;
  abrirPopup({
    titulo: 'Aberto por outra pessoa',
    corpoHtml: r.dados.map(o => `<p>${esc(o.usuario)} (${esc(o.computador)}) está com este projeto aberto desde ${esc(o.hora)}. Cuidado com alterações simultâneas.</p>`).join(''),
    botoes: [{ texto: 'OK', primario: true }],
  });
}

window.addEventListener('unhandledrejection', e => {
  if (e.reason instanceof ErroApi) e.preventDefault(); // já mostrado ao usuário
});

/* ---- Tema ------------------------------------------------------------ */

function aplicarTema(tema) {
  document.body.classList.toggle('light', tema === 'claro');
}

/* ---- Logo (embutida no HTML para seguir as cores do tema) ------------- */

let _svgLogo = null;
let _contLogo = 0;

async function carregarLogo() {
  try {
    const r = await fetch('img/orbit-logo.svg');
    if (r.ok) _svgLogo = await r.text();
  } catch (e) { /* fica a <img> */ }
  embutirLogos();
}

function embutirLogos(raiz = document) {
  if (!_svgLogo) return;
  raiz.querySelectorAll('[data-logo-orbit]').forEach(el => {
    const id = `orbit-frente-${++_contLogo}`;
    el.innerHTML = _svgLogo.replaceAll('orbit-frente', id);
    el.removeAttribute('data-logo-orbit');
  });
}

/* ---- Cabeçalho -------------------------------------------------------- */

const SECAO_DA_ROTA = {
  clientes: 'clientes', cliente: 'clientes', projeto: 'clientes',
  maquinas: 'maquinas', maquina: 'maquinas',
  envios: 'envios', config: 'config',
};

/* Logo da empresa no espaço reservado do cabeçalho. */
function atualizarLogoEmpresa() {
  const box = document.getElementById('logo-empresa');
  if (!box) return;
  const url = Orbit.config && Orbit.config.logo_url;
  box.classList.toggle('tem-logo', !!url);
  if (url) {
    box.innerHTML = `<img src="${esc(url)}" alt="Logo da empresa">`;
  } else {
    box.textContent = 'LOGO';
  }
}

function marcarNavegacao(rota) {
  const secao = SECAO_DA_ROTA[rota];
  document.querySelectorAll('#nav a').forEach(a =>
    a.classList.toggle('on', a.dataset.secao === secao));
}

function ativarNavegacao(ativa) {
  document.getElementById('nav').classList.toggle('desativada', !ativa);
}

/* ---- Teste de conexão (spec §12) ---------------------------------------- */

let _testandoConexao = false;
let _popupFalhaConexao = null;

function _pintarIndicador(r, testando) {
  const box = document.getElementById('conexao');
  if (!box) return;
  const cls = testando ? 'testando' : (r ? (r.ok ? 'ok' : 'falha') : '');
  const texto = testando ? 'Testando…' : (r ? (r.ok ? 'Conectado' : 'Sem acesso') : '');
  box.innerHTML = r || testando
    ? `<button type="button" class="ind ${cls}" id="btn-conexao" title="Testar conexão com a pasta base"><span class="ponto"></span>${esc(texto)}</button>`
    : '';
  const b = document.getElementById('btn-conexao');
  if (b) b.addEventListener('click', () => testarConexao({ detalhe: true }));
}

/* Roda o teste e atualiza o indicador. Só um teste por vez (cliques extras são ignorados).
 * opcoes.falha: popup de falha (abertura); opcoes.detalhe: popup de detalhe (clique). */
async function testarConexao({ falha = false, detalhe = false } = {}) {
  if (_testandoConexao) return;
  _testandoConexao = true;
  _pintarIndicador(Orbit.conexao, true);
  let r = null;
  try {
    const lista = await api('testar_conexao');
    r = lista && lista[0];
  } catch (e) {
    if (!(e instanceof ErroApi)) console.error(e);
  } finally {
    _testandoConexao = false;
  }
  Orbit.conexao = r;
  _pintarIndicador(r, false);
  if (!r) return;
  if (r.ok) {
    if (_popupFalhaConexao) _popupFalhaConexao.fechar();
    if (detalhe) mostrarDetalheConexao(r);
  } else if (detalhe) {
    mostrarDetalheConexao(r);
  } else if (falha) {
    mostrarFalhaConexao(r);
  }
}

/* Nova tentativa depois de uma falha. Devolve true se a base está acessível e o estado
 * foi recarregado. Com a base fechada (offline na abertura), pede à Api para reabri-la. */
async function tentarDeNovo() {
  if (!Orbit.settings.base_ok) {
    const r = await _apiQuieta('reabrir_base');
    if (r && r.ok) { await recarregar(); return true; }
    return { erro: (r && r.erro) || 'Erro desconhecido.' };
  }
  await testarConexao();
  if (Orbit.conexao && Orbit.conexao.ok) { await recarregar(); return true; }
  return { erro: Orbit.conexao && Orbit.conexao.erro };
}

function mostrarFalhaConexao(r) {
  if (_popupFalhaConexao) _popupFalhaConexao.fechar();
  const p = _popupFalhaConexao = abrirPopup({
    titulo: 'Sem acesso à pasta base',
    corpoHtml: `<p id="falha-msg">Não foi possível acessar a pasta base ${esc(r.pasta)}: ${esc(r.erro || 'erro desconhecido')}</p>`,
    botoes: [
      { texto: 'Configurações', acao: () => { irPara('#/config'); } },
      { texto: 'Tentar de novo', primario: true, acao: async popup => {
        const res = await tentarDeNovo();
        if (res === true) return undefined; // recarregar() já fechou o popup
        const m = popup.elemento.querySelector('#falha-msg');
        if (m) m.textContent = `Não foi possível acessar a pasta base ${r.pasta}: ${res.erro || 'erro desconhecido'}`;
        return false;
      } },
    ],
    classe: 'erro',
  });
  p._aoFechar = () => { if (_popupFalhaConexao === p) _popupFalhaConexao = null; };
}

function mostrarDetalheConexao(r) {
  const sn = v => v ? '<span class="sim">OK</span>' : '<span class="nao">Falhou</span>';
  abrirPopup({
    titulo: r.ok ? 'Conectado' : 'Sem acesso',
    subtitulo: r.pasta,
    corpoHtml: `<table class="detalhe-conexao">
      <tr><td>Leitura</td><td>${sn(r.leitura)}</td></tr>
      <tr><td>Escrita</td><td>${sn(r.escrita)}</td></tr>
      <tr><td>Tempo</td><td>${esc(r.ms)} ms</td></tr>
      ${r.erro ? `<tr><td>Erro</td><td>${esc(r.erro)}</td></tr>` : ''}</table>`,
    botoes: [{ texto: 'OK', primario: true }],
    classe: r.ok ? '' : 'erro',
  });
}

/* ---- Roteador --------------------------------------------------------- */

const TITULOS = {
  clientes: 'Clientes', cliente: 'Cliente', projeto: 'Projeto',
  maquinas: 'Máquinas Padrão', maquina: 'Máquina', envios: 'Envios', config: 'Configurações',
};

function lerRota() {
  const partes = location.hash.replace(/^#\/?/, '').split('/');
  const nome = partes[0] || 'clientes';
  const id = partes.length > 1 ? decodeURIComponent(partes.slice(1).join('/')) : null;
  return { nome: TITULOS[nome] ? nome : 'clientes', id };
}

function irPara(hash) {
  if (location.hash === hash) renderizar(); else location.hash = hash;
}

let _renderizacao = 0;

async function renderizar() {
  if (!Orbit.settings) return;
  if (!Orbit.settings.base_ok) {
    if (Orbit.settings.pasta_base) telaSemBase();
    return;
  }
  const { nome, id } = lerRota();
  marcarNavegacao(nome);
  atualizarPresenca(nome, id);
  const el = document.getElementById('conteudo');
  const minha = ++_renderizacao;
  el.innerHTML = '';
  const view = Orbit.views[nome] || telaEmConstrucao(nome);
  try {
    await view(el, id, () => minha === _renderizacao);
  } catch (e) {
    if (!(e instanceof ErroApi)) {
      console.error(e);
      mostrarErro(`Erro ao montar a tela: ${e && e.message ? e.message : e}`);
    }
  }
}

function telaEmConstrucao(nome) {
  return async el => {
    el.innerHTML = `
      <div class="crumb">Orbit</div>
      <h1>${esc(TITULOS[nome])}</h1>
      <div class="pagina"><p class="texto-sec">Esta tela ainda está em construção.</p></div>`;
  };
}

/* ---- Primeira execução: boas-vindas ----------------------------------- */

function telaBoasVindas() {
  sairPresenca();
  ativarNavegacao(false);
  marcarNavegacao(null);
  const erro = Orbit.settings && Orbit.settings.erro_base;
  const el = document.getElementById('conteudo');
  el.innerHTML = `
    <div class="boas-vindas"><div class="caixa">
      <div class="simbolo" data-logo-orbit><img src="img/orbit-logo.svg" alt=""></div>
      <h1>Bem-vindo ao Orbit</h1>
      <p>Para começar, escolha a <b>pasta base</b>: a pasta (local ou na rede) onde ficam
         os clientes, os projetos e as máquinas padrão. O Orbit cria nela a pasta
         <b>.orbit</b> com as configurações compartilhadas.</p>
      ${erro ? `<p class="aviso">${esc(erro)}</p>` : ''}
      <button type="button" class="btn solid" id="btn-pasta-base">Escolher pasta base</button>
    </div></div>`;
  embutirLogos(el);
  el.querySelector('#btn-pasta-base').addEventListener('click', escolherPastaBase);
}

/* Pasta base configurada mas inacessível na abertura (rede fora, pendrive removido):
 * só Configurações fica disponível, com indicador vermelho e popup de falha. */
function telaSemBase(autoTeste = false) {
  sairPresenca();
  const nav = document.getElementById('nav');
  ativarNavegacao(true);
  nav.classList.add('sem-base');
  marcarNavegacao('config');
  const s = Orbit.settings;
  const el = document.getElementById('conteudo');
  el.innerHTML = `
    <div class="crumb">Orbit</div>
    <h1>Configurações</h1>
    <div class="pagina">
      <div class="secao-titulo">Pasta base</div>
      <div class="bloco">
        <div class="caminho">${esc(s.pasta_base)}</div>
        <p class="aviso">${esc(s.erro_base || 'A pasta base não está acessível.')}</p>
        <button type="button" class="btn solid" id="sb-tentar">Tentar de novo</button>
        <button type="button" class="btn" id="sb-testar">Testar conexão</button>
        <button type="button" class="btn" id="sb-trocar">Trocar pasta base</button>
      </div>
    </div>`;
  el.querySelector('#sb-tentar').addEventListener('click', async () => {
    const res = await tentarDeNovo();
    if (res !== true) mostrarErro(res.erro || 'Pasta base inacessível.');
  });
  el.querySelector('#sb-testar').addEventListener('click', () => testarConexao({ detalhe: true }));
  el.querySelector('#sb-trocar').addEventListener('click', escolherPastaBase);
  return autoTeste ? testarConexao({ falha: true }) : undefined;
}

async function escolherPastaBase() {
  const settings = await api('escolher_pasta_base');
  if (!settings) return; // cancelado
  await recarregar();
}

/* ---- Inicialização ----------------------------------------------------- */

async function recarregar() {
  Orbit.settings = await api('get_settings');
  aplicarTema(Orbit.settings.tema);
  if (!Orbit.settings.base_ok) {
    Orbit.config = null;
    atualizarLogoEmpresa();
    if (Orbit.settings.pasta_base) { await telaSemBase(true); return; }
    Orbit.conexao = null;
    _pintarIndicador(null, false);
    telaBoasVindas();
    return;
  }
  if (_popupFalhaConexao) _popupFalhaConexao.fechar();
  document.getElementById('nav').classList.remove('sem-base');
  Orbit.config = await api('get_config');
  atualizarLogoEmpresa();
  ativarNavegacao(true);
  if (!location.hash) location.hash = '#/clientes';
  await renderizar();
  testarConexao({ falha: true }); // sem await: não atrasa a primeira tela
}

window.addEventListener('hashchange', renderizar);

let _iniciado = false;
function iniciar() {
  if (_iniciado || !(window.pywebview && window.pywebview.api)) return;
  _iniciado = true;
  carregarLogo();
  recarregar().catch(e => { if (!(e instanceof ErroApi)) console.error(e); });
}

window.addEventListener('pywebviewready', iniciar);
window.addEventListener('DOMContentLoaded', iniciar);
