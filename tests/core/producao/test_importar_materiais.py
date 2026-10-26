import pytest
from openpyxl import Workbook

from orbit.core.errors import OrbitError
from orbit.core.producao import etapas, importar, materiais as M
from orbit.core.revisions import RevisionService


def test_csv_ponto_e_virgula_latin1(tmp_path):
    f = tmp_path / "lista.csv"
    f.write_bytes("Origem;Destino;Seção\nX1:1;K1:A1;1,0\n\nX1:2;K2:A1;1,5\n".encode("latin-1"))
    t = importar.ler_tabela(f)
    assert t["cabecalho"] == ["Origem", "Destino", "Seção"]
    assert t["linhas"] == [["X1:1", "K1:A1", "1,0"], ["X1:2", "K2:A1", "1,5"]]


def test_csv_virgula_utf8_com_bom(tmp_path):
    f = tmp_path / "lista.csv"
    f.write_bytes("﻿Tag,Descrição\nS1,Emergência\n".encode("utf-8"))
    t = importar.ler_tabela(f)
    assert t["cabecalho"] == ["Tag", "Descrição"] and t["linhas"] == [["S1", "Emergência"]]


def test_xlsx_pula_linhas_vazias_no_topo(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append([])
    ws.append(["Código", "Descrição", "Qtd"])
    ws.append(["3RT2015", "Contator", 2])
    ws.append([None, None, None])
    ws.append(["5SL6", "Disjuntor", 1.5])
    f = tmp_path / "bom.xlsx"
    wb.save(f)
    t = importar.ler_tabela(f)
    assert t["cabecalho"] == ["Código", "Descrição", "Qtd"]
    assert t["linhas"] == [["3RT2015", "Contator", "2"], ["5SL6", "Disjuntor", "1.5"]]


def test_formato_nao_suportado(tmp_path):
    f = tmp_path / "x.xls"
    f.write_bytes(b"x")
    with pytest.raises(OrbitError):
        importar.ler_tabela(f)


def test_mapear_colunas():
    t = {"cabecalho": ["A", "B", "C"], "linhas": [["1", "2", "3"], ["", "", "x"], ["4", "", "6"]]}
    out = importar.mapear(t, {"origem": 0, "destino": 2, "fio": None}, obrigatorios=["origem"])
    assert out == [{"origem": "1", "destino": "3", "fio": ""}, {"origem": "4", "destino": "6",
                                                               "fio": ""}]
    with pytest.raises(OrbitError):
        importar.mapear(t, {"origem": 9}, obrigatorios=["origem"])
    with pytest.raises(OrbitError):
        importar.mapear(t, {"destino": 1}, obrigatorios=["origem"])


@pytest.fixture
def op(prod, tmp_path):
    svc, repo, p = prod
    f = tmp_path / "d.pdf"
    f.write_bytes(b"x")
    RevisionService(repo).enviar_revisao(p.id, "diagrama_eletrico", f, [], "Aprovado", "")
    o = svc.criar_op(p.id, {"painel": "QGBT-01"})
    return svc, o["id"]


ITENS = [{"codigo": "3RT2015", "descricao": "Contator", "quantidade": "2", "unidade": "pç",
          "fabricante": "Siemens"},
         {"codigo": "5SL6", "descricao": "Disjuntor", "quantidade": "1,5", "unidade": "",
          "fabricante": ""},
         {"codigo": "", "descricao": "", "quantidade": "", "unidade": "", "fabricante": ""}]


def test_importar_materiais_e_situacoes(op):
    svc, op_id = op
    assert M.importar(svc, op_id, ITENS) == 2
    mats = svc.carregar(op_id)["materiais"]
    assert mats[1]["quantidade"] == 1.5 and mats[0]["situacao"] == "pendente"
    with pytest.raises(OrbitError):
        M.importar(svc, op_id, ITENS)  # já existe lista
    M.mudar_situacao(svc, op_id, [mats[0]["id"]], "falta", "thiago", obs="sem estoque",
                     previsao="2026-10-30")
    o = svc.carregar(op_id)
    assert M.resumo(o)["falta"] == 1 and M.faltas(o)[0]["previsao"] == "2026-10-30"
    with pytest.raises(OrbitError):
        M.mudar_situacao(svc, op_id, [mats[0]["id"]], "perdido", "thiago")
    M.mudar_situacao(svc, op_id, [m["id"] for m in mats], "recebido", "thiago")
    o = svc.carregar(op_id)
    assert M.faltas(o) == [] and M.resumo(o)["recebido"] == 2
    assert o["materiais"][0]["previsao"] is None


def test_substituir_lista_guarda_a_anterior(op):
    svc, op_id = op
    M.importar(svc, op_id, ITENS)
    M.importar(svc, op_id, ITENS[:1], substituir=True)
    o = svc.carregar(op_id)
    assert len(o["materiais"]) == 1 and len(o["materiais_anteriores"]) == 1


def test_adicionar_item_manual(op):
    svc, op_id = op
    it = M.adicionar(svc, op_id, {"descricao": "Canaleta 50x50", "quantidade": 3})
    assert it["quantidade"] == 3 and it["situacao"] == "pendente"
    with pytest.raises(OrbitError):
        M.adicionar(svc, op_id, {"descricao": " "})


def test_sugerir_mapa():
    m = importar.sugerir_mapa(["Nº", "Origem", "Destino", "Nº do fio", "Seção (mm²)", "Cor"],
                              "ponto_a_ponto")
    assert m == {"origem": 1, "destino": 2, "fio": 3, "secao": 4, "cor": 5}
    m = importar.sugerir_mapa(["Item", "Código", "Descrição", "Qtd.", "Un", "Fabricante"],
                              "materiais")
    assert m == {"codigo": 1, "descricao": 2, "quantidade": 3, "unidade": 4, "fabricante": 5}
    assert importar.sugerir_mapa(["x"], "io") == {"tag": None, "descricao": None,
                                                  "endereco": None, "tipo": None}
