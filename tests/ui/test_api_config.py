import urllib.request

import pytest

from orbit.core.config import UserSettings, load_shared_config, save_user_settings
from orbit.ui.api import Api


class JanelaFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def create_file_dialog(self, tipo, *args, **kwargs):
        self.chamadas.append((tipo, kwargs))
        return self.resposta


@pytest.fixture
def cfg(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings, log = tmp_path / "appdata" / "settings.json", tmp_path / "appdata" / "orbit.log"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    api = Api(settings_path=settings, log_path=log)
    c = api.criar_cliente({"nome": "Alfa"})["dados"]
    p = api.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    origem = tmp_path / "origem"
    origem.mkdir()
    yield api, base, p["id"], origem
    api._fileserver.stop()


def _tipos(api):
    return api.get_config()["dados"]["tipos"]


def _enviar(api, pid, tipo, origem, status="Em elaboração"):
    f = origem / f"{tipo}.pdf"
    f.write_text("x", encoding="utf-8")
    r = api.enviar_revisao(pid, tipo, str(f), [], status, "m", None)
    assert r["ok"] is True, r


# --- tipos -----------------------------------------------------------------

def test_renomear_e_desativar_tipo_preserva_id_e_pasta(cfg):
    api, base, pid, _ = cfg
    tipos = _tipos(api)
    tipos[0]["nome"] = "Esquema Elétrico"
    tipos[5]["ativo"] = False
    r = api.salvar_tipos(tipos)
    assert r["ok"] is True, r
    novos = _tipos(api)
    assert novos[0]["id"] == "diagrama_eletrico"
    assert novos[0]["nome"] == "Esquema Elétrico"
    assert novos[0]["pasta"] == "Diagrama Elétrico"
    assert novos[5]["ativo"] is False
    assert load_shared_config(base).tipos[0].nome == "Esquema Elétrico"
    painel = api.obter_painel(pid)["dados"]
    assert painel["documentos"][0]["nome"] == "Esquema Elétrico"


def test_adicionar_tipo_novo_aparece_em_projeto_existente_e_novo(cfg):
    api, base, pid, _ = cfg
    tipos = _tipos(api) + [{"id": None, "nome": "Lista de Cabos", "ativo": True}]
    assert api.salvar_tipos(tipos)["ok"] is True
    assert _tipos(api)[-1]["id"] == "lista_de_cabos"
    existente = api.obter_painel(pid)["dados"]
    assert "lista_de_cabos" in [d["tipo_id"] for d in existente["documentos"]]
    c = api.listar_clientes()["dados"][0]["id"]
    novo = api.criar_projeto(c, {"codigo": "P-2", "nome": "Outro"})["dados"]
    assert "lista_de_cabos" in [d["tipo_id"]
                                for d in api.obter_painel(novo["id"])["dados"]["documentos"]]


def test_desativado_some_de_projeto_novo_e_fica_em_projeto_com_revisao(cfg):
    api, base, pid, origem = cfg
    _enviar(api, pid, "consumo_pneumatico", origem)
    tipos = _tipos(api)
    for t in tipos:
        if t["id"] == "consumo_pneumatico":
            t["ativo"] = False
    assert api.salvar_tipos(tipos)["ok"] is True
    c = api.listar_clientes()["dados"][0]["id"]
    novo = api.criar_projeto(c, {"codigo": "P-2", "nome": "Outro"})["dados"]
    ids_novo = [d["tipo_id"] for d in api.obter_painel(novo["id"])["dados"]["documentos"]]
    assert "consumo_pneumatico" not in ids_novo
    ids_antigo = [d["tipo_id"] for d in api.obter_painel(pid)["dados"]["documentos"]]
    assert "consumo_pneumatico" in ids_antigo


def test_tipo_ausente_da_lista_e_rejeitado_sem_remover(cfg):
    api, base, *_ = cfg
    r = api.salvar_tipos(_tipos(api)[1:])
    assert r["ok"] is False and "remo" in r["erro"].lower()
    assert len(_tipos(api)) == 9


@pytest.mark.parametrize("mudar", [
    lambda t: t.__setitem__(0, {**t[0], "nome": "  "}),
    lambda t: t.__setitem__(0, {**t[0], "nome": 5}),
    lambda t: t.__setitem__(0, {**t[0], "ativo": "sim"}),
    lambda t: t.__setitem__(0, {**t[0], "id": "inventado"}),
    lambda t: t.append(dict(t[0])),
    lambda t: t.__setitem__(1, {**t[1], "nome": "diagrama elétrico"}),
    lambda t: t.append({"id": None, "nome": "diagrama elétrico", "ativo": True}),
    lambda t: t.append("texto"),
])
def test_tipos_invalidos_nao_alteram_nada(cfg, mudar):
    api, base, *_ = cfg
    antes = _tipos(api)
    tipos = _tipos(api)
    mudar(tipos)
    assert api.salvar_tipos(tipos)["ok"] is False
    assert _tipos(api) == antes
    assert load_shared_config(base).tipos[0].nome == antes[0]["nome"]


def test_salvar_tipos_exige_lista(cfg):
    api, *_ = cfg
    assert api.salvar_tipos("x")["ok"] is False
    assert api.salvar_tipos(None)["ok"] is False


# --- status ----------------------------------------------------------------

def test_remover_status_em_uso_bloqueia(cfg):
    api, base, pid, origem = cfg
    _enviar(api, pid, "diagrama_eletrico", origem, status="As Built")
    status = [s for s in api.get_config()["dados"]["status"] if s != "As Built"]
    r = api.salvar_status(status)
    assert r["ok"] is False
    assert "As Built" in r["erro"] and "Esteira" in r["erro"]
    assert "Diagrama Elétrico" in r["erro"]
    assert "As Built" in api.get_config()["dados"]["status"]
    assert "As Built" in load_shared_config(base).status


def test_renomear_status_em_uso_bloqueia(cfg):
    api, base, pid, origem = cfg
    _enviar(api, pid, "diagrama_eletrico", origem, status="Aprovado")
    status = ["Aprovada" if s == "Aprovado" else s for s in api.get_config()["dados"]["status"]]
    assert api.salvar_status(status)["ok"] is False


def test_status_so_em_revisao_arquivada_pode_sair(cfg):
    api, base, pid, origem = cfg
    _enviar(api, pid, "diagrama_eletrico", origem, status="As Built")
    f = origem / "novo.pdf"
    f.write_text("y", encoding="utf-8")
    assert api.enviar_revisao(pid, "diagrama_eletrico", str(f), [], "Aprovado", "m",
                              None)["ok"] is True
    status = [s for s in api.get_config()["dados"]["status"] if s != "As Built"]
    assert api.salvar_status(status)["ok"] is True
    assert "As Built" not in api.get_config()["dados"]["status"]


def test_status_sem_uso_pode_ser_renomeado_adicionado_e_reordenado(cfg):
    api, base, *_ = cfg
    r = api.salvar_status(["Aprovado", "  Em revisão  ", "Em elaboração"])
    assert r["ok"] is True, r
    assert api.get_config()["dados"]["status"] == ["Aprovado", "Em revisão", "Em elaboração"]
    assert load_shared_config(base).status == ["Aprovado", "Em revisão", "Em elaboração"]


@pytest.mark.parametrize("status", [[], "x", None, ["A", ""], ["A", "a"], ["A", 3], ["  "]])
def test_status_invalidos(cfg, status):
    api, *_ = cfg
    antes = api.get_config()["dados"]["status"]
    assert api.salvar_status(status)["ok"] is False
    assert api.get_config()["dados"]["status"] == antes


# --- logo ------------------------------------------------------------------

def _logo(tmp_path, nome, conteudo=b"img"):
    f = tmp_path / nome
    f.write_bytes(conteudo)
    return f


def test_logo_copia_e_serve(cfg, tmp_path):
    api, base, *_ = cfg
    f = _logo(tmp_path, "empresa.PNG", b"\x89PNGdados")
    api.definir_janela(JanelaFalsa((str(f),)))
    r = api.definir_logo_empresa()
    assert r["ok"] is True, r
    assert f.exists()  # copiou, não moveu
    assert (base / ".orbit" / "logo-empresa.png").read_bytes() == b"\x89PNGdados"
    assert load_shared_config(base).logo_empresa == "logo-empresa.png"
    url = api.get_config()["dados"]["logo_url"]
    assert url == r["dados"]["logo_url"]
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.read() == b"\x89PNGdados"


def test_logo_troca_de_extensao_remove_a_antiga(cfg, tmp_path):
    api, base, *_ = cfg
    api.definir_janela(JanelaFalsa((str(_logo(tmp_path, "a.png")),)))
    assert api.definir_logo_empresa()["ok"] is True
    api.definir_janela(JanelaFalsa((str(_logo(tmp_path, "b.svg", b"<svg/>")),)))
    assert api.definir_logo_empresa()["ok"] is True
    assert sorted(p.name for p in (base / ".orbit").glob("logo-empresa.*")) == ["logo-empresa.svg"]
    assert load_shared_config(base).logo_empresa == "logo-empresa.svg"


def test_logo_cancelado_e_extensao_invalida(cfg, tmp_path):
    api, base, *_ = cfg
    api.definir_janela(JanelaFalsa(None))
    assert api.definir_logo_empresa() == {"ok": True, "dados": None}
    api.definir_janela(JanelaFalsa((str(_logo(tmp_path, "x.exe")),)))
    r = api.definir_logo_empresa()
    assert r["ok"] is False and ".png" in r["erro"]
    assert list((base / ".orbit").glob("logo-empresa.*")) == []
    assert api.get_config()["dados"]["logo_url"] is None


def test_logo_mesma_imagem_escolhida_de_novo(cfg, tmp_path):
    api, base, *_ = cfg
    api.definir_janela(JanelaFalsa((str(_logo(tmp_path, "a.png", b"1")),)))
    assert api.definir_logo_empresa()["ok"] is True
    api.definir_janela(JanelaFalsa((str(base / ".orbit" / "logo-empresa.png"),)))
    assert api.definir_logo_empresa()["ok"] is True
    assert (base / ".orbit" / "logo-empresa.png").read_bytes() == b"1"


def test_trocar_pasta_base_usa_o_mesmo_caminho_seguro(cfg, tmp_path):
    api, base, *_ = cfg
    nova = tmp_path / "Outra"
    nova.mkdir()
    api.definir_janela(JanelaFalsa((str(nova),)))
    r = api.trocar_pasta_base()
    assert r["ok"] is True and r["dados"]["pasta_base"] == str(nova)
    assert (nova / ".orbit" / "config.json").exists()
