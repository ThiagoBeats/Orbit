"""Apontamentos de trabalho e paradas (spec Produção §4 "Apontamentos").

Ficam em `op["apontamentos"]`. Cada operador tem no máximo um apontamento
aberto em todas as OPs: iniciar outro encerra o anterior. Pausar abre uma
parada com motivo; retomar fecha a parada e abre trabalho na mesma OP.
Horas produtivas = trabalho; ociosidade = paradas (por motivo).
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from orbit.core.errors import OrbitError
from orbit.core.producao.modelo import _FMT, ProducaoService

ETAPAS_COM_APONTAMENTO = ("liberada", "em_montagem", "em_teste", "verificacao_final")
HORAS_ESQUECIDO = 10


def _operador(nome) -> str:
    nome = nome.strip() if isinstance(nome, str) else ""
    if not nome:
        raise OrbitError("Informe o operador.")
    return nome


def _dt(s: str) -> datetime:
    return datetime.strptime(s, _FMT)


def aberto_do_operador(svc: ProducaoService, operador: str) -> tuple[str, dict] | None:
    """(op_id, apontamento) aberto do operador, em qualquer OP."""
    for op in svc.todas_ops():
        for ap in op.get("apontamentos") or []:
            if ap.get("operador") == operador and ap.get("fim") is None:
                return op["id"], ap
    return None


def _fechar_em(svc: ProducaoService, op_id: str, operador: str, obs: str = "") -> dict | None:
    with svc.editar(op_id) as op:
        for ap in op["apontamentos"]:
            if ap["operador"] == operador and ap["fim"] is None:
                ap["fim"] = svc.agora_iso()
                if obs:
                    ap["obs"] = (ap.get("obs") + " | " if ap.get("obs") else "") + obs
                return dict(ap)
    return None


def _validar_alvo(op: dict, tipo: str) -> None:
    if op["etapa"] not in ETAPAS_COM_APONTAMENTO:
        raise OrbitError("Esta OP não está na produção (precisa estar liberada e não "
                         "aprovada/expedida).")
    if tipo == "trabalho" and op.get("bloqueio"):
        raise OrbitError(f"OP bloqueada: {op['bloqueio']['motivo']}. Desbloqueie antes de "
                         "trabalhar nela.")


def _abrir(svc: ProducaoService, op_id: str, operador: str, tipo: str, motivo: str | None,
           obs: str) -> dict:
    with svc.editar(op_id) as op:
        _validar_alvo(op, tipo)
        if op["etapa"] == "liberada" and tipo == "trabalho":
            op["etapa"] = "em_montagem"
            svc.registrar(op, "etapa_avancada", {"para": "em_montagem", "automatico": True},
                          operador)
        ap = {"id": uuid4().hex[:12], "operador": operador, "etapa": op["etapa"], "tipo": tipo,
              "motivo": motivo, "inicio": svc.agora_iso(), "fim": None, "obs": obs or "",
              "editado_por": None, "editado_em": None}
        op["apontamentos"].append(ap)
    return ap


def iniciar(svc: ProducaoService, op_id: str, operador: str, obs: str = "") -> dict:
    operador = _operador(operador)
    _validar_alvo(svc.carregar(op_id), "trabalho")  # antes de encerrar o que está aberto
    atual = aberto_do_operador(svc, operador)
    if atual is not None:
        _fechar_em(svc, atual[0], operador)
    return _abrir(svc, op_id, operador, "trabalho", None, obs)


def pausar(svc: ProducaoService, operador: str, motivo: str, obs: str = "") -> dict:
    operador = _operador(operador)
    if motivo not in svc.config()["motivos_parada"]:
        raise OrbitError("Escolha o motivo da parada.")
    atual = aberto_do_operador(svc, operador)
    if atual is None or atual[1]["tipo"] != "trabalho":
        raise OrbitError("Não há trabalho em andamento para pausar.")
    _validar_alvo(svc.carregar(atual[0]), "parada")
    _fechar_em(svc, atual[0], operador)
    return _abrir(svc, atual[0], operador, "parada", motivo, obs)


def retomar(svc: ProducaoService, operador: str) -> dict:
    operador = _operador(operador)
    atual = aberto_do_operador(svc, operador)
    if atual is None or atual[1]["tipo"] != "parada":
        raise OrbitError("Não há parada em andamento para retomar.")
    _validar_alvo(svc.carregar(atual[0]), "trabalho")
    _fechar_em(svc, atual[0], operador)
    return _abrir(svc, atual[0], operador, "trabalho", None, "")


def encerrar(svc: ProducaoService, operador: str, obs: str = "") -> dict:
    operador = _operador(operador)
    atual = aberto_do_operador(svc, operador)
    if atual is None:
        raise OrbitError("Não há apontamento aberto.")
    return _fechar_em(svc, atual[0], operador, obs)


def editar(svc: ProducaoService, op_id: str, ap_id: str, inicio: str, fim: str | None,
           usuario: str) -> dict:
    """Correção pela gestão (ex.: apontamento esquecido aberto)."""
    usuario = _operador(usuario)
    try:
        ini = _dt(inicio)
        f = _dt(fim) if fim else None
    except (TypeError, ValueError):
        raise OrbitError("Data/hora inválida.") from None
    if f is not None and f <= ini:
        raise OrbitError("O fim precisa ser depois do início.")
    if f is None:
        dono = next((x.get("operador") for x in svc.carregar(op_id)["apontamentos"]
                     if x.get("id") == ap_id), None)
        if any(x.get("fim") is None and x.get("id") != ap_id and x.get("operador") == dono
               for outra in svc.todas_ops() for x in outra.get("apontamentos") or []):
            raise OrbitError("Este operador já tem outro apontamento aberto; informe o fim.")
    with svc.editar(op_id) as op:
        ap = next((x for x in op["apontamentos"] if x["id"] == ap_id), None)
        if ap is None:
            raise OrbitError("Apontamento não encontrado.")
        antes = {"inicio": ap["inicio"], "fim": ap["fim"]}
        ap["inicio"] = ini.strftime(_FMT)
        ap["fim"] = f.strftime(_FMT) if f else None
        ap["editado_por"] = usuario
        ap["editado_em"] = svc.agora_iso()
        svc.registrar(op, "apontamento_editado", {"apontamento": ap_id, "antes": antes,
                                                   "depois": {"inicio": ap["inicio"],
                                                              "fim": ap["fim"]}}, usuario)
    return dict(ap)


# ---------- cálculos ----------
def _horas(ap: dict, agora: datetime, desde: datetime | None, ate: datetime | None) -> float:
    try:
        ini = _dt(ap["inicio"])
        fim = _dt(ap["fim"]) if ap.get("fim") else agora
    except (KeyError, TypeError, ValueError):
        return 0.0
    if desde is not None:
        ini = max(ini, desde)
    if ate is not None:
        fim = min(fim, ate)
    return max(0.0, (fim - ini).total_seconds() / 3600)


def totais(ops: list[dict], agora: datetime, desde: datetime | None = None,
           ate: datetime | None = None) -> dict:
    out = {"trabalho_h": 0.0, "parada_h": 0.0, "por_etapa": {}, "por_operador": {},
           "por_motivo": {}, "por_op": {}}
    for op in ops:
        for ap in op.get("apontamentos") or []:
            h = _horas(ap, agora, desde, ate)
            if h <= 0:
                continue
            chave = "trabalho_h" if ap.get("tipo") == "trabalho" else "parada_h"
            out[chave] += h
            pop = out["por_operador"].setdefault(ap.get("operador") or "?",
                                                 {"trabalho_h": 0.0, "parada_h": 0.0})
            pop[chave] += h
            pop_op = out["por_op"].setdefault(op.get("numero") or op.get("id"),
                                              {"trabalho_h": 0.0, "parada_h": 0.0})
            pop_op[chave] += h
            if chave == "trabalho_h":
                e = ap.get("etapa") or "?"
                out["por_etapa"][e] = out["por_etapa"].get(e, 0.0) + h
            else:
                m = ap.get("motivo") or "Outro"
                out["por_motivo"][m] = out["por_motivo"].get(m, 0.0) + h
    return _arredondar(out)


def _arredondar(x):
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, dict):
        return {k: _arredondar(v) for k, v in x.items()}
    return x


def abertos_esquecidos(ops: list[dict], agora: datetime, horas: float = HORAS_ESQUECIDO) -> list:
    out = []
    for op in ops:
        for ap in op.get("apontamentos") or []:
            if ap.get("fim") is None and _horas(ap, agora, None, None) > horas:
                out.append({**ap, "op_id": op["id"], "op_numero": op.get("numero"),
                            "painel": op.get("painel"),
                            "aberto_h": round(_horas(ap, agora, None, None), 1)})
    return out
