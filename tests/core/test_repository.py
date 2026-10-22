import pytest

from orbit.core.config import add_tipo
from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.models import Arquivo, Contato, Revisao


def test_criar_projeto_cria_pastas(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora Linha 2")
    raiz = tmp_path / "Clientes" / "Cliente X" / "001 - Envasadora Linha 2"
    assert (raiz / "projeto.json").exists()
    assert (raiz / "Lista de Tags" / "Antigos").is_dir()
    assert len(p.documentos) == 9
    assert repo.container_path(p) == raiz
    assert repo.doc_path(p, "lista_tags") == raiz / "Lista de Tags"


def test_mesmo_cliente_dois_projetos_independentes(repo):
    cli = repo.create_cliente("C")
    a = repo.create_projeto(cli.id, "1", "A")
    b = repo.create_projeto(cli.id, "2", "B")
    a.documentos["lista_tags"].revisoes.append(
        Revisao(0, "2026-10-22", "Em elaboração", "", "thiago", "PC1", [Arquivo("x.pdf", "principal")]))
    repo.save_container(a)
    assert repo.load_container(a.id).documentos["lista_tags"].atual is not None
    assert repo.load_container(b.id).documentos["lista_tags"].atual is None
    assert a.id != b.id


def test_nomes_que_colidem_dao_erro(repo):
    repo.create_cliente("A/B")
    with pytest.raises(OrbitError):
        repo.create_cliente("A:B")


def test_nome_com_barra_e_acento(repo, tmp_path):
    repo.create_cliente("A/B Automação Ltda")
    assert (tmp_path / "Clientes" / "A-B Automação Ltda").is_dir()


def test_maquina_padrao(repo, tmp_path):
    m = repo.create_maquina("EC-200", "Esteira Compacta EC-200")
    assert (tmp_path / "Máquinas Padrão" / "Esteira Compacta EC-200" / "maquina.json").exists()
    assert repo.name_parts(m) == ["Esteira Compacta EC-200"]
    assert [r.nome for r in repo.list_maquinas()] == ["Esteira Compacta EC-200"]
    assert repo.load_container(m.id).codigo == "EC-200"


def test_projetos_colidindo_dao_erro(repo):
    cli = repo.create_cliente("C")
    repo.create_projeto(cli.id, "1", "A/B")
    with pytest.raises(OrbitError):
        repo.create_projeto(cli.id, "1", "A:B")


def test_renomear_cliente_nao_move_pasta_e_muda_name_parts(repo, tmp_path):
    cli = repo.create_cliente("Antigo")
    p = repo.create_projeto(cli.id, "1", "Proj")
    assert repo.name_parts(p) == ["Antigo", "Proj"]
    cli.nome = "Novo"
    repo.update_cliente(cli)
    assert (tmp_path / "Clientes" / "Antigo" / "cliente.json").exists()
    assert not (tmp_path / "Clientes" / "Novo").exists()
    p2 = repo.load_container(p.id)
    assert repo.name_parts(p2) == ["Novo", "Proj"]
    assert repo.container_path(p2) == tmp_path / "Clientes" / "Antigo" / "1 - Proj"
    assert repo.get_cliente(cli.id).nome == "Novo"
    assert repo.cliente_de(p2).nome == "Novo"
    assert repo.cliente_de(repo.create_maquina("M", "Maq")) is None


def test_listar_clientes_ordenado(repo):
    repo.create_cliente("Zeta")
    repo.create_cliente("Alfa")
    assert [c.nome for c in repo.list_clientes()] == ["Alfa", "Zeta"]


def test_json_corrompido_nao_derruba_lista(repo, tmp_path):
    cli = repo.create_cliente("C"); a = repo.create_projeto(cli.id, "1", "A"); repo.create_projeto(cli.id, "2", "B")
    (repo.container_path(a) / "projeto.json").write_text("{quebrado", encoding="utf-8")
    resumos = repo.list_projetos(cli.id)
    assert len(resumos) == 2 and sum(1 for r in resumos if r.erro) == 1


def test_json_parcial_vira_orbitdataerror(repo):
    cli = repo.create_cliente("C"); a = repo.create_projeto(cli.id, "1", "A")
    (repo.container_path(a) / "projeto.json").write_text('{"id": "%s"}' % a.id, encoding="utf-8")
    with pytest.raises(OrbitDataError):
        repo.load_container(a.id)
    assert [r.erro is not None for r in repo.list_projetos(cli.id)] == [True]


def test_json_ausente_nao_derruba_lista(repo):
    cli = repo.create_cliente("C"); a = repo.create_projeto(cli.id, "1", "A"); repo.create_projeto(cli.id, "2", "B")
    (repo.container_path(a) / "projeto.json").unlink()
    resumos = repo.list_projetos(cli.id)
    assert len(resumos) == 2 and sum(1 for r in resumos if r.erro) == 1


def test_tipo_novo_aparece_em_projeto_existente(repo):
    cli = repo.create_cliente("C"); p = repo.create_projeto(cli.id, "1", "A")
    tipo = add_tipo(repo.config, "Certificados")
    c = repo.load_container(p.id)
    assert len(c.documentos) == 10
    assert c.documentos[tipo.id].pasta == "Certificados"
    assert repo.doc_path(c, tipo.id) == repo.container_path(c) / "Certificados"


def test_doc_path_usa_pasta_gravada(repo):
    cli = repo.create_cliente("C"); p = repo.create_projeto(cli.id, "1", "A")
    repo.config.tipo("lista_tags").nome = "Outro Nome"
    repo.config.tipo("lista_tags").pasta = "Outra Pasta"
    assert repo.doc_path(p, "lista_tags").name == "Lista de Tags"


def test_resumo(repo):
    cli = repo.create_cliente("C"); p = repo.create_projeto(cli.id, "1", "A")
    p.documentos["lista_tags"].nao_se_aplica = True
    p.documentos["diagrama_eletrico"].revisoes.append(
        Revisao(0, "2026-10-20", "Aprovado", "", "t", "PC", [Arquivo("x.pdf", "principal")]))
    p.documentos["memorial_descritivo"].revisoes.append(
        Revisao(1, "2026-10-21", "Aprovado", "", "t", "PC", [Arquivo("y.pdf", "principal")]))
    repo.save_container(p)
    (r,) = repo.list_projetos(cli.id)
    assert (r.id, r.nome, r.codigo, r.situacao) == (p.id, "A", "1", "ativo")
    assert (r.emitidos, r.aplicaveis, r.ultima_emissao, r.erro) == (2, 8, "2026-10-21", None)


def test_update_dados_registra_evento_sem_renomear(repo, tmp_path):
    cli = repo.create_cliente("C"); p = repo.create_projeto(cli.id, "1", "A")
    c = repo.update_dados(p.id, nome="Novo Nome", pedido="PO-9")
    assert c.nome == "Novo Nome" and c.pedido == "PO-9"
    assert (tmp_path / "Clientes" / "C" / "1 - A" / "projeto.json").exists()
    ev = repo.load_container(p.id).historico[-1]
    assert (ev.tipo, ev.usuario, ev.computador, ev.data_hora) == (
        "dados_alterados", "thiago", "PC1", "2026-10-22T14:32:00")
    assert ev.dados["alterados"]["nome"] == ["A", "Novo Nome"]
    with pytest.raises(OrbitError):
        repo.update_dados(p.id, id="x")


def test_id_encontrado_apos_reconstruir_indice(repo, tmp_path):
    from orbit.core.identity import Identity
    from orbit.core.repository import Repository
    cli = repo.create_cliente("C"); p = repo.create_projeto(cli.id, "1", "A")
    outro = Repository(tmp_path, Identity("u", "PC2"), repo.config)
    assert outro.load_container(p.id).id == p.id
    assert outro.get_cliente(cli.id).nome == "C"
    with pytest.raises(OrbitError):
        outro.load_container("inexistente")


def test_contatos_e_cnpj(repo):
    cli = repo.create_cliente("C", "12.345", [Contato("Ana", "a@x.com")])
    got = repo.get_cliente(cli.id)
    assert got.cnpj == "12.345" and got.contatos[0].email == "a@x.com"
