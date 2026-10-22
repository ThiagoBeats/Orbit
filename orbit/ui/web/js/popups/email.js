/* Popup de e-mail (spec §11).
 *
 * popupEmail({containerId, selecoes:[{tipo_id, numero}], nomesTipos}) -> Promise<bool>
 *   true = o rascunho foi aberto no Outlook.
 * O popup pede à Api todos os arquivos (editáveis incluídos) e deixa o usuário
 * marcar o que vai. Documento desmarcado sai do envio; os editáveis começam
 * desmarcados. Os anexos são refeitos no Python a partir das seleções.
 */

const LIMITE_ANEXOS = 20 * 1024 * 1024;

async function popupEmail({ containerId, selecoes, nomesTipos = {} }) {
  let m;
  try {
    m = await api('montar_email', containerId,
      selecoes.map(s => ({ tipo_id: s.tipo_id, numero: s.numero, incluir_editaveis: true })));
  } catch (e) { return false; }

  return new Promise(resolve => {
    let aberto = false;
    const grupos = selecoes.map(s => {
      const arqs = m.anexos.filter(a => a.tipo_id === s.tipo_id && a.numero === s.numero);
      return { ...s, principais: arqs.filter(a => a.papel === 'principal'),
               editaveis: arqs.filter(a => a.papel === 'editavel') };
    });
    const tam = a => `<span class="texto-sec">${esc(_formatarTamanho(a.tamanho))}</span>`;
    const linhasGrupo = (g, i) => `
      <div class="anexo-grupo" data-g="${i}">
        <label class="anexo-linha"><input type="checkbox" data-doc checked>
          <b>${esc(nomesTipos[g.tipo_id] || g.tipo_id)} ${formatarRev(g.numero)}</b></label>
        ${g.principais.map(a => `<div class="anexo-arq">${esc(a.nome)} ${tam(a)}</div>`).join('')}
        ${g.editaveis.length ? `<label class="anexo-linha ed"><input type="checkbox" data-ed>
          Incluir editáveis</label>${g.editaveis.map(a =>
          `<div class="anexo-arq ed">${esc(a.nome)} ${tam(a)}</div>`).join('')}` : ''}
      </div>`;

    const popup = abrirPopup({
      titulo: 'Enviar por e-mail',
      subtitulo: 'O Outlook abre com o rascunho pronto; você revisa e envia por lá.',
      classe: 'largo',
      corpoHtml: `
        <div class="field"><label for="em-para">Para (separe por ;)</label>
          <input type="text" id="em-para" value="${esc(m.destinatarios.join('; '))}"></div>
        <div class="field"><label for="em-assunto">Assunto</label>
          <input type="text" id="em-assunto" value="${esc(m.assunto)}"></div>
        <div class="field"><label>Anexos</label>
          <div class="anexos-lista">${grupos.map(linhasGrupo).join('')}</div>
          <div class="dica" id="em-total"></div></div>
        <div class="field"><label for="em-corpo">Mensagem</label>
          <textarea id="em-corpo" rows="6">${esc(m.corpo)}</textarea></div>
        <div class="erro-email oculto" id="em-erro"></div>`,
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Abrir no Outlook', primario: true, acao: async p => {
          const sels = selecaoAtual();
          if (!sels.length) { mostrarErro('Marque ao menos um documento.'); return false; }
          const r = await apiSilenciosa('preparar_email', containerId, {
            destinatarios: [el.querySelector('#em-para').value],
            assunto: el.querySelector('#em-assunto').value,
            corpo: el.querySelector('#em-corpo').value,
          }, sels);
          if (!r.ok) { mostrarFalha(r.erro); return false; }
          aberto = true;
        } },
      ],
    });
    const el = popup.elemento;

    function selecaoAtual() {
      const out = [];
      grupos.forEach((g, i) => {
        const bloco = el.querySelector(`[data-g="${i}"]`);
        if (!bloco.querySelector('[data-doc]').checked) return;
        const ed = bloco.querySelector('[data-ed]');
        out.push({ tipo_id: g.tipo_id, numero: g.numero, incluir_editaveis: !!(ed && ed.checked) });
      });
      return out;
    }

    function atualizarTotal() {
      let total = 0;
      grupos.forEach((g, i) => {
        const bloco = el.querySelector(`[data-g="${i}"]`);
        const docOk = bloco.querySelector('[data-doc]').checked;
        const edBox = bloco.querySelector('[data-ed]');
        bloco.classList.toggle('desmarcado', !docOk);
        if (edBox) edBox.disabled = !docOk;
        if (docOk) total += g.principais.reduce((s, a) => s + a.tamanho, 0);
        if (docOk && edBox && edBox.checked) total += g.editaveis.reduce((s, a) => s + a.tamanho, 0);
      });
      const alvo = el.querySelector('#em-total');
      const grande = total > LIMITE_ANEXOS;
      alvo.classList.toggle('aviso-ambar', grande);
      alvo.textContent = `Tamanho total: ${_formatarTamanho(total)}`
        + (grande ? ' · acima de 20 MB, o servidor de e-mail pode recusar.' : '');
    }

    function mostrarFalha(msg) {
      const caixa = el.querySelector('#em-erro');
      caixa.classList.remove('oculto');
      caixa.innerHTML = `<div>${esc(msg)}</div>
        <button type="button" class="btn pequeno" id="em-pasta">Abrir pasta</button>`;
      caixa.querySelector('#em-pasta').addEventListener('click', () => {
        const alvo = (selecaoAtual()[0] || selecoes[0]).tipo_id;
        api('abrir_pasta', containerId, alvo).catch(() => {});
      });
    }

    el.querySelector('.anexos-lista').addEventListener('change', atualizarTotal);
    atualizarTotal();
    popup._aoFechar = () => resolve(aberto);
  });
}
