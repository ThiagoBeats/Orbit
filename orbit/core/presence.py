"""Presença de usuários num container e travas de upload (spec §12).

Tudo fica em `<container>/.orbit/`:
- `presenca/<usuario>@<computador>.json`: renovado a cada ~30 s enquanto o
  container está aberto; `outros()` ignora sinais com mais de 2 min.
- `travas/<tipo_id>.lock`: criado de forma atômica (O_CREAT | O_EXCL) durante
  um upload ou importação; com mais de 10 min é considerado abandonado.

Arquivos de presença ou trava ilegíveis nunca derrubam o programa: presenças
ruins são ignoradas e uma trava ilegível vale como trava de "desconhecido",
com a data de modificação do arquivo como hora.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from orbit.core.errors import LockHeld, OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.naming import sanitize

PASTA_ORBIT = ".orbit"
PASTA_PRESENCA = "presenca"
PASTA_TRAVAS = "travas"
MAX_IDADE_PRESENCA_S = 120
MAX_IDADE_TRAVA_S = 600
DESCONHECIDO = "desconhecido"
_FORMATO = "%Y-%m-%dT%H:%M:%S"


@dataclass
class Presenca:
    usuario: str
    computador: str
    desde: str
    ultimo_sinal: str


def _ler_hora(texto) -> datetime:
    """ISO gravado pelo Orbit; ValueError/TypeError se não for."""
    return datetime.strptime(str(texto), _FORMATO)


def _nome_arquivo(texto: str) -> str:
    return sanitize(texto) or "_"


class PresenceService:
    def __init__(self, identity: Identity, agora: Callable[[], datetime] = datetime.now):
        self.identity = identity
        self.agora = agora

    def _agora_iso(self) -> str:
        return self.agora().strftime(_FORMATO)

    # ---------- presença ----------
    @staticmethod
    def _pasta_presenca(container_dir: Path) -> Path:
        return Path(container_dir) / PASTA_ORBIT / PASTA_PRESENCA

    def _arquivo_presenca(self, container_dir: Path) -> Path:
        nome = _nome_arquivo(f"{self.identity.usuario}@{self.identity.computador}")
        return self._pasta_presenca(container_dir) / f"{nome}.json"

    @staticmethod
    def _ler_presenca(arq: Path) -> Presenca | None:
        try:
            d = read_json(arq)
            p = Presenca(str(d["usuario"]), str(d["computador"]), str(d["desde"]),
                         str(d["ultimo_sinal"]))
            _ler_hora(p.desde)
            _ler_hora(p.ultimo_sinal)
            return p
        except (OrbitDataError, KeyError, ValueError, TypeError):
            return None

    def sinalizar(self, container_dir: Path) -> None:
        arq = self._arquivo_presenca(container_dir)
        arq.parent.mkdir(parents=True, exist_ok=True)
        agora = self._agora_iso()
        anterior = self._ler_presenca(arq) if arq.exists() else None
        desde = anterior.desde if anterior is not None else agora
        write_json_atomic(arq, {
            "versao_formato": 1,
            "usuario": self.identity.usuario,
            "computador": self.identity.computador,
            "desde": desde,
            "ultimo_sinal": agora,
        })

    def outros(self, container_dir: Path,
               max_idade_s: int = MAX_IDADE_PRESENCA_S) -> list[Presenca]:
        pasta = self._pasta_presenca(container_dir)
        try:
            arquivos = sorted(pasta.glob("*.json"))
        except OSError:
            return []
        agora = self.agora()
        eu = (self.identity.usuario, self.identity.computador)
        lista: list[Presenca] = []
        for arq in arquivos:
            p = self._ler_presenca(arq)
            if p is None or (p.usuario, p.computador) == eu:
                continue
            if (agora - _ler_hora(p.ultimo_sinal)).total_seconds() > max_idade_s:
                continue
            lista.append(p)
        return sorted(lista, key=lambda p: (p.desde, p.usuario, p.computador))

    def sair(self, container_dir: Path) -> None:
        try:
            self._arquivo_presenca(container_dir).unlink()
        except FileNotFoundError:
            pass

    # ---------- travas ----------
    @staticmethod
    def caminho_trava(container_dir: Path, tipo_id: str) -> Path:
        return (Path(container_dir) / PASTA_ORBIT / PASTA_TRAVAS
                / f"{_nome_arquivo(tipo_id)}.lock")

    @staticmethod
    def _ler_trava(lock: Path) -> tuple[str, str, datetime] | None:
        """(usuario, computador, desde). None se a trava não existe mais."""
        try:
            with open(lock, "r", encoding="utf-8") as f:
                d = json.load(f)
            return str(d["usuario"]), str(d["computador"]), _ler_hora(d["desde"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            pass  # ilegível (inclusive sendo gravada agora): vale como "desconhecido"
        try:
            mtime = datetime.fromtimestamp(lock.stat().st_mtime)
        except OSError:
            return None
        return DESCONHECIDO, DESCONHECIDO, mtime

    def travar(self, container_dir: Path, tipo_id: str) -> Path:
        lock = self.caminho_trava(container_dir, tipo_id)
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            info = self._ler_trava(lock)
            usuario, computador, desde = info or (DESCONHECIDO, DESCONHECIDO, self.agora())
            erro = LockHeld(f"{usuario} ({computador}) está enviando uma revisão deste "
                            f"documento desde {desde:%H:%M}.")
            erro.tipo_id = tipo_id
            erro.abandonada = self._idade(desde) > MAX_IDADE_TRAVA_S
            raise erro
        dados = json.dumps({
            "versao_formato": 1,
            "usuario": self.identity.usuario,
            "computador": self.identity.computador,
            "desde": self._agora_iso(),
        }, ensure_ascii=False).encode("utf-8")
        try:
            try:
                os.write(fd, dados)
            finally:
                os.close(fd)
        except OSError as e:
            self.liberar(lock)  # a trava acabou de ser criada por nós
            raise OrbitError(f"Não foi possível criar a trava de upload: {e}") from e
        return lock

    def _idade(self, desde: datetime) -> float:
        return (self.agora() - desde).total_seconds()

    def trava_abandonada(self, lock: Path, max_idade_s: int = MAX_IDADE_TRAVA_S) -> bool:
        info = self._ler_trava(Path(lock))
        return info is not None and self._idade(info[2]) > max_idade_s

    def liberar(self, lock: Path) -> None:
        try:
            Path(lock).unlink()
        except FileNotFoundError:
            pass

    def travar_varios(self, container_dir: Path, tipo_ids) -> list[Path]:
        """Trava cada tipo (em ordem, sem repetição). Se um falhar, solta os já travados."""
        travas: list[Path] = []
        try:
            for t in sorted(set(tipo_ids)):
                travas.append(self.travar(container_dir, t))
        except BaseException:
            self.liberar_varios(travas)
            raise
        return travas

    def liberar_varios(self, travas: list[Path]) -> None:
        for lock in reversed(travas):
            try:
                self.liberar(lock)
            except OSError:
                pass  # trava presa vira "abandonada" depois de 10 min
