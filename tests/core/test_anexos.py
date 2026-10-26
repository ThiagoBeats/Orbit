import pytest

from orbit.core.anexos import PASTA_ANEXOS, adicionar_anexos, caminho_anexo, listar_anexos
from orbit.core.errors import OrbitError


@pytest.fixture
def proj(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    origem = tmp_path / "origem"
    origem.mkdir()
    return repo, p, origem


def _arq(pasta, nome, conteudo=b"x"):
    f = pasta / nome
    f.write_bytes(conteudo)
    return f


def test_adiciona_copiando_com_o_mesmo_nome(proj):
    repo, p, origem = proj
    nf = _arq(origem, "NF 1234.pdf", b"nota")
    nomes = adicionar_anexos(repo, p.id, [nf])
    assert nomes == ["NF 1234.pdf"]
    destino = repo.container_path(repo.load_container(p.id)) / PASTA_ANEXOS / "NF 1234.pdf"
    assert destino.read_bytes() == b"nota" and nf.exists()  # original continua
    lista = listar_anexos(repo, p.id)
    assert [(a["nome"], a["tamanho"]) for a in lista] == [("NF 1234.pdf", 4)]


def test_nome_repetido_nao_substitui(proj):
    repo, p, origem = proj
    a = _arq(origem, "manual.pdf", b"v1")
    adicionar_anexos(repo, p.id, [a])
    outra = origem / "sub"
    outra.mkdir()
    b = _arq(outra, "manual.pdf", b"v2")
    c = _arq(origem, "manual (2).pdf", b"v3")
    assert adicionar_anexos(repo, p.id, [b, c]) == ["manual (2).pdf", "manual (2) (2).pdf"]
    pasta = repo.container_path(repo.load_container(p.id)) / PASTA_ANEXOS
    assert (pasta / "manual.pdf").read_bytes() == b"v1"
    assert (pasta / "manual (2).pdf").read_bytes() == b"v2"
    assert (pasta / "manual (2) (2).pdf").read_bytes() == b"v3"


def test_maquina_padrao_tambem_tem_anexos(repo, tmp_path):
    m = repo.create_maquina("EC", "Esteira")
    f = _arq(tmp_path, "informativo.docx")
    assert adicionar_anexos(repo, m.id, [f]) == ["informativo.docx"]
    assert [a["nome"] for a in listar_anexos(repo, m.id)] == ["informativo.docx"]


def test_validacoes(proj, tmp_path):
    repo, p, origem = proj
    with pytest.raises(OrbitError):
        adicionar_anexos(repo, p.id, [origem / "nao_existe.pdf"])
    with pytest.raises(OrbitError):
        adicionar_anexos(repo, p.id, [origem])  # pasta não
    with pytest.raises(OrbitError):
        adicionar_anexos(repo, p.id, [])
    assert listar_anexos(repo, p.id) == []  # sem pasta ainda: lista vazia


def test_caminho_anexo_so_aceita_nome_da_lista(proj):
    repo, p, origem = proj
    adicionar_anexos(repo, p.id, [_arq(origem, "a.pdf")])
    assert caminho_anexo(repo, p.id, "a.pdf").name == "a.pdf"
    for ruim in ("../projeto.json", "b.pdf", "", "..\\x"):
        with pytest.raises(OrbitError):
            caminho_anexo(repo, p.id, ruim)
