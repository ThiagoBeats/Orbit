from datetime import datetime

import pytest

from orbit.core.errors import OrbitError
from orbit.core.producao import apontamentos as A, etapas
from orbit.core.revisions import RevisionService


@pytest.fixture
def duas_ops(prod, tmp_path):
    svc, repo, p = prod
    f = tmp_path / "d.pdf"
    f.write_bytes(b"x")
    RevisionService(repo).enviar_revisao(p.id, "diagrama_eletrico", f, [], "Aprovado", "")
    ids = []
    for nome in ("QGBT-01", "CCM-02"):
        op = svc.criar_op(p.id, {"painel": nome})
        etapas.liberar(svc, op["id"])
        ids.append(op["id"])
    return svc, ids


def test_iniciar_leva_a_op_liberada_para_montagem(duas_ops, relogio):
    svc, (a, b) = duas_ops
    ap = A.iniciar(svc, a, "João")
    assert ap["tipo"] == "trabalho" and ap["fim"] is None and ap["etapa"] == "em_montagem"
    assert svc.carregar(a)["etapa"] == "em_montagem"
    assert A.aberto_do_operador(svc, "João")[0] == a


def test_um_apontamento_aberto_por_operador(duas_ops, relogio):
    svc, (a, b) = duas_ops
    A.iniciar(svc, a, "João")
    relogio.avancar(hours=1)
    A.iniciar(svc, b, "João")  # encerra o de A
    ap_a = svc.carregar(a)["apontamentos"][0]
    assert ap_a["fim"] == "2026-10-24T09:00:00"
    assert A.aberto_do_operador(svc, "João")[0] == b
    A.iniciar(svc, a, "Maria")  # outra pessoa pode trabalhar na mesma OP
    assert A.aberto_do_operador(svc, "Maria")[0] == a


def test_pausar_retomar_encerrar(duas_ops, relogio):
    svc, (a, b) = duas_ops
    with pytest.raises(OrbitError):
        A.pausar(svc, "João", "Falta de material")  # nada aberto
    A.iniciar(svc, a, "João")
    relogio.avancar(hours=2)
    with pytest.raises(OrbitError):
        A.pausar(svc, "João", "Café")  # motivo fora da lista
    A.pausar(svc, "João", "Falta de material", obs="faltou contator")
    relogio.avancar(minutes=30)
    A.retomar(svc, "João")
    relogio.avancar(hours=1)
    A.encerrar(svc, "João")
    aps = svc.carregar(a)["apontamentos"]
    assert [(x["tipo"], x["motivo"]) for x in aps] == [
        ("trabalho", None), ("parada", "Falta de material"), ("trabalho", None)]
    assert all(x["fim"] for x in aps)
    assert A.aberto_do_operador(svc, "João") is None
    t = A.totais([svc.carregar(a)], relogio())
    assert t["trabalho_h"] == 3.0 and t["parada_h"] == 0.5
    assert t["por_motivo"] == {"Falta de material": 0.5}
    assert t["por_operador"]["João"] == {"trabalho_h": 3.0, "parada_h": 0.5}
    assert t["por_etapa"]["em_montagem"] == 3.0


def test_totais_com_periodo_cortam_os_intervalos(duas_ops, relogio):
    svc, (a, b) = duas_ops
    A.iniciar(svc, a, "João")  # 08:00
    relogio.avancar(hours=4)
    A.encerrar(svc, "João")  # 12:00
    t = A.totais([svc.carregar(a)], relogio(), desde=datetime(2026, 10, 24, 10, 0))
    assert t["trabalho_h"] == 2.0


def test_aberto_ha_mais_de_10h_e_edicao_pela_gestao(duas_ops, relogio):
    svc, (a, b) = duas_ops
    A.iniciar(svc, a, "João")
    relogio.avancar(hours=11)
    esquecidos = A.abertos_esquecidos(svc.todas_ops(), relogio())
    assert len(esquecidos) == 1 and esquecidos[0]["operador"] == "João"
    ap = esquecidos[0]
    with pytest.raises(OrbitError):
        A.editar(svc, a, ap["id"], "2026-10-24T08:00:00", "2026-10-24T07:00:00", "thiago")
    A.editar(svc, a, ap["id"], "2026-10-24T08:00:00", "2026-10-24T17:00:00", "thiago")
    ap = svc.carregar(a)["apontamentos"][0]
    assert ap["fim"] == "2026-10-24T17:00:00" and ap["editado_por"] == "thiago"
    assert A.abertos_esquecidos(svc.todas_ops(), relogio()) == []


def test_op_planejada_ou_expedida_nao_recebe_apontamento(prod):
    svc, repo, p = prod
    op = svc.criar_op(p.id, {"painel": "X"})
    with pytest.raises(OrbitError):
        A.iniciar(svc, op["id"], "João")


def test_retomar_em_op_bloqueada_nao_perde_a_parada(duas_ops, relogio):
    svc, (a, b) = duas_ops
    A.iniciar(svc, a, "João")
    A.pausar(svc, "João", "Falta de material")
    etapas.bloquear(svc, a, "Falta de material")
    with pytest.raises(OrbitError):
        A.retomar(svc, "João")
    assert A.aberto_do_operador(svc, "João")[1]["tipo"] == "parada"
    with pytest.raises(OrbitError):
        A.iniciar(svc, a, "João")
    assert A.aberto_do_operador(svc, "João")[1]["tipo"] == "parada"


def test_editar_nao_reabre_se_ja_tem_outro_aberto(duas_ops, relogio):
    svc, (a, b) = duas_ops
    A.iniciar(svc, a, "João")
    relogio.avancar(hours=1)
    A.iniciar(svc, b, "João")
    ap = svc.carregar(a)["apontamentos"][0]
    with pytest.raises(OrbitError):
        A.editar(svc, a, ap["id"], ap["inicio"], None, "thiago")
