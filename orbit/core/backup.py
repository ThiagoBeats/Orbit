"""Serviço de backup (spec de backup §4, §6 e §8).

- configurar: valida o caminho, faz a primeira cópia (pasta vazia) ou a junção
  (backup do Orbit que já existe) e salva o caminho nas preferências da máquina;
- espelhar: depois de cada alteração local, sincroniza só o que mudou numa
  thread em segundo plano; falhas viram pendências, nunca erro para o usuário;
- status: estado do backup para o indicador (compara no máximo a cada N minutos);
- recuperar_juntando / restaurar_pc_novo: as duas formas de recuperação.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from orbit.core.actionlog import ActionLog
from orbit.core.config import UserSettings
from orbit.core.connection import pasta_existe
from orbit.core.errors import LockHeld, OrbitError
from orbit.core.identity import Identity
from orbit.core.sync.motor import Comparacao, ResultadoSync, SyncEngine, copiar_seguro
from orbit.core.sync.varredura import CONFIG_REL, Retrato, calcular_hash, id_par, varrer

NUVENS = ("onedrive", "google drive", "googledrive", "meu drive", "my drive", "dropbox",
          "iclouddrive", "icloud drive")
TIMEOUT_ACESSO_S = 5.0


@dataclass
class StatusBackup:
    estado: str  # desativado | em_dia | diferente | inacessivel | sincronizando
    pendentes: int = 0
    divergencias: int = 0
    ultima_sync: str | None = None
    erro: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _resolver(p: Path) -> Path:
    try:
        return Path(p).resolve()
    except OSError:
        return Path(p)


def _dentro(a: Path, b: Path) -> bool:
    """a está dentro de b (ou é b)?"""
    try:
        _resolver(a).relative_to(_resolver(b))
        return True
    except ValueError:
        return False


def _vazia(pasta: Path) -> bool:
    try:
        return not any(Path(pasta).iterdir())
    except OSError as e:
        raise OrbitError(f"Não foi possível ler a pasta {pasta}: {e}")


def _eh_backup_orbit(pasta: Path) -> bool:
    return (Path(pasta) / CONFIG_REL).is_file()


def restaurar_pc_novo(caminho_backup: Path, nova_base: Path, identity: Identity,
                      ancoras_path: Path, agora: Callable[[], datetime] = datetime.now,
                      progresso: Callable[[str, int, int], None] = lambda f, a, t: None,
                      cancelar: Callable[[], bool] = lambda: False) -> ResultadoSync:
    """Copia o backup inteiro para uma pasta base nova (vazia) e confere tudo."""
    caminho_backup, nova_base = Path(caminho_backup), Path(nova_base)
    if not pasta_existe(caminho_backup, TIMEOUT_ACESSO_S):
        raise OrbitError(f"Backup inacessível: {caminho_backup}")
    if not _eh_backup_orbit(caminho_backup):
        raise OrbitError("A pasta indicada não é um backup do Orbit.")
    if not nova_base.is_dir():
        raise OrbitError(f"Pasta não encontrada: {nova_base}")
    if not _vazia(nova_base):
        raise OrbitError("A pasta escolhida para a nova pasta base precisa estar vazia.")
    if _dentro(nova_base, caminho_backup) or _dentro(caminho_backup, nova_base):
        raise OrbitError("A nova pasta base não pode ficar dentro do backup (nem o contrário).")
    res = ResultadoSync()
    arquivos = varrer(caminho_backup, cancelar=cancelar)
    total = len(arquivos)
    for i, (rel, info) in enumerate(sorted(arquivos.items()), start=1):
        if cancelar():
            res.cancelado = True
            return res
        progresso("Restaurando…", i, total)
        destino = nova_base / rel
        try:
            copiar_seguro(caminho_backup / rel, destino)
            if calcular_hash(destino) != info.hash:
                res.pulados.append(f"{rel}: conteúdo diferente depois da cópia")
                continue
            res.recebidos += 1
        except (OrbitError, OSError) as e:
            res.pulados.append(f"{rel}: {e}")
    log = ActionLog(nova_base, identity, ancoras_path, agora=agora)
    relatorio = log.verificar()
    log.registrar_acao("recuperacao", {"modo": "pc_novo", "backup": str(caminho_backup),
                                       "arquivos": res.recebidos, "falhas": len(res.pulados),
                                       "log_integro": relatorio.integro})
    if res.pulados:
        res.erro = f"{len(res.pulados)} arquivo(s) não puderam ser restaurados."
    return res


class BackupService:
    def __init__(self, base: Path, settings: UserSettings, identity: Identity,
                 log: ActionLog | None, sync_dir: Path,
                 agora: Callable[[], datetime] = datetime.now,
                 registrar: Callable[[BaseException], None] | None = None,
                 salvar_settings: Callable[[], None] = lambda: None):
        self.base = Path(base)
        self.settings = settings
        self.identity = identity
        self.log = log
        self.sync_dir = Path(sync_dir)
        self.agora = agora
        self.registrar = registrar
        self.salvar_settings = salvar_settings
        self._fila: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._trava = threading.RLock()
        self._pendentes: set[tuple[str, str | None]] = set()
        self._sincronizando = False
        self._ultimo_status: StatusBackup | None = None
        self._ultima_comparacao = 0.0
        self._caches: dict[str, dict] = {}  # par -> cache de hash dos dois lados (entre rodadas)

    # ---------- utilitários ----------
    @property
    def backup(self) -> Path | None:
        return Path(self.settings.backup) if self.settings.backup else None

    def engine(self, caminho: Path | None = None) -> SyncEngine:
        destino = Path(caminho) if caminho else self.backup
        if destino is None:
            raise OrbitError("Nenhum backup configurado.")
        par = id_par(self.base, destino)
        return SyncEngine(self.base, destino, self.identity, Retrato(self.sync_dir / par),
                          self.log, agora=self.agora, registrar=self.registrar,
                          caches=self._caches.setdefault(par, {}))

    def _falha(self, e: BaseException) -> None:
        if self.registrar:
            try:
                self.registrar(e)
            except Exception:
                pass

    def pendentes(self) -> set:
        with self._trava:
            return set(self._pendentes)

    # ---------- configuração ----------
    def analisar_caminho(self, caminho: Path) -> str:
        caminho = Path(caminho)
        if not pasta_existe(caminho, TIMEOUT_ACESSO_S):
            raise OrbitError(f"A pasta de backup não foi encontrada ou está inacessível: "
                             f"{caminho}")
        if _dentro(caminho, self.base):
            raise OrbitError("O backup não pode ficar dentro da pasta base.")
        if _dentro(self.base, caminho):
            raise OrbitError("A pasta base não pode ficar dentro do backup.")
        if _vazia(caminho):
            return "vazio"
        if _eh_backup_orbit(caminho):
            return "orbit"
        return "estranho"

    @staticmethod
    def aviso_nuvem(caminho: Path) -> str | None:
        partes = [p.casefold() for p in Path(caminho).parts]
        if any(any(p == n or p.startswith(n + " ") or p.startswith(n + "-") for n in NUVENS)
               for p in partes):
            return ("Esta pasta parece ser de um serviço de nuvem. Funciona bem como backup de "
                    "uma máquina; com várias máquinas sincronizando pela mesma pasta de nuvem, "
                    "as travas chegam atrasadas e podem surgir cópias de conflito. Para uso em "
                    "equipe, prefira uma pasta no servidor da empresa.")
        return None

    def configurar(self, caminho: Path, progresso=lambda f, a, t: None,
                   cancelar=lambda: False) -> ResultadoSync:
        analise = self.analisar_caminho(caminho)
        if analise == "estranho":
            raise OrbitError("A pasta escolhida tem arquivos que não são do Orbit. Escolha uma "
                             "pasta vazia ou um backup do Orbit.")
        res = self._sincronizar_com(self.engine(caminho), progresso, cancelar)
        if res.erro is None and not res.cancelado:
            self.settings.backup = str(caminho)
            self.salvar_settings()
            self._ultimo_status = None
        return res

    def desativar(self) -> None:
        self.settings.backup = None
        self.salvar_settings()
        with self._trava:
            self._pendentes.clear()
            self._ultimo_status = None

    def definir_intervalo(self, minutos) -> int:
        from orbit.core.config import limitar_intervalo
        self.settings.intervalo_backup_min = limitar_intervalo(minutos)
        self.salvar_settings()
        return self.settings.intervalo_backup_min

    # ---------- sincronização ----------
    def _sincronizar_com(self, eng: SyncEngine, progresso, cancelar,
                         somente: str | None = None) -> ResultadoSync:
        with self._trava:
            self._sincronizando = True
        try:
            return eng.sincronizar(cancelar=cancelar, progresso=progresso,
                                   somente_container=somente)
        finally:
            with self._trava:
                self._sincronizando = False
                self._ultimo_status = None  # força nova comparação no próximo status

    def sincronizar(self, progresso=lambda f, a, t: None, cancelar=lambda: False
                    ) -> ResultadoSync:
        res = self._sincronizar_com(self.engine(), progresso, cancelar)
        if res.erro is None and not res.cancelado and not res.pulados:
            with self._trava:
                self._pendentes.clear()  # tudo o que estava pendente foi para o backup
        return res

    # ---------- espelhamento ----------
    def espelhar(self, escopo: str, id: str | None) -> None:
        """Agenda a cópia da alteração para o backup. Nunca lança erro."""
        if self.backup is None:
            return
        with self._trava:
            self._pendentes.add((escopo, id))
            self._fila.put((escopo, id))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._trabalhar, daemon=True,
                                                name="orbit-espelhamento")
                self._worker.start()

    def _trabalhar(self) -> None:
        while True:
            try:
                escopo, id = self._fila.get(timeout=0.5)
            except queue.Empty:
                return
            try:
                self._espelhar_agora(escopo, id)
            except Exception as e:  # nunca derruba a thread
                self._falha(e)
            finally:
                self._fila.task_done()

    def _espelhar_agora(self, escopo: str, id: str | None) -> None:
        if self.backup is None or not pasta_existe(self.backup, TIMEOUT_ACESSO_S):
            return  # continua pendente
        try:
            res = self._sincronizar_com(self.engine(), lambda f, a, t: None, lambda: False,
                                        somente=id if escopo == "container" else None)
        except LockHeld:
            return  # outra máquina sincronizando: fica pendente
        except OrbitError as e:
            self._falha(e)
            return
        if res.erro is None and not res.pulados:
            with self._trava:
                self._pendentes.discard((escopo, id))

    def aguardar_espelhamento(self, timeout: float = 30.0) -> bool:
        """Espera a fila de espelhamento esvaziar (usado em testes e ao fechar)."""
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if self._fila.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False

    def enviar_pendencias_locais(self) -> None:
        """Backup acessível de novo: envia sozinho o que mudou localmente sem divergência."""
        if self.backup is None or not pasta_existe(self.backup, TIMEOUT_ACESSO_S):
            return
        pend = self.pendentes()
        if pend:
            for escopo, id in sorted(pend, key=lambda p: (p[0], p[1] or "")):
                self._espelhar_agora(escopo, id)
            return
        # nada registrado (ex.: o programa foi fechado com o backup fora do ar): envia
        # sozinho só quando o que mudou é desta máquina e não há divergência
        try:
            comp = self._comparar()
        except OrbitError as e:
            self._falha(e)
            return
        so_local = (comp.enviar or comp.restaurar_backup or comp.containers)
        if (so_local and not comp.divergencias and not comp.receber
                and not comp.restaurar_local):
            try:
                self.sincronizar()
            except (LockHeld, OrbitError) as e:
                self._falha(e)

    # ---------- status ----------
    def _comparar(self) -> Comparacao:
        return self.engine().comparar()

    def status(self, forcar_comparacao: bool = False) -> StatusBackup:
        if self.backup is None:
            return StatusBackup("desativado")
        with self._trava:
            if self._sincronizando:
                return StatusBackup("sincronizando", ultima_sync=self._ultima_sync())
        if not pasta_existe(self.backup, TIMEOUT_ACESSO_S):
            st = StatusBackup("inacessivel", pendentes=len(self.pendentes()),
                              ultima_sync=self._ultima_sync(),
                              erro=f"Não foi possível acessar {self.backup}")
            self._ultimo_status = st
            return st
        intervalo = self.settings.intervalo_backup_min * 60
        if (not forcar_comparacao and self._ultimo_status is not None
                and self._ultimo_status.estado != "inacessivel"
                and time.monotonic() - self._ultima_comparacao < intervalo):
            return self._ultimo_status
        try:
            comp = self._comparar()
        except OrbitError as e:
            return StatusBackup("inacessivel", ultima_sync=self._ultima_sync(), erro=str(e))
        pend = (len(comp.enviar) + len(comp.receber) + len(comp.restaurar_local)
                + len(comp.restaurar_backup) + len(comp.containers))
        st = StatusBackup("em_dia" if comp.identico else "diferente", pendentes=pend,
                          divergencias=len(comp.divergencias), ultima_sync=self._ultima_sync())
        self._ultimo_status = st
        self._ultima_comparacao = time.monotonic()
        return st

    def _ultima_sync(self) -> str | None:
        if self.backup is None:
            return None
        return Retrato(self.sync_dir / id_par(self.base, self.backup)).ultima_sync()

    # ---------- recuperação ----------
    def recuperar_juntando(self, caminho: Path, progresso=lambda f, a, t: None,
                           cancelar=lambda: False) -> ResultadoSync:
        if self.analisar_caminho(caminho) != "orbit":
            raise OrbitError("A pasta indicada não é um backup do Orbit.")
        res = self._sincronizar_com(self.engine(caminho), progresso, cancelar)
        if self.log is not None:
            try:
                self.log.registrar_acao("recuperacao", {
                    "modo": "juntar", "backup": str(caminho), "recebidos": res.recebidos,
                    "enviados": res.enviados, "divergencias": len(res.divergencias)})
            except Exception as e:
                self._falha(e)
        return res
