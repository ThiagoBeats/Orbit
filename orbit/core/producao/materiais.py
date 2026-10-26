"""Lista de materiais da OP (spec Produção §4 "Materiais").

Situação: pendente → solicitado → recebido → separado, ou falta (com
observação e previsão opcional). Substituir a lista guarda a anterior.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from orbit.core.errors import OrbitError
from orbit.core.producao.modelo import ProducaoService

SITUACOES = ("pendente", "solicitado", "recebido", "separado", "falta")
NOMES_SITUACOES = {"pendente": "Pendente", "solicitado": "Solicitado", "recebido": "Recebido",
                   "separado": "Separado", "falta": "Falta"}


def _qtd(v) -> float | int:
    if isinstance(v, bool):
        raise OrbitError("Quantidade inválida.")
    if isinstance(v, (int, float)):
        q = v
    else:
        s = str(v or "").strip().replace(" ", "")
        if not s:
            return 1
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            q = float(s)
        except ValueError:
            raise OrbitError(f"Quantidade inválida: {v}") from None
    if q < 0:
        raise OrbitError("Quantidade inválida.")
    return int(q) if float(q).is_integer() else q


def _item(d: dict) -> dict | None:
    texto = lambda k: str(d.get(k) or "").strip()
    if not texto("descricao") and not texto("codigo"):
        return None
    return {"id": uuid4().hex[:12], "codigo": texto("codigo"), "descricao": texto("descricao"),
            "quantidade": _qtd(d.get("quantidade")), "unidade": texto("unidade"),
            "fabricante": texto("fabricante"), "situacao": "pendente", "obs": "",
            "previsao": None, "atualizado_por": None, "atualizado_em": None}


def importar(svc: ProducaoService, op_id: str, itens: list[dict], substituir: bool = False) -> int:
    if not isinstance(itens, list):
        raise OrbitError("Lista de materiais inválida.")
    novos = [x for x in (_item(d) for d in itens if isinstance(d, dict)) if x]
    if not novos:
        raise OrbitError("Nenhum item com código ou descrição na lista.")
    with svc.editar(op_id) as op:
        if op["materiais"] and not substituir:
            raise OrbitError("A OP já tem lista de materiais. Confirme para substituir "
                             "(a anterior fica guardada).")
        if op["materiais"]:
            op.setdefault("materiais_anteriores", []).append(
                {"em": svc.agora_iso(), "itens": op["materiais"]})
        op["materiais"] = novos
        svc.registrar(op, "materiais_importados", {"itens": len(novos)})
    return len(novos)


def adicionar(svc: ProducaoService, op_id: str, dados: dict) -> dict:
    it = _item(dados if isinstance(dados, dict) else {})
    if it is None:
        raise OrbitError("Informe a descrição ou o código do item.")
    with svc.editar(op_id) as op:
        op["materiais"].append(it)
    return it


def mudar_situacao(svc: ProducaoService, op_id: str, ids: list[str], situacao: str,
                   usuario: str, obs: str = "", previsao: str | None = None) -> int:
    if situacao not in SITUACOES:
        raise OrbitError("Situação inválida.")
    if not isinstance(ids, list) or not ids:
        raise OrbitError("Selecione ao menos um item.")
    if previsao:
        try:
            date.fromisoformat(previsao)
        except (TypeError, ValueError):
            raise OrbitError("Previsão inválida.") from None
    usuario = usuario.strip() if isinstance(usuario, str) else ""
    with svc.editar(op_id) as op:
        alvo = [m for m in op["materiais"] if m["id"] in set(ids)]
        if not alvo:
            raise OrbitError("Item não encontrado.")
        for m in alvo:
            m["situacao"] = situacao
            m["atualizado_por"] = usuario or svc.identity.usuario
            m["atualizado_em"] = svc.agora_iso()
            if situacao == "falta":
                m["obs"] = obs or m.get("obs", "")
                m["previsao"] = previsao or None
            else:
                m["previsao"] = None
                if obs:
                    m["obs"] = obs
        if situacao == "falta":
            svc.registrar(op, "material_em_falta",
                          {"itens": [m["codigo"] or m["descricao"] for m in alvo]}, usuario)
    return len(alvo)


def resumo(op: dict) -> dict:
    out = {s: 0 for s in SITUACOES}
    for m in op.get("materiais") or []:
        out[m.get("situacao", "pendente")] = out.get(m.get("situacao", "pendente"), 0) + 1
    out["total"] = len(op.get("materiais") or [])
    return out


def faltas(op: dict) -> list[dict]:
    return [m for m in op.get("materiais") or [] if m.get("situacao") == "falta"]
