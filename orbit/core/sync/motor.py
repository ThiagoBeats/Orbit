"""Motor da sincronização em duas vias entre a pasta base e o backup (spec de backup §5).

Ordem de uma sincronização:
1. trava de sincronização no backup (`.orbit/travas/_sincronizacao.lock`);
2. varredura dos dois lados (com cache de hash) e descoberta de clientes,
   projetos e máquinas pelo `id` do JSON;
3. clientes; 4. projetos/máquinas (um por vez, com a trava do container nos
   dois lados; com upload em andamento o container é pulado);
5. configuração; 6. demais arquivos (não controlados pelo Orbit);
7. log de ações; 8. retrato.

Regras que nunca mudam: nada é apagado nem sobrescrito. Cópias entre lados usam
temporário + `os.rename`; mover só para `Antigos` ou `_Divergências`.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from orbit.core.actionlog import ActionLog, LinhaLog, _ler_arquivo, mesclar_logs, verificar_linhas
from orbit.core.config import SharedConfig
from orbit.core.errors import ArquivoEmUso, LockHeld, OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.meudia import _travar_com_espera, mesclar_por_id
from orbit.core.presence import MAX_IDADE_TRAVA_S, PresenceService
from orbit.core.repository import (ARQ_CLIENTE, ARQ_MAQUINA, ARQ_PROJETO, PASTA_CLIENTES,
                                   PASTA_MAQUINAS, Repository)
from orbit.core.revisions import _recusar_copia
from orbit.core.sync.mesclar import (Divergencia, definir_campo, mesclar_cliente,
                                     mesclar_config, mesclar_container)
from orbit.core.sync.varredura import (CONFIG_REL, LOG_REL, PASTA_DIVERGENCIAS, InfoArquivo,
                                       Retrato, eh_json_orbit, varrer)

TRAVA_SYNC = "_sincronizacao"
LISTAS_POR_ID = ("notas", "itens", "lembretes")


def _unido_por_id(rel: str) -> bool:
    """anotacoes.json (pasta de projeto) e .orbit/usuarios/<x>/meu_dia.json."""
    partes = rel.casefold().split("/")
    if partes[-1] == "anotacoes.json":
        return True
    return (len(partes) == 4 and partes[0] == ".orbit" and partes[1] == "usuarios"
            and partes[3] == "meu_dia.json")
RENOVAR_TRAVA_S = 60  # a trava de sincronização é renovada enquanto a rodada dura
TRAVA_CONTAINER = "_container"


# ---------- operações seguras de arquivo ----------
def copiar_seguro(origem: Path, destino: Path) -> None:
    """Copia sem nunca sobrescrever: temporário na pasta de destino + os.rename."""
    destino = Path(destino)
    if os.path.lexists(destino):
        raise OrbitError(f"Já existe \"{destino.name}\" no destino. Nada foi sobrescrito.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.parent / f"~orbit-{uuid4().hex}.tmp"
    try:
        shutil.copy2(origem, tmp)
        os.rename(tmp, destino)  # no Windows falha se o destino surgiu no meio-tempo
    except BaseException:
        try:
            if os.path.lexists(tmp):
                os.unlink(tmp)  # só a nossa própria cópia temporária
        except OSError:
            pass
        raise


def mover_seguro(origem: Path, destino: Path) -> None:
    """Move no mesmo volume, sem sobrescrever e sem o fallback copiar+apagar."""
    destino = Path(destino)
    if os.path.lexists(destino):
        raise OrbitError(f"Já existe \"{destino.name}\" no destino. Nada foi sobrescrito.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino), copy_function=_recusar_copia)


def guardar_em_divergencias(raiz: Path, rel: str, carimbo: str) -> Path:
    """Move `raiz/rel` para `raiz/_Divergências/<carimbo>/<rel>` (nunca apaga)."""
    destino = Path(raiz) / PASTA_DIVERGENCIAS / carimbo / rel
    n = 2
    while os.path.lexists(destino):
        destino = Path(raiz) / PASTA_DIVERGENCIAS / f"{carimbo}-{n}" / rel
        n += 1
    mover_seguro(Path(raiz) / rel, destino)
    return destino


# ---------- resultados ----------
@dataclass
class Comparacao:
    enviar: list[str] = field(default_factory=list)
    receber: list[str] = field(default_factory=list)
    restaurar_local: list[str] = field(default_factory=list)
    restaurar_backup: list[str] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)
    divergencias: list[Divergencia] = field(default_factory=list)
    identico: bool = True

    def to_dict(self) -> dict:
        return {"enviar": self.enviar, "receber": self.receber,
                "restaurar_local": self.restaurar_local,
                "restaurar_backup": self.restaurar_backup, "containers": self.containers,
                "divergencias": [d.to_dict() for d in self.divergencias],
                "identico": self.identico}


@dataclass
class ResultadoSync:
    enviados: int = 0
    recebidos: int = 0
    restaurados: int = 0
    divergencias: list[Divergencia] = field(default_factory=list)
    pulados: list[str] = field(default_factory=list)
    cancelado: bool = False
    erro: str | None = None

    def to_dict(self) -> dict:
        return {"enviados": self.enviados, "recebidos": self.recebidos,
                "restaurados": self.restaurados,
                "divergencias": [d.to_dict() for d in self.divergencias],
                "pulados": self.pulados, "cancelado": self.cancelado, "erro": self.erro}


class _BackupInacessivel(Exception):
    pass


class _Cancelado(Exception):
    pass


class _Lado:
    """Um lado da sincronização: o que existe nele, indexado por id."""

    def __init__(self, raiz: Path, nome: str):
        self.raiz = Path(raiz)
        self.nome = nome  # "local" ou "backup"
        self.clientes: dict[str, str] = {}               # id -> pasta relativa
        self.containers: dict[str, tuple[str, str]] = {}  # id -> (pasta relativa, nome do JSON)
        self.json_ilegiveis: list[str] = []
        self.arquivos: dict[str, InfoArquivo] = {}

    def _id(self, arq: Path) -> str | None:
        try:
            v = read_json(arq).get("id")
        except (OrbitDataError, AttributeError):
            self.json_ilegiveis.append(arq.relative_to(self.raiz).as_posix())
            return None
        return v if isinstance(v, str) and v else None

    def descobrir(self) -> None:
        clientes = self.raiz / PASTA_CLIENTES
        if clientes.is_dir():
            for f in sorted(clientes.glob(f"*/{ARQ_CLIENTE}")):
                i = self._id(f)
                if i:
                    self.clientes[i] = f.parent.relative_to(self.raiz).as_posix()
            for f in sorted(clientes.glob(f"*/*/{ARQ_PROJETO}")):
                i = self._id(f)
                if i:
                    self.containers[i] = (f.parent.relative_to(self.raiz).as_posix(), ARQ_PROJETO)
        maquinas = self.raiz / PASTA_MAQUINAS
        if maquinas.is_dir():
            for f in sorted(maquinas.glob(f"*/{ARQ_MAQUINA}")):
                i = self._id(f)
                if i:
                    self.containers[i] = (f.parent.relative_to(self.raiz).as_posix(), ARQ_MAQUINA)

    def caminho(self, rel: str) -> Path:
        return self.raiz / rel


def _com_valores_do_backup(junto: dict, divs: list[Divergencia], jb: dict) -> dict:
    """Versão a gravar no backup: o juntado, mas com o valor do próprio backup em cada
    item ainda em divergência (enquanto não resolvida, nenhum lado perde o seu valor)."""
    para_b = copy.deepcopy(junto)
    for d in divs:
        if d.tipo == "campo":
            definir_campo(para_b, d.chave, d.backup.get("valor"))
        elif d.tipo == "revisao":
            _, tipo, _, n = d.chave.split(".")
            doc_b = (jb.get("documentos") or {}).get(tipo) or {}
            rev_b = next((r for r in doc_b.get("revisoes") or [] if r["numero"] == int(n)), None)
            doc = para_b["documentos"].get(tipo)
            if rev_b is not None and doc is not None:
                doc["revisoes"] = [dict(copy.deepcopy(rev_b), arquivada=r.get("arquivada", False))
                                   if r["numero"] == int(n) else r for r in doc["revisoes"]]
    return para_b


def _escrever_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(caminho, dados)


class SyncEngine:
    def __init__(self, base: Path, backup: Path, identity: Identity, retrato: Retrato,
                 log: ActionLog | None, agora: Callable[[], datetime] = datetime.now,
                 registrar: Callable[[BaseException], None] | None = None,
                 caches: dict | None = None):
        self.base = Path(base)
        self.backup = Path(backup)
        self.identity = identity
        self.retrato = retrato
        self.log = log
        self.agora = agora
        self.registrar = registrar
        # cache de hash por lado; o BackupService passa o mesmo dict entre rodadas
        self._caches = caches if caches is not None else {}
        self._caches.setdefault("l", {})
        self._caches.setdefault("b", {})

    @property
    def _cache_l(self) -> dict:
        return self._caches["l"]

    @_cache_l.setter
    def _cache_l(self, v: dict) -> None:
        self._caches["l"] = v

    @property
    def _cache_b(self) -> dict:
        return self._caches["b"]

    @_cache_b.setter
    def _cache_b(self, v: dict) -> None:
        self._caches["b"] = v

    # ---------- API ----------
    def comparar(self, cancelar: Callable[[], bool] = lambda: False,
                 progresso: Callable[[str, int, int], None] = lambda f, a, t: None
                 ) -> Comparacao:
        if not self.backup.is_dir():
            raise OrbitError(f"Backup inacessível: {self.backup}")
        exe = _Execucao(self, aplicar=False, cancelar=cancelar, progresso=progresso,
                        somente=None)
        exe.rodar()
        c = exe.comp
        c.divergencias = exe.res.divergencias
        c.identico = not (c.enviar or c.receber or c.restaurar_local or c.restaurar_backup
                          or c.containers or c.divergencias)
        return c

    def sincronizar(self, cancelar: Callable[[], bool] = lambda: False,
                    progresso: Callable[[str, int, int], None] = lambda f, a, t: None,
                    somente_container: str | None = None) -> ResultadoSync:
        if not self.backup.is_dir():
            return ResultadoSync(erro=f"Backup inacessível: {self.backup}")
        with self.trava_sincronizacao():
            exe = _Execucao(self, aplicar=True, cancelar=cancelar, progresso=progresso,
                            somente=somente_container)
            exe.rodar()
            return exe.res

    @contextmanager
    def trava_sincronizacao(self) -> Iterator[None]:
        """Uma sincronização (ou resolução) por backup de cada vez."""
        svc = PresenceService(self.identity, agora=datetime.now, registrar=self.registrar)
        trava = self._travar_sync(svc)
        parar = threading.Event()

        def renovar():
            while not parar.wait(RENOVAR_TRAVA_S):
                try:
                    if not svc.renovar(trava):
                        return
                except Exception as e:
                    if self.registrar:
                        self.registrar(e)
        t = threading.Thread(target=renovar, daemon=True, name="orbit-renova-sync")
        t.start()
        try:
            yield
        finally:
            parar.set()
            t.join(5)
            svc.liberar_varios([trava])

    def juntar_logs(self) -> None:
        """Só a junção do log de ações (chamar com a trava de sincronização)."""
        exe = _Execucao(self, aplicar=True, cancelar=lambda: False,
                        progresso=lambda f, a, t: None, somente=None)
        exe._log()

    def _travar_sync(self, svc: PresenceService):
        lock = svc.caminho_trava(self.backup, TRAVA_SYNC)
        for _ in range(2):
            try:
                return svc.travar(self.backup, TRAVA_SYNC)
            except LockHeld:
                if svc.trava_abandonada(lock, MAX_IDADE_TRAVA_S):
                    svc.liberar_abandonada(lock, MAX_IDADE_TRAVA_S)
                    continue
                info = svc._ler_trava(lock)
                quem = f"{info.usuario} ({info.computador})" if info else "Outra pessoa"
                erro = LockHeld(f"{quem} está sincronizando com este backup; "
                                "tente em instantes.")
                erro.tipo_id = TRAVA_SYNC
                erro.abandonada = False
                raise erro from None
        raise OrbitError("Não foi possível obter a trava de sincronização.")

    def _logar(self, acao: str, detalhes: dict) -> None:
        if self.log is None:
            return
        try:
            self.log.registrar_acao(acao, detalhes)
        except Exception as e:
            if self.registrar:
                self.registrar(e)


class _Execucao:
    """Uma rodada de comparação (aplicar=False) ou sincronização (aplicar=True)."""

    def __init__(self, eng: SyncEngine, aplicar: bool, cancelar, progresso, somente):
        self.eng = eng
        self.aplicar = aplicar
        self.cancelar = cancelar
        self.progresso = progresso
        self.somente = somente
        self.res = ResultadoSync()
        self.comp = Comparacao()
        self.L = _Lado(eng.base, "local")
        self.B = _Lado(eng.backup, "backup")
        self.ret_arq = eng.retrato.arquivos()
        self.carimbo = eng.agora().strftime("%Y-%m-%d_%H%M%S")
        self.ref_l: set[str] = set()      # rels (lado local) tratados pelos passos de JSON
        self.ref_b: set[str] = set()
        self.prefixos: list[tuple[str, str]] = []  # (pasta local, pasta backup) do mesmo id
        self.bloqueados_l: list[str] = []          # pastas puladas (não mexer nos arquivos)
        self.clientes_bloqueados: set[str] = set()
        self.jsons_novos: dict[str, object] = {}
        self.jsons_manter: set[str] = set()        # chaves cujo retrato não deve mudar
        cfg = SharedConfig.default()
        self.repo_l = Repository(eng.base, eng.identity, cfg, agora=datetime.now)
        self.repo_b = Repository(eng.backup, eng.identity, cfg, agora=datetime.now)

    # ---------- utilitários ----------
    def _checar_cancelado(self):
        if self.cancelar():
            raise _Cancelado()

    def _checar_backup(self, e: BaseException):
        if not self.eng.backup.is_dir():
            raise _BackupInacessivel(str(e)) from e

    def _para_b(self, rel_l: str) -> str:
        """Traduz um caminho local para o backup (pasta do projeto antes da do cliente)."""
        for pl, pb in sorted(self.prefixos, key=lambda par: len(par[0]), reverse=True):
            if rel_l == pl or rel_l.startswith(pl + "/"):
                return pb + rel_l[len(pl):]
        return rel_l

    def _para_l(self, rel_b: str) -> str:
        for pl, pb in sorted(self.prefixos, key=lambda par: len(par[1]), reverse=True):
            if rel_b == pb or rel_b.startswith(pb + "/"):
                return pl + rel_b[len(pb):]
        return rel_b

    def _ja_tem_pasta_id(self, caminho: str) -> bool:
        return any(d.tipo == "pasta_id" and d.caminho == caminho for d in self.res.divergencias)

    def _pular(self, nome: str, motivo: str, pasta_l: str | None = None):
        self.res.pulados.append(f"{nome}: {motivo}")
        if pasta_l:
            self.bloqueados_l.append(pasta_l)

    def _copiar(self, origem: Path, destino: Path, para_backup: bool, rel_l: str,
                restaurado: bool):
        if self.aplicar:
            copiar_seguro(origem, destino)
            if restaurado:
                self.res.restaurados += 1
                self.eng._logar("arquivo_restaurado", {
                    "arquivo": rel_l, "lado": "backup" if para_backup else "local"})
            elif para_backup:
                self.res.enviados += 1
            else:
                self.res.recebidos += 1
        else:
            if restaurado:
                (self.comp.restaurar_backup if para_backup else self.comp.restaurar_local
                 ).append(rel_l)
            else:
                (self.comp.enviar if para_backup else self.comp.receber).append(rel_l)

    # ---------- rodada ----------
    def rodar(self):
        try:
            self.progresso("Comparando…", 0, 0)
            self.L.descobrir()
            self.B.descobrir()
            self.L.arquivos = varrer(self.eng.base, self.eng._cache_l, self.cancelar)
            self.B.arquivos = varrer(self.eng.backup, self.eng._cache_b, self.cancelar)
            self.eng._cache_l, self.eng._cache_b = dict(self.L.arquivos), dict(self.B.arquivos)
            self._clientes()
            self._containers()
            if self.somente is None:
                self._config()
            self._demais_arquivos()
            if self.aplicar:
                self.eng._logar("sincronizacao", {
                    "backup": str(self.eng.backup), "enviados": self.res.enviados,
                    "recebidos": self.res.recebidos, "restaurados": self.res.restaurados,
                    "divergencias": len(self.res.divergencias),
                    "pulados": len(self.res.pulados)})
            self._log()  # sempre: toda ação local vira linha no log
            if self.aplicar:
                self._salvar_retrato()
        except _Cancelado:
            self.res.cancelado = True
        except _BackupInacessivel as e:
            self.res.erro = f"Backup inacessível: {e}"
        except OrbitError as e:
            if "cancelada" in str(e).lower():
                self.res.cancelado = True
            elif not self.eng.backup.is_dir():
                self.res.erro = f"Backup inacessível: {e}"
            else:
                raise

    # ---------- clientes ----------
    def _clientes_necessarios(self) -> set[str] | None:
        if self.somente is None:
            return None
        for lado in (self.L, self.B):
            if self.somente in lado.containers:
                rel, nome = lado.containers[self.somente]
                try:
                    cid = read_json(lado.caminho(f"{rel}/{nome}")).get("cliente_id")
                except OrbitDataError:
                    cid = None
                return {cid} if cid else set()
        return set()

    def _clientes(self):
        precisa = self._clientes_necessarios()
        ids = list(self.L.clientes) + [i for i in self.B.clientes if i not in self.L.clientes]
        for cid in ids:
            if precisa is not None and cid not in precisa:
                continue
            self._checar_cancelado()
            rl, rb = self.L.clientes.get(cid), self.B.clientes.get(cid)
            try:
                if rl and rb:
                    if rl != rb:
                        self.prefixos.append((rl, rb))
                    self._mesclar_json(f"cliente:{cid}", self.L.caminho(f"{rl}/{ARQ_CLIENTE}"),
                                       self.B.caminho(f"{rb}/{ARQ_CLIENTE}"), mesclar_cliente,
                                       f"{rl}/{ARQ_CLIENTE}")
                    self.ref_l.add(f"{rl}/{ARQ_CLIENTE}")
                    self.ref_b.add(f"{rb}/{ARQ_CLIENTE}")
                else:
                    origem, destino = (self.L, self.B) if rl else (self.B, self.L)
                    rel = rl or rb
                    alvo = destino.caminho(f"{rel}/{ARQ_CLIENTE}")
                    (self.ref_l if rl else self.ref_b).add(f"{rel}/{ARQ_CLIENTE}")
                    if alvo.exists():
                        outro = destino._id(alvo)
                        self.clientes_bloqueados.add(cid)
                        if self._ja_tem_pasta_id(f"{rel}/{ARQ_CLIENTE}"):
                            continue  # o mesmo conflito, visto do outro lado
                        self.res.divergencias.append(Divergencia(
                            uuid4().hex, "pasta_id", cid, f"{rel}/{ARQ_CLIENTE}", "cliente",
                            f"Existem dois clientes diferentes na pasta \"{rel}\".",
                            {"id": cid if rl else outro}, {"id": outro if rl else cid},
                            ["ambos", "juntar"]))
                        continue
                    self._copiar(origem.caminho(f"{rel}/{ARQ_CLIENTE}"), alvo,
                                 para_backup=bool(rl), rel_l=f"{rel}/{ARQ_CLIENTE}",
                                 restaurado=False)
                    if self.aplicar:
                        self.jsons_novos[f"cliente:{cid}"] = read_json(alvo)
            except (ArquivoEmUso, PermissionError, OrbitError) as e:
                self._checar_backup(e)
                self.clientes_bloqueados.add(cid)
                self._pular(f"Cliente {rl or rb}", str(e))
            except OSError as e:
                self._checar_backup(e)
                self.clientes_bloqueados.add(cid)
                self._pular(f"Cliente {rl or rb}", str(e))

    def _mesclar_json(self, chave, arq_l: Path, arq_b: Path, func, caminho_rel,
                      campos_pasta=("pasta",)):
        jl, jb = read_json(arq_l), read_json(arq_b)
        base = self.eng.retrato.json_base(chave)
        junto, divs = func(base, jl, jb)
        for d in divs:
            d.caminho = caminho_rel
        self.res.divergencias.extend(divs)
        para_b = _com_valores_do_backup(junto, divs, jb)
        for c in campos_pasta:
            if c in jb:
                para_b[c] = jb[c]
        if junto != jl or para_b != jb:
            if self.aplicar:
                if junto != jl:
                    _escrever_json(arq_l, junto)
                if para_b != jb:
                    _escrever_json(arq_b, para_b)
            else:
                self.comp.containers.append(chave)
        if divs:
            self.jsons_manter.add(chave)
        else:
            self.jsons_novos[chave] = junto
        return junto, divs

    # ---------- containers ----------
    def _upload_ativo(self, pasta: Path) -> str | None:
        travas = pasta / ".orbit" / "travas"
        if not travas.is_dir():
            return None
        svc = PresenceService(self.eng.identity, agora=datetime.now)
        for f in travas.glob("*.lock"):
            if f.stem.casefold() == TRAVA_CONTAINER:
                continue
            if not svc.trava_abandonada(f):
                info = svc._ler_trava(f)
                return f"{info.usuario} ({info.computador})" if info else "outra pessoa"
        return None

    def _containers(self):
        ids = list(self.L.containers) + [i for i in self.B.containers
                                         if i not in self.L.containers]
        if self.somente is not None:
            ids = [i for i in ids if i == self.somente]
        total = len(ids)
        for i, cid in enumerate(ids, start=1):
            self._checar_cancelado()
            self.progresso("Sincronizando projetos e máquinas…", i, total)
            rl = self.L.containers.get(cid)
            rb = self.B.containers.get(cid)
            nome_pasta = (rl or rb)[0].rsplit("/", 1)[-1]
            try:
                if rl and rb:
                    self._sync_container(cid, rl, rb)
                else:
                    self._copiar_container(cid, rl, rb)
            except (ArquivoEmUso, PermissionError, LockHeld, OrbitError) as e:
                self._checar_backup(e)
                self._pular(nome_pasta, str(e), rl[0] if rl else rb[0])
            except OSError as e:
                self._checar_backup(e)
                self._pular(nome_pasta, str(e), rl[0] if rl else rb[0])

    def _copiar_container(self, cid, rl, rb):
        origem, destino = (self.L, self.B) if rl else (self.B, self.L)
        rel, nome_json = rl or rb
        para_backup = bool(rl)
        traduzir = self._para_b if para_backup else self._para_l
        rel_d = traduzir(rel)
        alvo_json = destino.caminho(f"{rel_d}/{nome_json}")
        try:
            dados = read_json(origem.caminho(f"{rel}/{nome_json}"))
        except OrbitDataError as e:
            raise OrbitError(str(e))
        cli = dados.get("cliente_id")
        if alvo_json.exists():
            outro = destino._id(alvo_json)
            if self._ja_tem_pasta_id(f"{rel}/{nome_json}"):
                self.bloqueados_l.append(rel)
                return  # o mesmo conflito, visto do outro lado
            self.res.divergencias.append(Divergencia(
                uuid4().hex, "pasta_id", cid, f"{rel}/{nome_json}", "container",
                f"Existem dois projetos ou máquinas diferentes na pasta \"{rel}\".",
                {"id": cid if rl else outro}, {"id": outro if rl else cid},
                ["ambos", "juntar"]))
            self.bloqueados_l.append(rel)
            return
        if cli and cli in self.clientes_bloqueados:
            raise OrbitError("o cliente deste projeto está em divergência; resolva-a primeiro")
        arquivos = sorted((r for r in origem.arquivos if r.startswith(rel + "/")),
                          key=lambda r: (eh_json_orbit(r), r))  # JSON por último
        for r in arquivos:
            self._checar_cancelado()
            r_d = traduzir(r)
            (self.ref_l if para_backup else self.ref_b).add(r)
            (self.ref_b if para_backup else self.ref_l).add(r_d)
            alvo = destino.caminho(r_d)
            if alvo.exists():
                info = destino.arquivos.get(r_d)
                if info is not None and info.hash == origem.arquivos[r].hash:
                    continue
                raise OrbitError(f"já existe \"{alvo.name}\" diferente do outro lado")
            self._copiar(origem.caminho(r), alvo, para_backup, r, restaurado=False)
        if self.aplicar:
            self.jsons_novos[f"container:{cid}"] = dados  # base para a próxima junção
        else:
            self.comp.containers.append(cid)

    def _sync_container(self, cid, rl, rb):
        """Duas fases, para nunca segurar a trava do projeto durante cópias longas.

        1. Sem a trava do projeto: junta, planeja e copia os arquivos que faltam,
           segurando só a trava de upload dos documentos que recebem arquivos.
        2. Com a trava do projeto nos dois lados: relê os JSONs (alguém pode ter
           gravado no meio-tempo), junta de novo, leva para Antigos e grava.
        """
        rel_l, nome_json = rl
        rel_b, _ = rb
        if rel_l != rel_b:
            self.prefixos.append((rel_l, rel_b))
        self.ref_l.add(f"{rel_l}/{nome_json}")
        self.ref_b.add(f"{rel_b}/{nome_json}")
        for lado, rel in ((self.L, rel_l), (self.B, rel_b)):
            quem = self._upload_ativo(lado.caminho(rel))
            if quem:
                raise OrbitError(f"{quem} está enviando uma revisão agora; "
                                 "fica para a próxima sincronização")
        arq_l = self.L.caminho(f"{rel_l}/{nome_json}")
        arq_b = self.B.caminho(f"{rel_b}/{nome_json}")

        # fase 1: cópias, sem a trava do projeto
        junto, divs, ops = self._juntar_container(cid, read_json(arq_l), read_json(arq_b),
                                                  rel_l, rel_b, nome_json)
        copias = [op for op in ops if op[0] == "copiar"]
        if copias:
            with self._travas_upload(copias, rel_l, rel_b):
                for op in copias:
                    self._checar_cancelado()
                    self._executar_copia(op)

        # fase 2: com a trava do projeto, relê e grava
        with ExitStack() as pilha:
            if self.aplicar:
                pilha.enter_context(self.repo_l.trava_container(cid))
                pilha.enter_context(self.repo_b.trava_container(cid))
            jl, jb = read_json(arq_l), read_json(arq_b)
            junto, divs, ops = self._juntar_container(cid, jl, jb, rel_l, rel_b, nome_json)
            feitos: list[tuple[Path, Path]] = []
            try:
                for op in ops:  # normalmente só idas para Antigos (as cópias já foram feitas)
                    self._checar_cancelado()
                    if op[0] == "mover":
                        _, origem, destino = op
                        if self.aplicar:
                            mover_seguro(origem, destino)
                            feitos.append((origem, destino))
                    else:
                        self._executar_copia(op)
                para_b = _com_valores_do_backup(junto, divs, jb)
                para_b["pasta"] = jb.get("pasta", para_b.get("pasta"))
                for tipo, d in (jb.get("documentos") or {}).items():
                    if tipo in para_b["documentos"]:
                        para_b["documentos"][tipo]["pasta"] = d.get("pasta")
                if junto != jl or para_b != jb:
                    if self.aplicar:
                        if junto != jl:
                            _escrever_json(arq_l, junto)
                        if para_b != jb:
                            _escrever_json(arq_b, para_b)
                    elif cid not in self.comp.containers:
                        self.comp.containers.append(cid)
            except BaseException:
                for origem, destino in reversed(feitos):  # desfaz as idas para Antigos
                    try:
                        if not os.path.lexists(origem):
                            os.rename(destino, origem)
                    except OSError:
                        pass
                raise
        self.res.divergencias.extend(divs)
        if divs:
            self.jsons_manter.add(f"container:{cid}")
        else:
            self.jsons_novos[f"container:{cid}"] = junto

    def _juntar_container(self, cid, jl, jb, rel_l, rel_b, nome_json):
        base = self.eng.retrato.json_base(f"container:{cid}")
        junto, divs = mesclar_container(base, jl, jb)
        divs += self._revisoes_com_conteudo_diferente(cid, junto, jl, jb, rel_l, rel_b, divs)
        for d in divs:
            d.caminho = f"{rel_l}/{nome_json}"
        divergentes = {tuple(d.chave.split(".")[1:4:2]) for d in divs if d.tipo == "revisao"}
        return junto, divs, self._planejar_arquivos(junto, jl, jb, rel_l, rel_b, divergentes)

    @contextmanager
    def _travas_upload(self, copias, rel_l, rel_b):
        """Trava de upload dos documentos que vão receber arquivos (no lado de destino)."""
        if not self.aplicar:
            yield
            return
        svc = PresenceService(self.eng.identity, agora=datetime.now,
                              registrar=self.eng.registrar)
        por_lado = {True: set(), False: set()}
        for op in copias:
            por_lado[op[4]].add(op[7])
        travas = []
        try:
            for para_backup, tipos in por_lado.items():
                if tipos:
                    pasta = self.B.caminho(rel_b) if para_backup else self.L.caminho(rel_l)
                    travas += svc.travar_varios(pasta, tipos)
            yield
        except LockHeld as e:
            raise OrbitError(f"{e} Fica para a próxima sincronização.") from None
        finally:
            svc.liberar_varios(travas)

    def _executar_copia(self, op):
        _, outro_lado, candidatos, destino, para_backup, rel_ref, restaurado, _tipo = op
        origem = next((outro_lado.caminho(c) for c in candidatos
                       if outro_lado.caminho(c).is_file()), None)
        if origem is None:
            raise OrbitError(f"o arquivo \"{destino.name}\" não foi encontrado do outro lado")
        if destino.is_file():
            return  # já copiado (ex.: na fase 1)
        self._copiar(origem, destino, para_backup, rel_ref, restaurado)

    def _revisoes_com_conteudo_diferente(self, cid, junto, jl, jb, rel_l, rel_b, divs
                                         ) -> list[Divergencia]:
        """Mesma revisão, mesmos nomes de arquivo, conteúdo diferente nos dois lados.

        Acontece quando cada lado criou a sua RevNN no mesmo dia: o nome sai igual.
        """
        ja = {d.chave for d in divs if d.tipo == "revisao"}
        novas = []
        docs_l, docs_b = jl.get("documentos") or {}, jb.get("documentos") or {}
        for tipo in junto["documentos"]:
            dl, db = docs_l.get(tipo), docs_b.get(tipo)
            if dl is None or db is None:
                continue
            revs_b = {r["numero"]: r for r in db.get("revisoes") or []}
            for rl_ in dl.get("revisoes") or []:
                n = rl_["numero"]
                chave = f"documentos.{tipo}.revisoes.{n}"
                rb_ = revs_b.get(n)
                if rb_ is None or chave in ja:
                    continue
                diferente = False
                for a in rl_.get("arquivos") or []:
                    hl = next((self.L.arquivos[c].hash for c in (
                        f"{rel_l}/{dl['pasta']}/{a['nome']}",
                        f"{rel_l}/{dl['pasta']}/Antigos/{a['nome']}") if c in self.L.arquivos), None)
                    hb = next((self.B.arquivos[c].hash for c in (
                        f"{rel_b}/{db['pasta']}/{a['nome']}",
                        f"{rel_b}/{db['pasta']}/Antigos/{a['nome']}") if c in self.B.arquivos), None)
                    if hl is not None and hb is not None and hl != hb:
                        diferente = True
                if diferente:
                    novas.append(Divergencia(
                        uuid4().hex, "revisao", cid, "", chave,
                        f"Rev{n:02d} do documento {tipo} tem conteúdo diferente nos dois lados.",
                        {"revisao": copy.deepcopy(rl_), "usuario": rl_.get("usuario"),
                         "computador": rl_.get("computador"), "data_hora": rl_.get("data")},
                        {"revisao": copy.deepcopy(rb_), "usuario": rb_.get("usuario"),
                         "computador": rb_.get("computador"), "data_hora": rb_.get("data")},
                        ["local", "backup", "ambos"]))
        return novas

    def _planejar_arquivos(self, junto, jl, jb, rel_l, rel_b, divergentes) -> list:
        ops = []
        docs_l, docs_b = jl.get("documentos") or {}, jb.get("documentos") or {}
        for tipo, doc in junto["documentos"].items():
            pasta_l = (docs_l.get(tipo) or doc)["pasta"]
            pasta_b = (docs_b.get(tipo) or doc)["pasta"]
            for rev in doc.get("revisoes") or []:
                for arq in rev.get("arquivos") or []:
                    nome = arq["nome"]
                    cl = [f"{rel_l}/{pasta_l}/{nome}", f"{rel_l}/{pasta_l}/Antigos/{nome}"]
                    cb = [f"{rel_b}/{pasta_b}/{nome}", f"{rel_b}/{pasta_b}/Antigos/{nome}"]
                    self.ref_l.update(cl)
                    self.ref_b.update(cb)
                    if (tipo, str(rev["numero"])) in divergentes:
                        continue
                    i = 1 if rev.get("arquivada") else 0
                    # consulta o disco (não a varredura): entre as fases os arquivos mudam
                    onde_l = next((c for c in ([cl[i]] + cl) if self.L.caminho(c).is_file()), None)
                    onde_b = next((c for c in ([cb[i]] + cb) if self.B.caminho(c).is_file()), None)
                    for lado, onde, alvo, outro_lado, outro, cands, para_backup in (
                            (self.L, onde_l, cl[i], self.B, onde_b, cb, False),
                            (self.B, onde_b, cb[i], self.L, onde_l, cl, True)):
                        if onde == alvo:
                            continue
                        if onde is not None and onde.endswith(f"/Antigos/{nome}"):
                            continue  # nunca tira um arquivo de Antigos
                        if onde is not None:
                            ops.append(("mover", lado.caminho(onde), lado.caminho(alvo)))
                        elif outro is not None:
                            # estava nos dois lados na última sincronização: alguém apagou
                            restaurado = any(c in self.ret_arq for c in cl)
                            # a origem é resolvida na hora da cópia: ela pode ter ido
                            # para Antigos nesse meio-tempo
                            ops.append(("copiar", outro_lado, cands, lado.caminho(alvo),
                                        para_backup, cl[i], restaurado, tipo))
        # idas para Antigos antes das cópias (libera o nome na pasta do tipo)
        return [o for o in ops if o[0] == "mover"] + [o for o in ops if o[0] == "copiar"]

    # ---------- configuração ----------
    def _config(self):
        arq_l, arq_b = self.L.caminho(CONFIG_REL), self.B.caminho(CONFIG_REL)
        self.ref_l.add(CONFIG_REL)
        self.ref_b.add(CONFIG_REL)
        try:
            if arq_l.exists() and arq_b.exists():
                self._mesclar_json("config", arq_l, arq_b, mesclar_config, CONFIG_REL,
                                   campos_pasta=())
            elif arq_l.exists() or arq_b.exists():
                para_backup = arq_l.exists()
                self._copiar(arq_l if para_backup else arq_b, arq_b if para_backup else arq_l,
                             para_backup, CONFIG_REL, restaurado=False)
                if self.aplicar:
                    self.jsons_novos["config"] = read_json(arq_l)
        except (OrbitError, OSError) as e:
            self._checar_backup(e)
            self._pular("Configurações", str(e))

    # ---------- demais arquivos ----------
    def _demais_arquivos(self):
        prefixo_somente = None
        if self.somente is not None:
            r = self.L.containers.get(self.somente) or self.B.containers.get(self.somente)
            prefixo_somente = r[0] if r else None
            if prefixo_somente is None:
                return

        def livre(rel_l: str) -> bool:
            if eh_json_orbit(rel_l):
                return False
            if prefixo_somente is not None and not rel_l.startswith(prefixo_somente + "/"):
                return False
            return not any(rel_l.startswith(p + "/") for p in self.bloqueados_l)

        locais = {r: i for r, i in self.L.arquivos.items() if r not in self.ref_l and livre(r)}
        do_backup = {}
        for r, i in self.B.arquivos.items():
            if r in self.ref_b:
                continue
            rl = self._para_l(r)
            if livre(rl):
                do_backup[rl] = (r, i)
        rels = sorted(set(locais) | set(do_backup))
        total = len(rels)
        for k, rel in enumerate(rels, start=1):
            self._checar_cancelado()
            self.progresso("Copiando arquivos…", k, total)
            il = locais.get(rel)
            rb, ib = do_backup.get(rel, (self._para_b(rel), None))
            anterior = self.ret_arq.get(rel)
            try:
                if il is not None and ib is not None:
                    if il.hash == ib.hash:
                        continue
                    if _unido_por_id(rel) and self._juntar_por_id(rel, rb):
                        continue  # anotações / Meu dia: juntados item a item, sem popup
                    if anterior is not None and il.hash == anterior.hash:
                        self._trocar(rel, rb, para_backup=False)
                    elif anterior is not None and ib.hash == anterior.hash:
                        self._trocar(rel, rb, para_backup=True)
                    else:
                        self.res.divergencias.append(Divergencia(
                            uuid4().hex, "arquivo", None, rel, rel,
                            f"O arquivo \"{rel}\" mudou nos dois lados.",
                            {"tamanho": il.tamanho}, {"tamanho": ib.tamanho, "caminho": rb},
                            ["local", "backup", "ambos"]))
                elif il is not None:
                    self._copiar(self.L.caminho(rel), self.B.caminho(rb), True, rel,
                                 restaurado=anterior is not None)
                else:
                    self._copiar(self.B.caminho(rb), self.L.caminho(rel), False, rel,
                                 restaurado=anterior is not None)
            except (ArquivoEmUso, PermissionError, OrbitError) as e:
                self._checar_backup(e)
                self._pular(rel, str(e))
            except OSError as e:
                self._checar_backup(e)
                self._pular(rel, str(e))

    def _juntar_por_id(self, rel_l: str, rel_b: str) -> bool:
        """Junta as listas por id e grava nos dois lados. False = ilegível (segue o normal)."""
        arq_l, arq_b = self.L.caminho(rel_l), self.B.caminho(rel_b)
        pasta = rel_l.rsplit("/", 1)[0] if "/" in rel_l else ""
        cid = next((i for i, (r, _) in self.L.containers.items() if r == pasta), None)
        with ExitStack() as pilha:
            if self.aplicar and cid is not None:  # anotacoes.json: mesma trava do projeto
                pilha.enter_context(self.repo_l.trava_container(cid))
                pilha.enter_context(self.repo_b.trava_container(cid))
            elif self.aplicar and rel_l.casefold().endswith("/meu_dia.json"):
                # meu_dia.json: a mesma trava pessoal usada pelo Orbit ao gravar
                svc = PresenceService(self.eng.identity, agora=datetime.now)
                for arq in (arq_l, arq_b):
                    trava = _travar_com_espera(svc, arq.parent, "_meu_dia")
                    pilha.callback(svc.liberar_varios, [trava])
            try:
                jl, jb = read_json(arq_l), read_json(arq_b)
            except OrbitDataError:
                return False
            junto = copy.deepcopy(jl)
            for chave in LISTAS_POR_ID:
                if chave in jl or chave in jb:
                    la, lb = jl.get(chave) or [], jb.get(chave) or []
                    if not isinstance(la, list) or not isinstance(lb, list):
                        return False
                    junto[chave] = mesclar_por_id(la, lb)
            for arq, atual, para_backup in ((arq_l, jl, False), (arq_b, jb, True)):
                if atual == junto:
                    continue
                if self.aplicar:
                    _escrever_json(arq, junto)
                    if para_backup:
                        self.res.enviados += 1
                    else:
                        self.res.recebidos += 1
                else:
                    (self.comp.enviar if para_backup else self.comp.receber).append(rel_l)
        return True

    def _trocar(self, rel_l: str, rel_b: str, para_backup: bool):
        """Um lado só mudou: guarda o antigo em _Divergências e copia o novo."""
        if not self.aplicar:
            (self.comp.enviar if para_backup else self.comp.receber).append(rel_l)
            return
        if para_backup:
            guardar_em_divergencias(self.eng.backup, rel_b, self.carimbo)
            copiar_seguro(self.L.caminho(rel_l), self.B.caminho(rel_b))
            self.res.enviados += 1
        else:
            guardar_em_divergencias(self.eng.base, rel_l, self.carimbo)
            copiar_seguro(self.B.caminho(rel_b), self.L.caminho(rel_l))
            self.res.recebidos += 1

    # ---------- log ----------
    def _log(self):
        arq_l, arq_b = self.L.caminho(LOG_REL), self.B.caminho(LOG_REL)
        try:
            with ExitStack() as pilha:
                if self.aplicar:
                    for raiz in (self.eng.base, self.eng.backup):
                        lg = ActionLog(raiz, self.eng.identity, Path(os.devnull))
                        svc = PresenceService(self.eng.identity, agora=datetime.now)
                        trava = lg._travar(svc)
                        pilha.callback(svc.liberar_varios, [trava])
                ll, il_ = _ler_arquivo(arq_l)
                lb, ib_ = _ler_arquivo(arq_b)
                juntas, conflitos = mesclar_logs(ll, lb)
                if conflitos:
                    prob_l = {p.computador for p in verificar_linhas(ll, il_)}
                    prob_b = {p.computador for p in verificar_linhas(lb, ib_)}
                    por_b = {l.seq: l for l in lb}
                    juntas = [por_b[l.seq] if (l.seq in conflitos and l.computador in prob_l
                                               and l.computador not in prob_b) else l
                              for l in juntas]
                    self.res.divergencias.append(Divergencia(
                        uuid4().hex, "log", None, LOG_REL, "log",
                        "O log de ações tem linhas diferentes nos dois lados "
                        f"({', '.join(conflitos[:5])}). Uma cópia de cada lado foi guardada "
                        "em _Divergências.", {"linhas": conflitos}, {"linhas": conflitos},
                        ["ciente"]))
                texto = "".join(json.dumps(l.to_dict(), ensure_ascii=False) + "\n"
                                for l in juntas)
                for arq, linhas, ileg, raiz in ((arq_l, ll, il_, self.eng.base),
                                                (arq_b, lb, ib_, self.eng.backup)):
                    if [l.to_dict() for l in linhas] == [l.to_dict() for l in juntas] and not ileg:
                        continue
                    if not self.aplicar:
                        (self.comp.enviar if raiz == self.eng.backup else self.comp.receber
                         ).append(LOG_REL)
                        continue
                    if (conflitos or ileg) and arq.exists():
                        destino = raiz / PASTA_DIVERGENCIAS / self.carimbo / LOG_REL
                        if not destino.exists():
                            copiar_seguro(arq, destino)
                    arq.parent.mkdir(parents=True, exist_ok=True)
                    tmp = arq.parent / f"~orbit-{uuid4().hex}.tmp"
                    try:
                        tmp.write_text(texto, encoding="utf-8", newline="\n")
                        os.replace(tmp, arq)  # o log é do Orbit: a versão unida contém tudo
                    finally:
                        if tmp.exists():
                            tmp.unlink()
        except (OrbitError, OSError) as e:
            self._checar_backup(e)
            self._pular("Log de ações", str(e))

    # ---------- retrato ----------
    def _salvar_retrato(self):
        L = varrer(self.eng.base, self.eng._cache_l)
        B = varrer(self.eng.backup, self.eng._cache_b)
        self.eng._cache_l, self.eng._cache_b = dict(L), dict(B)
        arquivos = dict(self.ret_arq)
        for rel, info in L.items():
            ib = B.get(self._para_b(rel))
            if ib is not None and ib.hash == info.hash:
                arquivos[rel] = info
        for rel in list(arquivos):
            if rel not in L and self._para_b(rel) not in B:
                arquivos.pop(rel)
        # chaves com divergência pendente mantêm a base anterior (a divergência volta
        # a aparecer até ser resolvida); as demais passam a ser o resultado da junção
        jsons = self._jsons_anteriores()
        jsons.update(self.jsons_novos)
        self.eng.retrato.salvar(arquivos, jsons, self.eng.agora().strftime("%Y-%m-%dT%H:%M:%S"))
        novas = [d.to_dict() for d in self.res.divergencias]
        if self.somente is not None:
            # rodada de um projeto só: as divergências dos outros continuam pendentes
            novas = [d for d in self.eng.retrato.divergencias_pendentes()
                     if d.get("escopo_id") != self.somente] + novas
        self.eng.retrato.salvar_divergencias(novas)

    def _jsons_anteriores(self) -> dict:
        return self.eng.retrato.todos_jsons()
