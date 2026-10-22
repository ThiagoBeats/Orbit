/* Popups do Orbit.
 *
 * abrirPopup({titulo, subtitulo, corpoHtml, botoes:[{texto, primario, acao}], classe})
 *   -> {fechar(), elemento}
 *   - "acao(popup)" pode ser assíncrona. O popup fecha depois dela, a menos que
 *     ela devolva false ou lance um erro (útil para validar formulários).
 *   - Botão sem "acao" apenas fecha.
 *   - Esc fecha o popup do topo.
 * confirmar(texto) -> Promise<bool>
 * mostrarErro(mensagem)
 * esc(texto) -> texto seguro para colocar em HTML
 */

function esc(texto) {
  return String(texto ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const _popupsAbertos = [];

function abrirPopup({ titulo = '', subtitulo = '', corpoHtml = '', botoes = [], classe = '' } = {}) {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.innerHTML = `
    <div class="modal ${esc(classe)}" role="dialog" aria-modal="true">
      <button type="button" class="close" data-fechar>FECHAR ✕</button>
      <h2>${esc(titulo)}</h2>
      ${subtitulo ? `<div class="sub">${esc(subtitulo)}</div>` : ''}
      <div class="corpo">${corpoHtml}</div>
      <div class="botoes"></div>
    </div>`;

  let fechado = false;
  const popup = {
    elemento: overlay.querySelector('.modal'),
    fechar() {
      if (fechado) return;
      fechado = true;
      overlay.remove();
      const i = _popupsAbertos.indexOf(popup);
      if (i >= 0) _popupsAbertos.splice(i, 1);
      if (popup._aoFechar) popup._aoFechar();
    },
  };

  const areaBotoes = overlay.querySelector('.botoes');
  for (const b of botoes) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'btn' + (b.primario ? ' solid' : '');
    el.textContent = b.texto;
    el.addEventListener('click', async () => {
      if (!b.acao) { popup.fechar(); return; }
      el.disabled = true;
      try {
        const r = await b.acao(popup);
        if (r !== false) popup.fechar();
      } catch (e) {
        // erro da Api já foi mostrado; o popup continua aberto
        if (!(e instanceof ErroApi)) console.error(e);
      } finally {
        el.disabled = false;
      }
    });
    areaBotoes.appendChild(el);
  }

  overlay.querySelector('[data-fechar]').addEventListener('click', () => popup.fechar());
  document.body.appendChild(overlay);
  _popupsAbertos.push(popup);
  const foco = overlay.querySelector('input, select, textarea') || areaBotoes.querySelector('.btn.solid');
  if (foco) foco.focus();
  return popup;
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && _popupsAbertos.length) {
    _popupsAbertos[_popupsAbertos.length - 1].fechar();
  }
});

function confirmar(texto) {
  return new Promise(resolve => {
    let resposta = false;
    const popup = abrirPopup({
      titulo: 'Confirmar',
      corpoHtml: `<p>${esc(texto)}</p>`,
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Confirmar', primario: true, acao: () => { resposta = true; } },
      ],
    });
    popup._aoFechar = () => resolve(resposta);
  });
}

function mostrarErro(mensagem) {
  return abrirPopup({
    titulo: 'Não foi possível concluir',
    corpoHtml: `<p>${esc(mensagem)}</p>`,
    botoes: [{ texto: 'OK', primario: true }],
    classe: 'erro',
  });
}

/* Erro devolvido pela Api ({ok:false}); o popup já foi mostrado por api(). */
class ErroApi extends Error {}
