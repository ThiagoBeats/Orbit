"""Presença de usuários num container e travas de upload (spec §12).

Tudo fica em `<container>/.orbit/`:
- `presenca/<usuario>@<computador>.json`: renovado a cada ~30 s enquanto o
  container está aberto; `outros()` ignora sinais com mais de 2 min.
- `travas/<tipo_id>.lock`: criado de forma atômica (O_CREAT | O_EXCL) durante
  um upload ou importação; com mais de 10 min é considerado abandonado. Cada
  trava leva um `token` único; só quem tem o token (o objeto devolvido por
  `travar`) a libera, e a liberação forçada (`liberar_abandonada`) só remove
  trava abandonada, conferida no próprio arquivo removido.

Arquivos de presença ou trava ilegíveis nunca derrubam o programa: presenças
ruins são ignoradas e uma trava ilegível vale como trava de "desconhecido",
com a data de modificação do arquivo como hora.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from orbit.core.errors import LockHeld, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import write_json_atomic
from orbit.core.naming import sanitize

PASTA_ORBIT = ".orbit"
PASTA_PRESENCA = "presenca"
PASTA_TRAVAS = "travas"
MAX_IDADE_PRESENCA_S = 120
MAX_IDADE_TRAVA_S = 600
DESCONHECIDO = "desconhecido"
_FORMATO = "%Y-%m-%dT%H:%M:%S"

# Apagar/renomear no Windows falha com PermissionError (WinError 32) enquanto
# outro processo está com o arquivo aberto sem FILE_SHARE_DELETE: tenta de novo.
_TENTATIVAS = 5
_ESPERA_S = 0.1


@dataclass
class Presenca:
    usuario: str
    computador: str
    desde: str
    ultimo_sinal: str


@dataclass
class _InfoTrava:
    usuario: str
    computador: str
    desde: datetime
    token: str | None


class TravaUpload(type(Path())):
    """Caminho da trava + `token` do dono (o mesmo gravado dentro do arquivo).

    É um Path comum (compara, abre, etc.). O token só existe no objeto
    devolvido por `travar` e é o que autoriza `liberar`.
    """
    token: str | None = None


def _ler_hora(texto) -> datetime:
    """ISO gravado pelo Orbit; ValueError/TypeError se não for."""
    return datetime.strptime(str(texto), _FORMATO)


def _nome_arquivo(texto: str) -> str:
    return sanitize(texto) or "_"


def _com_retentativas(fn, *args):
    for i in range(_TENTATIVAS):
        try:
            return fn(*args)
        except PermissionError:
            if i == _TENTATIVAS - 1:
                raise
            time.sleep(_ESPERA_S)


def _ler_bytes(caminho: Path) -> bytes:
    """Lê o arquivo sem impedir que outro processo o apague ou renomeie ao mesmo tempo.

    O open() do Python no Windows não pede FILE_SHARE_DELETE: enquanto alguém lê
    a trava, o dono não consegue apagá-la (WinError 32). Aqui o arquivo é aberto
    com CreateFileW compartilhando leitura, escrita e exclusão.
    """
    if os.name != "nt":
        return Path(caminho).read_bytes()
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    criar = k32.CreateFileW
    criar.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    criar.restype = wintypes.HANDLE
    generic_read, compartilhar_tudo, open_existing, normal = 0x80000000, 0x7, 3, 0x80
    h = criar(str(caminho), generic_read, compartilhar_tudo, None, open_existing, normal,
              None)
    if h is None or h == wintypes.HANDLE(-1).value:
        cod = ctypes.get_last_error()
        raise OSError(None, ctypes.FormatError(cod), str(caminho), cod)
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        k32.CloseHandle(wintypes.HANDLE(h))
        raise
    with os.fdopen(fd, "rb") as f:
        return f.read()


class PresenceService:
    def __init__(self, identity: Identity, agora: Callable[[], datetime] = datetime.now,
                 registrar: Callable[[BaseException], None] | None = None):
        self.identity = identity
        self.agora = agora
        self.registrar = registrar  # log de falhas que não podem interromper a operação

    def _registrar(self, e: BaseException) -> None:
        if self.registrar is not None:
            try:
                self.registrar(e)
            except Exception:
                pass

    def _agora_iso(self) -> str:
        return self.agora().strftime(_FORMATO)

    def _idade(self, desde: datetime) -> float:
        return (self.agora() - desde).total_seconds()

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
            d = json.loads(_ler_bytes(arq).decode("utf-8"))
            p = Presenca(str(d["usuario"]), str(d["computador"]), str(d["desde"]),
                         str(d["ultimo_sinal"]))
            _ler_hora(p.desde)
            _ler_hora(p.ultimo_sinal)
            return p
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def sinalizar(self, container_dir: Path) -> None:
        arq = self._arquivo_presenca(container_dir)
        arq.parent.mkdir(parents=True, exist_ok=True)
        agora = self._agora_iso()
        anterior = self._ler_presenca(arq)
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
            _com_retentativas(os.unlink, self._arquivo_presenca(container_dir))
        except FileNotFoundError:
            pass

    # ---------- travas ----------
    @staticmethod
    def caminho_trava(container_dir: Path, tipo_id: str) -> Path:
        return (Path(container_dir) / PASTA_ORBIT / PASTA_TRAVAS
                / f"{_nome_arquivo(tipo_id)}.lock")

    @staticmethod
    def _ler_trava(lock: Path) -> _InfoTrava | None:
        """Dono, hora e token da trava. None se ela não existe mais.

        A leitura não impede que o dono apague a trava ao mesmo tempo (_ler_bytes).
        """
        try:
            d = json.loads(_ler_bytes(lock).decode("utf-8"))
            token = d.get("token")
            return _InfoTrava(str(d["usuario"]), str(d["computador"]), _ler_hora(d["desde"]),
                              str(token) if token else None)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass  # ilegível (inclusive sendo gravada agora): vale como "desconhecido"
        try:
            mtime = datetime.fromtimestamp(Path(lock).stat().st_mtime)
        except OSError:
            return None
        return _InfoTrava(DESCONHECIDO, DESCONHECIDO, mtime, None)

    def travar(self, container_dir: Path, tipo_id: str) -> TravaUpload:
        """Cria a trava de forma atômica. Devolve o caminho com o token deste dono."""
        lock = self.caminho_trava(container_dir, tipo_id)
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OrbitError(f"Não foi possível criar a pasta de travas de upload "
                             f"({lock.parent}): {e}") from e
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        for tentativa in range(2):
            try:
                # PermissionError no Windows: trava sendo apagada agora por outro processo
                fd = _com_retentativas(os.open, lock, flags)
                break
            except FileExistsError:
                info = self._ler_trava(lock)
                if info is None and tentativa == 0:
                    continue  # sumiu entre o open e a leitura: tenta criar de novo
                info = info or _InfoTrava(DESCONHECIDO, DESCONHECIDO, self.agora(), None)
                erro = LockHeld(f"{info.usuario} ({info.computador}) está enviando uma "
                                f"revisão deste documento desde {info.desde:%H:%M}.")
                erro.tipo_id = tipo_id
                erro.abandonada = self._idade(info.desde) > MAX_IDADE_TRAVA_S
                raise erro
            except OSError as e:
                raise OrbitError(f"Não foi possível criar a trava de upload "
                                 f"({lock.name}): {e}") from e
        token = uuid4().hex
        dados = json.dumps({
            "versao_formato": 1,
            "usuario": self.identity.usuario,
            "computador": self.identity.computador,
            "desde": self._agora_iso(),
            "token": token,
        }, ensure_ascii=False).encode("utf-8")
        try:
            try:
                os.write(fd, dados)
            finally:
                os.close(fd)
        except OSError as e:
            try:  # a trava acabou de ser criada por nós
                _com_retentativas(os.unlink, lock)
            except OSError as e2:
                self._registrar(e2)
            raise OrbitError(f"Não foi possível criar a trava de upload: {e}") from e
        trava = TravaUpload(lock)
        trava.token = token
        return trava

    def trava_abandonada(self, lock: Path, max_idade_s: int = MAX_IDADE_TRAVA_S) -> bool:
        info = self._ler_trava(Path(lock))
        return info is not None and self._idade(info.desde) > max_idade_s

    def _remover_se(self, lock: Path, aceitar: Callable[[_InfoTrava], bool]) -> bool:
        """Remove a trava só se `aceitar(info)`. True se ela não existe mais.

        Para não apagar uma trava que outra pessoa acabou de criar no lugar:
        1. lê a trava e confere (`aceitar`);
        2. renomeia para um nome único (`<tipo>.lock.<uuid>.liberando`), que
           ninguém mais usa, liberando o nome `.lock`;
        3. relê o arquivo renomeado e confere de novo (mesmo token e `aceitar`);
           se ele mudou entre 1 e 2, devolve-o ao nome original;
        4. apaga o arquivo renomeado.
        Sobra só uma janela mínima: se a trava foi trocada entre 1 e 2 e, além
        disso, outra trava foi criada entre 2 e 3, a devolução falha e vira
        OrbitError (que vai para o log).
        """
        lock = Path(lock)
        info = self._ler_trava(lock)
        if info is None:
            return True
        if not aceitar(info):
            return False
        tmp = lock.with_name(f"{lock.name}.{uuid4().hex}.liberando")
        try:
            _com_retentativas(os.rename, lock, tmp)
        except FileNotFoundError:
            return True
        except OSError as e:
            raise OrbitError(f"Não foi possível liberar a trava {lock.name}: {e}") from e
        info2 = self._ler_trava(tmp)
        if info2 is None or info2.token != info.token or not aceitar(info2):
            try:
                _com_retentativas(os.rename, tmp, lock)
            except OSError as e:
                raise OrbitError(f"A trava {lock.name} foi trocada durante a liberação e não "
                                 f"pôde ser devolvida (ficou como {tmp.name}): {e}") from e
            return False
        try:
            _com_retentativas(os.unlink, tmp)
        except FileNotFoundError:
            pass
        except OSError as e:
            # o documento já está livre (o nome .lock foi desocupado); só sobra o arquivo
            self._registrar(e)
        return True

    def liberar(self, trava: TravaUpload) -> bool:
        """Solta uma trava criada por `travar`, só se ela ainda for deste dono (token).

        Devolve False se a trava foi trocada por outra (ex.: liberada à força por
        estar abandonada e criada de novo por outra pessoa): a nova fica intacta.
        Lança OrbitError se não conseguir removê-la mesmo com as retentativas.
        """
        token = getattr(trava, "token", None)
        if not token:
            raise TypeError("liberar() precisa da trava devolvida por travar()")
        return self._remover_se(trava, lambda info: info.token == token)

    def liberar_abandonada(self, lock: Path, max_idade_s: int = MAX_IDADE_TRAVA_S) -> bool:
        """Remove a trava de qualquer dono, só se ela estiver abandonada.

        A idade é conferida de novo no próprio arquivo removido. Devolve False se
        a trava não está abandonada; True se foi removida ou já não existia.
        """
        return self._remover_se(lock, lambda info: self._idade(info.desde) > max_idade_s)

    def travar_varios(self, container_dir: Path, tipo_ids) -> list[TravaUpload]:
        """Trava cada tipo (em ordem, sem repetição). Se um falhar, solta os já travados."""
        travas: list[TravaUpload] = []
        try:
            for t in sorted(set(tipo_ids)):
                travas.append(self.travar(container_dir, t))
        except BaseException:
            self.liberar_varios(travas)
            raise
        return travas

    def liberar_varios(self, travas: list[TravaUpload]) -> list[str]:
        """Solta as travas sem lançar erro (é chamado em `finally`).

        As falhas são registradas (callback `registrar`; a Api o liga ao orbit.log)
        e devolvidas. Uma trava que ficou presa vira "abandonada" depois de 10 min.
        """
        falhas: list[str] = []
        for trava in reversed(travas):
            try:
                self.liberar(trava)
            except (OSError, OrbitError) as e:
                falhas.append(f"{Path(trava).name}: {e}")
                self._registrar(e)
        return falhas
