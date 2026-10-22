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


# --- clientes e projetos (Tarefa 10) ---------------------------------------

@pytest.fixture
def api_base(caminhos, tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    save_user_settings(UserSettings(str(base), "escuro"), caminhos[0])
    return _api(caminhos), base


def _cliente(api, nome, **extra):
    r = api.criar_cliente({"nome": nome, **extra})
    assert r["ok"] is True, r
    return r["dados"]


def _projeto(api, cliente_id, codigo, nome, **extra):
    r = api.criar_projeto(cliente_id, {"codigo": codigo, "nome": nome, **extra})
    assert r["ok"] is True, r
    return r["dados"]


def test_busca_por_projeto_encontra_cliente(api_base):
    api, _ = api_base
    c1 = _cliente(api, "Alfa Ltda")
    _cliente(api, "Beta SA")
    _projeto(api, c1["id"], "P-001", "Esteira Transportadora")
    r = api.listar_clientes("esteira")
    assert [c["nome"] for c in r["dados"]] == ["Alfa Ltda"]
    assert len(api.listar_clientes("")["dados"]) == 2


def test_busca_ignora_acento(api_base):
    api, _ = api_base
    _cliente(api, "Automação Industrial")
    _cliente(api, "Outro")
    assert [c["nome"] for c in api.listar_clientes("automacao")["dados"]] == ["Automação Industrial"]
    assert [c["nome"] for c in api.listar_clientes("AUTOMAÇÃO")["dados"]] == ["Automação Industrial"]


def test_listar_clientes_resumo(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    _projeto(api, c["id"], "P-1", "Um")
    p2 = _projeto(api, c["id"], "P-2", "Dois")
    assert api.atualizar_projeto(p2["id"], {"situacao": "concluido"})["ok"] is True
    item = api.listar_clientes()["dados"][0]
    assert item["projetos_ativos"] == 1
    assert item["ultima_emissao"] is None
    assert set(item) == {"id", "nome", "projetos_ativos", "ultima_emissao"}


def test_obter_cliente_e_atualizar_nao_renomeia_pasta(api_base):
    api, base = api_base
    c = _cliente(api, "Alfa", contatos=[{"nome": "Ana", "email": "a@x.com"}])
    _projeto(api, c["id"], "P-1", "Um")
    r = api.atualizar_cliente(c["id"], {"nome": "Alfa Novo", "contatos": []})
    assert r["ok"] is True
    d = api.obter_cliente(c["id"])["dados"]
    assert d["cliente"]["nome"] == "Alfa Novo" and d["cliente"]["contatos"] == []
    assert d["projetos"][0]["codigo"] == "P-1" and d["projetos"][0]["erro"] is None
    assert (base / "Clientes" / "Alfa" / "P-1 - Um").is_dir()
    assert not (base / "Clientes" / "Alfa Novo").exists()


def test_projeto_com_json_corrompido_aparece_com_erro(api_base):
    api, base = api_base
    c = _cliente(api, "Alfa")
    _projeto(api, c["id"], "P-1", "Um")
    (base / "Clientes" / "Alfa" / "P-1 - Um" / "projeto.json").write_text("{", encoding="utf-8")
    d = api.obter_cliente(c["id"])["dados"]
    assert d["projetos"][0]["erro"]
    assert api.listar_clientes()["ok"] is True


def test_atualizar_projeto_com_contatos(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    p = _projeto(api, c["id"], "P-1", "Um")
    r = api.atualizar_projeto(p["id"], {"nome": "Um B", "pedido": "99",
                                        "contatos": [{"nome": "Bia", "email": "b@x.com"}]})
    assert r["ok"] is True
    proj = api.obter_cliente(c["id"])["dados"]["projetos"][0]
    assert proj["nome"] == "Um B"
    carregado = api._repo.load_container(p["id"])
    assert [(x.nome, x.email) for x in carregado.contatos] == [("Bia", "b@x.com")]
    assert carregado.pedido == "99"


def test_criar_projeto_cliente_inexistente_da_erro(api_base):
    api, _ = api_base
    assert api.criar_projeto("nao-existe", {"codigo": "1", "nome": "x"})["ok"] is False


def test_clientes_sem_base_da_erro(caminhos):
    r = _api(caminhos).listar_clientes()
    assert r["ok"] is False and "pasta base" in r["erro"].lower()


def test_criar_projeto_situacao_invalida_nao_cria_nada(api_base):
    api, base = api_base
    c = _cliente(api, "Alfa")
    r = api.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Um", "situacao": "xyz"})
    assert r["ok"] is False and "situação" in r["erro"].lower()
    assert list((base / "Clientes" / "Alfa").glob("*/projeto.json")) == []
    assert [p.name for p in (base / "Clientes" / "Alfa").iterdir()] == ["cliente.json"]


def test_criar_projeto_concluido_persiste(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    p = _projeto(api, c["id"], "P-1", "Um", situacao="concluido")
    assert p["situacao"] == "concluido"
    assert api._repo.load_container(p["id"]).situacao == "concluido"


def test_atualizar_projeto_situacao_invalida(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    p = _projeto(api, c["id"], "P-1", "Um")
    assert api.atualizar_projeto(p["id"], {"situacao": "xyz"})["ok"] is False


def test_atualizar_projeto_strip_e_vazio(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    p = _projeto(api, c["id"], "P-1", "Um")
    assert api.atualizar_projeto(p["id"], {"nome": "  Novo  ", "responsavel": " Zé "})["ok"] is True
    cont = api._repo.load_container(p["id"])
    assert cont.nome == "Novo" and cont.responsavel == "Zé"
    for campo in ("codigo", "nome"):
        r = api.atualizar_projeto(p["id"], {campo: "   "})
        assert r["ok"] is False and "informe" in r["erro"].lower()
    assert api._repo.load_container(p["id"]).nome == "Novo"


def test_atualizar_cliente_strip_cnpj(api_base):
    api, _ = api_base
    c = _cliente(api, "Alfa")
    api.atualizar_cliente(c["id"], {"cnpj": " 12.345 "})
    assert api.obter_cliente(c["id"])["dados"]["cliente"]["cnpj"] == "12.345"


def test_testar_conexao_sem_base_devolve_lista_vazia(caminhos):
    assert _api(caminhos).testar_conexao() == {"ok": True, "dados": []}


def test_testar_conexao_com_base(caminhos, tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    save_user_settings(UserSettings(pasta_base=str(base)), caminhos[0])
    api = _api(caminhos)
    r = api.testar_conexao()
    assert r["ok"] and len(r["dados"]) == 1
    d = r["dados"][0]
    assert d["pasta"] == str(base) and d["ok"] is True and d["escrita"] is True
    api.ao_fechar_janela()


def test_testar_conexao_base_configurada_mas_nao_abriu(caminhos, tmp_path):
    save_user_settings(UserSettings(pasta_base=str(tmp_path / "sumiu")), caminhos[0])
    api = _api(caminhos)
    assert api.get_settings()["dados"]["base_ok"] is False
    r = api.testar_conexao()
    assert r["ok"] and len(r["dados"]) == 1
    assert r["dados"][0]["ok"] is False and r["dados"][0]["erro"]


def test_reabrir_base_sucesso_e_falha(caminhos, tmp_path):
    base = tmp_path / "base"
    save_user_settings(UserSettings(pasta_base=str(base)), caminhos[0])
    api = _api(caminhos)
    falha = api.reabrir_base()
    assert falha["ok"] is False and "base" in falha["erro"]
    assert api.get_settings()["dados"]["erro_base"]
    base.mkdir()
    ok = api.reabrir_base()
    assert ok["ok"] and ok["dados"]["base_ok"] is True and ok["dados"]["erro_base"] is None
    api.ao_fechar_janela()


def test_reabrir_base_sem_pasta_configurada(caminhos):
    assert _api(caminhos).reabrir_base()["ok"] is False


def test_abrir_base_com_rede_travada_nao_bloqueia(caminhos, tmp_path, monkeypatch):
    import time
    from orbit.core import connection
    monkeypatch.setattr(connection.Path, "is_dir", lambda self: time.sleep(3) or True)
    save_user_settings(UserSettings(pasta_base=str(tmp_path)), caminhos[0])
    t0 = time.perf_counter()
    api = Api(settings_path=caminhos[0], log_path=caminhos[1], timeout_conexao=0.1)
    assert time.perf_counter() - t0 < 2
    assert "Tempo esgotado" in api.get_settings()["dados"]["erro_base"]


def test_criar_projeto_concluido_grava_uma_vez(api_base, monkeypatch):
    api, _ = api_base
    c = _cliente(api, "Alfa")

    def proibido(*a, **k):
        raise AssertionError("não deveria regravar")
    monkeypatch.setattr(api._repo, "update_dados", proibido)
    p = _projeto(api, c["id"], "P-1", "Um", situacao="concluido")
    assert api._repo.load_container(p["id"]).situacao == "concluido"


def test_falha_de_gravacao_vira_mensagem_clara(api_base, monkeypatch):
    import os
    from orbit.core import jsonstore
    api, _ = api_base
    c = _cliente(api, "Alfa")
    p = _projeto(api, c["id"], "P-1", "Um")

    def em_uso(a, b):
        raise PermissionError(32, "em uso")
    monkeypatch.setattr(jsonstore, "_ESPERA_S", 0)
    monkeypatch.setattr(jsonstore.os, "replace", em_uso)
    r = api.atualizar_projeto(p["id"], {"nome": "Dois"})
    assert r["ok"] is False and "Erro inesperado" not in r["erro"]
    assert "projeto.json" in r["erro"]
