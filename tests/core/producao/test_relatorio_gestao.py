from datetime import date

import pytest

from orbit.core.producao import apontamentos as A, etapas, gestao, materiais as M, relatorio
from orbit.core.producao import testes as T
from orbit.core.revisions import RevisionService


@pytest.fixture
def op(prod, tmp_path):
    svc, repo, p = prod
    f = tmp_path / "d.pdf"
    f.write_bytes(b"x")
    RevisionService(repo).enviar_revisao(p.id, "diagrama_eletrico", f, [], "Aprovado", "")
    o = svc.criar_op(p.id, {"painel": "QGBT <01>", "prazo": "2026-10-20", "prioridade": "alta"})
    etapas.liberar(svc, o["id"])
    return svc, o["id"]


def test_relatorio_grava_html_escapado(op):
    svc, op_id = op
    T.itens_inspecao(svc, op_id)
    T.carregar_ponto_a_ponto(svc, op_id, [{"origem": "X1:1", "destino": "K1:A1"}])
    caminho = relatorio.gerar(svc, op_id)
    assert caminho.name == "Relatório de ensaio OP-0001.html"
    assert caminho.parent == svc.pasta_op(op_id)
    html = caminho.read_text(encoding="utf-8")
    assert "QGBT &lt;01&gt;" in html and "<01>" not in html
    assert "IEC 61439" in html and "X1:1" in html and "Rev00" in html
    relatorio.gerar(svc, op_id)  # regrava sem erro


def test_indicadores(op, relogio):
    svc, op_id = op
    A.iniciar(svc, op_id, "João")
    relogio.avancar(hours=2)
    A.pausar(svc, "João", "Falta de material")
    relogio.avancar(hours=1)
    M.importar(svc, op_id, [{"descricao": "Contator"}])
    m = svc.carregar(op_id)["materiais"][0]
    M.mudar_situacao(svc, op_id, [m["id"]], "falta", "thiago")
    T.abrir_nc(svc, op_id, "Identificação", "anilha faltando", "João")
    ind = gestao.indicadores(svc)
    assert {x["etapa"]: x["n"] for x in ind["por_etapa"]}["em_montagem"] == 1
    assert [a["numero"] for a in ind["atrasadas"]] == ["OP-0001"]
    assert ind["semana"]["trabalho_h"] == 2.0 and ind["semana"]["parada_h"] == 1.0
    assert ind["semana"]["por_motivo"] == {"Falta de material": 1.0}
    assert len(ind["faltas"]) == 1 and ind["pareto_nc"] == [{"tipo": "Identificação", "n": 1}]
    assert ind["ncs_abertas"] == 1 and len(ind["em_andamento"]) == 1


def test_fila_ordenada_e_cartao(op, prod):
    svc, op_id = op
    _, repo, p = prod
    svc.criar_op(p.id, {"painel": "CCM", "prioridade": "urgente"})
    cards = gestao.fila(svc, hoje=date(2026, 10, 24))
    assert [c["painel"] for c in cards] == ["CCM", "QGBT <01>"]
    c = cards[1]
    assert c["atrasada"] and c["etapa"] == "liberada" and c["revisao_nova"] == 0
