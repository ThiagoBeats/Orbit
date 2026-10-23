"""Resolução das divergências de sincronização (spec de backup §5, "Divergências").

Nada é apagado: a versão descartada vai para `_Divergências/<data-hora>/` no
lado onde foi descartada. Tudo acontece sob a trava de sincronização do backup
e, para projetos/máquinas, sob a trava do container nos dois lados.
"""
from __future__ import annotations

import copy
import os
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from orbit.core.config import SharedConfig, load_shared_config
from orbit.core.errors import OrbitError
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.models import Container
from orbit.core.repository import ARQ_CLIENTE, Repository
from orbit.core.revisions import _nomes_finais
from orbit.core.sync.mesclar import (Divergencia, definir_campo, mesclar_cliente,
                                     mesclar_container)
from orbit.core.sync.motor import (SyncEngine, _Lado, copiar_seguro,
                                   guardar_em_divergencias, mover_seguro)
from orbit.core.sync.varredura import CONFIG_REL, excluido

MOTIVO_AMBOS = "Divergência de sincronização"


class _Ctx:
    def __init__(self, eng: SyncEngine):
        self.eng = eng
        self.L, self.B = _Lado(eng.base, "local"), _Lado(eng.backup, "backup")
        self.L.descobrir()
        self.B.descobrir()
        self.repo_l = Repository(eng.base, eng.identity, load_shared_config(eng.base))
        self.repo_b = Repository(eng.backup, eng.identity, SharedConfig.default())
        self.carimbo = eng.agora().strftime("%Y-%m-%d_%H%M%S")

    def lado(self, nome: str) -> _Lado:
        return self.L if nome == "local" else self.B

    def repo(self, nome: str) -> Repository:
        return self.repo_l if nome == "local" else self.repo_b


def resolver(eng: SyncEngine, div_id: str, escolha: str) -> None:
    pendentes = eng.retrato.divergencias_pendentes()
    bruta = next((d for d in pendentes if d.get("id") == div_id), None)
    if bruta is None:
        raise OrbitError("Divergência não encontrada (talvez já tenha sido resolvida). "
                         "Sincronize de novo para atualizar a lista.")
    div = Divergencia.from_dict(bruta)
    if escolha not in div.acoes:
        raise OrbitError("Ação inválida para esta divergência.")
    if not eng.backup.is_dir():
        raise OrbitError(f"Backup inacessível: {eng.backup}")
    with eng.trava_sincronizacao():
        ctx = _Ctx(eng)
        {"campo": _campo, "revisao": _revisao, "arquivo": _arquivo,
         "pasta_id": _pasta_id, "log": lambda c, d, e: None}[div.tipo](ctx, div, escolha)
        eng.retrato.salvar_divergencias([d for d in pendentes if d.get("id") != div_id])
        eng._logar("divergencia_resolvida", {"tipo": div.tipo, "chave": div.chave,
                                             "caminho": div.caminho, "escolha": escolha})
        eng.juntar_logs()


# ---------- campo ----------
def _arquivos_do_escopo(ctx: _Ctx, div: Divergencia) -> tuple[Path, Path, str | None]:
    nome = div.caminho.rsplit("/", 1)[-1].casefold()
    if div.caminho.casefold() == CONFIG_REL:
        return ctx.L.caminho(CONFIG_REL), ctx.B.caminho(CONFIG_REL), None
    if nome == ARQ_CLIENTE:
        rl, rb = ctx.L.clientes.get(div.escopo_id), ctx.B.clientes.get(div.escopo_id)
        if not rl or not rb:
            raise OrbitError("O cliente não existe mais nos dois lados.")
        return ctx.L.caminho(f"{rl}/{ARQ_CLIENTE}"), ctx.B.caminho(f"{rb}/{ARQ_CLIENTE}"), None
    rl, rb = ctx.L.containers.get(div.escopo_id), ctx.B.containers.get(div.escopo_id)
    if not rl or not rb:
        raise OrbitError("O projeto ou máquina não existe mais nos dois lados.")
    return (ctx.L.caminho(f"{rl[0]}/{rl[1]}"), ctx.B.caminho(f"{rb[0]}/{rb[1]}"),
            div.escopo_id)


def _travas(ctx: _Ctx, pilha: ExitStack, cid_l: str | None, cid_b: str | None = None):
    if cid_l:
        pilha.enter_context(ctx.repo_l.trava_container(cid_l))
    if cid_b or cid_l:
        pilha.enter_context(ctx.repo_b.trava_container(cid_b or cid_l))


def _campo(ctx: _Ctx, div: Divergencia, escolha: str):
    valor = (div.local if escolha == "local" else div.backup).get("valor")
    arq_l, arq_b, cid = _arquivos_do_escopo(ctx, div)
    with ExitStack() as pilha:
        _travas(ctx, pilha, cid)
        for arq in (arq_l, arq_b):
            d = read_json(arq)
            definir_campo(d, div.chave, valor)
            write_json_atomic(arq, d)


# ---------- revisão ----------
def _localizar(lado: _Lado, rel: str, pasta: str, nome: str) -> Path | None:
    for p in (lado.caminho(f"{rel}/{pasta}/{nome}"), lado.caminho(f"{rel}/{pasta}/Antigos/{nome}")):
        if p.is_file():
            return p
    return None


def _destino(lado: _Lado, rel: str, pasta: str, nome: str, arquivada: bool) -> Path:
    return lado.caminho(f"{rel}/{pasta}/Antigos/{nome}" if arquivada else f"{rel}/{pasta}/{nome}")


def _rel(lado: _Lado, p: Path) -> str:
    return p.relative_to(lado.raiz).as_posix()


def _rev(doc: dict, n: int) -> dict:
    r = next((r for r in doc.get("revisoes") or [] if r["numero"] == n), None)
    if r is None:
        raise OrbitError(f"A Rev{n:02d} não existe mais nos dois lados.")
    return r


def _ajustar_atuais(ctx: _Ctx, lado: _Lado, rel: str, doc: dict) -> None:
    """Recalcula a revisão atual e leva para Antigos os arquivos das que deixaram de ser."""
    maior = max((r["numero"] for r in doc["revisoes"]), default=None)
    for r in doc["revisoes"]:
        arquivada = r["numero"] != maior
        if arquivada:
            for a in r.get("arquivos") or []:
                atual = lado.caminho(f"{rel}/{doc['pasta']}/{a['nome']}")
                if atual.is_file():
                    mover_seguro(atual, _destino(lado, rel, doc["pasta"], a["nome"], True))
        r["arquivada"] = arquivada


def _revisao(ctx: _Ctx, div: Divergencia, escolha: str):
    _, tipo, _, n = div.chave.split(".")
    n = int(n)
    cid = div.escopo_id
    rl, rb = ctx.L.containers.get(cid), ctx.B.containers.get(cid)
    if not rl or not rb:
        raise OrbitError("O projeto ou máquina não existe mais nos dois lados.")
    rels = {"local": rl[0], "backup": rb[0]}
    arqs = {"local": ctx.L.caminho(f"{rl[0]}/{rl[1]}"), "backup": ctx.B.caminho(f"{rb[0]}/{rb[1]}")}
    with ExitStack() as pilha:
        _travas(ctx, pilha, cid)
        js = {k: read_json(v) for k, v in arqs.items()}
        docs = {k: js[k]["documentos"][tipo] for k in js}
        revs = {k: _rev(docs[k], n) for k in js}
        if escolha in ("local", "backup"):
            w, x = escolha, ("backup" if escolha == "local" else "local")
            lw, lx = ctx.lado(w), ctx.lado(x)
            origens = []
            for a in revs[w]["arquivos"]:
                src = _localizar(lw, rels[w], docs[w]["pasta"], a["nome"])
                if src is None:
                    raise OrbitError(f"Arquivo \"{a['nome']}\" não encontrado em {w}.")
                origens.append((src, a["nome"]))
            for a in revs[x]["arquivos"]:
                p = _localizar(lx, rels[x], docs[x]["pasta"], a["nome"])
                if p is not None:
                    guardar_em_divergencias(lx.raiz, _rel(lx, p), ctx.carimbo)
            for src, nome in origens:
                copiar_seguro(src, _destino(lx, rels[x], docs[x]["pasta"], nome,
                                            revs[x].get("arquivada", False)))
            nova = copy.deepcopy(revs[w])
            nova["arquivada"] = revs[x].get("arquivada", False)
            docs[x]["revisoes"] = [nova if r["numero"] == n else r for r in docs[x]["revisoes"]]
            write_json_atomic(arqs[x], js[x])
            return
        # "ambos": a versão do backup vira a próxima revisão livre, nos dois lados
        m = max(r["numero"] for k in js for r in docs[k]["revisoes"]) + 1
        rb_ = revs["backup"]
        principal = next(a for a in rb_["arquivos"] if a["papel"] == "principal")
        editaveis = [a for a in rb_["arquivos"] if a["papel"] != "principal"]
        hoje = ctx.eng.agora().date()
        nome_p, nomes_e = _nomes_finais(ctx.repo_l, Container.from_dict(js["local"]), tipo,
                                        Path(principal["nome"]), [Path(a["nome"]) for a in editaveis],
                                        m, hoje)
        novos = [(principal["nome"], nome_p, "principal")] + [
            (a["nome"], ne, a["papel"]) for a, ne in zip(editaveis, nomes_e)]
        fontes = {}
        for velho, _, _ in novos:
            src = _localizar(ctx.B, rels["backup"], docs["backup"]["pasta"], velho)
            if src is None:
                raise OrbitError(f"Arquivo \"{velho}\" não encontrado no backup.")
            fontes[velho] = src
        # 1. cópias da versão do backup como Rev m (nos dois lados)
        for k in ("local", "backup"):
            for velho, novo, _ in novos:
                copiar_seguro(fontes[velho], _destino(ctx.lado(k), rels[k], docs[k]["pasta"],
                                                      novo, False))
        # 2. no backup, a Rev n passa a ser a versão local (a do backup já virou Rev m)
        locais = []
        for a in revs["local"]["arquivos"]:
            src = _localizar(ctx.L, rels["local"], docs["local"]["pasta"], a["nome"])
            if src is None:
                raise OrbitError(f"Arquivo \"{a['nome']}\" não encontrado localmente.")
            locais.append((src, a["nome"]))
        for velho in fontes.values():
            guardar_em_divergencias(ctx.B.raiz, _rel(ctx.B, velho), ctx.carimbo)
        for src, nome in locais:
            copiar_seguro(src, _destino(ctx.B, rels["backup"], docs["backup"]["pasta"], nome, True))
        docs["backup"]["revisoes"] = [copy.deepcopy(revs["local"]) if r["numero"] == n else r
                                      for r in docs["backup"]["revisoes"]]
        nova = {"numero": m, "data": hoje.isoformat(), "status": rb_.get("status", ""),
                "motivo": MOTIVO_AMBOS, "usuario": rb_.get("usuario", ""),
                "computador": rb_.get("computador", ""),
                "arquivos": [{"nome": novo, "papel": papel} for _, novo, papel in novos],
                "arquivada": False}
        for k in ("local", "backup"):
            docs[k]["revisoes"].append(copy.deepcopy(nova))
            _ajustar_atuais(ctx, ctx.lado(k), rels[k], docs[k])
            write_json_atomic(arqs[k], js[k])


# ---------- arquivo solto ----------
def _arquivo(ctx: _Ctx, div: Divergencia, escolha: str):
    rel = div.caminho
    pl, pb = ctx.L.caminho(rel), ctx.B.caminho(rel)
    if not pl.is_file() or not pb.is_file():
        raise OrbitError(f"O arquivo \"{rel}\" não existe mais nos dois lados.")
    if escolha == "local":
        guardar_em_divergencias(ctx.B.raiz, rel, ctx.carimbo)
        copiar_seguro(pl, pb)
    elif escolha == "backup":
        guardar_em_divergencias(ctx.L.raiz, rel, ctx.carimbo)
        copiar_seguro(pb, pl)
    else:  # ambos: a versão do backup fica ao lado, com outro nome, nos dois lados
        p = Path(rel)
        novo = p.with_name(f"{p.stem} (backup {ctx.carimbo}){p.suffix}").as_posix()
        mover_seguro(pb, ctx.B.caminho(novo))
        copiar_seguro(ctx.B.caminho(novo), ctx.L.caminho(novo))
        copiar_seguro(pl, pb)


# ---------- pasta com ids diferentes ----------
def _livre(lado: _Lado, rel: str) -> str:
    n = 2
    while lado.caminho(f"{rel} ({n})").exists():
        n += 1
    return f"{rel} ({n})"


def _copiar_pasta(origem: _Lado, rel_o: str, destino: _Lado, rel_d: str, nome_json: str,
                  pasta_json: str):
    """Copia a pasta inteira (sem travas/temporários) e ajusta o campo "pasta" do JSON."""
    raiz = origem.caminho(rel_o)
    arquivos = sorted((p for p in raiz.rglob("*") if p.is_file()),
                      key=lambda p: (p.name.casefold() == nome_json, str(p)))
    for p in arquivos:
        sub = p.relative_to(raiz).as_posix()
        if excluido(f"{rel_o}/{sub}"):
            continue
        alvo = destino.caminho(f"{rel_d}/{sub}")
        if sub.casefold() == nome_json:
            d = read_json(p)
            d["pasta"] = pasta_json
            if os.path.lexists(alvo):
                raise OrbitError(f"Já existe \"{alvo}\". Nada foi sobrescrito.")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(alvo, d)
        else:
            copiar_seguro(p, alvo)


def _pasta_id(ctx: _Ctx, div: Divergencia, escolha: str):
    rel, nome_json = div.caminho.rsplit("/", 1)
    id_l, id_b = div.local.get("id"), div.backup.get("id")
    eh_cliente = div.chave == "cliente"
    indice_l = ctx.L.clientes if eh_cliente else ctx.L.containers
    indice_b = ctx.B.clientes if eh_cliente else ctx.B.containers
    if id_l in indice_b or id_b in indice_l:
        return  # já resolvida por outra ação (ex.: o cliente inteiro foi copiado)
    if escolha == "ambos":
        rel_b2 = _livre(ctx.B, rel)
        rel_l2 = _livre(ctx.L, rel)
        _copiar_pasta(ctx.L, rel, ctx.B, rel_b2, nome_json, rel_b2.rsplit("/", 1)[-1])
        _copiar_pasta(ctx.B, rel, ctx.L, rel_l2, nome_json, rel_l2.rsplit("/", 1)[-1])
        return
    # "juntar": fica o id desta máquina
    if eh_cliente:
        arq_l, arq_b = ctx.L.caminho(f"{rel}/{nome_json}"), ctx.B.caminho(f"{rel}/{nome_json}")
        jl, jb = read_json(arq_l), read_json(arq_b)
        junto, _ = mesclar_cliente(None, jl, jb)
        para_b = dict(junto, pasta=jb.get("pasta", junto.get("pasta")))
        write_json_atomic(arq_l, junto)
        guardar_em_divergencias(ctx.B.raiz, f"{rel}/{nome_json}", ctx.carimbo)
        write_json_atomic(arq_b, para_b)
        for cid, (crel, cnome) in ctx.B.containers.items():
            arq = ctx.B.caminho(f"{crel}/{cnome}")
            with ctx.repo_b.trava_container(cid):
                d = read_json(arq)
                if d.get("cliente_id") == id_b:
                    d["cliente_id"] = id_l
                    write_json_atomic(arq, d)
        return
    arq_l, arq_b = ctx.L.caminho(f"{rel}/{nome_json}"), ctx.B.caminho(f"{rel}/{nome_json}")
    with ExitStack() as pilha:
        _travas(ctx, pilha, id_l, id_b)
        jl, jb = read_json(arq_l), read_json(arq_b)
        junto, _ = mesclar_container(None, jl, jb)
        # revisões que só existem no backup: traz os arquivos para a pasta local
        for tipo, doc in junto["documentos"].items():
            doc_l = (jl.get("documentos") or {}).get(tipo)
            doc_b = (jb.get("documentos") or {}).get(tipo)
            if doc_b is None:
                continue
            nums_l = {r["numero"] for r in (doc_l or {}).get("revisoes") or []}
            pasta_l = (doc_l or doc)["pasta"]
            for r in doc_b.get("revisoes") or []:
                if r["numero"] in nums_l:
                    continue
                for a in r.get("arquivos") or []:
                    src = _localizar(ctx.B, rel, doc_b["pasta"], a["nome"])
                    if src is not None:
                        copiar_seguro(src, _destino(ctx.L, rel, pasta_l, a["nome"], False))
            doc["pasta"] = pasta_l
            _ajustar_atuais(ctx, ctx.L, rel, doc)
        write_json_atomic(arq_l, junto)
    # o projeto do backup (com o outro id) vai inteiro para _Divergências
    guardar_em_divergencias(ctx.B.raiz, rel, ctx.carimbo)
    _copiar_pasta(ctx.L, rel, ctx.B, rel, nome_json, rel.rsplit("/", 1)[-1])
