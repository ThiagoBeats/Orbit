import json

import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.ui.api import Api


@pytest.fixture
def api(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    a = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    yield a
    a._fileserver.stop()


def test_ancoras_ficam_junto_das_preferencias(api, tmp_path):
    api.criar_cliente({"nome": "Alfa"})
    assert (tmp_path / "appdata" / "ancoras.json").is_file()


def test_api_ler_log_filtra_por_acao(api):
    c = api.criar_cliente({"nome": "Alfa"})["dados"]
    api.criar_projeto(c["id"], {"codigo": "1", "nome": "Esteira"})
    r = api.ler_log({"acao": "projeto_criado"})
    assert r["ok"], r
    linhas = r["dados"]["linhas"]
    assert [l["acao"] for l in linhas] == ["projeto_criado"]
    assert r["dados"]["integridade"]["integro"] is True


def test_api_ler_log_filtra_por_texto_e_usuario(api):
    api.criar_cliente({"nome": "Alfa"})
    api.criar_cliente({"nome": "Beta"})
    assert len(api.ler_log({"texto": "beta"})["dados"]["linhas"]) == 1
    assert api.ler_log({"usuario": "ninguem"})["dados"]["linhas"] == []


def test_configuracao_alterada_vai_para_o_log(api):
    status = api.get_config()["dados"]["status"] + ["Revisar"]
    assert api.salvar_status(status)["ok"]
    acoes = [l["acao"] for l in api.ler_log({})["dados"]["linhas"]]
    assert "configuracao_alterada" in acoes


def test_api_verificar_log_alerta(api):
    api.criar_cliente({"nome": "Alfa"})
    caminho = api._log.caminho
    d = json.loads(caminho.read_text(encoding="utf-8").splitlines()[0])
    d["detalhes"]["cliente_nome"] = "Forjado"
    caminho.write_text(json.dumps(d, ensure_ascii=False) + "\n", encoding="utf-8")
    r = api.verificar_log()
    assert r["ok"] and r["dados"]["integro"] is False
    assert r["dados"]["problemas"][0]["a_partir_de_n"] == 1
    # o alerta foi registrado e não se repete
    assert api.verificar_log()["dados"]["integro"] is True
    acoes = [l["acao"] for l in api.ler_log({})["dados"]["linhas"]]
    assert acoes.count("adulteracao_detectada") == 1
