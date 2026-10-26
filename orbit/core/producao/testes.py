"""Testes do painel, não conformidades e verificação final (spec Produção §2/§4).

Blocos: inspeção de rotina (IEC 61439-1 §11), ponto a ponto com aperto,
isolação, energização (passos + tensões) e entradas/saídas. Marcar "nc"
exige o tipo da NC, que é aberta junto. A NC só fecha com reteste
(verificada); aí a linha de origem passa a "ok".

Verificação final: amostragem das ligações por pessoa diferente de quem
marcou o ponto a ponto. Falha → NC, OP volta para "Em teste" e o ponto a
ponto é zerado (o anterior fica guardado).
"""
from __future__ import annotations

import math
import random
from uuid import uuid4

from orbit.core.errors import OrbitError
from orbit.core.producao.modelo import ProducaoService

RESULTADOS = ("ok", "nc", "na")
NOMES_BLOCOS = {"inspecao": "Inspeção de rotina (IEC 61439)", "ponto_a_ponto": "Ponto a ponto",
                "isolacao": "Isolação", "energizacao": "Energização", "io": "Entradas e saídas"}
CHECKLIST_FINAL = ["Identificação de fios e componentes conferida",
                   "Aperto marcado (torque mark) nos bornes conferidos",
                   "Tampas, canaletas e proteções instaladas",
                   "Documentação na porta e placa de identificação"]


def _id() -> str:
    return uuid4().hex[:12]


def _operador(nome) -> str:
    nome = nome.strip() if isinstance(nome, str) else ""
    if not nome:
        raise OrbitError("Informe o operador.")
    return nome


def _resultado(r, permitidos=RESULTADOS):
    if r not in permitidos:
        raise OrbitError("Resultado inválido.")
    return r


def _achar(lista: list[dict], item_id: str, rotulo: str) -> dict:
    it = next((x for x in lista if x.get("id") == item_id), None)
    if it is None:
        raise OrbitError(f"{rotulo} não encontrado.")
    return it


# ---------- NCs ----------
def _nova_nc(svc: ProducaoService, op: dict, tipo, descricao: str, origem: dict,
             operador: str) -> dict:
    tipos = svc.config()["tipos_nc"]
    if tipo not in tipos:
        raise OrbitError("Escolha o tipo da não conformidade.")
    numero = max((n["numero"] for n in op["ncs"]), default=0) + 1
    nc = {"id": _id(), "numero": numero, "tipo": tipo, "descricao": descricao or "",
          "origem": origem, "aberta_por": operador, "aberta_em": svc.agora_iso(),
          "situacao": "aberta", "corrigida_por": None, "corrigida_em": None,
          "correcao": "", "verificada_por": None, "verificada_em": None}
    op["ncs"].append(nc)
    svc.registrar(op, "nc_aberta", {"numero": numero, "tipo": tipo}, operador)
    return nc


def abrir_nc(svc: ProducaoService, op_id: str, tipo: str, descricao: str, operador: str,
             origem: dict | None = None) -> dict:
    operador = _operador(operador)
    with svc.editar(op_id) as op:
        return _nova_nc(svc, op, tipo, descricao, origem or {"bloco": "manual"}, operador)


def corrigir_nc(svc: ProducaoService, op_id: str, nc_id: str, operador: str,
                correcao: str = "") -> dict:
    operador = _operador(operador)
    with svc.editar(op_id) as op:
        nc = _achar(op["ncs"], nc_id, "Não conformidade")
        if nc["situacao"] != "aberta":
            raise OrbitError("Esta não conformidade não está aberta.")
        nc.update(situacao="corrigida", corrigida_por=operador, corrigida_em=svc.agora_iso(),
                  correcao=correcao or "")
        svc.registrar(op, "nc_corrigida", {"numero": nc["numero"]}, operador)
    return nc


def _marcar_origem_ok(op: dict, origem: dict) -> None:
    bloco, lid = origem.get("bloco"), origem.get("linha_id")
    t = op["testes"]
    lista = {"inspecao": t["inspecao"]["itens"], "ponto_a_ponto": t["ponto_a_ponto"]["linhas"],
             "isolacao": t["isolacao"]["circuitos"], "io": t["io"]["sinais"],
             "energizacao": t["energizacao"]["pontos"] + t["energizacao"]["passos"]}.get(bloco)
    item = next((x for x in lista or [] if x.get("id") == lid), None)
    if item is None:
        return
    for medida in ("medido_mohm", "medido_v"):
        if medida in item and item.get("resultado") == "nc":
            # medição reprovada: o reteste é uma nova medição (o valor antigo fica na NC)
            item.update({medida: None, "resultado": None, "por": None, "em": None})
            return
    for campo in ("resultado", "ligacao", "aperto"):
        if item.get(campo) == "nc":
            item[campo] = "ok"


def verificar_nc(svc: ProducaoService, op_id: str, nc_id: str, operador: str) -> dict:
    """Reteste aprovado: fecha a NC e a linha de origem passa a "ok"."""
    operador = _operador(operador)
    with svc.editar(op_id) as op:
        nc = _achar(op["ncs"], nc_id, "Não conformidade")
        if nc["situacao"] != "corrigida":
            raise OrbitError("Registre a correção antes do reteste.")
        nc.update(situacao="verificada", verificada_por=operador, verificada_em=svc.agora_iso())
        _marcar_origem_ok(op, nc.get("origem") or {})
        svc.registrar(op, "nc_verificada", {"numero": nc["numero"]}, operador)
    return nc


def _marca(svc: ProducaoService, op: dict, item: dict, resultado: str, operador: str,
           obs: str, nc_tipo, bloco: str, campo: str = "resultado") -> None:
    ja_era_nc = item.get(campo) == "nc"
    item[campo] = resultado
    item["obs"] = obs or item.get("obs", "")
    item["por"] = operador
    item["em"] = svc.agora_iso()
    if resultado == "nc" and not ja_era_nc:
        _nova_nc(svc, op, nc_tipo, obs, {"bloco": bloco, "linha_id": item["id"]}, operador)


# ---------- A. inspeção ----------
def itens_inspecao(svc: ProducaoService, op_id: str) -> list[dict]:
    op = svc.carregar(op_id)
    if op["testes"]["inspecao"]["itens"]:
        return op["testes"]["inspecao"]["itens"]
    with svc.editar(op_id) as op:
        if not op["testes"]["inspecao"]["itens"]:
            op["testes"]["inspecao"]["itens"] = [
                {"id": _id(), "ref": i["ref"], "texto": i["texto"], "resultado": None, "obs": "",
                 "por": None, "em": None} for i in svc.config()["checklist_iec"]]
        return op["testes"]["inspecao"]["itens"]


def marcar_inspecao(svc, op_id, item_id, resultado, operador, obs="", nc_tipo=None) -> dict:
    operador, resultado = _operador(operador), _resultado(resultado)
    with svc.editar(op_id) as op:
        item = _achar(op["testes"]["inspecao"]["itens"], item_id, "Item")
        _marca(svc, op, item, resultado, operador, obs, nc_tipo, "inspecao")
    return item


# ---------- B. ponto a ponto ----------
def carregar_ponto_a_ponto(svc, op_id, linhas: list[dict], substituir: bool = False) -> int:
    if not isinstance(linhas, list) or not linhas:
        raise OrbitError("A lista de conexões está vazia.")
    novas = []
    for l in linhas:
        origem, destino = str(l.get("origem") or "").strip(), str(l.get("destino") or "").strip()
        if not origem or not destino:
            continue
        novas.append({"id": _id(), "origem": origem, "destino": destino,
                      "fio": str(l.get("fio") or ""), "secao": str(l.get("secao") or ""),
                      "cor": str(l.get("cor") or ""), "ligacao": None, "aperto": None,
                      "obs": "", "por": None, "em": None})
    if not novas:
        raise OrbitError("Nenhuma linha com origem e destino na lista.")
    with svc.editar(op_id) as op:
        pp = op["testes"]["ponto_a_ponto"]
        marcadas = any(l["ligacao"] or l["aperto"] for l in pp["linhas"])
        if marcadas and not substituir:
            raise OrbitError("O ponto a ponto já começou. Confirme para substituir a lista "
                             "(a anterior fica guardada no histórico).")
        if pp["linhas"]:
            pp["anteriores"].append({"em": svc.agora_iso(), "linhas": pp["linhas"]})
        pp["linhas"] = novas
        pp["importado_em"] = svc.agora_iso()
        svc.registrar(op, "ponto_a_ponto_carregado", {"linhas": len(novas)})
    return len(novas)


def marcar_ligacao(svc, op_id, linha_id, ligacao, aperto, operador, obs="", nc_tipo=None) -> dict:
    operador = _operador(operador)
    for v in (ligacao, aperto):
        if v not in (None, "ok", "nc"):
            raise OrbitError("Resultado inválido.")
    with svc.editar(op_id) as op:
        linha = _achar(op["testes"]["ponto_a_ponto"]["linhas"], linha_id, "Ligação")
        nova_nc = "nc" in (ligacao, aperto) and "nc" not in (linha["ligacao"], linha["aperto"])
        linha.update(ligacao=ligacao, aperto=aperto, por=operador, em=svc.agora_iso(),
                     obs=obs or linha.get("obs", ""))
        if nova_nc:
            tipo = nc_tipo or ("Aperto/borne solto" if aperto == "nc" and ligacao != "nc"
                               else None)
            _nova_nc(svc, op, tipo, obs or f"{linha['origem']} → {linha['destino']}",
                     {"bloco": "ponto_a_ponto", "linha_id": linha_id}, operador)
    return linha


# ---------- C. isolação ----------
def adicionar_circuito(svc, op_id, nome: str, tensao_v) -> dict:
    nome = nome.strip() if isinstance(nome, str) else ""
    if not nome:
        raise OrbitError("Informe o circuito.")
    if isinstance(tensao_v, bool) or not isinstance(tensao_v, (int, float)) or tensao_v <= 0:
        raise OrbitError("Tensão de ensaio inválida.")
    c = {"id": _id(), "nome": nome, "tensao_v": tensao_v, "medido_mohm": None,
         "resultado": None, "por": None, "em": None, "obs": ""}
    with svc.editar(op_id) as op:
        op["testes"]["isolacao"]["circuitos"].append(c)
    return c


def medir_isolacao(svc, op_id, circuito_id, medido_mohm, operador, obs="") -> dict:
    operador = _operador(operador)
    if isinstance(medido_mohm, bool) or not isinstance(medido_mohm, (int, float)) \
            or medido_mohm < 0:
        raise OrbitError("Valor medido inválido.")
    minimo = float(svc.config()["isolacao_min_mohm"])
    with svc.editar(op_id) as op:
        c = _achar(op["testes"]["isolacao"]["circuitos"], circuito_id, "Circuito")
        c["medido_mohm"] = medido_mohm
        _marca(svc, op, c, "ok" if medido_mohm >= minimo else "nc", operador,
               obs or (f"{medido_mohm} MΩ < {minimo} MΩ" if medido_mohm < minimo else ""),
               "Isolação", "isolacao")
    return c


# ---------- D. energização ----------
def passos_energizacao(svc, op_id) -> list[dict]:
    op = svc.carregar(op_id)
    if op["testes"]["energizacao"]["passos"]:
        return op["testes"]["energizacao"]["passos"]
    with svc.editar(op_id) as op:
        if not op["testes"]["energizacao"]["passos"]:
            op["testes"]["energizacao"]["passos"] = [
                {"id": _id(), "texto": t, "resultado": None, "obs": "", "por": None, "em": None}
                for t in svc.config()["passos_energizacao"]]
        return op["testes"]["energizacao"]["passos"]


def marcar_passo(svc, op_id, passo_id, resultado, operador, obs="", nc_tipo=None) -> dict:
    operador, resultado = _operador(operador), _resultado(resultado)
    with svc.editar(op_id) as op:
        p = _achar(op["testes"]["energizacao"]["passos"], passo_id, "Passo")
        _marca(svc, op, p, resultado, operador, obs, nc_tipo, "energizacao")
    return p


def adicionar_ponto_tensao(svc, op_id, nome: str, esperado_v) -> dict:
    nome = nome.strip() if isinstance(nome, str) else ""
    if not nome:
        raise OrbitError("Informe o ponto de medição.")
    if isinstance(esperado_v, bool) or not isinstance(esperado_v, (int, float)) or esperado_v <= 0:
        raise OrbitError("Tensão esperada inválida.")
    p = {"id": _id(), "nome": nome, "esperado_v": esperado_v, "medido_v": None,
         "resultado": None, "obs": "", "por": None, "em": None}
    with svc.editar(op_id) as op:
        op["testes"]["energizacao"]["pontos"].append(p)
    return p


def medir_tensao(svc, op_id, ponto_id, medido_v, operador, obs="") -> dict:
    operador = _operador(operador)
    if isinstance(medido_v, bool) or not isinstance(medido_v, (int, float)):
        raise OrbitError("Valor medido inválido.")
    tol = float(svc.config()["tolerancia_tensao_pct"]) / 100
    with svc.editar(op_id) as op:
        p = _achar(op["testes"]["energizacao"]["pontos"], ponto_id, "Ponto")
        p["medido_v"] = medido_v
        ok = abs(medido_v - p["esperado_v"]) <= p["esperado_v"] * tol
        _marca(svc, op, p, "ok" if ok else "nc", operador,
               obs or ("" if ok else f"{medido_v} V fora de {p['esperado_v']} V ±{tol:.0%}"),
               "Função/lógica", "energizacao")
    return p


# ---------- E. entradas e saídas ----------
def carregar_io(svc, op_id, sinais: list[dict], substituir: bool = False) -> int:
    novos = [{"id": _id(), "tag": str(s.get("tag") or "").strip(),
              "descricao": str(s.get("descricao") or ""), "endereco": str(s.get("endereco") or ""),
              "tipo": str(s.get("tipo") or ""), "resultado": None, "obs": "", "por": None,
              "em": None} for s in sinais or [] if str(s.get("tag") or "").strip()]
    if not novos:
        raise OrbitError("Nenhum sinal com tag na lista.")
    with svc.editar(op_id) as op:
        io = op["testes"]["io"]
        if any(s["resultado"] for s in io["sinais"]) and not substituir:
            raise OrbitError("O teste de entradas e saídas já começou. Confirme para substituir.")
        if io["sinais"]:
            io.setdefault("anteriores", []).append({"em": svc.agora_iso(), "sinais": io["sinais"]})
        io["sinais"] = novos
        io["importado_em"] = svc.agora_iso()
        svc.registrar(op, "io_carregado", {"sinais": len(novos)})
    return len(novos)


def marcar_sinal(svc, op_id, sinal_id, resultado, operador, obs="", nc_tipo=None) -> dict:
    operador, resultado = _operador(operador), _resultado(resultado)
    with svc.editar(op_id) as op:
        s = _achar(op["testes"]["io"]["sinais"], sinal_id, "Sinal")
        _marca(svc, op, s, resultado, operador, obs, nc_tipo or "Função/lógica", "io")
    return s


# ---------- situação e pendências ----------
def situacao(op: dict, cfg: dict) -> dict:
    t = op["testes"]

    def resumo(itens, feito, obrigatorio):
        total = len(itens)
        feitos = sum(1 for i in itens if feito(i))
        mexidos = any(i.get("resultado") or i.get("ligacao") or i.get("aperto") for i in itens)
        nc = sum(1 for i in itens if "nc" in (i.get("resultado"), i.get("ligacao"),
                                              i.get("aperto")))
        estado = ("concluido" if total and feitos == total else
                  "em_andamento" if mexidos else "nao_iniciado")
        return {"estado": estado, "total": total, "feitos": feitos, "nc": nc,
                "obrigatorio": obrigatorio}

    feito = lambda i: i.get("resultado") is not None
    return {
        "inspecao": resumo(t["inspecao"]["itens"], feito, True),
        "ponto_a_ponto": resumo(t["ponto_a_ponto"]["linhas"],
                                lambda l: l["ligacao"] is not None and l["aperto"] is not None,
                                bool(t["ponto_a_ponto"]["linhas"])),
        "isolacao": resumo(t["isolacao"]["circuitos"], feito, True),
        "energizacao": resumo(t["energizacao"]["passos"] + t["energizacao"]["pontos"], feito,
                              False),
        "io": resumo(t["io"]["sinais"], feito, bool(t["io"]["sinais"])),
    }


def pendencias(op: dict, cfg: dict) -> list[str]:
    out = []
    for bloco, st in situacao(op, cfg).items():
        if st["obrigatorio"] and st["estado"] != "concluido":
            falta = "não iniciado" if st["total"] == 0 else f"{st['feitos']}/{st['total']}"
            out.append(f"{NOMES_BLOCOS[bloco]} incompleto ({falta})")
    abertas = [n for n in op["ncs"] if n["situacao"] != "verificada"]
    if abertas:
        out.append(f"{len(abertas)} não conformidade(s) sem reteste")
    return out


# ---------- verificação final por amostragem ----------
def sortear_amostra(svc, op_id, verificador, rnd: random.Random | None = None) -> dict:
    verificador = _operador(verificador)
    cfg = svc.config()
    with svc.editar(op_id) as op:
        if op["etapa"] != "verificacao_final":
            raise OrbitError("A OP precisa estar na etapa \"Verificação final\".")
        linhas = op["testes"]["ponto_a_ponto"]["linhas"]
        quem_testou = {l["por"] for l in linhas if l.get("por")}
        if verificador.casefold() in {q.casefold() for q in quem_testou}:
            raise OrbitError("A verificação final precisa ser feita por outra pessoa, diferente "
                             "de quem fez o ponto a ponto.")
        v_atual = op["testes"]["verificacao"]
        if v_atual.get("concluida") and v_atual.get("aprovada"):
            raise OrbitError("A verificação final desta OP já foi aprovada.")
        operadores = [o for o in cfg.get("operadores") or [] if isinstance(o, dict)]
        if operadores and not any(
                str(o.get("nome", "")).casefold() == verificador.casefold() and o.get("verifica")
                for o in operadores):
            raise OrbitError(f"{verificador} não está habilitado para a verificação final "
                             "(Configurações → Produção).")
        n = len(linhas)
        k = min(n, max(int(cfg["amostragem_min"]), math.ceil(n * cfg["amostragem_pct"] / 100)))
        escolhidas = (rnd or random.SystemRandom()).sample([l["id"] for l in linhas], k)
        v = op["testes"]["verificacao"]
        v.update(sorteadas=escolhidas, verificador=verificador, resultados={},
                 checklist=[{"texto": t, "resultado": None} for t in CHECKLIST_FINAL],
                 concluida=False, aprovada=None, sorteada_em=svc.agora_iso())
        svc.registrar(op, "amostra_sorteada", {"ligacoes": k}, verificador)
        return v


def _verificacao_do(op: dict, verificador: str) -> dict:
    v = op["testes"]["verificacao"]
    if op["etapa"] != "verificacao_final" or not v.get("sorteadas"):
        raise OrbitError("A OP precisa estar na etapa \"Verificação final\" com a amostra sorteada.")
    if v.get("concluida"):
        raise OrbitError("Esta verificação já foi concluída. Para refazer, sorteie uma nova amostra.")
    if not v.get("verificador") or v["verificador"].casefold() != verificador.casefold():
        raise OrbitError("Sorteie a amostra com o seu nome antes de verificar.")
    return v


def marcar_amostra(svc, op_id, linha_id, resultado, verificador, obs="") -> None:
    verificador, resultado = _operador(verificador), _resultado(resultado, ("ok", "nc"))
    with svc.editar(op_id) as op:
        v = _verificacao_do(op, verificador)
        if linha_id not in v["sorteadas"]:
            raise OrbitError("Ligação fora da amostra.")
        v["resultados"][linha_id] = {"resultado": resultado, "obs": obs or ""}


def marcar_checklist_final(svc, op_id, indice: int, resultado, verificador) -> None:
    verificador, resultado = _operador(verificador), _resultado(resultado, ("ok", "nc"))
    with svc.editar(op_id) as op:
        v = _verificacao_do(op, verificador)
        if isinstance(indice, bool) or not isinstance(indice, int) \
                or not 0 <= indice < len(v["checklist"]):
            raise OrbitError("Item inválido.")
        v["checklist"][indice]["resultado"] = resultado


def concluir_verificacao(svc, op_id, verificador) -> dict:
    verificador = _operador(verificador)
    with svc.editar(op_id) as op:
        v = _verificacao_do(op, verificador)
        faltam = [l for l in v["sorteadas"] if l not in v["resultados"]]
        if faltam or any(c["resultado"] is None for c in v["checklist"]):
            raise OrbitError("Confira todas as ligações sorteadas e o checklist final.")
        falhas = [l for l, r in v["resultados"].items() if r["resultado"] == "nc"]
        falhas_check = [c["texto"] for c in v["checklist"] if c["resultado"] == "nc"]
        v["concluida"] = True
        v["historico"].append({"em": svc.agora_iso(), "verificador": verificador,
                               "falhas": len(falhas) + len(falhas_check)})
        if not falhas and not falhas_check:
            v["aprovada"] = True
            svc.registrar(op, "verificacao_aprovada", {}, verificador)
            return op
        v["aprovada"] = False
        linhas = {l["id"]: l for l in op["testes"]["ponto_a_ponto"]["linhas"]}
        for lid in falhas:
            l = linhas.get(lid, {})
            _nova_nc(svc, op, "Fio/ligação trocada",
                     v["resultados"][lid]["obs"] or f"{l.get('origem')} → {l.get('destino')}",
                     {"bloco": "verificacao", "linha_id": lid}, verificador)
        for texto in falhas_check:
            _nova_nc(svc, op, "Outro", texto, {"bloco": "verificacao"}, verificador)
        pp = op["testes"]["ponto_a_ponto"]
        if falhas:  # erro na amostra: revisão completa do ponto a ponto
            pp["anteriores"].append({"em": svc.agora_iso(), "linhas": pp["linhas"]})
            pp["linhas"] = [dict(l, ligacao=None, aperto=None, por=None, em=None)
                            for l in pp["linhas"]]
        op["etapa"] = "em_teste"
        svc.registrar(op, "etapa_voltada", {"de": "verificacao_final", "para": "em_teste",
                                            "motivo": "Falha na verificação por amostragem"},
                      verificador)
    return op
