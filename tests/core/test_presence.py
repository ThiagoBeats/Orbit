import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orbit.core.errors import LockHeld, OrbitError
from orbit.core.identity import Identity
from orbit.core.importer import ImportService, ItemImportacao
from orbit.core.presence import Presenca, PresenceService
from orbit.core.revisions import RevisionService

T0 = datetime(2026, 10, 22, 14, 32, 0)
TIPO = "diagrama_eletrico"
TIPO2 = "topologia_rede"


class Relogio:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def avancar(self, s: int) -> None:
        self.t += timedelta(seconds=s)


@pytest.fixture
def relogio():
    return Relogio(T0)


def _svc(usuario, computador, relogio):
    return PresenceService(Identity(usuario, computador), agora=relogio)


# ---------- presença ----------

def test_outros_ignora_proprio_e_velho(tmp_path, relogio):
    eu = _svc("thiago", "PC1", relogio)
    fulano = _svc("fulano", "PC-XYZ", relogio)
    velho = _svc("velho", "PC-OLD", relogio)
    velho.sinalizar(tmp_path)
    relogio.avancar(60)
    fulano.sinalizar(tmp_path)
    eu.sinalizar(tmp_path)
    relogio.avancar(61)  # velho: 121 s; fulano: 61 s
    outros = eu.outros(tmp_path)
    assert outros == [Presenca("fulano", "PC-XYZ", "2026-10-22T14:33:00",
                               "2026-10-22T14:33:00")]
    # o mesmo usuário em outro computador conta como outro
    _svc("thiago", "PC2", relogio).sinalizar(tmp_path)
    assert {(p.usuario, p.computador) for p in eu.outros(tmp_path)} == {
        ("fulano", "PC-XYZ"), ("thiago", "PC2")}
    # limite configurável
    assert [p.usuario for p in eu.outros(tmp_path, max_idade_s=30)] == ["thiago"]


def test_desde_preservado(tmp_path, relogio):
    eu = _svc("thiago", "PC1", relogio)
    eu.sinalizar(tmp_path)
    relogio.avancar(90)
    eu.sinalizar(tmp_path)
    arq = tmp_path / ".orbit" / "presenca" / "thiago@PC1.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    assert dados["desde"] == "2026-10-22T14:32:00"
    assert dados["ultimo_sinal"] == "2026-10-22T14:33:30"
    assert dados["versao_formato"] == 1
    assert (dados["usuario"], dados["computador"]) == ("thiago", "PC1")
    outro = _svc("ana", "PC2", relogio)
    assert outro.outros(tmp_path) == [Presenca("thiago", "PC1", "2026-10-22T14:32:00",
                                               "2026-10-22T14:33:30")]


def test_sair_remove_presenca(tmp_path, relogio):
    eu = _svc("thiago", "PC1", relogio)
    outro = _svc("ana", "PC2", relogio)
    eu.sinalizar(tmp_path)
    assert len(outro.outros(tmp_path)) == 1
    eu.sair(tmp_path)
    assert outro.outros(tmp_path) == []
    eu.sair(tmp_path)  # sem arquivo: não quebra
    # depois de sair, o "desde" recomeça
    relogio.avancar(300)
    eu.sinalizar(tmp_path)
    assert outro.outros(tmp_path)[0].desde == "2026-10-22T14:37:00"


def test_nome_do_arquivo_higienizado(tmp_path, relogio):
    svc = _svc("dom\\joão", "PC:1", relogio)
    svc.sinalizar(tmp_path)
    nomes = [f.name for f in (tmp_path / ".orbit" / "presenca").iterdir()]
    assert nomes == ["dom-joão@PC-1.json"]
    assert _svc("ana", "PC2", relogio).outros(tmp_path)[0].usuario == "dom\\joão"


def test_presenca_corrompida_ignorada(tmp_path, relogio):
    pasta = tmp_path / ".orbit" / "presenca"
    pasta.mkdir(parents=True)
    (pasta / "lixo@PC9.json").write_text("{não é json", encoding="utf-8")
    (pasta / "lista@PC9.json").write_text("[1, 2]", encoding="utf-8")
    (pasta / "sem_data@PC9.json").write_text(
        json.dumps({"usuario": "x", "computador": "y", "desde": "ontem",
                    "ultimo_sinal": "nunca"}), encoding="utf-8")
    _svc("fulano", "PC-XYZ", relogio).sinalizar(tmp_path)
    eu = _svc("thiago", "PC1", relogio)
    assert [p.usuario for p in eu.outros(tmp_path)] == ["fulano"]
    # a própria presença corrompida é reescrita
    (pasta / "thiago@PC1.json").write_text("xx", encoding="utf-8")
    eu.sinalizar(tmp_path)
    assert json.loads((pasta / "thiago@PC1.json").read_text(encoding="utf-8"))["desde"] \
        == "2026-10-22T14:32:00"


def test_outros_sem_pasta(tmp_path, relogio):
    assert _svc("thiago", "PC1", relogio).outros(tmp_path) == []


# ---------- travas ----------

def test_trava_dupla_lanca_lock_held(tmp_path, relogio):
    a = _svc("fulano", "PC-XYZ", relogio)
    b = _svc("thiago", "PC1", relogio)
    lock = a.travar(tmp_path, TIPO)
    assert lock == tmp_path / ".orbit" / "travas" / f"{TIPO}.lock"
    dados = json.loads(lock.read_text(encoding="utf-8"))
    assert (dados["usuario"], dados["computador"], dados["desde"]) == (
        "fulano", "PC-XYZ", "2026-10-22T14:32:00")
    relogio.avancar(120)
    with pytest.raises(LockHeld) as e:
        b.travar(tmp_path, TIPO)
    assert str(e.value) == ("fulano (PC-XYZ) está enviando uma revisão deste documento "
                            "desde 14:32.")
    assert e.value.tipo_id == TIPO
    assert e.value.abandonada is False
    # a própria pessoa também não consegue travar de novo (dois uploads ao mesmo tempo)
    with pytest.raises(LockHeld):
        a.travar(tmp_path, TIPO)
    # outro tipo é independente
    b.liberar(b.travar(tmp_path, TIPO2))
    a.liberar(lock)
    assert not lock.exists()
    b.liberar(b.travar(tmp_path, TIPO))
    a.liberar(lock)  # já liberada: não quebra


def test_trava_abandonada(tmp_path, relogio):
    a = _svc("fulano", "PC-XYZ", relogio)
    lock = a.travar(tmp_path, TIPO)
    relogio.avancar(600)
    assert a.trava_abandonada(lock) is False
    relogio.avancar(1)
    assert a.trava_abandonada(lock) is True
    assert a.trava_abandonada(lock, max_idade_s=3600) is False
    with pytest.raises(LockHeld) as e:
        _svc("thiago", "PC1", relogio).travar(tmp_path, TIPO)
    assert e.value.abandonada is True
    a.liberar(lock)
    assert a.trava_abandonada(lock) is False  # trava inexistente não está abandonada


def test_trava_ilegivel_usa_mtime(tmp_path, relogio):
    pasta = tmp_path / ".orbit" / "travas"
    pasta.mkdir(parents=True)
    lock = pasta / f"{TIPO}.lock"
    lock.write_text("", encoding="utf-8")
    t = datetime(2026, 10, 22, 9, 5, 0)
    os.utime(lock, (t.timestamp(), t.timestamp()))
    svc = _svc("thiago", "PC1", relogio)
    with pytest.raises(LockHeld) as e:
        svc.travar(tmp_path, TIPO)
    assert str(e.value) == ("desconhecido (desconhecido) está enviando uma revisão deste "
                            "documento desde 09:05.")
    assert svc.trava_abandonada(lock) is True


# ---------- integração com upload e importação ----------

@pytest.fixture
def ctx(repo, tmp_path, relogio):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora Linha 2")
    origem = tmp_path / "origem"
    origem.mkdir()
    presenca = PresenceService(repo.identity, agora=relogio)
    return p, origem, presenca, repo.container_path(p)


def _arq(pasta: Path, nome: str, conteudo: str = "x") -> Path:
    f = pasta / nome
    f.write_text(conteudo, encoding="utf-8")
    return f


def _travas(cdir: Path) -> list[str]:
    pasta = cdir / ".orbit" / "travas"
    return sorted(f.name for f in pasta.iterdir()) if pasta.is_dir() else []


def test_upload_libera_trava_mesmo_com_erro(repo, ctx):
    p, origem, presenca, cdir = ctx
    svc = RevisionService(repo, presence=presenca)
    # erro de validação
    with pytest.raises(OrbitError):
        svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf"), [], "Status inexistente", "m")
    assert _travas(cdir) == []
    # erro no meio da transação (arquivo em uso ao copiar)
    src = _arq(origem, "b.pdf")
    import orbit.core.revisions as rv
    original = rv.shutil.copy2

    def falha(*a, **k):
        raise PermissionError("em uso")
    rv.shutil.copy2 = falha
    try:
        with pytest.raises(OrbitError):
            svc.enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "m")
    finally:
        rv.shutil.copy2 = original
    assert _travas(cdir) == []
    # sucesso também libera
    svc.enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "m")
    assert _travas(cdir) == []


def test_upload_bloqueado_por_trava(repo, ctx, relogio):
    p, origem, presenca, cdir = ctx
    outro = PresenceService(Identity("fulano", "PC-XYZ"), agora=relogio)
    lock = outro.travar(cdir, TIPO)
    svc = RevisionService(repo, presence=presenca)
    with pytest.raises(LockHeld):
        svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf"), [], "Em elaboração", "m")
    assert repo.load_container(p.id).documentos[TIPO].revisoes == []
    assert lock.exists()  # a trava do outro continua lá
    # sem presence: comportamento antigo (não olha travas)
    RevisionService(repo).enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf"), [],
                                         "Em elaboração", "m")


def test_importacao_trava_todos_os_tipos(repo, ctx, relogio):
    p, origem, presenca, cdir = ctx
    svc = ImportService(repo, presence=presenca)
    itens = [ItemImportacao(_arq(origem, "a.pdf"), TIPO, 0, "Em elaboração"),
             ItemImportacao(_arq(origem, "b.pdf"), TIPO2, 0, "Em elaboração")]
    outro = PresenceService(Identity("fulano", "PC-XYZ"), agora=relogio)
    lock = outro.travar(cdir, TIPO2)
    with pytest.raises(LockHeld):
        svc.importar(p.id, itens)
    assert _travas(cdir) == [f"{TIPO2}.lock"]  # a de TIPO foi solta
    assert repo.load_container(p.id).documentos[TIPO].revisoes == []
    outro.liberar(lock)
    # erro de validação também libera
    with pytest.raises(OrbitError):
        svc.importar(p.id, [ItemImportacao(origem / "nao_existe.pdf", TIPO, 0,
                                           "Em elaboração")])
    assert _travas(cdir) == []
    svc.importar(p.id, itens)
    assert _travas(cdir) == []
    assert repo.load_container(p.id).documentos[TIPO2].atual.numero == 0


# ---------- dono da trava, retentativas e corridas (fix round 1) ----------

import orbit.core.presence as presence_mod  # noqa: E402


@pytest.fixture
def sem_espera(monkeypatch):
    monkeypatch.setattr(presence_mod, "_ESPERA_S", 0)


def _token(lock: Path) -> str:
    return json.loads(lock.read_text(encoding="utf-8"))["token"]


def test_liberar_nao_apaga_trava_de_outro_dono(tmp_path, relogio):
    a = _svc("fulano", "PC-XYZ", relogio)
    b = _svc("thiago", "PC1", relogio)
    trava_a = a.travar(tmp_path, TIPO)
    assert _token(trava_a) == trava_a.token
    relogio.avancar(601)  # o upload de A demorou: B libera à força e trava de novo
    assert b.liberar_abandonada(trava_a) is True
    trava_b = b.travar(tmp_path, TIPO)
    assert a.liberar(trava_a) is False  # o finally de A não apaga a trava de B
    assert trava_b.exists() and _token(trava_b) == trava_b.token
    assert [f.name for f in trava_b.parent.iterdir()] == [f"{TIPO}.lock"]
    assert b.liberar(trava_b) is True
    assert not trava_b.exists()
    with pytest.raises(TypeError):
        b.liberar(Path(trava_b))  # sem token não libera


def test_liberar_abandonada_so_se_abandonada(tmp_path, relogio):
    a = _svc("fulano", "PC-XYZ", relogio)
    trava = a.travar(tmp_path, TIPO)
    relogio.avancar(600)
    assert a.liberar_abandonada(trava) is False
    assert trava.exists()
    relogio.avancar(1)
    assert a.liberar_abandonada(trava) is True
    assert not trava.exists()
    assert a.liberar_abandonada(trava) is True  # já não existe


def test_liberar_tenta_de_novo_se_arquivo_em_uso(tmp_path, relogio, monkeypatch, sem_espera):
    a = _svc("fulano", "PC-XYZ", relogio)
    trava = a.travar(tmp_path, TIPO)
    real, chamadas = os.rename, []

    def rename(origem, destino):
        chamadas.append(origem)
        if len(chamadas) <= 2:
            raise PermissionError(32, "em uso")
        return real(origem, destino)
    monkeypatch.setattr(presence_mod.os, "rename", rename)
    assert a.liberar(trava) is True
    assert len(chamadas) == 3
    assert not trava.exists()


def test_liberar_falha_final_e_registrada(tmp_path, relogio, monkeypatch, sem_espera):
    erros = []
    a = PresenceService(Identity("fulano", "PC-XYZ"), agora=relogio, registrar=erros.append)
    trava = a.travar(tmp_path, TIPO)

    def rename(origem, destino):
        raise PermissionError(32, "em uso")
    monkeypatch.setattr(presence_mod.os, "rename", rename)
    with pytest.raises(OrbitError, match="Não foi possível liberar a trava"):
        a.liberar(trava)
    falhas = a.liberar_varios([trava])  # não lança: só devolve e registra
    assert len(falhas) == 1 and f"{TIPO}.lock" in falhas[0]
    assert len(erros) == 1 and isinstance(erros[0], OrbitError)
    monkeypatch.undo()
    assert trava.exists()


@pytest.mark.skipif(os.name != "nt", reason="bloqueio de exclusão é do Windows")
def test_leitor_com_arquivo_aberto_nao_impede_liberar(tmp_path, relogio, monkeypatch):
    import threading
    monkeypatch.setattr(presence_mod, "_ESPERA_S", 0.05)
    a = _svc("fulano", "PC-XYZ", relogio)
    trava = a.travar(tmp_path, TIPO)
    # a leitura do Orbit compartilha exclusão: não atrapalha o rename
    assert a.trava_abandonada(trava) is False
    # um open() comum (sem FILE_SHARE_DELETE) bloqueia; a retentativa espera ele fechar
    f = open(trava, "rb")
    threading.Timer(0.12, f.close).start()
    assert a.liberar(trava) is True
    assert not trava.exists()


def test_travar_tenta_de_novo_se_trava_sumiu(tmp_path, relogio, monkeypatch):
    lock = PresenceService.caminho_trava(tmp_path, TIPO)
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")
    original = PresenceService._ler_trava

    def some(caminho):  # a trava some entre o FileExistsError e a leitura
        Path(caminho).unlink()
        return None
    monkeypatch.setattr(PresenceService, "_ler_trava", staticmethod(some))
    trava = _svc("thiago", "PC1", relogio).travar(tmp_path, TIPO)
    monkeypatch.setattr(PresenceService, "_ler_trava", staticmethod(original))
    assert _token(trava) == trava.token


def test_travar_erro_de_disco_vira_orbit_error(tmp_path, relogio):
    (tmp_path / ".orbit").write_text("sou um arquivo", encoding="utf-8")
    with pytest.raises(OrbitError, match="Não foi possível criar a pasta de travas"):
        _svc("thiago", "PC1", relogio).travar(tmp_path, TIPO)


def test_upload_com_falha_ao_liberar_registra_e_devolve_revisao(repo, ctx, monkeypatch):
    p, origem, _, cdir = ctx
    erros = []
    presenca = PresenceService(repo.identity, registrar=erros.append)

    def falha(self, lock, aceitar):
        raise OrbitError("Não foi possível liberar a trava x: em uso")
    monkeypatch.setattr(PresenceService, "_remover_se", falha)
    rev = RevisionService(repo, presence=presenca).enviar_revisao(
        p.id, TIPO, _arq(origem, "a.pdf"), [], "Em elaboração", "m")
    assert rev.numero == 0
    assert [str(e) for e in erros] == ["Não foi possível liberar a trava x: em uso"]
    assert PresenceService.caminho_trava(cdir, TIPO).exists()  # ficou presa (10 min)
    # e a falha ao liberar não esconde o erro original da operação
    with pytest.raises(OrbitError, match="Status inválido"):
        RevisionService(repo, presence=presenca).enviar_revisao(
            p.id, TIPO2, _arq(origem, "b.pdf"), [], "Nada", "m")
    assert len(erros) == 2


def test_renovar_atualiza_a_hora_e_respeita_o_dono(tmp_path):
    from datetime import datetime, timedelta
    from orbit.core.identity import Identity
    from orbit.core.presence import PresenceService
    t = [datetime(2026, 10, 23, 8, 0, 0)]
    svc = PresenceService(Identity("thiago", "PC1"), agora=lambda: t[0])
    trava = svc.travar(tmp_path, "_sincronizacao")
    t[0] += timedelta(minutes=9)
    assert svc.renovar(trava) is True
    assert svc._ler_trava(trava).desde == t[0]
    t[0] += timedelta(minutes=9)
    assert not svc.trava_abandonada(trava)  # 9 min desde a renovação
    outra = type(trava)(trava)
    outra.token = "x" * 32
    assert svc.renovar(outra) is False
