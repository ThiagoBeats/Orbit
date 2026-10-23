import os
from datetime import date, datetime
from pathlib import Path

import pytest

from orbit.core.errors import ArquivoEmUso, OrbitError
from orbit.core.importer import ImportService, ItemImportacao
from orbit.core.revisions import RevisionService

TIPO = "diagrama_eletrico"
PREFIXO = "Diagrama Elétrico - Cliente X - Envasadora Linha 2"
D = date(2026, 3, 10)


def _nome(n: int, ddmmaa: str = "100326", ext: str = ".pdf") -> str:
    return f"{PREFIXO} - {ddmmaa} - Rev{n:02d}{ext}"


@pytest.fixture
def ctx(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora Linha 2")
    origem = tmp_path / "origem"
    origem.mkdir()
    return ImportService(repo), p, origem


def _arq(pasta: Path, nome: str, conteudo: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / nome
    f.write_text(conteudo, encoding="utf-8")
    return f


def _snapshot(pasta: Path) -> dict[str, str]:
    return {str(f.relative_to(pasta)): f.read_text(encoding="utf-8")
            for f in sorted(pasta.rglob("*")) if f.is_file()}


def _item(origem: Path, n: int, **kw) -> ItemImportacao:
    kw.setdefault("data", D)
    return ItemImportacao(origem, kw.pop("tipo_id", TIPO), n, kw.pop("status", "Aprovado"), **kw)


def test_importa_tres_revisoes_mais_alta_fica_atual(ctx, repo):
    svc, p, origem = ctx
    itens = [_item(_arq(origem, f"r{n}.pdf", f"pdf{n}"), n, motivo=f"m{n}") for n in (0, 1, 2)]
    itens.append(_item(_arq(origem, "r2.dwg", "dwg2"), 2, papel="editavel"))
    assert svc.validar(p.id, itens) == [None] * 4
    svc.importar(p.id, itens)
    pasta = repo.doc_path(p, TIPO)
    assert _snapshot(pasta) == {
        _nome(2): "pdf2",
        _nome(2, ext=".dwg"): "dwg2",
        str(Path("Antigos") / _nome(0)): "pdf0",
        str(Path("Antigos") / _nome(1)): "pdf1",
    }
    c = repo.load_container(p.id)
    doc = c.documentos[TIPO]
    assert [(r.numero, r.arquivada) for r in doc.revisoes] == [(0, True), (1, True), (2, False)]
    atual = doc.atual
    assert atual.numero == 2
    assert (atual.status, atual.motivo, atual.data) == ("Aprovado", "m2", "2026-03-10")
    assert (atual.usuario, atual.computador) == ("thiago", "PC1")
    assert [(a.nome, a.papel) for a in atual.arquivos] == [
        (_nome(2), "principal"), (_nome(2, ext=".dwg"), "editavel")]
    ev = c.historico[-1]
    assert ev.tipo == "importacao"
    assert ev.dados == {"revisoes": [{"tipo_id": TIPO, "numero": n} for n in (0, 1, 2)]}
    assert (ev.usuario, ev.computador) == ("thiago", "PC1")
    assert not list(pasta.rglob("~orbit-*"))


def test_data_padrao_vem_do_mtime(ctx, repo):
    svc, p, origem = ctx
    src = _arq(origem, "antigo.pdf", "x")
    ts = datetime(2026, 9, 14, 10, 0).timestamp()
    os.utime(src, (ts, ts))
    svc.importar(p.id, [_item(src, 4, data=None)])
    rev = repo.load_container(p.id).documentos[TIPO].atual
    assert rev.principal.nome == _nome(4, "140926")
    assert rev.data == "2026-09-14"
    assert (repo.doc_path(p, TIPO) / _nome(4, "140926")).read_text(encoding="utf-8") == "x"


def test_originais_intactos(ctx):
    svc, p, origem = ctx
    a = _arq(origem, "a.pdf", "A")
    b = _arq(origem, "b.pdf", "B")
    e = _arq(origem, "b.dwg", "E")
    ts = datetime(2026, 1, 2, 3, 4).timestamp()
    os.utime(a, (ts, ts))
    svc.importar(p.id, [_item(a, 0), _item(b, 1), _item(e, 1, papel="editavel")])
    assert _snapshot(origem) == {"a.pdf": "A", "b.pdf": "B", "b.dwg": "E"}
    assert a.stat().st_mtime == ts


def test_numero_existente_bloqueado(ctx, repo, tmp_path):
    svc, p, origem = ctx
    RevisionService(repo).enviar_revisao(p.id, TIPO, _arq(tmp_path, "up.pdf", "0"), [],
                                         "Em elaboração", "")
    pasta = repo.doc_path(p, TIPO)
    antes = _snapshot(pasta)
    json_path = repo.container_path(p) / "projeto.json"
    json_antes = json_path.read_bytes()
    itens = [_item(_arq(origem, "a.pdf", "a"), 0), _item(_arq(origem, "b.pdf", "b"), 1)]
    erros = svc.validar(p.id, itens)
    assert erros[0] is not None and "Rev00" in erros[0] and "já existe" in erros[0]
    assert erros[1] is None
    with pytest.raises(OrbitError):
        svc.importar(p.id, itens)
    assert _snapshot(pasta) == antes
    assert json_path.read_bytes() == json_antes


def test_backfill_menor_vai_para_antigos(ctx, repo, tmp_path):
    svc, p, origem = ctx
    rev = RevisionService(repo)
    rev.enviar_revisao(p.id, TIPO, _arq(tmp_path, "up.pdf", "pdf3"), [], "Aprovado", "",
                       numero=3)
    svc.importar(p.id, [_item(_arq(origem, "velho.pdf", "pdf1"), 1)])
    pasta = repo.doc_path(p, TIPO)
    assert _snapshot(pasta) == {
        _nome(3, "221026"): "pdf3",
        str(Path("Antigos") / _nome(1)): "pdf1",
    }
    doc = repo.load_container(p.id).documentos[TIPO]
    assert doc.atual.numero == 3
    assert [(r.numero, r.arquivada) for r in sorted(doc.revisoes, key=lambda r: r.numero)] == [
        (1, True), (3, False)]


def test_importada_maior_arquiva_atual_existente(ctx, repo, tmp_path):
    svc, p, origem = ctx
    RevisionService(repo).enviar_revisao(p.id, TIPO, _arq(tmp_path, "up.pdf", "pdf0"), [],
                                         "Aprovado", "")
    svc.importar(p.id, [_item(_arq(origem, "novo.pdf", "pdf5"), 5)])
    pasta = repo.doc_path(p, TIPO)
    assert _snapshot(pasta) == {
        _nome(5): "pdf5",
        str(Path("Antigos") / _nome(0, "221026")): "pdf0",
    }
    doc = repo.load_container(p.id).documentos[TIPO]
    assert [(r.numero, r.arquivada) for r in doc.revisoes] == [(0, True), (5, False)]


def test_validacoes_por_item(ctx, repo):
    svc, p, origem = ctx
    a = _arq(origem, "a.pdf", "a")
    itens = [
        _item(a, 0, status="Inventado"),                        # status inválido
        _item(origem / "sumiu.pdf", 1),                         # origem inexistente
        _item(a, 2, papel="editavel"),                          # grupo sem principal
        _item(a, 3), _item(a, 3),                               # dois principais
        _item(a, 4, tipo_id="tipo_inventado"),                  # tipo desconhecido
        _item(a, 5, tipo_id="lista_tags"),                      # ok
    ]
    erros = svc.validar(p.id, itens)
    assert "Status inválido" in erros[0]
    assert "não encontrado" in erros[1]
    assert "principal" in erros[2]
    assert "principal" in erros[3] and "principal" in erros[4]
    assert "Tipo de documento" in erros[5]
    assert erros[6] is None
    with pytest.raises(OrbitError):
        svc.importar(p.id, itens)
    assert repo.load_container(p.id).documentos["lista_tags"].revisoes == []
    with pytest.raises(OrbitError):
        svc.importar(p.id, [])


def test_destino_existente_bloqueado(ctx, repo):
    svc, p, origem = ctx
    pasta = repo.doc_path(p, TIPO)
    _arq(pasta / "Antigos", _nome(1), "solto")
    itens = [_item(_arq(origem, "a.pdf", "a"), 1), _item(_arq(origem, "b.pdf", "b"), 2)]
    erros = svc.validar(p.id, itens)
    assert erros[0] is not None and "Já existe" in erros[0]
    assert erros[1] is None
    with pytest.raises(OrbitError):
        svc.importar(p.id, itens)
    assert _snapshot(pasta) == {str(Path("Antigos") / _nome(1)): "solto"}


def test_importacao_desliga_nao_se_aplica(ctx, repo):
    svc, p, origem = ctx
    RevisionService(repo).definir_nao_se_aplica(p.id, TIPO, True)
    svc.importar(p.id, [_item(_arq(origem, "a.pdf", "a"), 0)])
    c = repo.load_container(p.id)
    assert c.documentos[TIPO].nao_se_aplica is False
    assert [e.tipo for e in c.historico[-2:]] == ["nao_se_aplica_alterado", "importacao"]
    assert c.historico[-2].dados == {"tipo_id": TIPO, "valor": False}


def test_falha_no_meio_desfaz_tudo(ctx, repo, tmp_path, monkeypatch):
    svc, p, origem = ctx
    RevisionService(repo).enviar_revisao(p.id, TIPO, _arq(tmp_path, "up.pdf", "pdf0"),
                                         [_arq(tmp_path, "up.dwg", "dwg0")], "Aprovado", "")
    pasta = repo.doc_path(p, TIPO)
    json_path = repo.container_path(p) / "projeto.json"
    antes = _snapshot(pasta)
    json_antes = json_path.read_bytes()
    itens = [_item(_arq(origem, "r1.pdf", "pdf1"), 1),
             _item(_arq(origem, "r2.pdf", "pdf2"), 2),
             _item(_arq(origem, "r2.dwg", "dwg2"), 2, papel="editavel"),
             _item(_arq(origem, "t1.pdf", "tag1"), 1, tipo_id="lista_tags")]
    orig_antes = _snapshot(origem)

    real_rename = os.rename
    chamadas = []

    def rename_falha(src, dst, *a, **k):
        chamadas.append((src, dst))
        if len(chamadas) == 3:
            raise PermissionError(13, "Acesso negado", str(src))
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", rename_falha)
    with pytest.raises(ArquivoEmUso) as exc:
        svc.importar(p.id, itens)
    monkeypatch.undo()
    assert len(chamadas) > 3  # falhou depois de mover a atual; o desfazer também renomeou
    assert "está aberto em outro programa" in str(exc.value)
    assert "~orbit-" not in str(exc.value)
    assert _snapshot(pasta) == antes
    assert _snapshot(repo.doc_path(p, "lista_tags")) == {}
    assert json_path.read_bytes() == json_antes
    assert _snapshot(origem) == orig_antes
    assert not list(repo.container_path(p).rglob("~orbit-*"))
