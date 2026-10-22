"""Teste de conexão com as pastas (spec §12).

Lista a pasta e grava/lê/remove um arquivo temporário do próprio Orbit em
`.orbit/`. Tudo roda numa thread daemon com tempo limite: uma pasta de rede
travada não congela a interface (a thread presa é abandonada).
"""
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from orbit.core.errors import OrbitError
from orbit.core.identity import Identity
from orbit.core.naming import sanitize

TIMEOUT_PADRAO = 5.0


@dataclass
class ResultadoConexao:
    pasta: str
    ok: bool
    leitura: bool
    escrita: bool
    erro: str | None
    ms: int


def _verificar(pasta: Path, identity: Identity, estado: dict) -> None:
    """Preenche estado["leitura"], ["escrita"] e ["erro"] conforme avança."""
    try:
        with os.scandir(pasta) as it:
            for _ in it:
                break
        estado["leitura"] = True
    except OSError as e:
        estado["erro"] = _msg(e)
        return
    nome = sanitize(identity.usuario) or "usuario"
    arq = pasta / ".orbit" / f".teste-conexao-{nome}.tmp"
    try:
        arq.parent.mkdir(exist_ok=True)
        conteudo = f"orbit {identity.usuario}@{identity.computador}"
        with open(arq, "w", encoding="utf-8") as f:
            f.write(conteudo)
        estado["escrita"] = True
        with open(arq, "r", encoding="utf-8") as f:
            if f.read() != conteudo:
                estado["escrita"] = False
                estado["erro"] = "O arquivo de teste foi lido com conteúdo diferente."
    except OSError as e:
        estado["erro"] = _msg(e)
    finally:
        try:
            arq.unlink(missing_ok=True)  # arquivo temporário do próprio Orbit
        except OSError:
            pass


def pasta_existe(pasta: Path, timeout: float = TIMEOUT_PADRAO) -> bool:
    """Path.is_dir() com tempo limite: numa rede travada não bloqueia a abertura.

    Levanta OrbitError("Tempo esgotado") se estourar (a thread presa é abandonada).
    """
    res: list[bool] = []

    def rodar():
        try:
            res.append(Path(pasta).is_dir())
        except OSError:
            res.append(False)

    t = threading.Thread(target=rodar, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise OrbitError("Tempo esgotado")
    return res[0]


def _msg(e: OSError) -> str:
    return e.strerror or str(e) or type(e).__name__


def testar_pasta(pasta: Path, identity: Identity,
                 timeout: float = TIMEOUT_PADRAO) -> ResultadoConexao:
    """Nunca levanta: toda falha vira ResultadoConexao(ok=False, erro=...)."""
    pasta = Path(pasta)
    estado = {"leitura": False, "escrita": False, "erro": None}
    inicio = time.perf_counter()

    def rodar():
        try:
            _verificar(pasta, identity, estado)
        except Exception as e:  # nunca deixa a thread morrer sem explicação
            estado["erro"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=rodar, daemon=True)
    t.start()
    t.join(timeout)
    ms = int((time.perf_counter() - inicio) * 1000)
    if t.is_alive():
        return ResultadoConexao(str(pasta), False, False, False, "Tempo esgotado", ms)
    ok = estado["leitura"] and estado["escrita"] and estado["erro"] is None
    return ResultadoConexao(str(pasta), ok, estado["leitura"], estado["escrita"],
                            estado["erro"], ms)


testar_pasta.__test__ = False  # o pytest não deve coletá-la como teste
