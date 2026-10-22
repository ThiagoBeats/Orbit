import json

import pytest

from orbit.core.config import UserSettings, load_user_settings, save_user_settings
from orbit.core.errors import OrbitError
from orbit.ui.api import Api


class JanelaFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def create_file_dialog(self, tipo, *args, **kwargs):
        self.chamadas.append(tipo)
        return self.resposta


@pytest.fixture
def caminhos(tmp_path):
    return tmp_path / "appdata" / "settings.json", tmp_path / "appdata" / "orbit.log"


def _api(caminhos, janela=None):
    settings, log = caminhos
    api = Api(settings_path=settings, log_path=log)
    if janela:
        api.definir_janela(janela)
    return api


def test_api_erro_vira_ok_false(caminhos):
    api = _api(caminhos)

    def falha():
        raise OrbitError("x")

    assert api._chamar(falha) == {"ok": False, "erro": "x"}


def test_api_sucesso_vira_ok_true(caminhos):
    api = _api(caminhos)
    assert api._chamar(lambda a, b: a + b, 2, 3) == {"ok": True, "dados": 5}


def test_api_erro_inesperado_vai_para_o_log(caminhos):
    api = _api(caminhos)

    def quebra():
        raise ValueError("detalhe interno")

    r = api._chamar(quebra)
    assert r == {"ok": False, "erro": "Erro inesperado: ValueError. Veja o log."}
    log = caminhos[1].read_text(encoding="utf-8")
    assert "ValueError" in log and "detalhe interno" in log


def test_get_settings_sem_pasta_base(caminhos):
    r = _api(caminhos).get_settings()
    assert r["ok"] is True
    assert r["dados"]["pasta_base"] is None
    assert r["dados"]["tema"] == "escuro"


def test_get_config_sem_pasta_base_da_erro(caminhos):
    r = _api(caminhos).get_config()
    assert r["ok"] is False
    assert "pasta base" in r["erro"].lower()


def test_escolher_pasta_base_cria_config_e_grava(caminhos, tmp_path):
    pasta = tmp_path / "Projetos"
    pasta.mkdir()
    janela = JanelaFalsa((str(pasta),))
    api = _api(caminhos, janela)
    r = api.escolher_pasta_base()
    assert r["ok"] is True
    assert r["dados"]["pasta_base"] == str(pasta)
    assert (pasta / ".orbit" / "config.json").exists()
    assert load_user_settings(caminhos[0]).pasta_base == str(pasta)
    cfg = api.get_config()
    assert cfg["ok"] is True
    assert cfg["dados"]["status"][0] == "Em elaboração"


def test_escolher_pasta_base_cancelado(caminhos):
    api = _api(caminhos, JanelaFalsa(None))
    assert api.escolher_pasta_base() == {"ok": True, "dados": None}
    assert load_user_settings(caminhos[0]).pasta_base is None


def test_pasta_base_salva_e_carregada_ao_iniciar(caminhos, tmp_path):
    pasta = tmp_path / "Base"
    pasta.mkdir()
    save_user_settings(UserSettings(str(pasta), "claro"), caminhos[0])
    api = _api(caminhos)
    assert api.get_settings()["dados"]["tema"] == "claro"
    assert api.get_config()["ok"] is True


def test_pasta_base_inacessivel_nao_quebra(caminhos, tmp_path):
    save_user_settings(UserSettings(str(tmp_path / "nao_existe"), "escuro"), caminhos[0])
    api = _api(caminhos)
    d = api.get_settings()["dados"]
    assert d["base_ok"] is False
    assert d["erro_base"]


def test_set_tema_persiste(caminhos):
    api = _api(caminhos)
    assert api.set_tema("claro")["ok"] is True
    assert load_user_settings(caminhos[0]).tema == "claro"
    assert _api(caminhos).get_settings()["dados"]["tema"] == "claro"


def test_set_tema_invalido(caminhos):
    r = _api(caminhos).set_tema("roxo")
    assert r["ok"] is False


def test_estado_interno_nao_exposto(caminhos):
    api = _api(caminhos)
    publicos = [n for n in vars(api) if not n.startswith("_")]
    assert publicos == []
    json.dumps(api.get_settings())


def test_definir_janela_nao_exposta_ao_js():
    assert getattr(Api.definir_janela, "_serializable", True) is False


def test_troca_de_base_falhando_mantem_estado_anterior(caminhos, tmp_path, monkeypatch):
    from orbit.ui import api as modulo
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir()
    api = _api(caminhos, JanelaFalsa((str(a),)))
    assert api.escolher_pasta_base()["ok"] is True
    antigo = api._fileserver
    original = modulo.FileServer.start

    def start_falha(self):
        raise OSError("porta indisponível")

    monkeypatch.setattr(modulo.FileServer, "start", start_falha)
    api._janela = JanelaFalsa((str(b),))
    assert api.escolher_pasta_base()["ok"] is False
    monkeypatch.setattr(modulo.FileServer, "start", original)
    assert api._fileserver is antigo and api._base == a
    assert api.get_settings()["dados"]["pasta_base"] == str(a)
    url = antigo.url_para(a / ".orbit" / "config.json")
    import urllib.request
    with urllib.request.urlopen(url, timeout=5) as r:
        assert r.status == 200
