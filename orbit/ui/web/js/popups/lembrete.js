/* Lembretes (spec Meu dia §4).
 *
 * popupLembrete(lembrete|null, depois)  criar / editar / excluir
 * window.orbitLembrete(l)               aviso de lembrete vencido (chamado pelo Python)
 * window.orbitLembretesPerdidos(lista)  lembretes que venceram com o Orbit fechado
 */

const _REC = [['nenhuma', 'Não repete'], ['diaria', 'Todo dia'], ['dias_uteis', 'Dias úteis'],
  ['semanal', 'Toda semana'], ['mensal', 'Todo mês']];
const _DIAS_CURTOS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']; // 0 = segunda

function _agoraMaisUmaHora() {
  const t = new Date(Date.now() + 3600000);
  const p = n => String(n).padStart(2, '0');
  return [`${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`, `${p(t.getHours())}:00`];
}

async function popupLembrete(l, depois = () => {}) {
  const projetos = await opcoesProjetos();
  const [dPad, hPad] = _agoraMaisUmaHora();
  const quando = l ? l.quando : `${dPad}T${hPad}`;
  const rec = (l && l.recorrencia) || { tipo: 'nenhuma' };
  const dias = new Set(rec.dias || []);
  const p = abrirPopup({
    titulo: l ? 'Lembrete' : 'Novo lembrete',
    corpoHtml: `
      <div class="field"><label>Texto</label><input type="text" id="lb-texto" maxlength="300" value="${esc(l ? l.texto : '')}"></div>
      <div class="linha-campos">
        <div class="field"><label>Data</label><input type="date" id="lb-data" value="${esc(quando.slice(0, 10))}"></div>
        <div class="field"><label>Hora</label><input type="time" id="lb-hora" value="${esc(quando.slice(11, 16))}"></div>
      </div>
      <div class="field"><label>Repetir</label><select id="lb-rec">${_REC.map(([k, v]) =>
        `<option value="${k}"${k === rec.tipo ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
      <div class="field dias-semana" id="lb-dias"${rec.tipo === 'semanal' ? '' : ' hidden'}>
        ${_DIAS_CURTOS.map((n, i) => `<label><input type="checkbox" value="${i}"${dias.has(i) ? ' checked' : ''}> ${n}</label>`).join('')}</div>
      <div class="field"><label>Projeto (opcional)</label><select id="lb-proj">${_optionsProjetos(projetos, l ? l.container_id : null)}</select></div>
      <p class="texto-sec">O aviso aparece no Windows com o Orbit aberto, mesmo minimizado.</p>`,
    botoes: [
      ...(l ? [{ texto: 'Excluir', acao: async () => {
        if (!(await confirmar('Excluir este lembrete?'))) return false;
        await api('excluir_lembrete', l.id); depois();
      } }] : []),
      { texto: 'Cancelar' },
      { texto: 'Salvar', primario: true, acao: async popup => {
        const q = s => popup.elemento.querySelector(s);
        const tipo = q('#lb-rec').value;
        const recorrencia = { tipo };
        if (tipo === 'semanal') {
          recorrencia.dias = [...popup.elemento.querySelectorAll('#lb-dias input:checked')].map(x => Number(x.value));
        }
        await api('salvar_lembrete', {
          id: l ? l.id : undefined, texto: q('#lb-texto').value,
          quando: `${q('#lb-data').value}T${q('#lb-hora').value}`, recorrencia,
          container_id: q('#lb-proj').value || null,
        });
        depois();
      } },
    ],
  });
  p.elemento.querySelector('#lb-rec').addEventListener('change', e => {
    p.elemento.querySelector('#lb-dias').hidden = e.target.value !== 'semanal';
  });
}

function _depoisDeAcao() {
  if (Orbit.recarregarInicio && lerRota().nome === 'inicio') Orbit.recarregarInicio();
}

window.orbitLembrete = l => {
  abrirPopup({
    titulo: 'Lembrete',
    corpoHtml: `<p class="texto-lembrete">${esc(l.texto)}</p>`,
    botoes: [
      { texto: 'Adiar 10 min', acao: async () => { await api('acao_lembrete', l.id, 'adiar10'); _depoisDeAcao(); } },
      { texto: 'Adiar 1 h', acao: async () => { await api('acao_lembrete', l.id, 'adiar60'); _depoisDeAcao(); } },
      { texto: 'Concluir', primario: true, acao: async () => { await api('acao_lembrete', l.id, 'concluir'); _depoisDeAcao(); } },
    ],
  });
};

window.orbitLembretesPerdidos = lista => {
  const p = abrirPopup({
    titulo: 'Lembretes perdidos',
    subtitulo: 'Venceram enquanto o Orbit estava fechado',
    corpoHtml: lista.map(l => `<div class="lembrete"><span class="hora">${esc(formatarDataHora(l.quando))}</span>
      <span class="txt">${esc(l.texto)}</span></div>`).join(''),
    botoes: [{ texto: 'OK', primario: true, acao: () => { _depoisDeAcao(); } }],
  });
  return p;
};
