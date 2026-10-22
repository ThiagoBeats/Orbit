"""Rascunho .eml quando o Outlook clássico (COM) não está disponível (I3, Ruling R12)."""
import email
import os
from datetime import date
from email import policy

import pytest

from orbit.core import eml as emlmod
from orbit.core.email import EmailDraft, EmailService, SelecaoEnvio
from orbit.core.eml import escrever_eml
from orbit.core.errors import OrbitError
from orbit.core.models import Contato
from orbit.core.revisions import RevisionService

DIAG = "diagrama_eletrico"
MEM = "memorial_descritivo"


class SemOutlook:
    def __init__(self):
        self.abertos = []

    def disponivel(self):
        return False

    def abrir_rascunho(self, d):  # nunca deve ser chamado
        self.abertos.append(d)


def _ler(caminho):
    return email.message_from_bytes(caminho.read_bytes(), policy=policy.default)


def test_eml_tem_x_unsent_destinatarios_assunto_corpo_e_anexos(tmp_path):
    orig = tmp_path / "orig"
    orig.mkdir()
    pdf = orig / "Diagrama Rev01.pdf"
    pdf.write_bytes(b"%PDF-1.4\n\x00\x01\x02\xff" * 50)
    dwg = orig / "Diagrama Rev01.dwg"
    dwg.write_bytes(bytes(range(256)))
    txt = orig / "lista.txt"
    txt.write_bytes("ação\r\nlinha 2\n".encode("utf-8"))
    d = EmailDraft(["ana@x.com", "bo@x.com"], "Cliente - Projeto - Documentos ç/:*?",
                   "Prezados,\n\nSeguem os documentos.\n", [pdf, dwg, txt])
    arq = escrever_eml(d, tmp_path / "raiz")
    assert arq.suffix == ".eml" and arq.is_file()
    assert arq.parent.parent == tmp_path / "raiz"
    m = _ler(arq)
    assert m["X-Unsent"] == "1"
    assert m["To"] == "ana@x.com, bo@x.com"
    assert m["Subject"] == "Cliente - Projeto - Documentos ç/:*?"
    assert m.get_body(("plain",)).get_content().replace("\r\n", "\n") == d.corpo
    anexos = {a.get_filename(): a for a in m.iter_attachments()}
    assert set(anexos) == {pdf.name, dwg.name, txt.name}
    assert anexos[pdf.name].get_content_type() == "application/pdf"
    for f in (pdf, dwg, txt):
        assert anexos[f.name].get_payload(decode=True) == f.read_bytes()
    # nada nos originais mudou
    assert pdf.is_file() and dwg.is_file() and txt.is_file()


def test_eml_cada_envio_em_pasta_nova(tmp_path):
    d = EmailDraft([], "", "", [])
    a = escrever_eml(d, tmp_path)
    b = escrever_eml(d, tmp_path)
    assert a.parent != b.parent and a.is_file() and b.is_file()
    assert _ler(a)["X-Unsent"] == "1"


@pytest.fixture
def ctx(repo, tmp_path, tmp_path_factory, monkeypatch):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    repo.update_dados(p.id, contatos=[Contato("Ana", "ana@x.com")])
    origem = tmp_path / "origem"
    origem.mkdir()
    rs = RevisionService(repo)
    f = origem / "a.pdf"
    f.write_bytes(b"conteudo do pdf")
    rs.enviar_revisao(p.id, DIAG, f, [], "Em elaboração", "", data=date(2026, 10, 22))
    raiz = tmp_path_factory.mktemp("temp") / "Orbit"  # fora da base (= tmp_path)
    monkeypatch.setattr(emlmod, "raiz_temporaria", lambda: raiz)
    abertos = []
    monkeypatch.setattr(os, "startfile", lambda c, *a, **k: abertos.append(c))
    return repo, p, raiz, abertos


def _eventos(repo, p):
    return [e for e in repo.load_container(p.id).historico if e.tipo == "email_preparado"]


def test_sem_outlook_abre_eml_e_registra_depois(ctx, monkeypatch):
    repo, p, raiz, abertos = ctx
    out = SemOutlook()
    svc = EmailService(repo, out)
    sel = [SelecaoEnvio(DIAG, 0)]
    d = svc.montar(p.id, sel)
    eventos_na_abertura = []

    def abrir(c, *a, **k):
        eventos_na_abertura.append(len(_eventos(repo, p)))
        abertos.append(c)
    monkeypatch.setattr(os, "startfile", abrir)
    assert svc.preparar(p.id, d, sel) == "eml"
    assert out.abertos == []
    assert len(abertos) == 1 and abertos[0].endswith(".eml")
    assert eventos_na_abertura == [0]  # registrado só depois de abrir
    arq = __import__("pathlib").Path(abertos[0])
    assert raiz in arq.parents
    assert repo.base not in arq.parents
    m = _ler(arq)
    assert m["X-Unsent"] == "1"
    [anexo] = list(m.iter_attachments())
    assert anexo.get_payload(decode=True) == d.anexos[0].read_bytes()
    assert len(_eventos(repo, p)) == 1


def test_falha_ao_abrir_eml_abre_a_pasta_e_nao_registra(ctx, monkeypatch):
    repo, p, raiz, abertos = ctx

    def abrir(c, *a, **k):
        if str(c).endswith(".eml"):
            raise OSError(1155, "Nenhum aplicativo associado")
        abertos.append(c)
    monkeypatch.setattr(os, "startfile", abrir)
    svc = EmailService(repo, SemOutlook())
    sel = [SelecaoEnvio(DIAG, 0)]
    with pytest.raises(OrbitError, match="pasta") as e:
        svc.preparar(p.id, svc.montar(p.id, sel), sel)
    assert len(abertos) == 1
    pasta = __import__("pathlib").Path(abertos[0])
    assert pasta.parent == raiz and any(pasta.glob("*.eml"))
    assert str(pasta) in str(e.value)
    assert _eventos(repo, p) == []


def test_raiz_temporaria_dentro_da_base_e_recusada(ctx, monkeypatch):
    repo, p, _, abertos = ctx
    monkeypatch.setattr(emlmod, "raiz_temporaria", lambda: repo.base / "tmp")
    svc = EmailService(repo, SemOutlook())
    sel = [SelecaoEnvio(DIAG, 0)]
    with pytest.raises(OrbitError):
        svc.preparar(p.id, svc.montar(p.id, sel), sel)
    assert abertos == [] and not (repo.base / "tmp").exists()
    assert _eventos(repo, p) == []


def test_raiz_temporaria_padrao_fica_no_temp():
    import tempfile
    from pathlib import Path
    assert emlmod.raiz_temporaria() == Path(tempfile.gettempdir()) / "Orbit"


def test_com_outlook_continua_usando_outlook(ctx):
    repo, p, _, abertos = ctx

    class ComOutlook(SemOutlook):
        def disponivel(self):
            return True
    out = ComOutlook()
    svc = EmailService(repo, out)
    sel = [SelecaoEnvio(DIAG, 0)]
    assert svc.preparar(p.id, svc.montar(p.id, sel), sel) == "outlook"
    assert len(out.abertos) == 1 and abertos == []


def test_pastas_dos_documentos_por_revisao(ctx):
    repo, p, _, _ = ctx
    origem = repo.base / "origem"
    rs = RevisionService(repo)
    for nome in ("b.pdf", "m.pdf"):
        (origem / nome).write_bytes(b"x")
    rs.enviar_revisao(p.id, DIAG, origem / "b.pdf", [], "Em elaboração", "",
                      data=date(2026, 10, 22))
    rs.enviar_revisao(p.id, MEM, origem / "m.pdf", [], "Em elaboração", "",
                      data=date(2026, 10, 22))
    c = repo.load_container(p.id)
    svc = EmailService(repo, SemOutlook())
    pastas = svc.pastas_dos_documentos(p.id, [SelecaoEnvio(DIAG, 0), SelecaoEnvio(DIAG, 1),
                                              SelecaoEnvio(MEM, 0)])
    assert pastas == [repo.doc_path(c, DIAG) / "Antigos", repo.doc_path(c, DIAG),
                      repo.doc_path(c, MEM)]
    # repetidas saem uma vez só
    assert svc.pastas_dos_documentos(p.id, [SelecaoEnvio(DIAG, 1), SelecaoEnvio(DIAG, 1)]) \
        == [repo.doc_path(c, DIAG)]
