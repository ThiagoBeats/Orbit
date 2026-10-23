from datetime import datetime, timedelta

import pytest

from orbit.core.errors import OrbitError
from orbit.core.lembretes import (Lembrete, adiar, avancar_ate_futuro, concluir,
                                  marcar_disparado, proximo, vencidos)
from tests.core.test_meudia import amb  # noqa: F401  (fixture)

D = datetime


def _l(quando, rec=None, **kw):
    return Lembrete("id1", "Texto", None, "thiago", quando.strftime("%Y-%m-%dT%H:%M"),
                    rec or {"tipo": "nenhuma"}, criado_em="x", alterado_em="x", **kw)


def test_proximo_diario_e_dias_uteis():
    assert proximo(D(2026, 10, 23, 9, 0), {"tipo": "diaria"}) == D(2026, 10, 24, 9, 0)
    sexta = D(2026, 10, 23, 9, 0)  # 23/10/2026 é sexta-feira
    assert sexta.weekday() == 4
    assert proximo(sexta, {"tipo": "dias_uteis"}) == D(2026, 10, 26, 9, 0)
    assert proximo(D(2026, 10, 26, 9, 0), {"tipo": "dias_uteis"}) == D(2026, 10, 27, 9, 0)
    assert proximo(sexta, {"tipo": "nenhuma"}) is None


def test_semanal_nos_dias_escolhidos():
    rec = {"tipo": "semanal", "dias": [0, 2]}  # segunda e quarta
    seg = D(2026, 10, 26, 8, 0)
    assert proximo(seg, rec) == D(2026, 10, 28, 8, 0)
    assert proximo(D(2026, 10, 28, 8, 0), rec) == D(2026, 11, 2, 8, 0)


def test_mensal_dia_31_vai_para_o_ultimo_dia():
    rec = {"tipo": "mensal"}
    q = D(2026, 3, 31, 10, 0)
    q = proximo(q, rec)
    assert q == D(2026, 4, 30, 10, 0)
    assert proximo(q, rec, dia_base=31) == D(2026, 5, 31, 10, 0)
    assert proximo(D(2028, 1, 31, 10, 0), rec) == D(2028, 2, 29, 10, 0)
    assert proximo(D(2027, 1, 31, 10, 0), rec) == D(2027, 2, 28, 10, 0)


def test_mensal_lembra_o_dia_original():
    lem = _l(D(2026, 1, 31, 10, 0), {"tipo": "mensal"})
    lem = marcar_disparado(lem, D(2026, 1, 31, 10, 0, 5))
    assert lem.quando == "2026-02-28T10:00"
    lem = marcar_disparado(lem, D(2026, 2, 28, 10, 0, 5))
    assert lem.quando == "2026-03-31T10:00"


def test_vencido_uma_vez_so():
    lem = _l(D(2026, 10, 23, 9, 0))
    agora = D(2026, 10, 23, 9, 0, 30)
    assert vencidos([lem], agora) == [lem]
    lem = marcar_disparado(lem, agora)
    assert vencidos([lem], agora + timedelta(minutes=5)) == []
    assert lem.ativo is False


def test_suspenso_por_horas_dispara_uma_vez_e_avanca():
    lem = _l(D(2026, 10, 20, 9, 0), {"tipo": "diaria"})
    agora = D(2026, 10, 23, 15, 0)
    assert len(vencidos([lem], agora)) == 1
    lem = marcar_disparado(lem, agora)
    assert lem.quando == "2026-10-24T09:00" and lem.ativo
    assert vencidos([lem], agora + timedelta(minutes=1)) == []


def test_adiar_10_e_60():
    lem = marcar_disparado(_l(D(2026, 10, 23, 9, 0)), D(2026, 10, 23, 9, 0))
    agora = D(2026, 10, 23, 9, 1)
    lem = adiar(lem, 10, agora)
    assert lem.ativo and lem.efetivo == D(2026, 10, 23, 9, 11)
    assert vencidos([lem], D(2026, 10, 23, 9, 10)) == []
    assert vencidos([lem], D(2026, 10, 23, 9, 11)) == [lem]
    assert adiar(lem, 60, agora).efetivo == D(2026, 10, 23, 10, 1)


def test_adiar_valor_invalido():
    with pytest.raises(OrbitError):
        adiar(_l(D(2026, 10, 23, 9, 0)), 7, D(2026, 10, 23, 9, 0))


def test_concluir_nao_recorrente_desativa():
    lem = adiar(_l(D(2026, 10, 23, 9, 0)), 10, D(2026, 10, 23, 9, 0))
    lem = concluir(lem, D(2026, 10, 23, 9, 2))
    assert lem.ativo is False and lem.adiado_ate is None
    rec = concluir(_l(D(2026, 10, 23, 9, 0), {"tipo": "diaria"}), D(2026, 10, 23, 9, 2))
    assert rec.ativo and rec.quando == "2026-10-24T09:00"


def test_avancar_ate_futuro():
    assert avancar_ate_futuro(D(2026, 10, 1, 8, 0), {"tipo": "diaria"},
                              D(2026, 10, 23, 12, 0)) == D(2026, 10, 24, 8, 0)


def test_salvar_lembrete_valida(amb):  # noqa: F811
    svc, repo, p, *_ = amb
    l = svc.salvar_lembrete({"texto": "Reunião", "quando": "2026-10-23T14:00",
                             "recorrencia": {"tipo": "semanal", "dias": [0, 4]},
                             "container_id": p.id})
    assert [x.id for x in svc.lembretes()] == [l.id]
    l2 = svc.salvar_lembrete({"id": l.id, "texto": "Reunião 2", "quando": "2026-10-23T15:00",
                              "recorrencia": {"tipo": "nenhuma"}})
    assert l2.id == l.id and svc.lembretes()[0].texto == "Reunião 2"
    for ruim in ({"texto": "", "quando": "2026-10-23T14:00"},
                 {"texto": "x", "quando": "amanhã"},
                 {"texto": "x", "quando": "2026-10-23T14:00", "recorrencia": {"tipo": "anual"}},
                 {"texto": "x", "quando": "2026-10-23T14:00",
                  "recorrencia": {"tipo": "semanal", "dias": [7]}},
                 {"texto": "x", "quando": "2026-10-23T14:00",
                  "recorrencia": {"tipo": "semanal", "dias": []}}):
        with pytest.raises(OrbitError):
            svc.salvar_lembrete(ruim)
    svc.excluir_lembrete(l.id)
    assert svc.lembretes() == []


def test_aplicar_grava(amb):  # noqa: F811
    svc, *_ = amb
    l = svc.salvar_lembrete({"texto": "x", "quando": "2026-10-23T09:00"})
    svc.aplicar(l.id, lambda lem: adiar(lem, 10, D(2026, 10, 23, 9, 0)))
    assert svc.lembretes()[0].adiado_ate == "2026-10-23T09:10"
