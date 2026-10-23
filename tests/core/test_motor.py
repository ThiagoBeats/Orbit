import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from orbit.core.actionlog import ActionLog
from orbit.core.config import load_shared_config
from orbit.core.errors import LockHeld
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json
from orbit.core.presence import PresenceService
from orbit.core.repository import Repository
from orbit.core.revisions import RevisionService
from orbit.core.sync import motor
from orbit.core.sync.motor import SyncEngine
from orbit.core.sync.varredura import Retrato

PC1, PC2 = Identity("thiago", "PC1"), Identity("ana", "PC2")
AGORA = lambda: datetime(2026, 10, 23, 9, 0)


class Ambiente:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.base, self.backup = tmp / "base", tmp / "backup"
        self.base.mkdir()
        self.backup.mkdir()
        self.origem = tmp / "origem"
        self.origem.mkdir()
        self.n = 0

    def repo(self, lado="base", ident=PC1):
        raiz = self.base if lado == "base" else self.backup
        return Repository(raiz, ident, load_shared_config(raiz), agora=AGORA)

    def pdf(self, conteudo: bytes = None) -> Path:
        self.n += 1
        f = self.origem / f"ABC{self.n}.pdf"
        f.write_bytes(conteudo or f"pdf {self.n}".encode())
        return f

    def subir(self, repo, cid, tipo="diagrama_eletrico", status="Em elaboração"):
        return RevisionService(repo).enviar_revisao(cid, tipo, self.pdf(), [], status, "m")

    def engine(self, ident=PC1, log=True):
        lg = ActionLog(self.base, ident, self.tmp / "ancoras.json", agora=AGORA) if log else None
        return SyncEngine(self.base, self.backup, ident, Retrato(self.tmp / "sync"), lg,
                          agora=AGORA)


@pytest.fixture
def amb(tmp_path):
    return Ambiente(tmp_path)


def _todos(raiz: Path) -> dict[str, str]:
    out = {}
    for p in raiz.rglob("*"):
        if p.is_file():
            out[p.relative_to(raiz).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _arquivos_doc(raiz: Path) -> set[str]:
    return {r for r in _todos(raiz) if r.endswith(".pdf")}


def _projeto(amb, lado="base", ident=PC1, cliente="Cliente X", nome="Envasadora"):
    r = amb.repo(lado, ident)
    cli = r.create_cliente(cliente)
    return r, cli, r.create_projeto(cli.id, "001", nome)


def test_primeira_sync_backup_vazio_copia_tudo(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    res = amb.engine().sincronizar()
    assert res.erro is None and res.enviados > 0 and res.divergencias == []
    assert _arquivos_doc(amb.backup) == _arquivos_doc(amb.base)
    assert read_json(amb.backup / "Clientes/Cliente X/001 - Envasadora/projeto.json")["id"] == p.id
    assert amb.engine().comparar().identico


def test_novo_de_cada_lado_vai_para_o_outro(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id, "diagrama_eletrico")
    amb.subir(amb.repo("backup", PC2), p.id, "topologia_rede")
    res = amb.engine().sincronizar()
    assert res.divergencias == [] and res.erro is None
    assert _arquivos_doc(amb.base) == _arquivos_doc(amb.backup)
    assert len(_arquivos_doc(amb.base)) == 2
    for lado in (amb.base, amb.backup):
        c = Repository(lado, PC1, load_shared_config(lado)).load_container(p.id)
        assert c.documentos["diagrama_eletrico"].atual.numero == 0
        assert c.documentos["topologia_rede"].atual.numero == 0


def test_upload_em_casa_move_antiga_para_antigos_no_backup(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    amb.engine().sincronizar()
    amb.subir(r, p.id)  # Rev01: a Rev00 vai para Antigos localmente
    res = amb.engine().sincronizar()
    assert res.erro is None and res.divergencias == []
    docs = {Path(x).parent.name + "/" + Path(x).name.split(" - ")[-1]
            for x in _arquivos_doc(amb.backup)}
    assert docs == {"Antigos/Rev00.pdf", "Diagrama Elétrico/Rev01.pdf"}
    assert _arquivos_doc(amb.base) == _arquivos_doc(amb.backup)


def test_arquivo_apagado_pelo_explorer_e_restaurado(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    eng = amb.engine()
    eng.sincronizar()
    alvo = next(amb.backup.rglob("*.pdf"))
    alvo.unlink()
    res = amb.engine().sincronizar()
    assert alvo.is_file() and res.restaurados == 1
    assert "arquivo_restaurado" in [l.acao for l in eng.log.ler()]


def test_arquivo_solto_mudado_de_um_lado_guarda_o_antigo(amb):
    _projeto(amb)
    solto = amb.base / "Clientes" / "Cliente X" / "notas.txt"
    solto.write_text("v1", encoding="utf-8")
    amb.engine().sincronizar()
    (amb.backup / "Clientes" / "Cliente X" / "notas.txt").write_text("v2-servidor",
                                                                     encoding="utf-8")
    res = amb.engine().sincronizar()
    assert res.divergencias == []
    assert solto.read_text(encoding="utf-8") == "v2-servidor"
    guardados = list((amb.base / "_Divergências").rglob("notas.txt"))
    assert len(guardados) == 1 and guardados[0].read_text(encoding="utf-8") == "v1"


def test_arquivo_solto_mudado_dos_dois_lados_diverge(amb):
    _projeto(amb)
    solto = amb.base / "Clientes" / "Cliente X" / "notas.txt"
    solto.write_text("v1", encoding="utf-8")
    amb.engine().sincronizar()
    solto.write_text("casa", encoding="utf-8")
    (amb.backup / "Clientes" / "Cliente X" / "notas.txt").write_text("servidor",
                                                                     encoding="utf-8")
    res = amb.engine().sincronizar()
    assert [d.tipo for d in res.divergencias] == ["arquivo"]
    assert solto.read_text(encoding="utf-8") == "casa"


def test_nada_sobrescrito_nem_apagado(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    amb.engine().sincronizar()
    amb.subir(r, p.id)
    amb.subir(amb.repo("backup", PC2), p.id, "topologia_rede")
    def pdfs(lado):
        return {h for rel, h in _todos(lado).items() if rel.endswith(".pdf")}
    antes = {lado: pdfs(lado) for lado in (amb.base, amb.backup)}
    amb.engine().sincronizar()
    for lado in (amb.base, amb.backup):
        assert antes[lado] <= pdfs(lado)  # nenhum documento sumiu nem foi trocado
    assert _arquivos_doc(amb.base) == _arquivos_doc(amb.backup)


def test_backup_some_no_meio(amb, monkeypatch):
    r, cli, p = _projeto(amb)
    for _ in range(3):
        amb.subir(r, p.id, "diagrama_eletrico")
    r2 = amb.repo()
    p2 = r2.create_projeto(cli.id, "002", "Rotuladora")
    amb.subir(r2, p2.id)
    original = motor.copiar_seguro
    chamadas = []
    sumido = amb.tmp / "backup_desconectado"

    def falha_no_terceiro(origem, destino):
        chamadas.append(1)
        if len(chamadas) == 3:
            amb.backup.rename(sumido)
            raise FileNotFoundError(2, "unidade removida")
        return original(origem, destino)
    monkeypatch.setattr(motor, "copiar_seguro", falha_no_terceiro)
    res = amb.engine().sincronizar()
    assert res.erro and "inacess" in res.erro.lower()
    assert not list(amb.base.rglob("~orbit-*")) and not list(sumido.rglob("~orbit-*"))
    monkeypatch.setattr(motor, "copiar_seguro", original)
    sumido.rename(amb.backup)
    comp = amb.engine().comparar()
    assert not comp.identico and comp.enviar


def test_arquivo_em_uso_no_backup_vira_pulado(amb):
    r, cli, p = _projeto(amb)
    p2 = r.create_projeto(cli.id, "002", "Rotuladora")
    amb.subir(r, p.id)
    amb.engine().sincronizar()
    amb.subir(r, p.id)       # Rev00 do backup precisará ir para Antigos
    amb.subir(r, p2.id)      # outro projeto, livre
    rev00_backup = next(f for f in amb.backup.rglob("*Rev00.pdf"))
    with open(rev00_backup, "rb"):
        res = amb.engine().sincronizar()
    assert any("Envasadora" in x for x in res.pulados)
    assert len([f for f in amb.backup.rglob("*.pdf") if "Rotuladora" in f.name]) == 1


def test_upload_ativo_no_servidor_pula_container(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)
    pasta_b = amb.backup / "Clientes" / "Cliente X" / "001 - Envasadora"
    trava = PresenceService(PC2, agora=datetime.now).travar(pasta_b, "diagrama_eletrico")
    res = amb.engine().sincronizar()
    assert any("Envasadora" in x for x in res.pulados)
    assert not list(pasta_b.rglob("*.pdf"))
    PresenceService(PC2, agora=datetime.now).liberar(trava)


def test_trava_de_sincronizacao_ocupada(amb):
    _projeto(amb)
    trava = PresenceService(PC2, agora=datetime.now).travar(amb.backup, "_sincronizacao")
    with pytest.raises(LockHeld) as e:
        amb.engine().sincronizar()
    assert "ana (PC2) está sincronizando com este backup" in str(e.value)
    PresenceService(PC2, agora=datetime.now).liberar(trava)


def test_pasta_mesma_com_ids_diferentes_diverge(amb):
    _, _, p_local = _projeto(amb)
    _, _, p_backup = _projeto(amb, "backup", PC2)
    res = amb.engine().sincronizar()
    assert "pasta_id" in [d.tipo for d in res.divergencias]
    j = read_json(amb.backup / "Clientes/Cliente X/001 - Envasadora/projeto.json")
    assert j["id"] == p_backup.id


def test_comparar_nao_altera_nada(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    antes = (_todos(amb.base), _todos(amb.backup))
    comp = amb.engine().comparar()
    assert (_todos(amb.base), _todos(amb.backup)) == antes
    assert comp.enviar and not comp.identico


def test_somente_container(amb):
    r, cli, p = _projeto(amb)
    p2 = r.create_projeto(cli.id, "002", "Rotuladora")
    amb.engine().sincronizar()
    amb.subir(r, p.id)
    amb.subir(r, p2.id)
    amb.engine().sincronizar(somente_container=p.id)
    nomes = {f.name for f in amb.backup.rglob("*.pdf")}
    assert any("Envasadora" in n for n in nomes)
    assert not any("Rotuladora" in n for n in nomes)


def test_log_unido_nos_dois_lados(amb):
    r, cli, p = _projeto(amb)
    eng = amb.engine()
    eng.log.registrar_acao("teste", {})
    eng.sincronizar()
    linhas_b = ActionLog(amb.backup, PC2, amb.tmp / "anc2.json").ler()
    assert "teste" in [l.acao for l in linhas_b]


def test_mesma_rev_com_mesmo_nome_e_conteudo_diferente_diverge(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)                         # Rev00 em casa
    amb.subir(amb.repo("backup", PC2), p.id)   # outra Rev00 no servidor, mesmo nome
    res = amb.engine().sincronizar()
    revs = [d for d in res.divergencias if d.tipo == "revisao"]
    assert len(revs) == 1 and revs[0].acoes == ["local", "backup", "ambos"]
    assert revs[0].chave == "documentos.diagrama_eletrico.revisoes.0"
    # nenhum lado foi alterado
    a = {f.read_bytes() for f in amb.base.rglob("*.pdf")}
    b = {f.read_bytes() for f in amb.backup.rglob("*.pdf")}
    assert a != b and len(a) == len(b) == 1


def test_revisao_arquivada_de_numero_maior_continua_arquivada(amb):
    """Rev05 registrada como antiga (Antigos) e Rev00 atual: sincronizar não troca a atual."""
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)  # Rev00 atual
    pasta = amb.base / "Clientes" / "Cliente X" / "001 - Envasadora" / "Diagrama Elétrico"
    antiga = pasta / "Antigos" / "Diagrama Elétrico - Cliente X - Envasadora - 010126 - Rev05.pdf"
    antiga.write_bytes(b"rev05 antiga")
    from orbit.core.reconcile import find_untracked, register_untracked
    c = r.load_container(p.id)
    register_untracked(r, p.id, find_untracked(r, c), "Aprovado")
    assert r.load_container(p.id).documentos["diagrama_eletrico"].atual.numero == 0
    for _ in range(2):
        res = amb.engine().sincronizar()
        assert res.erro is None and res.divergencias == []
    for lado in (amb.base, amb.backup):
        doc = Repository(lado, PC1, load_shared_config(lado)).load_container(p.id) \
            .documentos["diagrama_eletrico"]
        assert doc.atual.numero == 0
        pd = lado / "Clientes" / "Cliente X" / "001 - Envasadora" / "Diagrama Elétrico"
        assert (pd / "Antigos" / antiga.name).is_file()
        assert not (pd / antiga.name).exists()


def test_divergencia_nao_resolvida_mantem_o_valor_de_cada_lado(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    r.update_dados(p.id, pedido="PED-LOCAL")
    amb.repo("backup", PC2).update_dados(p.id, pedido="PED-BACKUP")
    for _ in range(2):
        res = amb.engine().sincronizar()
        assert [d.chave for d in res.divergencias] == ["pedido"]
    assert read_json(amb.backup / "Clientes/Cliente X/001 - Envasadora/projeto.json")["pedido"] \
        == "PED-BACKUP"
    assert read_json(amb.base / "Clientes/Cliente X/001 - Envasadora/projeto.json")["pedido"] \
        == "PED-LOCAL"


def test_revisao_divergente_mantem_os_arquivos_de_cada_lado_no_json(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)
    rb = amb.repo("backup", PC2)
    dwg = amb.origem / "x.dwg"
    dwg.write_bytes(b"dwg")
    RevisionService(rb).enviar_revisao(p.id, "diagrama_eletrico", amb.pdf(), [dwg],
                                       "Em elaboração", "m")
    for _ in range(2):
        res = amb.engine().sincronizar()
        assert [d.tipo for d in res.divergencias] == ["revisao"]
    jb = read_json(amb.backup / "Clientes/Cliente X/001 - Envasadora/projeto.json")
    arqs = jb["documentos"]["diagrama_eletrico"]["revisoes"][0]["arquivos"]
    assert len(arqs) == 2


def test_gravacao_de_colega_durante_a_copia_nao_se_perde(amb, monkeypatch):
    from datetime import timedelta
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)  # a sincronização vai copiar este PDF para o servidor
    colega = Repository(amb.backup, PC2, load_shared_config(amb.backup),
                        agora=lambda: datetime.now() + timedelta(seconds=120))
    original = motor.copiar_seguro
    feito = []

    def copia_lenta(origem, destino):
        if not feito and str(destino).endswith(".pdf"):
            feito.append(1)
            colega.update_dados(p.id, pedido="PEDIDO-DO-COLEGA")
        return original(origem, destino)
    monkeypatch.setattr(motor, "copiar_seguro", copia_lenta)
    res = amb.engine().sincronizar()
    assert feito and res.erro is None
    for lado in (amb.base, amb.backup):
        j = read_json(lado / "Clientes/Cliente X/001 - Envasadora/projeto.json")
        assert j["pedido"] == "PEDIDO-DO-COLEGA"


def test_copia_de_revisao_trava_o_documento_no_servidor(amb, monkeypatch):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)
    pasta_b = amb.backup / "Clientes" / "Cliente X" / "001 - Envasadora"
    vistos = []
    original = motor.copiar_seguro

    def olhando(origem, destino):
        if str(destino).endswith(".pdf"):
            vistos.append((pasta_b / ".orbit" / "travas" / "diagrama_eletrico.lock").exists())
        return original(origem, destino)
    monkeypatch.setattr(motor, "copiar_seguro", olhando)
    amb.engine().sincronizar()
    assert vistos == [True]
    assert not (pasta_b / ".orbit" / "travas" / "diagrama_eletrico.lock").exists()


def test_mudanca_de_um_lado_apos_primeira_copia_nao_diverge(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()  # o projeto é copiado inteiro para o backup
    amb.repo("backup", PC2).update_dados(p.id, pedido="SÓ NO SERVIDOR")
    res = amb.engine().sincronizar()
    assert res.divergencias == []
    assert read_json(amb.base / "Clientes/Cliente X/001 - Envasadora/projeto.json")["pedido"] \
        == "SÓ NO SERVIDOR"


def test_revisao_arquivada_de_um_lado_e_apagada_do_outro_e_restaurada(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)                       # Rev00 local
    amb.engine().sincronizar()
    amb.subir(amb.repo("backup", PC2), p.id)  # Rev01 no servidor: Rev00 vai para Antigos lá
    for f in amb.backup.rglob("*Rev00.pdf"):
        f.unlink()                            # e alguém apaga a Rev00 pelo Explorer
    res = amb.engine().sincronizar()
    assert res.pulados == [] and res.erro is None
    for lado in (amb.base, amb.backup):
        nomes = {f.parent.name + "/" + f.name[-9:] for f in lado.rglob("*.pdf")}
        assert nomes == {"Antigos/Rev00.pdf", "Diagrama Elétrico/Rev01.pdf"}
