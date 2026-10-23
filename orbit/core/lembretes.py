"""Regras dos lembretes (spec Meu dia §4).

Datas: `quando` e `adiado_ate` em "AAAA-MM-DDTHH:MM"; `ultimo_disparo` com segundos.
Recorrência: {"tipo": "nenhuma" | "diaria" | "dias_uteis" | "semanal" | "mensal",
"dias": [0..6] (semanal; 0 = segunda), "dia": 1..31 (mensal: dia original)}.
No mensal, um dia que não existe no mês cai no último dia, e o dia original é
lembrado para os meses seguintes (31/01 → 28/02 → 31/03).
"""
from __future__ import annotations

import calendar
import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from orbit.core.errors import OrbitError

TIPOS_RECORRENCIA = ("nenhuma", "diaria", "dias_uteis", "semanal", "mensal")
ADIAMENTOS_MIN = (10, 60)
_FMT_MIN = "%Y-%m-%dT%H:%M"
_FMT_SEG = "%Y-%m-%dT%H:%M:%S"


def ler_data(texto: str) -> datetime:
    for fmt in (_FMT_MIN, _FMT_SEG):
        try:
            return datetime.strptime(texto, fmt)
        except (TypeError, ValueError):
            continue
    raise OrbitError(f"Data e hora inválidas: {texto}")


@dataclass
class Lembrete:
    id: str
    texto: str
    container_id: str | None
    usuario: str
    quando: str
    recorrencia: dict = field(default_factory=lambda: {"tipo": "nenhuma"})
    adiado_ate: str | None = None
    ultimo_disparo: str | None = None
    ativo: bool = True
    excluido: bool = False
    criado_em: str = ""
    alterado_em: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Lembrete":
        rec = d.get("recorrencia") if isinstance(d.get("recorrencia"), dict) else {}
        return cls(str(d["id"]), str(d.get("texto", "")), d.get("container_id") or None,
                   str(d.get("usuario", "")), str(d["quando"]),
                   dict(rec or {"tipo": "nenhuma"}), d.get("adiado_ate") or None,
                   d.get("ultimo_disparo") or None, bool(d.get("ativo", True)),
                   bool(d.get("excluido", False)), str(d.get("criado_em", "")),
                   str(d.get("alterado_em", "")))

    @property
    def efetivo(self) -> datetime:
        return ler_data(self.adiado_ate or self.quando)


def _somar_mes(t: datetime, dia_base: int) -> datetime:
    ano, mes = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    ultimo = calendar.monthrange(ano, mes)[1]
    return t.replace(year=ano, month=mes, day=min(dia_base, ultimo))


def proximo(quando: datetime, rec: dict, dia_base: int | None = None) -> datetime | None:
    tipo = (rec or {}).get("tipo", "nenhuma")
    if tipo == "diaria":
        return quando + timedelta(days=1)
    if tipo == "dias_uteis":
        t = quando + timedelta(days=1)
        while t.weekday() >= 5:
            t += timedelta(days=1)
        return t
    if tipo == "semanal":
        dias = sorted(set(rec.get("dias") or []))
        if not dias:
            return None
        for n in range(1, 8):
            t = quando + timedelta(days=n)
            if t.weekday() in dias:
                return t
        return None
    if tipo == "mensal":
        return _somar_mes(quando, dia_base or rec.get("dia") or quando.day)
    return None


def avancar_ate_futuro(quando: datetime, rec: dict, agora: datetime) -> datetime | None:
    t = quando
    while t is not None and t <= agora:
        t = proximo(t, rec)
    return t


def vencidos(lista: list[Lembrete], agora: datetime) -> list[Lembrete]:
    out = []
    for lem in lista:
        if not lem.ativo or lem.excluido:
            continue
        efetivo = lem.efetivo
        if efetivo > agora:
            continue
        if lem.ultimo_disparo and ler_data(lem.ultimo_disparo) >= efetivo:
            continue
        out.append(lem)
    return out


def _copia(lem: Lembrete) -> Lembrete:
    novo = copy.deepcopy(lem)
    if novo.recorrencia.get("tipo") == "mensal" and "dia" not in novo.recorrencia:
        novo.recorrencia["dia"] = ler_data(novo.quando).day  # lembra o dia original
    return novo


def _reagendar(lem: Lembrete, agora: datetime) -> None:
    if lem.recorrencia.get("tipo", "nenhuma") == "nenhuma":
        lem.ativo = False
        return
    seguinte = avancar_ate_futuro(ler_data(lem.quando), lem.recorrencia, agora)
    if seguinte is None:
        lem.ativo = False
    else:
        lem.quando = seguinte.strftime(_FMT_MIN)


def marcar_disparado(lem: Lembrete, agora: datetime) -> Lembrete:
    novo = _copia(lem)
    novo.ultimo_disparo = agora.strftime(_FMT_SEG)
    novo.adiado_ate = None
    _reagendar(novo, agora)
    return novo


def adiar(lem: Lembrete, minutos: int, agora: datetime) -> Lembrete:
    if minutos not in ADIAMENTOS_MIN:
        raise OrbitError("Adiamento inválido.")
    novo = _copia(lem)
    novo.adiado_ate = (agora + timedelta(minutes=minutos)).strftime(_FMT_MIN)
    novo.ativo = True
    return novo


def concluir(lem: Lembrete, agora: datetime) -> Lembrete:
    novo = _copia(lem)
    novo.adiado_ate = None
    if novo.recorrencia.get("tipo", "nenhuma") == "nenhuma":
        novo.ativo = False
    elif ler_data(novo.quando) <= agora:
        _reagendar(novo, agora)
    return novo


def validar_recorrencia(rec) -> dict:
    if rec is None:
        return {"tipo": "nenhuma"}
    if not isinstance(rec, dict) or rec.get("tipo") not in TIPOS_RECORRENCIA:
        raise OrbitError("Recorrência inválida.")
    out = {"tipo": rec["tipo"]}
    if rec["tipo"] == "semanal":
        dias = rec.get("dias")
        if (not isinstance(dias, list) or not dias
                or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6
                           for d in dias)):
            raise OrbitError("Escolha os dias da semana do lembrete.")
        out["dias"] = sorted(set(dias))
    return out
