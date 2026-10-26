"""Etapas da OP, bloqueio e pacote de documentos (spec Produção §4).

O pacote congela, na liberação, a revisão atual de cada documento escolhido.
A produção abre exatamente esses arquivos (mesmo depois de irem para Antigos).
Revisão mais nova no projeto vira alerta; quem gerencia atualiza o pacote.
"""
from __future__ import annotations

from pathlib import Path

from orbit.core.errors import OrbitError
from orbit.core.producao.modelo import ETAPAS, NOMES_ETAPAS, ProducaoService


def _documentos_atuais(svc: ProducaoService, container_id: str) -> dict[str, dict]:
    c = svc.repo.load_container(container_id)
    nomes = {t.id: t.nome for t in svc.repo.config.tipos}
    out = {}
    for tipo, d in c.documentos.items():
        atual = d.atual
        if atual is None or d.nao_se_aplica:
            continue
        out[tipo] = {"tipo_id": tipo, "nome": nomes.get(tipo, tipo), "numero": atual.numero,
                     "principal": atual.principal.nome,
                     "arquivos": [a.nome for a in atual.arquivos], "status": atual.status}
    return out


def _congelar(svc: ProducaoService, op: dict, tipos: list[str] | None) -> list[dict]:
    atuais = _documentos_atuais(svc, op["container_id"])
    if tipos is None:
        escolhidos = list(atuais)
    else:
        if not isinstance(tipos, list) or not all(isinstance(t, str) for t in tipos):
            raise OrbitError("Lista de documentos inválida.")
        faltando = [t for t in tipos if t not in atuais]
        if faltando:
            raise OrbitError("Documento sem revisão emitida: " + ", ".join(faltando))
        escolhidos = tipos
    if not escolhidos:
        raise OrbitError("Nenhum documento emitido para liberar. Envie ao menos o diagrama "
                         "antes de liberar a OP.")
    return [atuais[t] for t in escolhidos]


def liberar(svc: ProducaoService, op_id: str, tipos: list[str] | None = None) -> dict:
    with svc.editar(op_id) as op:
        if op["etapa"] != "planejada":
            raise OrbitError("A OP já foi liberada. Use \"Atualizar pacote\" para trocar revisões.")
        op["pacote"] = _congelar(svc, op, tipos)
        op["pacote_liberado_em"] = svc.agora_iso()
        op["etapa"] = "liberada"
        svc.registrar(op, "pacote_liberado", {"documentos": [
            {"tipo_id": d["tipo_id"], "numero": d["numero"]} for d in op["pacote"]]})
    return op


def alertas_revisao(svc: ProducaoService, op: dict) -> list[dict]:
    """Documentos do pacote que ganharam revisão mais nova no projeto."""
    try:
        atuais = _documentos_atuais(svc, op["container_id"])
    except OrbitError:
        return []
    out = []
    for d in op.get("pacote") or []:
        a = atuais.get(d["tipo_id"])
        if a is not None and a["numero"] > d["numero"]:
            out.append({"tipo_id": d["tipo_id"], "nome": d["nome"], "liberada": d["numero"],
                        "atual": a["numero"]})
    return out


def atualizar_pacote(svc: ProducaoService, op_id: str, tipos: list[str] | None = None) -> dict:
    with svc.editar(op_id) as op:
        if not op.get("pacote"):
            raise OrbitError("A OP ainda não foi liberada.")
        atuais = _documentos_atuais(svc, op["container_id"])
        alvo = tipos if tipos is not None else [d["tipo_id"] for d in op["pacote"]]
        trocas = []
        novo = []
        for d in op["pacote"]:
            a = atuais.get(d["tipo_id"])
            if d["tipo_id"] in alvo and a is not None and a["numero"] != d["numero"]:
                trocas.append({"tipo_id": d["tipo_id"], "de": d["numero"], "para": a["numero"]})
                novo.append(a)
            else:
                novo.append(d)
        op["pacote"] = novo
        svc.registrar(op, "pacote_atualizado", {"trocas": trocas})
    return op


def arquivo_do_pacote(svc: ProducaoService, op_id: str, tipo_id: str) -> Path:
    op = svc.carregar(op_id)
    d = next((x for x in op.get("pacote") or [] if x["tipo_id"] == tipo_id), None)
    if d is None:
        raise OrbitError("Documento fora do pacote desta OP.")
    c = svc.repo.load_container(op["container_id"])
    pasta = svc.repo.doc_path(c, tipo_id)
    for p in (pasta / d["principal"], pasta / "Antigos" / d["principal"]):
        if p.is_file():
            return p
    raise OrbitError(f"Arquivo do pacote não encontrado: {d['principal']}")


def avancar(svc: ProducaoService, op_id: str, usuario: str | None = None) -> dict:
    from orbit.core.producao import testes  # evita import circular
    with svc.editar(op_id) as op:
        if op.get("bloqueio"):
            raise OrbitError(f"OP bloqueada: {op['bloqueio']['motivo']}. Desbloqueie antes.")
        i = ETAPAS.index(op["etapa"])
        if i + 1 >= len(ETAPAS):
            raise OrbitError("A OP já foi expedida.")
        destino = ETAPAS[i + 1]
        if op["etapa"] == "planejada":
            raise OrbitError("Libere o pacote de documentos para mandar a OP à produção.")
        if destino == "verificacao_final":
            pend = testes.pendencias(op, svc.config())
            if pend:
                raise OrbitError("Antes da verificação final: " + "; ".join(pend))
        if destino == "aprovada" and not op["testes"]["verificacao"].get("aprovada"):
            raise OrbitError("A verificação final por amostragem ainda não foi aprovada.")
        op["etapa"] = destino
        svc.registrar(op, "etapa_avancada", {"para": destino}, usuario)
    return op


def voltar(svc: ProducaoService, op_id: str, destino: str, motivo: str,
           usuario: str | None = None) -> dict:
    motivo = motivo.strip() if isinstance(motivo, str) else ""
    if not motivo:
        raise OrbitError("Informe o motivo para voltar a etapa.")
    if destino not in ETAPAS or destino == "planejada":
        raise OrbitError("Etapa inválida.")
    with svc.editar(op_id) as op:
        if ETAPAS.index(destino) >= ETAPAS.index(op["etapa"]):
            raise OrbitError(f"Só é possível voltar para uma etapa anterior a "
                             f"\"{NOMES_ETAPAS[op['etapa']]}\".")
        de = op["etapa"]
        op["etapa"] = destino
        if ETAPAS.index(destino) < ETAPAS.index("aprovada"):
            op["testes"]["verificacao"]["aprovada"] = None
        svc.registrar(op, "etapa_voltada", {"de": de, "para": destino, "motivo": motivo}, usuario)
    return op


def bloquear(svc: ProducaoService, op_id: str, motivo: str, usuario: str | None = None) -> dict:
    motivo = motivo.strip() if isinstance(motivo, str) else ""
    if not motivo:
        raise OrbitError("Informe o motivo do bloqueio.")
    with svc.editar(op_id) as op:
        op["bloqueio"] = {"motivo": motivo, "desde": svc.agora_iso(),
                          "por": usuario or svc.identity.usuario}
        svc.registrar(op, "op_bloqueada", {"motivo": motivo}, usuario)
    return op


def desbloquear(svc: ProducaoService, op_id: str, usuario: str | None = None) -> dict:
    with svc.editar(op_id) as op:
        if op.get("bloqueio"):
            svc.registrar(op, "op_desbloqueada", {"motivo": op["bloqueio"]["motivo"]}, usuario)
        op["bloqueio"] = None
    return op
