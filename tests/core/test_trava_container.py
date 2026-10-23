"""Trava do container: leituras-alterações-gravações do JSON não perdem atualização (I1)."""
import threading
from datetime import datetime
from pathlib import Path

import pytest

import orbit.core.repository as repmod
import orbit.core.revisions as rv
from orbit.core.email import EmailDraft, EmailService, SelecaoEnvio
from orbit.core.errors import LockHeld, OrbitError
from orbit.core.identity import Identity
from orbit.core.importer import ImportService, ItemImportacao
from orbit.core.presence import PresenceService
from orbit.core.repository import Repository
from orbit.core.revisions import RevisionService

DIAG, MEM, LAY = "diagrama_eletrico", "memorial_descritivo", "layout_painel"


@pytest.fixture
def ctx(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Linha")
    origem = tmp_path / "origem"
    origem.mkdir()
    return p, origem


def _arq(pasta: Path, nome: str, conteudo: str = "x") -> Path:
    f = pasta / nome
    f.write_text(conteudo, encoding="utf-8")
    return f


def _lock(repo, p) -> Path:
    return repo.container_path(p) / ".orbit" / "travas" / "_container.lock"


def _upload_parado_no_meio(repo, p, origem, monkeypatch, tipo=MEM, svc=None):
    """Inicia um upload numa thread e o segura durante a cópia dos arquivos."""
    chegou, segue = threading.Event(), threading.Event()
    original = rv.shutil.copy2

    def copia_lenta(*a, **k):
        chegou.set()
        assert segue.wait(10)
        return original(*a, **k)
    monkeypatch.setattr(rv.shutil, "copy2", copia_lenta)
    svc = svc or RevisionService(repo, presence=PresenceService(repo.identity, repo.agora))
    erro = []

    def rodar():
        try:
            svc.enviar_revisao(p.id, tipo, _arq(origem, "novo.pdf"), [], "Em elaboração", "m")
        except BaseException as e:  # noqa: BLE001
            erro.append(e)
    t = threading.Thread(target=rodar)
    t.start()
    assert chegou.wait(10)
    return t, segue, erro


def test_status_durante_upload_de_outro_tipo_nao_se_perde(repo, ctx, monkeypatch):
    p, origem = ctx
    svc = RevisionService(repo)
    svc.enviar_revisao(p.id, DIAG, _arq(origem, "d.pdf"), [], "Em elaboração", "m")
    t, segue, erro = _upload_parado_no_meio(repo, p, origem, monkeypatch)
    # enquanto o upload de MEM copia, outra thread muda o status de DIAG
    svc.alterar_status(p.id, DIAG, "Aprovado")
    svc.definir_nao_se_aplica(p.id, LAY, True)
    repo.update_dados(p.id, pedido="PED-9")
    segue.set()
    t.join(10)
    assert erro == []
    c = repo.load_container(p.id)
    assert c.documentos[DIAG].atual.status == "Aprovado"
    assert c.documentos[LAY].nao_se_aplica is True
    assert c.pedido == "PED-9"
    assert c.documentos[MEM].atual.numero == 0
    tipos = [e.tipo for e in c.historico]
    assert tipos.count("status_alterado") == 1 and tipos.count("revisao_enviada") == 2
    assert "dados_alterados" in tipos
    assert not _lock(repo, p).exists()


def test_importacao_durante_status_nao_se_perde(repo, ctx, monkeypatch):
    p, origem = ctx
    svc = RevisionService(repo)
    svc.enviar_revisao(p.id, DIAG, _arq(origem, "d.pdf"), [], "Em elaboração", "m")
    chegou, segue = threading.Event(), threading.Event()
    original = rv.shutil.copy2

    def copia_lenta(*a, **k):
        chegou.set()
        assert segue.wait(10)
        return original(*a, **k)
    monkeypatch.setattr(rv.shutil, "copy2", copia_lenta)
    imp = ImportService(repo, presence=PresenceService(repo.identity, repo.agora))
    item = ItemImportacao(_arq(origem, "m.pdf"), MEM, 3, "Aprovado")
    t = threading.Thread(target=lambda: imp.importar(p.id, [item]))
    t.start()
    assert chegou.wait(10)
    svc.alterar_status(p.id, DIAG, "Aprovado")
    segue.set()
    t.join(10)
    c = repo.load_container(p.id)
    assert c.documentos[DIAG].atual.status == "Aprovado"
    assert c.documentos[MEM].atual.numero == 3


def test_duas_maquinas_mudando_coisas_diferentes_ao_mesmo_tempo(repo, ctx):
    p, origem = ctx
    tipos = [t.id for t in repo.config.tipos_ativos()]
    svc0 = RevisionService(repo)
    for t in tipos:
        svc0.enviar_revisao(p.id, t, _arq(origem, f"{t}.pdf"), [], "Em elaboração", "m")
    maquinas = [Repository(repo.base, Identity("u", f"PC{i}"), repo.config) for i in (1, 2)]
    erros = []

    def trabalhar(r, meus):
        try:
            s = RevisionService(r)
            for t in meus:
                s.alterar_status(p.id, t, "Aprovado")
        except BaseException as e:  # noqa: BLE001
            erros.append(e)
    ths = [threading.Thread(target=trabalhar, args=(maquinas[0], tipos[0::2])),
           threading.Thread(target=trabalhar, args=(maquinas[1], tipos[1::2]))]
    for th in ths:
        th.start()
    for th in ths:
        th.join(30)
    assert erros == []
    c = repo.load_container(p.id)
    assert all(c.documentos[t].atual.status == "Aprovado" for t in tipos)
    assert sum(1 for e in c.historico if e.tipo == "status_alterado") == len(tipos)


def test_email_preparado_relido_dentro_da_trava(repo, ctx, monkeypatch):
    p, origem = ctx
    RevisionService(repo).enviar_revisao(p.id, DIAG, _arq(origem, "d.pdf"), [],
                                         "Em elaboração", "m")

    class Outlook:
        def disponivel(self):
            return True

        def abrir_rascunho(self, d):
            # outra máquina muda o status enquanto o Outlook abre
            RevisionService(repo).alterar_status(p.id, DIAG, "Aprovado")

    EmailService(repo, Outlook()).preparar(p.id, EmailDraft([], "a", "b", []),
                                           [SelecaoEnvio(DIAG, 0)])
    c = repo.load_container(p.id)
    assert c.documentos[DIAG].atual.status == "Aprovado"
    assert c.historico[-1].tipo == "email_preparado"


def test_trava_abandonada_e_recuperada(repo, ctx):
    p, _ = ctx
    velho = PresenceService(Identity("fulano", "PC-X"), agora=lambda: datetime(2026, 10, 22, 13, 0))
    lock = velho.travar(repo.container_path(p), "_container")
    assert lock == _lock(repo, p)
    repo.update_dados(p.id, pedido="P1")  # o relógio do repo está 1h32 à frente
    assert repo.load_container(p.id).pedido == "P1"
    assert not _lock(repo, p).exists()


def test_trava_ocupada_espera_e_desiste_com_mensagem_clara(repo, ctx, monkeypatch):
    p, _ = ctx
    monkeypatch.setattr(repmod, "ESPERA_TRAVA_CONTAINER_S", 0.2)
    outro = PresenceService(Identity("fulano", "PC-X"), agora=repo.agora)
    lock = outro.travar(repo.container_path(p), "_container")
    with pytest.raises(OrbitError, match="fulano") as e:
        repo.update_dados(p.id, pedido="P1")
    assert not isinstance(e.value, LockHeld)
    assert lock.exists()
    assert repo.load_container(p.id).pedido == ""


def test_trava_ocupada_e_solta_logo_depois_funciona(repo, ctx):
    p, _ = ctx
    outro = PresenceService(Identity("fulano", "PC-X"), agora=repo.agora)
    lock = outro.travar(repo.container_path(p), "_container")
    threading.Timer(0.3, lambda: outro.liberar(lock)).start()
    repo.update_dados(p.id, pedido="P1")
    assert repo.load_container(p.id).pedido == "P1"


def test_upload_sem_trava_do_container_desfaz_os_arquivos(repo, ctx, monkeypatch):
    p, origem = ctx
    svc = RevisionService(repo)
    svc.enviar_revisao(p.id, DIAG, _arq(origem, "d.pdf", "rev0"), [], "Em elaboração", "m")
    pasta = repo.doc_path(p, DIAG)
    antes = sorted(str(f.relative_to(pasta)) for f in pasta.rglob("*"))
    monkeypatch.setattr(repmod, "ESPERA_TRAVA_CONTAINER_S", 0.2)
    outro = PresenceService(Identity("fulano", "PC-X"), agora=repo.agora)
    outro.travar(repo.container_path(p), "_container")
    with pytest.raises(OrbitError, match="fulano"):
        svc.enviar_revisao(p.id, DIAG, _arq(origem, "d1.pdf", "rev1"), [], "Em elaboração", "m")
    assert sorted(str(f.relative_to(pasta)) for f in pasta.rglob("*")) == antes
    assert repo.load_container(p.id).documentos[DIAG].atual.numero == 0


def test_registro_relido_na_trava_nao_duplica(repo, ctx):
    from orbit.core.reconcile import find_untracked, register_untracked
    p, _ = ctx
    pasta = repo.doc_path(p, DIAG)
    (pasta / "Diagrama - Rev02.pdf").write_text("x")
    achados = find_untracked(repo, repo.load_container(p.id))
    register_untracked(repo, p.id, achados, "Em elaboração")
    register_untracked(repo, p.id, achados, "Em elaboração")  # lista antiga (outro PC já registrou)
    c = repo.load_container(p.id)
    assert [r.numero for r in c.documentos[DIAG].revisoes] == [2]
    assert [e.tipo for e in c.historico].count("arquivo_registrado") == 1
