/* Popups de importação de documentos antigos e de reconciliação (spec §10 e §7).
 *
 * popupImportacao({containerId, caminhos, tipos, tipoPadrao})
 *   -> Promise<bool importou>
 *   - tipos: [{tipo_id, nome}] na ordem do painel; tipoPadrao: tipo pré-selecionado.
 *   - Uma linha por arquivo. Papel padrão: o primeiro arquivo de cada (tipo, revisão)
 *     é o principal e os demais são editáveis; quem mexe no papel de uma linha a
 *     "trava" (as outras se ajustam em volta dela).
 *   - Cada mudança dispara validar_importacao; o botão fica desabilitado com erro.
 *   - Orbit.uploadAberto.adicionar(caminhos) recebe arquivos soltos na janela.
 *
 * popupNaoRegistrados({containerId}) -> Promise<bool registrou>
 */

async function popupImportacao({ containerId, caminhos = [], tipos = [], tipoPadrao = null }) {
  const statusLista = Orbit.config.status || [];
  const linhas = [];
  let importou = false;
  let erros = [];
  let validando = false;

  const paraApi = l => ({
    origem: l.origem, tipo_id: l.tipo_id, numero: l.numero === '' ? null : Number(l.numero),
    status: l.status, papel: l.papel, data: l.data || null,
  });

  const popup = abrirPopup({
    titulo: 'Importar documentos',
    subtitulo: 'Revise o tipo, a revisão e o status de cada arquivo. Os originais são apenas copiados.',
    classe: 'importacao',
    corpoHtml: `
      <div class="tabela-rolagem"><table class="tabela tabela-import">
        <thead><tr><th>Arquivo</th><th>Tipo</th><th>Rev.</th><th>Papel</th><th>Status</th>
          <th>Data</th><th></th></tr></thead>
        <tbody id="im-linhas"></tbody></table></div>
      <div class="acoes-import"><button type="button" class="btn pequeno" id="im-add">+ Adicionar arquivos</button>
        <span class="dica">Você também pode arrastar arquivos para esta janela.</span></div>`,
    botoes: [
      { texto: 'Cancelar' },
      { texto: 'Importar', primario: true, acao: async () => {
        try {
          await api('importar', containerId, linhas.map(paraApi));
          importou = true;
        } catch (e) {
          setTimeout(atualizarBotao, 0);
          throw e;
        }
      } },
    ],
  });
  const el = popup.elemento;
  const botaoImportar = [...el.querySelectorAll('.botoes .btn')].pop();

  function novaLinha(p) {
    return {
      origem: p.origem, nome: p.nome, tipo_id: tipoPadrao || '',
      numero: p.rev_detectada === null || p.rev_detectada === undefined ? '' : String(p.rev_detectada),
      papel: 'principal', papelManual: false, status: statusLista[0] || '',
      data: p.data_mtime || '',
    };
  }

  function recalcularPapeis() {
    const grupos = new Map();
    for (const l of linhas) {
      const k = `${l.tipo_id}|${l.numero}`;
      if (!grupos.has(k)) grupos.set(k, []);
      grupos.get(k).push(l);
    }
    for (const g of grupos.values()) {
      let temPrincipal = g.some(l => l.papelManual && l.papel === 'principal');
      for (const l of g) {
        if (l.papelManual) continue;
        l.papel = temPrincipal ? 'editavel' : 'principal';
        temPrincipal = true;
      }
    }
  }

  function desenhar() {
    el.querySelector('#im-linhas').innerHTML = linhas.map((l, i) => `
      <tr data-i="${esc(i)}">
        <td class="im-nome" title="${esc(l.origem)}">${esc(l.nome)}</td>
        <td><select data-c="tipo_id">
          ${l.tipo_id ? '' : '<option value="">Escolha…</option>'}
          ${tipos.map(t => `<option value="${esc(t.tipo_id)}"${t.tipo_id === l.tipo_id ? ' selected' : ''}>${esc(t.nome)}</option>`).join('')}
        </select></td>
        <td><input type="number" class="im-rev" data-c="numero" min="0" max="99" step="1" value="${esc(l.numero)}"></td>
        <td><select data-c="papel">
          <option value="principal"${l.papel === 'principal' ? ' selected' : ''}>Principal</option>
          <option value="editavel"${l.papel === 'editavel' ? ' selected' : ''}>Editável</option></select></td>
        <td><select data-c="status">${statusLista.map(s =>
          `<option value="${esc(s)}"${s === l.status ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select></td>
        <td><input type="date" data-c="data" value="${esc(l.data)}"></td>
        <td><button type="button" class="btn pequeno" data-rem title="Remover da lista">✕</button></td>
      </tr>
      <tr class="im-msg oculto" data-msg="${esc(i)}"><td colspan="7"></td></tr>`).join('');
    mostrarErros();
    atualizarBotao();
  }

  function mostrarErros() {
    el.querySelectorAll('#im-linhas tr[data-i]').forEach(tr => {
      const i = Number(tr.dataset.i);
      const msg = erros[i];
      const m = el.querySelector(`tr[data-msg="${i}"]`);
      tr.classList.toggle('linha-erro', !!msg);
      m.classList.toggle('linha-erro', !!msg);
      m.classList.toggle('oculto', !msg);
      m.firstElementChild.textContent = msg || '';
    });
  }

  function atualizarBotao() {
    const ok = linhas.length > 0 && !validando && erros.length === linhas.length && erros.every(e => !e);
    botaoImportar.disabled = !ok;
  }

  let seq = 0;
  let timer = null;
  function validar() {
    erros = [];
    validando = true;
    atualizarBotao();
    clearTimeout(timer);
    if (!linhas.length) { validando = false; atualizarBotao(); return; }
    timer = setTimeout(async () => {
      const minha = ++seq;
      const r = await apiSilenciosa('validar_importacao', containerId, linhas.map(paraApi));
      if (minha !== seq) return;
      validando = false;
      erros = r.ok ? r.dados : linhas.map(() => r.erro);
      mostrarErros();
      atualizarBotao();
    }, 150);
  }

  async function adicionar(novos) {
    const jaTem = new Set(linhas.map(l => l.origem));
    const lista = (novos || []).filter(c => !jaTem.has(c));
    if (!lista.length) return;
    const r = await apiSilenciosa('preparar_importacao', lista);
    if (!r.ok) { mostrarErro(r.erro); return; }
    for (const p of r.dados) linhas.push(novaLinha(p));
    recalcularPapeis();
    desenhar();
    validar();
  }

  el.addEventListener('change', e => {
    const campo = e.target.closest('[data-c]');
    if (!campo) return;
    const l = linhas[Number(campo.closest('tr').dataset.i)];
    const c = campo.dataset.c;
    l[c] = campo.value;
    if (c === 'papel') l.papelManual = true;
    if (c === 'tipo_id' || c === 'numero' || c === 'papel') { recalcularPapeis(); desenhar(); }
    validar();
  });
  el.addEventListener('input', e => {
    const campo = e.target.closest('input[data-c="numero"]');
    if (!campo) return;
    linhas[Number(campo.closest('tr').dataset.i)].numero = campo.value;
    validar();
  });
  el.addEventListener('click', e => {
    const rem = e.target.closest('[data-rem]');
    if (!rem) return;
    linhas.splice(Number(rem.closest('tr').dataset.i), 1);
    recalcularPapeis();
    desenhar();
    validar();
  });
  el.querySelector('#im-add').addEventListener('click', async () => {
    const lista = await api('escolher_arquivos', true);
    await adicionar(lista);
  });

  const registro = { adicionar };
  Orbit.uploadAberto = registro;
  const fim = new Promise(resolve => {
    popup._aoFechar = () => {
      clearTimeout(timer);
      if (Orbit.uploadAberto === registro) Orbit.uploadAberto = null;
      resolve(importou);
    };
  });
  desenhar();
  await adicionar(caminhos);
  return fim;
}

async function popupNaoRegistrados({ containerId }) {
  const lista = await api('listar_nao_registrados', containerId);
  if (!lista.length) {
    abrirPopup({
      titulo: 'Arquivos não registrados',
      corpoHtml: '<p class="texto-sec">Nenhum arquivo novo encontrado nas pastas.</p>',
      botoes: [{ texto: 'OK', primario: true }],
    });
    return false;
  }
  const statusLista = Orbit.config.status || [];
  let registrou = false;
  const popup = abrirPopup({
    titulo: 'Arquivos não registrados',
    subtitulo: 'Estes arquivos estão nas pastas, mas não constam no controle de revisões.',
    classe: 'largo',
    corpoHtml: `
      <div class="tabela-rolagem"><table class="tabela">
        <thead><tr><th></th><th>Arquivo</th><th>Tipo</th><th>Rev.</th></tr></thead>
        <tbody>${lista.map((u, i) => `
          <tr><td><input type="checkbox" data-i="${esc(i)}" checked></td>
            <td title="${esc(u.nome)}">${esc(u.nome)}${u.arquivado ? ' <span class="chip">Antigos</span>' : ''}</td>
            <td>${esc(u.tipo_nome)}</td><td class="nowrap">${esc(formatarRev(u.numero))}</td></tr>`).join('')}
        </tbody></table></div>
      <div class="field"><label for="nr-st">Status das revisões registradas</label>
        <select id="nr-st">${statusLista.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('')}</select></div>`,
    botoes: [
      { texto: 'Cancelar' },
      { texto: 'Registrar', primario: true, acao: async () => {
        const itens = [...popup.elemento.querySelectorAll('input[data-i]:checked')]
          .map(cb => ({ tipo_id: lista[Number(cb.dataset.i)].tipo_id, nome: lista[Number(cb.dataset.i)].nome }));
        if (!itens.length) { mostrarErro('Marque ao menos um arquivo.'); return false; }
        await api('registrar', containerId, itens, popup.elemento.querySelector('#nr-st').value);
        registrou = true;
      } },
    ],
  });
  return new Promise(resolve => { popup._aoFechar = () => resolve(registrou); });
}
