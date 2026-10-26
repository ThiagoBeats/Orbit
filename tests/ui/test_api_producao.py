import pytest

import orbit.ui.api_producao as mod
from orbit.core.config import UserSettings, save_user_settings
from orbit.ui.api import Api


@pytest.fixture
def amb(tmp_path, monkeypatch):
    abertos = []
    monkeypatch.setattr(mod, "_abrir", lambda c: abertos.append(c))
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    a = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    c = a.criar_cliente({"nome": "Alfa"})["dados"]
    p = a.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    pdf = tmp_path / "diag.pdf"
    pdf.write_bytes(b"%PDF")
    r = a.enviar_revisao(p["id"], "diagrama_eletrico", str(pdf), [], "Aprovado", "")
    assert r["ok"], r
    yield a, p["id"], tmp_path, abertos
    if a._agenda is not None:
        a._agenda.parar()
    a._fileserver.stop()


def _ok(r):
    assert r["ok"], r
    return r["dados"]


def test_fluxo_completo_pela_api(amb):
    a, pid, tmp, abertos = amb
    cfg = _ok(a.prod_config())
    assert cfg["ultimo_operador"] is None and len(cfg["etapas"]) == 7
    _ok(a.prod_salvar_config({"operadores": [{"nome": "João", "verifica": False},
                                             {"nome": "Maria", "verifica": True}]}))
    op = _ok(a.prod_criar_op(pid, {"painel": "QGBT-01", "prazo": "2026-12-01"}))
    d = _ok(a.prod_obter_op(op["id"]))
    assert [x["tipo_id"] for x in d["disponiveis"]] == ["diagrama_eletrico"]
    _ok(a.prod_liberar(op["id"], ["diagrama_eletrico"]))
    _ok(a.prod_abrir_documento(op["id"], "diagrama_eletrico"))
    assert abertos[-1].name.endswith(".pdf")

    # bancada
    _ok(a.prod_iniciar(op["id"], "João"))
    assert _ok(a.prod_config())["ultimo_operador"] == "João"
    mt = _ok(a.prod_meu_trabalho("João"))
    assert mt["aberto"]["op"]["numero"] == "OP-0001"
    _ok(a.prod_pausar("João", "Falta de material", "sem canaleta"))
    _ok(a.prod_retomar("João"))

    # materiais por planilha
    csv = tmp / "bom.csv"
    csv.write_text("Código;Descrição;Qtd\n3RT2015;Contator;2\n", encoding="utf-8")
    pl = _ok(a.prod_ler_planilha(str(csv), "materiais"))
    assert pl["sugestao"]["codigo"] == 0 and pl["total"] == 1
    assert _ok(a.prod_importar_planilha(op["id"], "materiais", str(csv), pl["sugestao"])) == 1
    mid = _ok(a.prod_obter_op(op["id"]))["op"]["materiais"][0]["id"]
    _ok(a.prod_situacao_materiais(op["id"], [mid], "falta", "sem estoque"))
    assert _ok(a.prod_fila())[0]["faltas"] == 1

    # testes
    lista = tmp / "lig.csv"
    lista.write_text("Origem,Destino\nX1:1,K1:A1\nX1:2,K1:A2\n", encoding="utf-8")
    pl = _ok(a.prod_ler_planilha(str(lista), "ponto_a_ponto"))
    _ok(a.prod_importar_planilha(op["id"], "ponto_a_ponto", str(lista), pl["sugestao"]))
    _ok(a.prod_avancar(op["id"], "João"))  # em_teste
    t = _ok(a.prod_preparar_testes(op["id"]))
    for it in t["inspecao"]["itens"]:
        _ok(a.prod_marcar(op["id"], "inspecao", it["id"], {"resultado": "ok", "operador": "João"}))
    for l in t["ponto_a_ponto"]["linhas"]:
        _ok(a.prod_marcar(op["id"], "ponto_a_ponto", l["id"],
                          {"ligacao": "ok", "aperto": "ok", "operador": "João"}))
    c = _ok(a.prod_adicionar_circuito(op["id"], "L1-L2-L3 x PE", 500))
    _ok(a.prod_marcar(op["id"], "isolacao", c["id"], {"valor": 300, "operador": "João"}))
    r = a.prod_marcar(op["id"], "outro", c["id"], {"operador": "João"})
    assert not r["ok"]
    _ok(a.prod_avancar(op["id"], "João"))  # verificação final
    assert not a.prod_sortear_amostra(op["id"], "João")["ok"]
    am = _ok(a.prod_sortear_amostra(op["id"], "Maria"))
    for lid in am["sorteadas"]:
        _ok(a.prod_marcar_amostra(op["id"], lid, "ok", "Maria"))
    for i in range(len(am["checklist"])):
        _ok(a.prod_marcar_checklist_final(op["id"], i, "ok", "Maria"))
    _ok(a.prod_concluir_verificacao(op["id"], "Maria"))
    assert _ok(a.prod_avancar(op["id"]))["etapa"] == "aprovada"

    caminho = _ok(a.prod_relatorio(op["id"]))
    assert caminho.endswith("Relatório de ensaio OP-0001.html")
    g = _ok(a.prod_gestao())
    assert g["faltas"] and g["geral"]["trabalho_h"] >= 0
    assert [o["numero"] for o in _ok(a.prod_ops_projeto(pid))] == ["OP-0001"]


def test_config_invalida_e_op_sem_base(tmp_path):
    a = Api(settings_path=tmp_path / "s.json", log_path=tmp_path / "l.log")
    r = a.prod_fila()
    assert not r["ok"] and "pasta base" in r["erro"]
