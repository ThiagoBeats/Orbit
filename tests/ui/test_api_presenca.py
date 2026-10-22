"""Api de presença e trava de upload (Tarefa 15)."""
from datetime import datetime, timedelta

import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.core.identity import Identity
from orbit.core.presence import PresenceService
from orbit.ui.api import Api

TIPO = "diagrama_eletrico"
T0 = datetime(2026, 10, 22, 14, 32, 0)


@pytest.fixture
def ctx(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    api = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    relogio = {"t": T0}
    api._agora = lambda: relogio["t"]
    c = api.criar_cliente({"nome": "Alfa"})["dados"]
    p = api.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    cdir = api._repo.container_path(api._repo.load_container(p["id"]))
    origem = tmp_path / "origem"
    origem.mkdir()
    (origem / "a.pdf").write_text("x", encoding="utf-8")
    yield api, p["id"], cdir, relogio, origem
    api._fileserver.stop()


def _fulano(relogio):
    return PresenceService(Identity("fulano", "PC-XYZ"), agora=lambda: relogio["t"])


def _minha_presenca(cdir):
    return [f for f in (cdir / ".orbit" / "presenca").iterdir()
            if not f.name.startswith("fulano@")]


def test_entrar_sinalizar_sair(ctx):
    api, pid, cdir, relogio, _ = ctx
    _fulano(relogio).sinalizar(cdir)
    r = api.entrar_container(pid)
    assert r == {"ok": True, "dados": [{"usuario": "fulano", "computador": "PC-XYZ",
                                        "desde": "2026-10-22T14:32:00", "hora": "14:32"}]}
    assert len(_minha_presenca(cdir)) == 1
    relogio["t"] = T0 + timedelta(seconds=30)
    assert api.sinalizar_container(pid) == {"ok": True, "dados": None}
    assert api.sair_container(pid) == {"ok": True, "dados": None}
    assert _minha_presenca(cdir) == []
    # sinal atrasado depois de sair não recria a presença
    assert api.sinalizar_container(pid)["ok"] is True
    assert _minha_presenca(cdir) == []


def test_fechar_janela_sai_de_todos(ctx):
    api, pid, cdir, relogio, _ = ctx
    api.entrar_container(pid)
    api.ao_fechar_janela()
    assert _minha_presenca(cdir) == []


def test_entrar_container_inexistente(ctx):
    api, *_ = ctx
    r = api.entrar_container("nao-existe")
    assert r["ok"] is False


def test_upload_com_trava_devolve_payload_e_liberar(ctx):
    api, pid, cdir, relogio, origem = ctx
    lock = _fulano(relogio).travar(cdir, TIPO)
    args = (pid, TIPO, str(origem / "a.pdf"), [], "Em elaboração", "m")
    r = api.enviar_revisao(*args)
    assert r == {"ok": False,
                 "erro": "fulano (PC-XYZ) está enviando uma revisão deste documento "
                         "desde 14:32.",
                 "trava": {"container_id": pid, "tipo_id": TIPO, "abandonada": False}}
    # trava recente não pode ser liberada
    r = api.liberar_trava(pid, TIPO)
    assert r["ok"] is False and "ainda está em uso" in r["erro"]
    assert lock.exists()
    # depois de 10 min fica abandonada
    relogio["t"] = T0 + timedelta(seconds=601)
    assert api.enviar_revisao(*args)["trava"]["abandonada"] is True
    assert api.liberar_trava(pid, TIPO) == {"ok": True, "dados": None}
    assert not lock.exists()
    assert api.liberar_trava(pid, TIPO)["ok"] is True  # já liberada
    assert api.enviar_revisao(*args)["ok"] is True
    assert not lock.exists()


def test_importar_com_trava(ctx):
    api, pid, cdir, relogio, origem = ctx
    _fulano(relogio).travar(cdir, TIPO)
    r = api.importar(pid, [{"origem": str(origem / "a.pdf"), "tipo_id": TIPO, "numero": 0,
                            "status": "Em elaboração", "papel": "principal"}])
    assert r["ok"] is False
    assert r["trava"] == {"container_id": pid, "tipo_id": TIPO, "abandonada": False}


def test_liberar_trava_tipo_invalido(ctx):
    api, pid, *_ = ctx
    assert api.liberar_trava(pid, "../x")["ok"] is False
