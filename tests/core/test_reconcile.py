import os

import pytest

from orbit.core.errors import OrbitError
from orbit.core.reconcile import find_untracked, register_untracked
from orbit.core.revisions import RevisionService

TIPO = "diagrama_eletrico"
N = "Diagrama Elétrico - Cliente X - Envasadora - 221026 - Rev{:02d}"


@pytest.fixture
def ctx(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    return repo, p, repo.doc_path(p, TIPO)


def _f(pasta, nome, txt="x"):
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / nome
    f.write_text(txt, encoding="utf-8")
    return f


def _snap(pasta):
    return sorted(str(f.relative_to(pasta)) for f in pasta.rglob("*") if f.is_file())


def test_arquivo_manual_aparece(ctx):
    repo, p, pasta = ctx
    _f(pasta, N.format(0) + ".pdf")
    _f(pasta / "Antigos", N.format(1) + ".dwg")
    itens = find_untracked(repo, p)
    assert {(i.tipo_id, i.numero, i.caminho.name, i.arquivado) for i in itens} == {
        (TIPO, 0, N.format(0) + ".pdf", False),
        (TIPO, 1, N.format(1) + ".dwg", True),
    }


def test_tmp_e_sem_rev_ignorados(ctx):
    repo, p, pasta = ctx
    _f(pasta, "~orbit-abc123 - Rev00.tmp")
    _f(pasta, "~orbit-abc123.tmp")
    _f(pasta, "anotacoes.txt")
    _f(pasta, N.format(2) + ".tmp")  # .tmp com RevNN, mas nao e ~orbit-
    assert [i.caminho.name for i in find_untracked(repo, p)] == [N.format(2) + ".tmp"]


def test_ja_registrado_nao_aparece_case_insensitive(ctx, tmp_path):
    repo, p, pasta = ctx
    o = tmp_path / "o"
    src = _f(o, "A.pdf")
    RevisionService(repo).enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "")
    nome = next(f.name for f in pasta.iterdir() if f.is_file())
    assert find_untracked(repo, repo.load_container(p.id)) == []
    (pasta / nome).rename(pasta / nome.upper().replace(".PDF", ".pdf"))
    assert find_untracked(repo, repo.load_container(p.id)) == []


def test_registrar_cria_revisao_sem_mover(ctx):
    repo, p, pasta = ctx
    pdf = _f(pasta, N.format(0) + ".pdf")
    dwg = _f(pasta, N.format(0) + ".dwg")
    os.utime(pdf, (1_700_000_000, 1_700_000_000))
    antes = _snap(p_dir := repo.container_path(p))
    itens = find_untracked(repo, p)
    register_untracked(repo, p.id, itens, "Em elaboração")
    assert _snap(p_dir) == antes
    c = repo.load_container(p.id)
    r = c.documentos[TIPO].revisoes[0]
    assert r.numero == 0 and r.arquivada is False
    assert r.principal.nome == pdf.name
    assert [(a.nome, a.papel) for a in r.arquivos] == [
        (pdf.name, "principal"), (dwg.name, "editavel")]
    assert r.status == "Em elaboração"
    assert r.motivo == "Registrado a partir de arquivo encontrado na pasta"
    assert (r.usuario, r.computador) == ("thiago", "PC1")
    assert r.data == "2023-11-14"
    assert c.historico[-1].tipo == "arquivo_registrado"
    assert find_untracked(repo, c) == []


def test_principal_sem_pdf_e_primeiro_alfabetico(ctx):
    repo, p, pasta = ctx
    _f(pasta, N.format(0) + ".xlsx")
    _f(pasta, N.format(0) + ".dwg")
    register_untracked(repo, p.id, find_untracked(repo, p), "Em elaboração")
    r = repo.load_container(p.id).documentos[TIPO].revisoes[0]
    assert r.principal.nome.endswith(".dwg")


def test_arquivo_em_revisao_existente_entra_como_editavel(ctx, tmp_path):
    repo, p, pasta = ctx
    src = _f(tmp_path / "o", "A.pdf")
    RevisionService(repo).enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "")
    extra = _f(pasta, N.format(0) + ".dwg")
    register_untracked(repo, p.id, find_untracked(repo, repo.load_container(p.id)), "Aprovado")
    docs = repo.load_container(p.id).documentos[TIPO]
    assert len(docs.revisoes) == 1
    assert docs.revisoes[0].status == "Em elaboração"
    assert docs.revisoes[0].arquivos[-1].nome == extra.name
    assert docs.revisoes[0].arquivos[-1].papel == "editavel"


def test_antigos_vira_arquivada(ctx):
    repo, p, pasta = ctx
    _f(pasta, N.format(2) + ".pdf")
    _f(pasta / "Antigos", N.format(1) + ".pdf")
    register_untracked(repo, p.id, find_untracked(repo, p), "Aprovado")
    d = repo.load_container(p.id).documentos[TIPO]
    por = {r.numero: r.arquivada for r in d.revisoes}
    assert por == {1: True, 2: False}
    assert d.atual.numero == 2


def test_numero_mais_baixo_na_pasta_principal_fica_arquivada_sem_mover(ctx, tmp_path):
    repo, p, pasta = ctx
    src = _f(tmp_path / "o", "A.pdf")
    RevisionService(repo).enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "", numero=5)
    baixo = _f(pasta, N.format(2) + ".pdf")
    antes = _snap(repo.container_path(p))
    register_untracked(repo, p.id, find_untracked(repo, p), "Aprovado")
    assert _snap(repo.container_path(p)) == antes
    assert baixo.exists()
    d = repo.load_container(p.id).documentos[TIPO]
    assert {r.numero: r.arquivada for r in d.revisoes} == {2: True, 5: False}
    assert d.atual.numero == 5


def test_revisao_mais_alta_na_pasta_principal_arquiva_a_anterior_so_no_json(ctx, tmp_path):
    repo, p, pasta = ctx
    src = _f(tmp_path / "o", "A.pdf")
    RevisionService(repo).enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "")
    _f(pasta, N.format(5) + ".pdf")
    antes = _snap(repo.container_path(p))
    register_untracked(repo, p.id, find_untracked(repo, p), "Aprovado")
    assert _snap(repo.container_path(p)) == antes
    d = repo.load_container(p.id).documentos[TIPO]
    por = {r.numero: r.arquivada for r in d.revisoes}
    assert por == {0: True, 5: False}
    assert d.atual.numero == 5


def test_status_invalido_e_rejeitado(ctx):
    repo, p, pasta = ctx
    _f(pasta, N.format(0) + ".pdf")
    with pytest.raises(OrbitError):
        register_untracked(repo, p.id, find_untracked(repo, p), "Inventado")
    assert repo.load_container(p.id).documentos[TIPO].revisoes == []
