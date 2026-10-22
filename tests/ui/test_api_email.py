"""Api de máquinas padrão, e-mail e envios (Tarefa 12)."""
import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.ui.api import Api

DIAG = "diagrama_eletrico"
MEM = "memorial_descritivo"


class FakeOutlook:
    def __init__(self, ok=True, erro=None):
        self.ok, self.erro, self.abertos = ok, erro, []

    def disponivel(self):
        return self.ok

    def abrir_rascunho(self, d):
        if self.erro:
            raise self.erro
        self.abertos.append(d)


class ComError(Exception):  # imita pywintypes.com_error
    pass


@pytest.fixture
def ctx(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings, log = tmp_path / "appdata" / "settings.json", tmp_path / "appdata" / "orbit.log"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    outlook = FakeOutlook()
    api = Api(settings_path=settings, log_path=log, outlook=outlook)
    cli = api.criar_cliente({"nome": "Alfa", "contatos": []})["dados"]
    p = api.criar_projeto(cli["id"], {"codigo": "P-1", "nome": "Esteira",
                                      "contatos": [{"nome": "Ana", "email": "ana@x.com"}]})["dados"]
    origem = tmp_path / "origem"
    origem.mkdir()

    def enviar(cid, tipo, nome, editaveis=(), status="Em elaboração"):
        f = origem / nome
        f.write_text("conteudo")
        eds = []
        for e in editaveis:
            g = origem / e
            g.write_text("ed")
            eds.append(str(g))
        r = api.enviar_revisao(cid, tipo, str(f), eds, status, "m", None)
        assert r["ok"], r
        return r["dados"]

    yield api, outlook, cli["id"], p["id"], enviar, log
    api._fileserver.stop()


def sel(tipo=DIAG, numero=0, ed=False):
    return {"tipo_id": tipo, "numero": numero, "incluir_editaveis": ed}


def test_maquinas_criar_listar_atualizar(ctx):
    api = ctx[0]
    r = api.criar_maquina({"codigo": "EC-200", "nome": "Esteira Compacta EC-200",
                           "descricao": "d"})
    assert r["ok"], r
    mid = r["dados"]["id"]
    lista = api.listar_maquinas()["dados"]
    assert [m["nome"] for m in lista] == ["Esteira Compacta EC-200"]
    assert lista[0]["aplicaveis"] == 9
    assert api.atualizar_maquina(mid, {"descricao": "nova", "codigo": "EC-201"})["ok"]
    p = api.obter_painel(mid)["dados"]
    assert p["container"]["descricao"] == "nova" and p["cliente_nome"] is None


def test_atualizar_maquina_recusa_projeto(ctx):
    api, _, _, pid, _, _ = ctx
    r = api.atualizar_maquina(pid, {"nome": "x"})
    assert r["ok"] is False and "máquina" in r["erro"]


def test_criar_maquina_sem_nome(ctx):
    r = ctx[0].criar_maquina({"nome": "  "})
    assert r["ok"] is False


def test_montar_email_projeto(ctx):
    api, _, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf", editaveis=["a.dwg"], status="Para aprovação")
    enviar(pid, MEM, "m.pdf", status="Para aprovação")
    r = api.montar_email(pid, [sel(), sel(MEM)])
    assert r["ok"], r
    d = r["dados"]
    assert d["destinatarios"] == ["ana@x.com"]
    assert d["assunto"].endswith("Documentos para aprovação")
    assert [a["nome"].endswith(".pdf") for a in d["anexos"]] == [True, True]
    assert d["tamanho_total"] == sum(a["tamanho"] for a in d["anexos"]) == 16
    d2 = api.montar_email(pid, [sel(ed=True)])["dados"]
    assert [a["papel"] for a in d2["anexos"]] == ["principal", "editavel"]


def test_montar_email_maquina_sem_destinatarios(ctx):
    api, _, _, _, enviar, _ = ctx
    mid = api.criar_maquina({"nome": "M1"})["dados"]["id"]
    enviar(mid, DIAG, "a.pdf")
    d = api.montar_email(mid, [sel()])["dados"]
    assert d["destinatarios"] == []


@pytest.mark.parametrize("ruim", [
    None, [], "x", [None], [{"tipo_id": "nope", "numero": 0}],
    [{"tipo_id": DIAG, "numero": "abc"}], [{"tipo_id": DIAG, "numero": 5}],
    [{"tipo_id": DIAG, "numero": 0, "incluir_editaveis": "sim"}],
    [{"tipo_id": 7, "numero": 0}], [{"numero": 0}], [{"tipo_id": DIAG, "numero": True}],
])
def test_selecoes_invalidas(ctx, ruim):
    api, _, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf")
    assert api.montar_email(pid, ruim)["ok"] is False
    assert api.preparar_email(pid, {"destinatarios": [], "assunto": "a", "corpo": "b"},
                              ruim)["ok"] is False


def test_preparar_email_reconstroi_anexos_no_servidor(ctx, tmp_path):
    api, outlook, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf", editaveis=["a.dwg"])
    segredo = tmp_path / "segredo.txt"
    segredo.write_text("s")
    draft = {"destinatarios": ["a@x.com; b@x.com ;; "], "assunto": "Assunto", "corpo": "Corpo",
             "anexos": [str(segredo)]}
    r = api.preparar_email(pid, draft, [sel()])
    assert r["ok"], r
    d = outlook.abertos[0]
    assert d.destinatarios == ["a@x.com", "b@x.com"]
    assert d.assunto == "Assunto" and d.corpo == "Corpo"
    assert [p.name.endswith(".pdf") for p in d.anexos] == [True]
    assert segredo not in d.anexos
    ev = api.obter_historico(pid)["dados"][0]
    assert ev["tipo"] == "email_preparado"
    assert api.listar_envios()["dados"][0]["destinatarios"] == ["a@x.com", "b@x.com"]


def test_preparar_email_destinatarios_lista(ctx):
    api, outlook, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf")
    assert api.preparar_email(pid, {"destinatarios": ["a@x.com", " b@x.com "],
                                    "assunto": "", "corpo": ""}, [sel()])["ok"]
    assert outlook.abertos[0].destinatarios == ["a@x.com", "b@x.com"]


@pytest.mark.parametrize("draft", [
    None, "x", {"destinatarios": "a@x.com", "assunto": "a", "corpo": "b"},
    {"destinatarios": [1], "assunto": "a", "corpo": "b"},
    {"destinatarios": [], "assunto": 3, "corpo": "b"},
    {"destinatarios": [], "assunto": "a", "corpo": None},
])
def test_preparar_email_draft_invalido(ctx, draft):
    api, outlook, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf")
    assert api.preparar_email(pid, draft, [sel()])["ok"] is False
    assert outlook.abertos == []


def test_preparar_sem_outlook_devolve_mensagem_do_nucleo(ctx):
    api, outlook, _, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf")
    outlook.ok = False
    r = api.preparar_email(pid, {"destinatarios": [], "assunto": "a", "corpo": "b"}, [sel()])
    assert r["ok"] is False and "Outlook clássico não encontrado" in r["erro"]
    assert api.listar_envios()["dados"] == []


def test_falha_com_vira_erro_amigavel(ctx):
    api, outlook, _, pid, enviar, log = ctx
    enviar(pid, DIAG, "a.pdf")
    outlook.erro = ComError("(-2147221005, 'Classe não registrada', None, None)")
    r = api.preparar_email(pid, {"destinatarios": [], "assunto": "a", "corpo": "b"}, [sel()])
    assert r["ok"] is False
    assert "Erro inesperado" not in r["erro"] and "Outlook" in r["erro"]
    assert api.listar_envios()["dados"] == []  # nada registrado


def test_listar_envios_filtro(ctx):
    api, _, cid, pid, enviar, _ = ctx
    enviar(pid, DIAG, "a.pdf")
    mid = api.criar_maquina({"nome": "M1"})["dados"]["id"]
    enviar(mid, DIAG, "b.pdf")
    dr = {"destinatarios": [], "assunto": "a", "corpo": "b"}
    api.preparar_email(pid, dr, [sel()])
    api.preparar_email(mid, dr, [sel()])
    assert len(api.listar_envios()["dados"]) == 2
    f = api.listar_envios(cid)["dados"]
    assert len(f) == 1 and f[0]["cliente_nome"] == "Alfa"
    assert api.listar_envios(7)["ok"] is False
