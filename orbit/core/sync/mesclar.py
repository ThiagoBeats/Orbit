"""Junção por item dos JSONs do Orbit (spec de backup §5, "JSONs").

Regra de 3 vias para campos simples: comparado ao retrato (`base`), quem mudou
vale; se os dois lados mudaram para valores diferentes, é divergência. Sem
retrato, toda diferença é divergência. Enquanto a divergência não é resolvida,
o resultado fica com o valor local.

Revisões são unidas pelo número; histórico é unido sem repetir. Depois da
união, só a revisão de maior número de cada documento fica como atual.

Campos de pasta (`pasta` do container/cliente/documento) ficam com o valor
local: cada lado mantém seus nomes de pasta (o motor ajusta ao gravar).
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from uuid import uuid4

_FALTA = object()

CAMPOS_CONTAINER = ("codigo", "nome", "pedido", "responsavel", "descricao", "situacao",
                    "contatos")
CAMPOS_CLIENTE = ("nome", "cnpj", "contatos")
CAMPOS_REVISAO = ("status", "motivo")

ROTULOS = {
    "codigo": "Código", "nome": "Nome", "pedido": "Nº do pedido",
    "responsavel": "Responsável", "descricao": "Descrição", "situacao": "Situação",
    "contatos": "Contatos", "cnpj": "CNPJ", "status": "Status", "motivo": "Motivo",
    "nao_se_aplica": "Não se aplica", "ativo": "Tipo ativo", "logo_empresa": "Logo da empresa",
}


@dataclass
class Divergencia:
    id: str
    tipo: str  # "campo" | "revisao" | "arquivo" | "pasta_id" | "log"
    escopo_id: str | None
    caminho: str
    chave: str
    descricao: str
    local: dict = field(default_factory=dict)
    backup: dict = field(default_factory=dict)
    acoes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Divergencia":
        return cls(str(d["id"]), str(d["tipo"]), d.get("escopo_id"), str(d.get("caminho", "")),
                   str(d.get("chave", "")), str(d.get("descricao", "")),
                   dict(d.get("local") or {}), dict(d.get("backup") or {}),
                   [str(a) for a in d.get("acoes") or []])


def _nova(tipo, escopo_id, chave, descricao, local, backup, acoes) -> Divergencia:
    return Divergencia(uuid4().hex, tipo, escopo_id, "", chave, descricao, local, backup, acoes)


def _tres_vias(b, l, k):
    """(valor, divergiu). `b` é _FALTA quando não há retrato."""
    if l == k:
        return l, False
    if b is not _FALTA:
        if l == b:
            return k, False
        if k == b:
            return l, False
    return l, True


def _campo(base: dict | None, local: dict, backup: dict, nome: str):
    b = base.get(nome) if base is not None else _FALTA
    return _tres_vias(b, local.get(nome), backup.get(nome))


def _chave_evento(e: dict) -> tuple:
    return (e.get("tipo"), e.get("data_hora"), e.get("usuario"), e.get("computador"),
            json.dumps(e.get("dados", {}), sort_keys=True, ensure_ascii=False))


def _unir_historico(*listas) -> list[dict]:
    vistos, out = set(), []
    for lista in listas:
        for e in lista or []:
            k = _chave_evento(e)
            if k not in vistos:
                vistos.add(k)
                out.append(copy.deepcopy(e))
    return sorted(out, key=lambda e: str(e.get("data_hora", "")))


def _arquivos(rev: dict) -> list:
    return sorted((a.get("nome"), a.get("papel")) for a in rev.get("arquivos") or [])


def _mesclar_documento(cid, tipo, base_doc, loc, bak, divs) -> dict:
    out = copy.deepcopy(loc)
    v, div = _tres_vias(base_doc.get("nao_se_aplica") if base_doc is not None else _FALTA,
                        loc.get("nao_se_aplica", False), bak.get("nao_se_aplica", False))
    out["nao_se_aplica"] = v
    if div:
        divs.append(_nova("campo", cid, f"documentos.{tipo}.nao_se_aplica",
                          f"\"Não se aplica\" diferente no documento {tipo}.",
                          {"valor": loc.get("nao_se_aplica", False)},
                          {"valor": bak.get("nao_se_aplica", False)}, ["local", "backup"]))
    base_revs = ({r["numero"]: r for r in base_doc.get("revisoes") or []}
                 if base_doc is not None else {})
    revs_l = {r["numero"]: r for r in loc.get("revisoes") or []}
    revs_b = {r["numero"]: r for r in bak.get("revisoes") or []}
    juntas = []
    for n in sorted(set(revs_l) | set(revs_b)):
        rl, rb = revs_l.get(n), revs_b.get(n)
        if rl is None or rb is None:
            juntas.append(copy.deepcopy(rl or rb))
            continue
        r = copy.deepcopy(rl)
        if _arquivos(rl) != _arquivos(rb):
            divs.append(_nova(
                "revisao", cid, f"documentos.{tipo}.revisoes.{n}",
                f"Rev{n:02d} do documento {tipo} tem arquivos diferentes nos dois lados.",
                {"revisao": copy.deepcopy(rl), "usuario": rl.get("usuario"),
                 "computador": rl.get("computador"), "data_hora": rl.get("data")},
                {"revisao": copy.deepcopy(rb), "usuario": rb.get("usuario"),
                 "computador": rb.get("computador"), "data_hora": rb.get("data")},
                ["local", "backup", "ambos"]))
        else:
            rbase = base_revs.get(n)
            for campo in CAMPOS_REVISAO:
                v, div = _tres_vias(rbase.get(campo) if rbase is not None else _FALTA,
                                    rl.get(campo), rb.get(campo))
                r[campo] = v
                if div:
                    divs.append(_nova(
                        "campo", cid, f"documentos.{tipo}.revisoes.{n}.{campo}",
                        f"{ROTULOS[campo]} da Rev{n:02d} do documento {tipo} diferente nos "
                        "dois lados.", {"valor": rl.get(campo)}, {"valor": rb.get(campo)},
                        ["local", "backup"]))
        juntas.append(r)
    # atual = a maior revisão que não está arquivada em pelo menos um dos lados
    # (uma revisão antiga registrada com número maior continua antiga)
    ativas = [n for n in set(revs_l) | set(revs_b)
              if any(not r.get("arquivada", False) for r in (revs_l.get(n), revs_b.get(n)) if r)]
    atual = max(ativas, default=None)
    for r in juntas:
        r["arquivada"] = r["numero"] != atual
    out["revisoes"] = juntas
    return out


def mesclar_container(base: dict | None, local: dict, backup: dict
                      ) -> tuple[dict, list[Divergencia]]:
    cid = local.get("id")
    divs: list[Divergencia] = []
    out = copy.deepcopy(local)
    for campo in CAMPOS_CONTAINER:
        v, div = _campo(base, local, backup, campo)
        out[campo] = v
        if div:
            divs.append(_nova("campo", cid, campo, f"{ROTULOS[campo]} diferente nos dois lados.",
                              {"valor": local.get(campo)}, {"valor": backup.get(campo)},
                              ["local", "backup"]))
    docs_base = (base or {}).get("documentos") or {}
    docs_l, docs_b = local.get("documentos") or {}, backup.get("documentos") or {}
    docs = {}
    for tipo in list(docs_l) + [t for t in docs_b if t not in docs_l]:
        dl, db = docs_l.get(tipo), docs_b.get(tipo)
        if dl is None or db is None:
            docs[tipo] = copy.deepcopy(dl or db)
        else:
            docs[tipo] = _mesclar_documento(cid, tipo, docs_base.get(tipo) if base else None,
                                            dl, db, divs)
    out["documentos"] = docs
    out["historico"] = _unir_historico(local.get("historico"), backup.get("historico"))
    return out, divs


def mesclar_cliente(base: dict | None, local: dict, backup: dict
                    ) -> tuple[dict, list[Divergencia]]:
    divs: list[Divergencia] = []
    out = copy.deepcopy(local)
    for campo in CAMPOS_CLIENTE:
        v, div = _campo(base, local, backup, campo)
        out[campo] = v
        if div:
            divs.append(_nova("campo", local.get("id"), campo,
                              f"{ROTULOS[campo]} do cliente diferente nos dois lados.",
                              {"valor": local.get(campo)}, {"valor": backup.get(campo)},
                              ["local", "backup"]))
    return out, divs


def mesclar_config(base: dict | None, local: dict, backup: dict
                   ) -> tuple[dict, list[Divergencia]]:
    divs: list[Divergencia] = []
    out = copy.deepcopy(local)
    tb = {t["id"]: t for t in (base or {}).get("tipos") or []}
    tl = {t["id"]: t for t in local.get("tipos") or []}
    tk = {t["id"]: t for t in backup.get("tipos") or []}
    tipos = []
    for tid in list(tl) + [t for t in tk if t not in tl]:
        a, b = tl.get(tid), tk.get(tid)
        if a is None or b is None:
            tipos.append(copy.deepcopy(a or b))
            continue
        t = copy.deepcopy(a)
        for campo in ("nome", "ativo"):
            v, div = _tres_vias(tb[tid].get(campo) if (base and tid in tb) else _FALTA,
                                a.get(campo), b.get(campo))
            t[campo] = v
            if div:
                divs.append(_nova("campo", None, f"tipos.{tid}.{campo}",
                                  f"{ROTULOS[campo]} do tipo {tid} diferente nos dois lados.",
                                  {"valor": a.get(campo)}, {"valor": b.get(campo)},
                                  ["local", "backup"]))
        tipos.append(t)
    out["tipos"] = tipos
    status = list(local.get("status") or [])
    status += [s for s in backup.get("status") or [] if s not in status]
    out["status"] = status
    v, div = _campo(base, local, backup, "logo_empresa")
    out["logo_empresa"] = v
    if div:
        divs.append(_nova("campo", None, "logo_empresa", "Logo da empresa diferente nos dois lados.",
                          {"valor": local.get("logo_empresa")},
                          {"valor": backup.get("logo_empresa")}, ["local", "backup"]))
    return out, divs


def definir_campo(d: dict, chave: str, valor) -> None:
    partes = chave.split(".")
    alvo = d
    i = 0
    while i < len(partes) - 1:
        p = partes[i]
        if p == "revisoes":
            n = int(partes[i + 1])
            alvo = next(r for r in alvo["revisoes"] if r["numero"] == n)
            i += 2
            continue
        if p == "tipos":
            alvo = next(t for t in alvo["tipos"] if t["id"] == partes[i + 1])
            i += 2
            continue
        alvo = alvo[p]
        i += 1
    alvo[partes[-1]] = copy.deepcopy(valor)


def aplicar_escolha(juntado: dict, div: Divergencia, escolha: str, backup: dict) -> dict:
    """Aplica a escolha de uma divergência de campo ("local" mantém o valor já no juntado)."""
    out = copy.deepcopy(juntado)
    if div.tipo == "campo" and escolha == "backup":
        definir_campo(out, div.chave, div.backup.get("valor"))
    return out
