"""Varredura das pastas e retrato da última sincronização (spec de backup §5).

O retrato guarda, por par pasta base + backup, como os dois lados ficaram na
última sincronização: a lista de arquivos (tamanho, data de modificação, hash)
e o conteúdo dos JSONs do Orbit. Comparando cada lado com o retrato, o motor
sabe quem mudou o quê.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.jsonstore import read_json, write_json_atomic

PASTA_DIVERGENCIAS = "_Divergências"
_BLOCO = 1024 * 1024
VERSAO_RETRATO = 1

# JSONs do Orbit: a junção é por item, não por arquivo inteiro
NOMES_JSON = ("cliente.json", "projeto.json", "maquina.json")
CONFIG_REL = ".orbit/config.json"
LOG_REL = ".orbit/log/acoes.log"


@dataclass(frozen=True)
class InfoArquivo:
    tamanho: int
    mtime_ns: int
    hash: str


def eh_json_orbit(rel: str) -> bool:
    r = rel.casefold()
    return r in (CONFIG_REL, LOG_REL) or r.rsplit("/", 1)[-1] in NOMES_JSON


def excluido(rel: str) -> bool:
    """Arquivos que nunca são sincronizados (presença, travas, temporários, descartes)."""
    partes = [p.casefold() for p in rel.replace("\\", "/").split("/") if p]
    if not partes:
        return True
    if partes[-1].startswith("~orbit-"):
        return True
    if PASTA_DIVERGENCIAS.casefold() in partes:
        return True
    for i, p in enumerate(partes[:-1]):
        if p == ".orbit" and i + 1 < len(partes) and partes[i + 1] in ("travas", "presenca"):
            return True
    return False


def calcular_hash(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while True:
            bloco = f.read(_BLOCO)
            if not bloco:
                break
            h.update(bloco)
    return h.hexdigest()


def varrer(raiz: Path, cache: dict[str, InfoArquivo] | None = None,
           cancelar: Callable[[], bool] = lambda: False) -> dict[str, InfoArquivo]:
    """Arquivos de `raiz` (caminhos relativos com "/"), sem os excluídos.

    Reaproveita o hash do cache quando tamanho e data de modificação não mudaram.
    """
    raiz = Path(raiz)
    cache = cache or {}
    out: dict[str, InfoArquivo] = {}
    for pasta, subpastas, arquivos in os.walk(raiz):
        if cancelar():
            raise OrbitError("Sincronização cancelada.")
        rel_pasta = Path(pasta).relative_to(raiz).as_posix()
        rel_pasta = "" if rel_pasta == "." else rel_pasta + "/"
        # não desce em pastas que serão totalmente excluídas
        subpastas[:] = [s for s in subpastas
                        if not excluido(f"{rel_pasta}{s}/x")]
        for nome in arquivos:
            rel = f"{rel_pasta}{nome}"
            if excluido(rel):
                continue
            caminho = Path(pasta) / nome
            try:
                st = caminho.stat()
            except OSError:
                continue  # sumiu durante a varredura
            ant = cache.get(rel)
            if ant is not None and ant.tamanho == st.st_size and ant.mtime_ns == st.st_mtime_ns:
                out[rel] = ant
                continue
            try:
                out[rel] = InfoArquivo(st.st_size, st.st_mtime_ns, calcular_hash(caminho))
            except OSError:
                continue  # ilegível agora (aberto/sumiu): fica para a próxima rodada
    return out


def id_par(base: Path, backup: Path) -> str:
    def norm(p: Path) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except OSError:
            return str(p).lower()
    texto = norm(base) + "|" + norm(backup)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


class Retrato:
    """Estado da última sincronização de um par, em `%APPDATA%/Orbit/sync/<par>/`."""

    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self._estado: dict | None = None
        self._jsons: dict | None = None

    @property
    def _arq_estado(self) -> Path:
        return self.pasta / "estado.json"

    @property
    def _arq_jsons(self) -> Path:
        return self.pasta / "jsons.json"

    @property
    def _arq_divergencias(self) -> Path:
        return self.pasta / "divergencias.json"

    def _ler(self, arq: Path) -> dict:
        try:
            return read_json(arq)
        except OrbitDataError:
            return {}

    def existe(self) -> bool:
        return self._arq_estado.is_file()

    def _estado_atual(self) -> dict:
        if self._estado is None:
            self._estado = self._ler(self._arq_estado)
        return self._estado

    def arquivos(self) -> dict[str, InfoArquivo]:
        out = {}
        for rel, v in (self._estado_atual().get("arquivos") or {}).items():
            try:
                out[rel] = InfoArquivo(int(v[0]), int(v[1]), str(v[2]))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def ultima_sync(self) -> str | None:
        return self._estado_atual().get("ultima_sync")

    def json_base(self, rel: str):
        if self._jsons is None:
            self._jsons = self._ler(self._arq_jsons).get("jsons") or {}
        return self._jsons.get(rel)

    def salvar(self, arquivos: dict[str, InfoArquivo], jsons: dict[str, object],
               quando: str) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self._arq_jsons, {"versao_formato": VERSAO_RETRATO, "jsons": jsons})
        estado = {"versao_formato": VERSAO_RETRATO, "ultima_sync": quando,
                  "arquivos": {r: [i.tamanho, i.mtime_ns, i.hash] for r, i in arquivos.items()}}
        write_json_atomic(self._arq_estado, estado)  # por último: marca o retrato como completo
        self._estado, self._jsons = estado, dict(jsons)

    def divergencias_pendentes(self) -> list[dict]:
        lista = self._ler(self._arq_divergencias).get("lista")
        return lista if isinstance(lista, list) else []

    def salvar_divergencias(self, lista: list[dict]) -> None:
        self.pasta.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self._arq_divergencias, {"versao_formato": VERSAO_RETRATO,
                                                   "lista": list(lista)})
