"""Api do painel do projeto/máquina (Tarefa 11)."""
import urllib.request

import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.core.errors import ArquivoEmUso
from orbit.ui.api import Api

TIPOS9 = ["diagrama_eletrico", "topologia_rede", "memorial_descritivo", "layout_painel",
          "planilha_cargas", "consumo_pneumatico", "manual_operacao",
          "descritivo_funcional", "lista_tags"]


class JanelaFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def create_file_dialog(self, tipo, *args, **kwargs):
        self.chamadas.append((tipo, kwargs.get("allow_multiple")))
        return self.resposta


@pytest.fixture
def caminhos(tmp_path):
    return tmp_path / "appdata" / "settings.json", tmp_path / "appdata" / "orbit.log"


@pytest.fixture
def painel(caminhos, tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    save_user_settings(UserSettings(str(base), "escuro"), caminhos[0])
    api = Api(settings_path=caminhos[0], log_path=caminhos[1])
    c = api.criar_cliente({"nome": "Alfa"})["dados"]
    p = api.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    origem = tmp_path / "origem"
    origem.mkdir()
    yield api, base, p["id"], origem
    api._fileserver.stop()


def _arq(pasta, nome, conteudo="x"):
    f = pasta / nome
    f.write_text(conteudo, encoding="utf-8")
    return str(f)


def _enviar(api, pid, tipo, principal, editaveis=(), status="Em elaboração", motivo="m",
            numero=None):
    r = api.enviar_revisao(pid, tipo, principal, list(editaveis), status, motivo, numero)
    assert r["ok"] is True, r
    return r["dados"]


def _ler(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read()


def test_painel_resumo_conta_aplicaveis(painel):
    api, _, pid, origem = painel
    assert api.definir_nao_se_aplica(pid, "consumo_pneumatico", True)["ok"] is True
    for t in TIPOS9[:5] + ["descritivo_funcional"]:
        _enviar(api, pid, t, _arq(origem, f"{t}.pdf"))
    r = api.obter_painel(pid)
    assert r["ok"] is True, r
    d = r["dados"]
    assert d["resumo"]["emitidos"] == 6
    assert d["resumo"]["aplicaveis"] == 8
    assert [x["tipo_id"] for x in d["documentos"]] == TIPOS9
    assert d["cliente_nome"] == "Alfa"
    assert d["container"]["nome"] == "Esteira" and d["container"]["tipo"] == "projeto"
    assert "historico" not in d["container"] and "documentos" not in d["container"]
    assert d["nao_registrados"] == 0
    na = d["documentos"][TIPOS9.index("consumo_pneumatico")]
    assert na["nao_se_aplica"] is True and na["atual"] is None
    dia = d["documentos"][0]
    assert dia["nome"] == "Diagrama Elétrico"
    assert dia["atual"]["numero"] == 0 and dia["atual"]["status"] == "Em elaboração"
    assert dia["atual"]["principal"].endswith("Rev00.pdf")
    assert dia["atual"]["editaveis"] == []
    assert d["resumo"]["ultima_atualizacao"]
    assert d["resumo"]["ultimo_emitido"]["numero"] == 0


def test_url_arquivo_visualizavel(painel):
    api, _, pid, origem = painel
    rev = _enviar(api, pid, "topologia_rede", _arq(origem, "a.pdf", "%PDF-1.4"),
                  [_arq(origem, "a.drawio")])
    pdf, drawio = rev["principal"], rev["editaveis"][0]
    r = api.url_arquivo(pid, "topologia_rede", 0, pdf)
    assert r["ok"] is True, r
    assert r["dados"]["visualizavel"] is True
    assert r["dados"]["url"].startswith("http://127.0.0.1:")
    assert _ler(r["dados"]["url"]) == b"%PDF-1.4"
    assert r["dados"]["tamanho"] == 8
    assert api.url_arquivo(pid, "topologia_rede", 0, drawio)["dados"]["visualizavel"] is False
    for ext, vis in ((".PNG", True), (".jpeg", True), (".svg", True), (".webp", True),
                     (".gif", True), (".jpg", True), (".xlsx", False)):
        rv = _enviar(api, pid, "lista_tags", _arq(origem, "img" + ext))
        r = api.url_arquivo(pid, "lista_tags", rv["numero"], rv["principal"])
        assert r["dados"]["visualizavel"] is vis, ext


def test_url_arquivo_recusa_nome_fora_da_revisao(painel, monkeypatch):
    api, base, pid, origem = painel
    chamadas = []
    monkeypatch.setattr("orbit.ui.api.os.startfile", lambda p: chamadas.append(p),
                        raising=False)
    rev = _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"))
    for nome in ("..\\..\\projeto.json", "../projeto.json", "projeto.json", "outro.pdf",
                 str(base / "Clientes" / "Alfa" / "cliente.json"), None, 5):
        assert api.url_arquivo(pid, "diagrama_eletrico", 0, nome)["ok"] is False, nome
        assert api.abrir_no_programa(pid, "diagrama_eletrico", 0, nome)["ok"] is False
    assert chamadas == []
    assert api.url_arquivo(pid, "diagrama_eletrico", 5, rev["principal"])["ok"] is False
    assert api.url_arquivo(pid, "diagrama_eletrico", "x", rev["principal"])["ok"] is False
    assert api.url_arquivo(pid, "nao_existe", 0, rev["principal"])["ok"] is False


def test_url_arquivo_revisao_arquivada_vem_de_antigos(painel):
    api, _, pid, origem = painel
    r0 = _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf", "rev0"))
    _enviar(api, pid, "diagrama_eletrico", _arq(origem, "b.pdf", "rev1"))
    url = api.url_arquivo(pid, "diagrama_eletrico", 0, r0["principal"])["dados"]["url"]
    assert "/Antigos/" in url
    assert _ler(url) == b"rev0"
    d = api.obter_painel(pid)["dados"]["documentos"][0]
    assert [r["numero"] for r in d["revisoes"]] == [1, 0]
    assert d["revisoes"][1]["arquivada"] is True
    assert d["atual"]["numero"] == 1


def test_arquivo_sumiu_da_pasta_da_erro_claro(painel):
    api, base, pid, origem = painel
    rev = _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"))
    pasta = base / "Clientes" / "Alfa" / "P-1 - Esteira" / "Diagrama Elétrico"
    (pasta / rev["principal"]).rename(origem / "movido.pdf")
    r = api.url_arquivo(pid, "diagrama_eletrico", 0, rev["principal"])
    assert r["ok"] is False and "não foi encontrado" in r["erro"]


def test_abrir_no_programa_e_pasta_usam_startfile(painel, monkeypatch):
    api, base, pid, origem = painel
    chamadas = []
    monkeypatch.setattr("orbit.ui.api.os.startfile", lambda p: chamadas.append(str(p)),
                        raising=False)
    rev = _enviar(api, pid, "planilha_cargas", _arq(origem, "c.xlsx"))
    assert api.abrir_no_programa(pid, "planilha_cargas", 0, rev["principal"])["ok"] is True
    assert api.abrir_pasta(pid, "planilha_cargas")["ok"] is True
    pasta = base / "Clientes" / "Alfa" / "P-1 - Esteira" / "Planilha de Cargas"
    assert chamadas == [str(pasta / rev["principal"]), str(pasta)]


def test_preview_upload(painel):
    api, _, pid, origem = painel
    p = _arq(origem, "ABCDE.pdf")
    r = api.preview_upload(pid, "diagrama_eletrico", p, [_arq(origem, "x.dwg")], None)
    assert r["ok"] is True, r
    d = r["dados"]
    assert d["numero"] == 0
    assert d["nome_principal"].startswith("Diagrama Elétrico - Alfa - Esteira - ")
    assert d["nome_principal"].endswith(" - Rev00.pdf")
    assert d["nomes_editaveis"][0].endswith(" - Rev00.dwg")
    assert api.preview_upload(pid, "diagrama_eletrico", p, [], "3")["dados"]["numero"] == 3
    assert api.preview_upload(pid, "diagrama_eletrico", p, [], "")["dados"]["numero"] == 0
    assert api.preview_upload(pid, "diagrama_eletrico", p, [], "abc")["ok"] is False
    assert api.preview_upload(pid, "diagrama_eletrico", p, [], -1)["ok"] is False
    assert api.preview_upload(pid, "diagrama_eletrico", "", [], None)["ok"] is False


def test_enviar_revisao_numero_texto_e_status(painel):
    api, _, pid, origem = painel
    rev = _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"), numero="2")
    assert rev["numero"] == 2
    r = api.alterar_status(pid, "diagrama_eletrico", "Aprovado")
    assert r["ok"] is True, r
    atual = api.obter_painel(pid)["dados"]["documentos"][0]["atual"]
    assert atual["status"] == "Aprovado"
    assert api.alterar_status(pid, "diagrama_eletrico", "xyz")["ok"] is False


def test_enviar_revisao_arquivo_em_uso_vira_erro(painel, monkeypatch):
    api, _, pid, origem = painel

    def em_uso(*a, **k):
        raise ArquivoEmUso("O arquivo X está aberto em outro programa.")

    monkeypatch.setattr("orbit.core.revisions.RevisionService.enviar_revisao", em_uso)
    r = api.enviar_revisao(pid, "diagrama_eletrico", _arq(origem, "a.pdf"), [], "Aprovado",
                           "", None)
    assert r == {"ok": False, "erro": "O arquivo X está aberto em outro programa."}


def test_painel_conta_nao_registrados(painel):
    api, base, pid, _ = painel
    pasta = base / "Clientes" / "Alfa" / "P-1 - Esteira" / "Lista de Tags"
    (pasta / "Lista de Tags - Alfa - Esteira - 010126 - Rev00.pdf").write_text("x")
    (pasta / "qualquer.txt").write_text("x")
    assert api.obter_painel(pid)["dados"]["nao_registrados"] == 1


def test_painel_de_maquina(painel):
    api, _, _, origem = painel
    m = api._repo.create_maquina("M-1", "Esteira EC-200")
    _enviar(api, m.id, "diagrama_eletrico", _arq(origem, "a.pdf"))
    d = api.obter_painel(m.id)["dados"]
    assert d["cliente_nome"] is None and d["container"]["tipo"] == "maquina"
    assert d["documentos"][0]["atual"]["principal"].startswith("Diagrama Elétrico - Esteira EC-200 - ")


def test_obter_historico_mais_recente_primeiro(painel):
    api, _, pid, origem = painel
    _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"))
    api.alterar_status(pid, "diagrama_eletrico", "Aprovado")
    api.definir_nao_se_aplica(pid, "lista_tags", True)
    r = api.obter_historico(pid)
    assert r["ok"] is True, r
    assert [e["tipo"] for e in r["dados"]] == ["nao_se_aplica_alterado", "status_alterado",
                                               "revisao_enviada"]


def test_escolher_arquivos(caminhos):
    janela = JanelaFalsa(("C:\\a.pdf", "C:\\b.dwg"))
    api = Api(settings_path=caminhos[0], log_path=caminhos[1])
    api.definir_janela(janela)
    assert api.escolher_arquivos(True) == {"ok": True, "dados": ["C:\\a.pdf", "C:\\b.dwg"]}
    assert janela.chamadas == [(10, True)]
    janela.resposta = None
    assert api.escolher_arquivos(False) == {"ok": True, "dados": []}
    assert janela.chamadas[-1] == (10, False)


def test_caminhos_do_drop():
    from orbit.ui.app import caminhos_do_drop
    ev = {"dataTransfer": {"files": [{"name": "a.pdf", "pywebviewFullPath": "C:\\x\\a.pdf"},
                                     {"name": "b.txt"}]}}
    assert caminhos_do_drop(ev) == ["C:\\x\\a.pdf"]
    assert caminhos_do_drop({}) == []
    assert caminhos_do_drop({"dataTransfer": None}) == []


# --- rodada de correção 1 ------------------------------------------------------

def _editar_json(base, alterar):
    import json
    f = base / "Clientes" / "Alfa" / "P-1 - Esteira" / "projeto.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    alterar(d)
    f.write_text(json.dumps(d), encoding="utf-8")


def test_numero_nao_inteiro_no_json_vira_erro_de_dados(painel):
    from orbit.core.errors import OrbitDataError
    api, base, pid, origem = painel
    _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"))

    def injetar(d):
        d["documentos"]["diagrama_eletrico"]["revisoes"][0]["numero"] = "<img src=x onerror=alert(1)>"
    _editar_json(base, injetar)
    r = api.obter_painel(pid)
    assert r["ok"] is False and "número de revisão inválido" in r["erro"].lower()
    try:
        api._obter_painel(pid)
    except OrbitDataError:
        pass
    else:
        raise AssertionError("esperava OrbitDataError")


def test_numero_texto_inteiro_no_json_sai_como_int(painel):
    api, base, pid, origem = painel
    _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"))
    _editar_json(base, lambda d: d["documentos"]["diagrama_eletrico"]["revisoes"][0]
                 .__setitem__("numero", "0"))
    d = api.obter_painel(pid)["dados"]["documentos"][0]
    assert d["atual"]["numero"] == 0 and d["revisoes"][0]["numero"] == 0
    assert type(d["atual"]["numero"]) is int


def test_preview_recusa_numero_menor_ou_igual_ao_atual(painel):
    api, _, pid, origem = painel
    _enviar(api, pid, "diagrama_eletrico", _arq(origem, "a.pdf"), numero=2)
    p = _arq(origem, "b.pdf")
    for n in (0, 2, "1"):
        r = api.preview_upload(pid, "diagrama_eletrico", p, [], n)
        assert r == {"ok": False, "erro": "A nova revisão precisa ser maior que a atual (Rev02)."}
        assert api.enviar_revisao(pid, "diagrama_eletrico", p, [], "Aprovado", "", n) == r
    assert api.preview_upload(pid, "diagrama_eletrico", p, [], 3)["ok"] is True


def test_editaveis_precisa_ser_lista(painel):
    api, _, pid, origem = painel
    p = _arq(origem, "a.pdf")
    for ruim in (r"C:x.dwg", None, {"a": 1}, [5]):
        assert api.preview_upload(pid, "diagrama_eletrico", p, ruim, None)["ok"] is False
        assert api.enviar_revisao(pid, "diagrama_eletrico", p, ruim, "Aprovado", "", None)["ok"] is False
    assert api.obter_painel(pid)["dados"]["documentos"][0]["atual"] is None
