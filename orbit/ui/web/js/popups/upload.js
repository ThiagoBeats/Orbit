/* Popup "Nova revisão".
 *
 * popupNovaRevisao({containerId, doc, subtitulo, arquivos})
 *   -> Promise<revisão enviada | null>
 *   - arquivos: caminhos já escolhidos (arrastar e soltar). O primeiro vira o
 *     principal e os outros, editáveis.
 *   - "Será salvo como" é atualizado a cada mudança via preview_upload.
 *   - Enquanto aberto, Orbit.uploadAberto.adicionar(caminhos) recebe arquivos
 *     soltos na janela (ver orbitDrop em painel.js).
 */

function _nomeArquivo(caminho) {
  return String(caminho || '').split(/[\\/]/).pop();
}

/* Chamada à Api sem popup de erro (para validações enquanto o usuário digita). */
async function apiSilenciosa(nome, ...args) {
  try {
    return await window.pywebview.api[nome](...args);
  } catch (e) {
    return { ok: false, erro: String(e && e.message ? e.message : e) };
  }
}

function popupNovaRevisao({ containerId, doc, subtitulo = '', arquivos = [] }) {
  return new Promise(resolve => {
    let enviada = null;
    let principal = arquivos[0] || null;
    let editaveis = arquivos.slice(1);
    const atual = doc.atual;
    const sugerido = atual ? atual.numero + 1 : 0;
    const status = (Orbit.config.status || []);
    const statusPadrao = atual && status.includes(atual.status) ? atual.status : status[0];

    const popup = abrirPopup({
      titulo: 'Nova revisão',
      subtitulo: subtitulo || doc.nome,
      classe: 'largo',
      corpoHtml: `
        <div class="field"><label>Arquivo principal</label>
          <div class="linha-arquivo"><div class="in" id="nr-principal"></div>
          <button type="button" class="btn pequeno" id="nr-escolher">Escolher…</button></div></div>
        <div class="field"><label>Editáveis (opcional)</label>
          <div id="nr-editaveis"></div>
          <button type="button" class="btn pequeno" id="nr-add-ed">+ Adicionar editável</button></div>
        <div class="field"><label for="nr-numero">Número da revisão</label>
          <input type="number" id="nr-numero" min="${sugerido}" max="99" step="1" value="${sugerido}">
          <div class="dica">${atual
            ? `Atual: ${formatarRev(atual.numero)}. Só números maiores que a atual.`
            : 'Primeira revisão deste documento.'}</div></div>
        <div class="field"><label>Será salvo como</label><div class="in preview" id="nr-preview"></div></div>
        <div class="field"><label for="nr-status">Status</label>
          <select id="nr-status">${status.map(s =>
            `<option value="${esc(s)}"${s === statusPadrao ? ' selected' : ''}>${esc(s)}</option>`).join('')}
          </select></div>
        <div class="field"><label for="nr-motivo">Motivo da revisão</label>
          <input type="text" id="nr-motivo" placeholder="${atual ? 'Ex.: comentários do cliente' : 'Emissão inicial'}"></div>
        <div class="dica" style="margin-top:12px">Você também pode arrastar arquivos para esta janela.</div>`,
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Salvar', primario: true, acao: async () => {
          if (!principal) { mostrarErro('Escolha o arquivo principal.'); return false; }
          enviada = await api('enviar_revisao', containerId, doc.tipo_id, principal, editaveis,
            el.querySelector('#nr-status').value, el.querySelector('#nr-motivo').value,
            el.querySelector('#nr-numero').value);
        } },
      ],
    });
    const el = popup.elemento;

    function desenhar() {
      const p = el.querySelector('#nr-principal');
      p.textContent = principal ? _nomeArquivo(principal) : 'Nenhum arquivo escolhido';
      p.title = principal || '';
      p.classList.toggle('vazio', !principal);
      el.querySelector('#nr-editaveis').innerHTML = editaveis.map((c, i) => `
        <div class="linha-arquivo"><div class="in" title="${esc(c)}">${esc(_nomeArquivo(c))}</div>
        <button type="button" class="btn pequeno" data-rem="${i}" title="Remover">✕</button></div>`).join('');
      atualizarPreview();
    }

    let seq = 0;
    async function atualizarPreview() {
      const alvo = el.querySelector('#nr-preview');
      if (!principal) { alvo.textContent = '—'; alvo.classList.remove('erro'); return; }
      const minha = ++seq;
      const r = await apiSilenciosa('preview_upload', containerId, doc.tipo_id, principal,
        editaveis, el.querySelector('#nr-numero').value);
      if (minha !== seq) return;
      alvo.classList.toggle('erro', !r.ok);
      alvo.innerHTML = r.ok
        ? [r.dados.nome_principal, ...r.dados.nomes_editaveis].map(n => `<div>${esc(n)}</div>`).join('')
        : esc(r.erro);
    }

    function adicionar(caminhos) {
      for (const c of caminhos || []) {
        if (c === principal || editaveis.includes(c)) continue;
        if (!principal) principal = c; else editaveis.push(c);
      }
      desenhar();
    }

    el.querySelector('#nr-escolher').addEventListener('click', async () => {
      const [c] = await api('escolher_arquivos', false);
      if (!c) return;
      editaveis = editaveis.filter(x => x !== c);
      principal = c;
      desenhar();
    });
    el.querySelector('#nr-add-ed').addEventListener('click', async () => {
      const lista = await api('escolher_arquivos', true);
      editaveis.push(...lista.filter(c => c !== principal && !editaveis.includes(c)));
      desenhar();
    });
    el.querySelector('#nr-editaveis').addEventListener('click', e => {
      const b = e.target.closest('[data-rem]');
      if (!b) return;
      editaveis.splice(Number(b.dataset.rem), 1);
      desenhar();
    });
    el.querySelector('#nr-numero').addEventListener('input', atualizarPreview);

    const registro = { adicionar };
    Orbit.uploadAberto = registro;
    popup._aoFechar = () => {
      if (Orbit.uploadAberto === registro) Orbit.uploadAberto = null;
      resolve(enviada);
    };
    desenhar();
  });
}
