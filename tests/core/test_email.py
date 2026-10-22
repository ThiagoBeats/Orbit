from datetime import date, datetime
from pathlib import Path

import pytest

from orbit.core.email import EmailDraft, EmailService, SelecaoEnvio
from orbit.core.errors import OrbitError
from orbit.core.models import Contato
from orbit.core.revisions import RevisionService

DIAG = "diagrama_eletrico"
MEM = "memorial_descritivo"


class FakeOutlook:
    def __init__(self, ok=True):
        self.ok = ok
        self.abertos: list[EmailDraft] = []

    def disponivel(self) -> bool:
        return self.ok

    def abrir_rascunho(self, d: EmailDraft) -> None:
        self.abertos.append(d)


@pytest.fixture
def ctx(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    repo.update_dados(p.id, contatos=[Contato("Ana", "ana@x.com"), Contato("Bo", "bo@x.com")])
    origem = tmp_path / "origem"
    origem.mkdir()
    return repo, p, origem, RevisionService(repo)


def _env(rs, p, origem, tipo, nome, status="Em elaboração", editavel=None, numero=None):
    f = origem / nome
    f.write_text("x")
    eds = []
    if editavel:
        e = origem / editavel
        e.write_text("e")
        eds = [e]
    return rs.enviar_revisao(p.id, tipo, f, eds, status, "", numero=numero,
                             data=date(2026, 10, 22))


def test_montar_anexa_principal_e_opcionalmente_editavel(ctx):
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf", editavel="a.dwg")
    svc = EmailService(repo, FakeOutlook())
    d = svc.montar(p.id, [SelecaoEnvio(DIAG, 0)])
    assert d.destinatarios == ["ana@x.com", "bo@x.com"]
    assert [a.suffix for a in d.anexos] == [".pdf"]
    assert "Diagrama Elétrico - Rev00" in d.corpo
    d2 = svc.montar(p.id, [SelecaoEnvio(DIAG, 0, incluir_editaveis=True)])
    assert sorted(a.suffix for a in d2.anexos) == [".dwg", ".pdf"]
    assert all(a.is_file() for a in d2.anexos)
    assert d2.assunto == "Cliente X - Envasadora - Documentos"


def test_revisao_antiga_vem_de_antigos(ctx):
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf")
    _env(rs, p, origem, DIAG, "b.pdf")
    svc = EmailService(repo, FakeOutlook())
    d = svc.montar(p.id, [SelecaoEnvio(DIAG, 0)])
    assert d.anexos[0].parent.name == "Antigos"
    assert d.anexos[0].is_file()
    assert "Rev00" in d.corpo
    with pytest.raises(OrbitError):
        svc.montar(p.id, [SelecaoEnvio(DIAG, 9)])


def test_arquivo_ausente_no_disco(ctx):
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf")
    svc = EmailService(repo, FakeOutlook())
    d = svc.montar(p.id, [SelecaoEnvio(DIAG, 0)])
    d.anexos[0].unlink()
    with pytest.raises(OrbitError, match="Rev00"):
        svc.montar(p.id, [SelecaoEnvio(DIAG, 0)])


def test_assunto_para_aprovacao(ctx):
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf", status="Para aprovação")
    _env(rs, p, origem, MEM, "m.pdf", status="Para aprovação")
    svc = EmailService(repo, FakeOutlook())
    c = repo.load_container(p.id)
    sel = [SelecaoEnvio(DIAG, 0), SelecaoEnvio(MEM, 0)]
    assert svc.assunto_sugerido(c, sel) == \
        "Cliente X - Envasadora - Documentos para aprovação"
    rs.alterar_status(p.id, MEM, "Aprovado")
    c = repo.load_container(p.id)
    assert svc.assunto_sugerido(c, sel) == "Cliente X - Envasadora - Documentos"


def test_assunto_maquina(repo):
    m = repo.create_maquina("M1", "Prensa")
    svc = EmailService(repo, FakeOutlook())
    assert svc.assunto_sugerido(m, []) == "Prensa - Documentos"


def test_preparar_registra_evento(ctx):
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf")
    out = FakeOutlook()
    svc = EmailService(repo, out)
    sel = [SelecaoEnvio(DIAG, 0)]
    d = svc.montar(p.id, sel)
    svc.preparar(p.id, d, sel)
    assert out.abertos == [d]
    ev = repo.load_container(p.id).historico[-1]
    assert ev.tipo == "email_preparado"
    assert ev.dados == {"destinatarios": d.destinatarios, "assunto": d.assunto,
                        "itens": [{"tipo_id": DIAG, "numero": 0}]}


def test_outlook_indisponivel_usa_eml_e_nao_chama_outlook(ctx, monkeypatch, tmp_path_factory):
    from orbit.core import eml as emlmod
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf")
    raiz = tmp_path_factory.mktemp("temp")
    monkeypatch.setattr(emlmod, "raiz_temporaria", lambda: raiz)
    abertos = []
    monkeypatch.setattr("os.startfile", lambda c, *a, **k: abertos.append(c))
    out = FakeOutlook(ok=False)
    svc = EmailService(repo, out)
    sel = [SelecaoEnvio(DIAG, 0)]
    d = svc.montar(p.id, sel)
    assert svc.preparar(p.id, d, sel) == "eml"
    assert out.abertos == [] and len(abertos) == 1 and abertos[0].endswith(".eml")
    assert repo.load_container(p.id).historico[-1].tipo == "email_preparado"


def test_listar_envios_ordenado(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    cli2 = repo.create_cliente("Outro")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    p2 = repo.create_projeto(cli2.id, "002", "Linha")
    m = repo.create_maquina("M1", "Prensa")
    svc = EmailService(repo, FakeOutlook())
    horas = iter([datetime(2026, 10, 22, 10), datetime(2026, 10, 22, 12),
                  datetime(2026, 10, 22, 11)])
    for c in (p, m, p2):
        repo.agora = lambda h=next(horas): h
        d = EmailDraft(["a@b.com"], f"as-{c.nome}", "corpo", [])
        svc.preparar(c.id, d, [SelecaoEnvio(DIAG, 0)])
    envios = svc.listar_envios()
    assert [e["container_nome"] for e in envios] == ["Prensa", "Linha", "Envasadora"]
    assert envios[0]["cliente_nome"] is None
    assert envios[1]["cliente_nome"] == "Outro"
    assert envios[0]["itens"] == [{"tipo_id": DIAG, "numero": 0}]
    assert envios[0]["assunto"] == "as-Prensa"
    assert envios[0]["container_id"] == m.id
    assert [e["container_nome"] for e in svc.listar_envios(cli.id)] == ["Envasadora"]


def test_revisao_arquivada_com_arquivo_ainda_na_pasta_do_tipo(ctx):
    """A reconciliação pode marcar como arquivada sem mover: o e-mail acha nos dois lugares (M1)."""
    repo, p, origem, rs = ctx
    _env(rs, p, origem, DIAG, "a.pdf")
    c = repo.load_container(p.id)
    c.documentos[DIAG].revisoes[0].arquivada = True
    repo.save_container(c)
    d = EmailService(repo, FakeOutlook()).montar(p.id, [SelecaoEnvio(DIAG, 0)])
    assert [a.parent for a in d.anexos] == [repo.doc_path(c, DIAG)]
