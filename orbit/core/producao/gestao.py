"""Indicadores da produção e cartões da fila (spec Produção §5 "Gestão")."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from orbit.core.producao import apontamentos as A
from orbit.core.producao import etapas, materiais
from orbit.core.producao.modelo import ETAPAS, NOMES_ETAPAS, ProducaoService
from orbit.core.producao.testes import pendencias, situacao

ETAPAS_FINAIS = ("aprovada", "expedida")


def atrasada(op: dict, hoje: date) -> bool:
    if not op.get("prazo") or op["etapa"] in ETAPAS_FINAIS:
        return False
    try:
        return date.fromisoformat(op["prazo"]) < hoje
    except ValueError:
        return False


def cartao(svc: ProducaoService, op: dict, hoje: date, cfg: dict | None = None,
           alertas: bool = True) -> dict:
    cfg = cfg or svc.config()
    rm = materiais.resumo(op)
    return {
        "id": op["id"], "numero": op["numero"], "painel": op["painel"],
        "descricao": op.get("descricao", ""), "container_id": op["container_id"],
        "container_nome": op.get("container_nome"), "cliente_nome": op.get("cliente_nome"),
        "etapa": op["etapa"], "nome_etapa": NOMES_ETAPAS.get(op["etapa"], op["etapa"]),
        "prioridade": op.get("prioridade", "normal"), "prazo": op.get("prazo"),
        "quantidade": op.get("quantidade", 1), "responsavel": op.get("responsavel", ""),
        "atrasada": atrasada(op, hoje), "bloqueio": op.get("bloqueio"),
        "faltas": rm["falta"], "materiais_total": rm["total"],
        "ncs_abertas": sum(1 for n in op["ncs"] if n["situacao"] != "verificada"),
        "revisao_nova": len(etapas.alertas_revisao(svc, op)) if alertas else 0,
        "trabalhando": sorted({a["operador"] for a in op.get("apontamentos") or []
                               if a.get("fim") is None and a.get("tipo") == "trabalho"}),
        "parados": sorted({a["operador"] for a in op.get("apontamentos") or []
                           if a.get("fim") is None and a.get("tipo") == "parada"}),
        "testes": situacao(op, cfg),
        "pendencias": pendencias(op, cfg) if op["etapa"] == "em_teste" else [],
    }


def fila(svc: ProducaoService, hoje: date | None = None, incluir_expedidas: bool = False):
    hoje = hoje or svc.agora().date()
    cfg = svc.config()
    out = []
    for op in svc.todas_ops():
        if op["etapa"] == "expedida" and not incluir_expedidas:
            continue
        out.append(cartao(svc, op, hoje, cfg))
    peso = {"urgente": 0, "alta": 1, "normal": 2}
    out.sort(key=lambda c: (peso.get(c["prioridade"], 3), c["prazo"] or "9999", c["numero"]))
    return out


def indicadores(svc: ProducaoService, agora: datetime | None = None) -> dict:
    agora = agora or svc.agora()
    hoje = agora.date()
    ops = svc.todas_ops()
    inicio_semana = datetime.combine(hoje - timedelta(days=hoje.weekday()), datetime.min.time())
    por_etapa = {e: 0 for e in ETAPAS}
    for op in ops:
        por_etapa[op["etapa"]] = por_etapa.get(op["etapa"], 0) + 1
    ref = lambda op: {"id": op["id"], "numero": op["numero"], "painel": op["painel"],
                      "container_nome": op.get("container_nome"), "prazo": op.get("prazo"),
                      "etapa": op["etapa"], "nome_etapa": NOMES_ETAPAS.get(op["etapa"])}
    faltas = []
    for op in ops:
        if op["etapa"] == "expedida":
            continue
        for m in materiais.faltas(op):
            faltas.append({**ref(op), "item": m})
    pareto: dict[str, int] = {}
    for op in ops:
        for n in op["ncs"]:
            pareto[n["tipo"]] = pareto.get(n["tipo"], 0) + 1
    return {
        "por_etapa": [{"etapa": e, "nome": NOMES_ETAPAS[e], "n": por_etapa.get(e, 0)}
                      for e in ETAPAS],
        "atrasadas": [ref(op) for op in ops if atrasada(op, hoje)],
        "bloqueadas": [{**ref(op), "bloqueio": op["bloqueio"]} for op in ops
                       if op.get("bloqueio") and op["etapa"] != "expedida"],
        "semana": A.totais(ops, agora, desde=inicio_semana),
        "geral": A.totais(ops, agora),
        "faltas": faltas,
        "pareto_nc": sorted(({"tipo": k, "n": v} for k, v in pareto.items()),
                            key=lambda x: (-x["n"], x["tipo"])),
        "ncs_abertas": sum(1 for op in ops for n in op["ncs"] if n["situacao"] != "verificada"),
        "esquecidos": A.abertos_esquecidos(ops, agora),
        "em_andamento": [{**ap, "op_id": op["id"], "op_numero": op["numero"],
                          "painel": op["painel"]} for op in ops
                         for ap in op.get("apontamentos") or [] if ap.get("fim") is None],
    }
