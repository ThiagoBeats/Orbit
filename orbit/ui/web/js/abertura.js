/* Abertura animada do Orbit (spec de backup §10, opção A).
 *
 * A camada #abertura já está no index.html, então aparece no primeiro quadro.
 * Sequência (≈2,5 s, só CSS): a folha entra girando, a órbita se desenha e
 * passa a rodar, o satélite aparece; aqui o JS digita "ORBIT" a partir de
 * 1,5 s, a 90 ms por letra.
 *
 * Abertura.concluir(): chamado pelo app.js depois da primeira carga; espera a
 * sequência terminar (se a carga demorar mais, a órbita continua rodando) e
 * some em 300 ms. Clique ou qualquer tecla pulam a animação.
 * Com "reduzir movimento" do Windows: logo parada e texto completo por 0,5 s.
 */
const Abertura = (() => {
  const camada = document.getElementById('abertura');
  const reduzir = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DURACAO_MS = reduzir ? 500 : 2500;
  const INICIO_TEXTO_MS = 1500;
  const POR_LETRA_MS = 90;
  const PALAVRA = 'ORBIT';
  const inicio = performance.now();
  let removida = !camada;
  const timers = [];

  if (camada) {
    const letras = camada.querySelector('#ab-letras');
    if (reduzir) {
      letras.textContent = PALAVRA;
    } else {
      [...PALAVRA].forEach((c, i) => timers.push(setTimeout(() => {
        letras.textContent += c;
      }, INICIO_TEXTO_MS + i * POR_LETRA_MS)));
    }
    camada.addEventListener('click', () => sumir());
    window.addEventListener('keydown', () => sumir(), { once: true });
  }

  function sumir() {
    if (removida) return;
    removida = true;
    timers.forEach(clearTimeout);
    camada.classList.add('saindo');
    setTimeout(() => camada.remove(), 300);
  }

  async function concluir() {
    if (removida) return;
    const falta = DURACAO_MS - (performance.now() - inicio);
    if (falta > 0) await new Promise(r => setTimeout(r, falta));
    sumir();
  }

  return { concluir, sumir };
})();
