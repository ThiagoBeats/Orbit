import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.ui import api as api_mod
from orbit.ui.api import Api


class JanelaSeq:
    def __init__(self, *respostas):
        self.respostas = list(respostas)

    def create_file_dialog(self, *a, **k):
        return self.respostas.pop(0) if self.respostas else None

    def evaluate_js(self, *_):
        pass


@pytest.fixture
def amb(tmp_path, monkeypatch):
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    a = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    c = a.criar_cliente({"nome": "Alfa"})["dados"]
    p = a.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    abertos = []
    monkeypatch.setattr(api_mod.os, "startfile", lambda x: abertos.append(str(x)), raising=False)
    origem = tmp_path / "origem"
    origem.mkdir()
    yield a, p["id"], origem, abertos
    a._fileserver.stop()


def test_adicionar_por_caminhos_e_listar(amb):
    a, pid, origem, _ = amb
    f = origem / "NF.pdf"
    f.write_bytes(b"nf")
    r = a.adicionar_anexos(pid, [str(f)])
    assert r["ok"] and r["dados"] == ["NF.pdf"]
    lista = a.listar_anexos(pid)["dados"]
    assert [x["nome"] for x in lista] == ["NF.pdf"]
    acoes = [l["acao"] for l in a.ler_log({})["dados"]["linhas"]]
    assert "anexos_adicionados" in acoes


def test_adicionar_pelo_dialogo(amb):
    a, pid, origem, _ = amb
    f1, f2 = origem / "m1.pdf", origem / "m2.pdf"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")
    a.definir_janela(JanelaSeq([str(f1), str(f2)]))
    assert a.adicionar_anexos(pid)["dados"] == ["m1.pdf", "m2.pdf"]
    a.definir_janela(JanelaSeq(None))
    assert a.adicionar_anexos(pid)["dados"] == []  # cancelado
    if a._agenda:
        a._agenda.parar()


def test_entradas_invalidas(amb):
    a, pid, origem, _ = amb
    assert a.adicionar_anexos(pid, "C:/x.pdf")["ok"] is False
    assert a.adicionar_anexos(pid, [5])["ok"] is False
    assert a.adicionar_anexos("nao-existe", [str(origem)])["ok"] is False
    assert a.abrir_anexo(pid, "../projeto.json")["ok"] is False


def test_abrir_anexo_e_pasta(amb):
    a, pid, origem, abertos = amb
    f = origem / "manual.pdf"
    f.write_bytes(b"m")
    a.adicionar_anexos(pid, [str(f)])
    assert a.abrir_anexo(pid, "manual.pdf")["ok"]
    assert a.abrir_pasta_anexos(pid)["ok"]
    assert abertos[0].endswith("manual.pdf") and abertos[1].endswith("Anexos")
