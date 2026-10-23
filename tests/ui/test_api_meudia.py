import json

import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.ui.api import Api


class JanelaJS:
    def __init__(self):
        self.js = []

    def evaluate_js(self, codigo):
        self.js.append(codigo)

    def create_file_dialog(self, *a, **k):
        return None


@pytest.fixture
def amb(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    a = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    c = a.criar_cliente({"nome": "Alfa"})["dados"]
    p = a.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    yield a, p["id"], base
    if a._agenda is not None:
        a._agenda.parar()
    a._fileserver.stop()


def _ok(r):
    assert r["ok"], r
    return r["dados"]


def test_dashboard_basico(amb):
    a, pid, base = amb
    _ok(a.adicionar_item({"texto": "Fazer A", "tipo": "atividade", "container_id": pid}))
    _ok(a.adicionar_item({"texto": "Pesquisar B", "tipo": "pesquisar", "container_id": pid}))
    _ok(a.adicionar_item({"texto": "Parei no M3", "tipo": "onde_parei", "container_id": pid}))
    _ok(a.adicionar_item({"texto": "Ideia", "tipo": "insight", "container_id": pid}))
    d = _ok(a.dashboard())
    assert [i["texto"] for i in d["itens"]] == ["Fazer A", "Pesquisar B"]
    assert d["itens"][0]["container_nome"] == "Esteira"
    assert d["numeros"]["abertas_hoje"] == 2 and d["numeros"]["projetos_ativos"] == 1
    assert d["numeros"]["docs_pendentes"] > 0
    assert [x["item"]["texto"] for x in d["onde_parei"]] == ["Parei no M3"]
    assert [x["item"]["texto"] for x in d["ideias"]] == ["Ideia"]
    assert d["erro_meu_dia"] is None and d["usuario"]


def test_adicionar_e_marcar_pela_api(amb):
    a, pid, base = amb
    it = _ok(a.adicionar_item({"texto": "Fazer", "tipo": "atividade"}))
    assert _ok(a.marcar_item(it["id"], True))["feito_em"]
    _ok(a.editar_item(it["id"], {"texto": "Fazer já"}))
    _ok(a.editar_item(it["id"], {"container_id": pid}))
    d = _ok(a.dashboard())
    assert d["itens"][0]["texto"] == "Fazer já" and d["itens"][0]["container_id"] == pid
    _ok(a.excluir_item(it["id"]))
    assert _ok(a.dashboard())["itens"] == []


def test_tipos_invalidos_do_js(amb):
    a, pid, base = amb
    assert a.adicionar_item("texto")["ok"] is False
    assert a.adicionar_item({"texto": 5})["ok"] is False
    assert a.adicionar_item({"texto": "x", "tipo": "kanban"})["ok"] is False
    assert a.adicionar_item({"texto": "x", "dia": "ontem"})["ok"] is False
    it = _ok(a.adicionar_item({"texto": "x"}))
    assert a.marcar_item(it["id"], "sim")["ok"] is False
    assert a.dashboard("23/10/2026")["ok"] is False
    assert a.acao_lembrete("x", "adiar5")["ok"] is False


def test_dashboard_com_meu_dia_corrompido(amb):
    a, pid, base = amb
    _ok(a.adicionar_item({"texto": "Ideia", "tipo": "insight", "container_id": pid}))
    arq = a._meudia.caminho_pessoal
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text("{quebrado", encoding="utf-8")
    d = _ok(a.dashboard())
    assert d["itens"] == [] and d["lembretes"] == [] and d["erro_meu_dia"]
    assert [x["item"]["texto"] for x in d["ideias"]] == ["Ideia"]
    assert arq.read_text(encoding="utf-8") == "{quebrado"


def test_lembrete_pela_api_e_acao(amb):
    a, pid, base = amb
    l = _ok(a.salvar_lembrete({"texto": "Reunião", "quando": "2030-01-01T09:00",
                               "recorrencia": {"tipo": "diaria"}}))
    assert [x["texto"] for x in _ok(a.listar_lembretes())] == ["Reunião"]
    assert [x["texto"] for x in _ok(a.dashboard())["lembretes"]] == ["Reunião"]
    _ok(a.acao_lembrete(l["id"], "adiar10"))
    assert _ok(a.listar_lembretes())[0]["adiado_ate"]
    _ok(a.excluir_lembrete(l["id"]))
    assert _ok(a.listar_lembretes()) == []


def test_anotacoes_projeto_com_onde_parei(amb):
    a, pid, base = amb
    _ok(a.adicionar_item({"texto": "Primeiro", "tipo": "onde_parei", "container_id": pid}))
    _ok(a.adicionar_item({"texto": "Último", "tipo": "onde_parei", "container_id": pid}))
    _ok(a.adicionar_item({"texto": "Definir IHM", "tipo": "definicao", "container_id": pid}))
    r = _ok(a.anotacoes_projeto(pid))
    assert r["onde_parei"]["texto"] == "Último"
    assert sorted(x["texto"] for x in r["anotacoes"]) == ["Definir IHM", "Primeiro", "Último"]


def test_lembrete_vencido_avisa_a_janela(amb):
    a, pid, base = amb
    janela = JanelaJS()
    a.definir_janela(janela)
    assert a._agenda is not None and a._agenda.rodando
    a._agenda.parar()
    l = _ok(a.salvar_lembrete({"texto": "Agora", "quando": "2000-01-01T09:00"}))
    a._agenda._primeira = False  # não é "perdido": simula um lembrete vencendo agora
    a._agenda.verificar_agora()
    chamadas = [j for j in janela.js if j.startswith("orbitLembrete(")]
    assert len(chamadas) == 1
    assert json.loads(chamadas[0][len("orbitLembrete("):-1])["texto"] == "Agora"
