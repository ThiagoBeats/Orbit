/* Popups de dados: cliente e projeto, com lista editável de contatos.
 *
 * popupDadosCliente({cliente?})            -> Promise<cliente salvo | null>
 * popupDadosProjeto({projeto?, clienteId?, clientes?})
 *     - sem "projeto": cria (com seletor de cliente se houver "clientes")
 *     - com "projeto" (objeto completo de dados): edita
 * Os campos mudam o JSON, nunca o nome das pastas já criadas.
 */

function _linhaContato(c = {}) {
  return `<div class="contato-linha">
    <input type="text" data-c="nome" placeholder="Nome" value="${esc(c.nome)}">
    <input type="text" data-c="email" placeholder="E-mail" value="${esc(c.email)}">
    <button type="button" class="btn pequeno" data-rem title="Remover contato">✕</button>
  </div>`;
}

function _editorContatos(contatos) {
  return `<div class="field"><label>Contatos</label>
    <div class="contatos-lista">${(contatos || []).map(_linhaContato).join('')}</div>
    <button type="button" class="btn pequeno" data-add>+ Adicionar contato</button></div>`;
}

function _ligarContatos(raiz) {
  const lista = raiz.querySelector('.contatos-lista');
  raiz.querySelector('[data-add]').addEventListener('click', () => {
    lista.insertAdjacentHTML('beforeend', _linhaContato());
    lista.lastElementChild.querySelector('input').focus();
  });
  lista.addEventListener('click', e => {
    const b = e.target.closest('[data-rem]');
    if (b) b.closest('.contato-linha').remove();
  });
}

function _lerContatos(raiz) {
  return [...raiz.querySelectorAll('.contato-linha')].map(l => ({
    nome: l.querySelector('[data-c="nome"]').value.trim(),
    email: l.querySelector('[data-c="email"]').value.trim(),
  })).filter(c => c.nome || c.email);
}

function _campo(rotulo, id, valor = '') {
  return `<div class="field"><label for="${id}">${esc(rotulo)}</label>
    <input type="text" id="${id}" value="${esc(valor)}"></div>`;
}

function popupDadosCliente({ cliente = null } = {}) {
  return new Promise(resolve => {
    let salvo = null;
    const popup = abrirPopup({
      titulo: cliente ? 'Editar cliente' : 'Novo cliente',
      subtitulo: cliente ? 'Alterar o nome não renomeia a pasta já criada.' : '',
      classe: 'largo',
      corpoHtml: _campo('Nome', 'dc-nome', cliente && cliente.nome)
        + _campo('CNPJ', 'dc-cnpj', cliente && cliente.cnpj)
        + _editorContatos(cliente && cliente.contatos),
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Salvar', primario: true, acao: async p => {
          const el = p.elemento;
          const dados = {
            nome: el.querySelector('#dc-nome').value.trim(),
            cnpj: el.querySelector('#dc-cnpj').value.trim(),
            contatos: _lerContatos(el),
          };
          salvo = cliente ? await api('atualizar_cliente', cliente.id, dados)
                          : await api('criar_cliente', dados);
        } },
      ],
    });
    _ligarContatos(popup.elemento);
    popup._aoFechar = () => resolve(salvo);
  });
}

function popupDadosProjeto({ projeto = null, clienteId = null, clientes = null } = {}) {
  return new Promise(resolve => {
    let salvo = null;
    const p0 = projeto || {};
    const seletor = !projeto && clientes ? `<div class="field"><label for="dp-cliente">Cliente</label>
      <select id="dp-cliente">${clientes.map(c =>
        `<option value="${esc(c.id)}"${c.id === clienteId ? ' selected' : ''}>${esc(c.nome)}</option>`).join('')}
      </select></div>` : '';
    const sit = p0.situacao || 'ativo';
    const popup = abrirPopup({
      titulo: projeto ? 'Editar projeto' : 'Novo projeto',
      subtitulo: projeto ? 'Alterar código ou nome não renomeia a pasta já criada.' : '',
      classe: 'largo',
      corpoHtml: seletor + _campo('Código', 'dp-codigo', p0.codigo) + _campo('Nome', 'dp-nome', p0.nome)
        + _campo('Nº do pedido', 'dp-pedido', p0.pedido) + _campo('Responsável', 'dp-resp', p0.responsavel)
        + `<div class="field"><label for="dp-sit">Situação</label><select id="dp-sit">
             <option value="ativo"${sit === 'ativo' ? ' selected' : ''}>Ativo</option>
             <option value="concluido"${sit === 'concluido' ? ' selected' : ''}>Concluído</option>
           </select></div>`
        + _editorContatos(p0.contatos),
      botoes: [
        { texto: 'Cancelar' },
        { texto: 'Salvar', primario: true, acao: async p => {
          const el = p.elemento;
          const dados = {
            codigo: el.querySelector('#dp-codigo').value.trim(),
            nome: el.querySelector('#dp-nome').value.trim(),
            pedido: el.querySelector('#dp-pedido').value.trim(),
            responsavel: el.querySelector('#dp-resp').value.trim(),
            situacao: el.querySelector('#dp-sit').value,
            contatos: _lerContatos(el),
          };
          if (projeto) {
            await api('atualizar_projeto', projeto.id, dados);
            salvo = { id: projeto.id };
          } else {
            const sel = el.querySelector('#dp-cliente');
            const cid = sel ? sel.value : clienteId;
            if (!cid) { mostrarErro('Escolha o cliente do projeto.'); return false; }
            salvo = await api('criar_projeto', cid, dados);
            salvo.cliente_id = cid;
          }
        } },
      ],
    });
    _ligarContatos(popup.elemento);
    popup._aoFechar = () => resolve(salvo);
  });
}
