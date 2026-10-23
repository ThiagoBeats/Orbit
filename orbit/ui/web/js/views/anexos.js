/* Seção "Anexos" do painel do projeto / máquina: arquivos guardados como estão
 * (manuais, NFs, informativos), sem revisão nem renomeação.
 * Arrastar arquivos sobre a seção (#pn-anexos) também adiciona (ver painel.js). */

async function montarAnexos(caixa, containerId) {
  const desenhar = async () => {
    const lista = await api('listar_anexos', containerId).catch(() => null);
    if (lista === null) return;
    caixa.innerHTML = `
      <div class="secao-titulo">Anexos</div>
      <div class="bloco" id="pn-anexos">
        <div class="texto-sec">Manuais, notas fiscais, informativos… Ficam guardados com o nome original,
          sem revisão. Arraste os arquivos para cá ou use o botão.</div>
        <div class="linha-cfg">
          <button type="button" class="btn" id="ax-adicionar">Adicionar anexos</button>
          <button type="button" class="btn" id="ax-pasta">Abrir pasta</button>
        </div>
        ${lista.length ? `<table class="tabela">
          <tr><th>Arquivo</th><th>Tamanho</th><th>Data</th><th></th></tr>
          ${lista.map(a => `<tr><td>${esc(a.nome)}</td><td>${esc(_formatarTamanho(a.tamanho))}</td>
            <td>${esc(formatarDataHora(a.modificado))}</td>
            <td><button type="button" class="btn pequeno" data-abrir-anexo="${esc(a.nome)}">Abrir</button></td></tr>`).join('')}
        </table>` : '<p class="texto-sec">Nenhum anexo ainda.</p>'}
      </div>`;
    caixa.querySelector('#ax-adicionar').addEventListener('click', async () => {
      const nomes = await api('adicionar_anexos', containerId).catch(() => null);
      if (nomes && nomes.length) desenhar();
    });
    caixa.querySelector('#ax-pasta').addEventListener('click', () =>
      api('abrir_pasta_anexos', containerId).catch(() => {}));
    caixa.querySelectorAll('[data-abrir-anexo]').forEach(b => b.addEventListener('click', () =>
      api('abrir_anexo', containerId, b.dataset.abrirAnexo).catch(() => {})));
  };
  Orbit.recarregarAnexos = desenhar;
  await desenhar();
}
