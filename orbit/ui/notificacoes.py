"""Notificação dos lembretes (spec Meu dia §4).

- ToastNotificador: toast nativo do Windows (biblioteca windows-toasts), com os
  botões "Adiar 10 min", "Adiar 1 h" e "Concluir". Aparece com o Orbit
  minimizado. Registra um AppUserModelID próprio em HKCU (sem admin) para o
  toast aparecer como "Orbit"; se não conseguir, usa o padrão da biblioteca.
- AgendaLembretes: thread que confere os lembretes a cada 20 s. Na primeira
  rodada, os vencidos antes da abertura vão para `ao_perdidos` (um popup só)
  em vez de virarem uma série de toasts.

Nenhuma falha de notificação interrompe a agenda nem o programa.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from orbit.core.errors import OrbitError
from orbit.core.lembretes import adiar, concluir, marcar_disparado, vencidos

AUMID = "LSdoBrasil.Orbit"
ACOES = {"adiar10": 10, "adiar60": 60}


def _registrar_aumid(icone: Path | None) -> bool:
    try:
        import winreg
        chave = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                 rf"Software\Classes\AppUserModelId\{AUMID}")
        winreg.SetValueEx(chave, "DisplayName", 0, winreg.REG_SZ, "Orbit")
        if icone is not None and Path(icone).is_file():
            winreg.SetValueEx(chave, "IconUri", 0, winreg.REG_SZ, str(icone))
        winreg.CloseKey(chave)
        return True
    except OSError:
        return False


class ToastNotificador:
    def __init__(self, registrar_aumid: bool = True, icone: Path | None = None,
                 registrar: Callable[[BaseException], None] | None = None):
        self._usar_aumid = registrar_aumid and _registrar_aumid(icone)
        self._registrar = registrar
        self._toaster = None

    def _falha(self, e: BaseException) -> None:
        if self._registrar:
            try:
                self._registrar(e)
            except Exception:
                pass

    def disponivel(self) -> bool:
        try:
            import windows_toasts  # noqa: F401
            return True
        except Exception:
            return False

    def mostrar(self, lem, ao_acao: Callable[[str], None]) -> None:
        try:
            from windows_toasts import (InteractableWindowsToaster, Toast, ToastButton,
                                        ToastScenario)
        except Exception as e:
            self._falha(e)
            return
        try:
            if self._toaster is None:
                self._toaster = InteractableWindowsToaster(
                    "Orbit", AUMID if self._usar_aumid else None)
            toast = Toast(["Lembrete", lem.texto], scenario=ToastScenario.Reminder)
            for texto, acao in (("Adiar 10 min", "adiar10"), ("Adiar 1 h", "adiar60"),
                                ("Concluir", "concluir")):
                toast.AddAction(ToastButton(texto, acao))

            def ativado(args):
                if args is not None and args.arguments in ("adiar10", "adiar60", "concluir"):
                    ao_acao(args.arguments)
            toast.on_activated = ativado
            self._toaster.show_toast(toast)
        except Exception as e:  # toast bloqueado, WinRT indisponível...
            self._falha(e)


class AgendaLembretes:
    def __init__(self, servico, notificadores: list, agora: Callable[[], datetime] = datetime.now,
                 intervalo_s: float = 20,
                 ao_perdidos: Callable[[list], None] = lambda lista: None,
                 registrar: Callable[[BaseException], None] | None = None):
        self.servico = servico
        self.notificadores = list(notificadores)
        self.agora = agora
        self.intervalo_s = intervalo_s
        self.ao_perdidos = ao_perdidos
        self.registrar = registrar
        self._inicio = agora()
        self._primeira = True
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._trava = threading.Lock()

    def _falha(self, e: BaseException) -> None:
        if self.registrar:
            try:
                self.registrar(e)
            except Exception:
                pass

    @property
    def rodando(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def acao(self, lembrete_id: str, acao: str) -> None:
        agora = self.agora()
        if acao in ACOES:
            self.servico.aplicar(lembrete_id, lambda l: adiar(l, ACOES[acao], agora))
        elif acao == "concluir":
            self.servico.aplicar(lembrete_id, lambda l: concluir(l, agora))
        else:
            raise OrbitError("Ação inválida.")

    def verificar_agora(self) -> None:
        with self._trava:
            try:
                lista = self.servico.lembretes()
            except OrbitError as e:  # meu_dia.json ilegível: tenta de novo depois
                self._falha(e)
                return
            agora = self.agora()
            venc = vencidos(lista, agora)
            perdidos = []
            if self._primeira:
                self._primeira = False
                limite = self._inicio - timedelta(seconds=60)
                perdidos = [l for l in venc if l.efetivo < limite]
            for lem in venc:
                try:
                    self.servico.aplicar(lem.id, lambda l: marcar_disparado(l, agora))
                except OrbitError as e:
                    self._falha(e)
                    continue
                if lem in perdidos:
                    continue
                for n in self.notificadores:
                    try:
                        n.mostrar(lem, lambda a, i=lem.id: self._acao_segura(i, a))
                    except Exception as e:
                        self._falha(e)
            if perdidos:
                try:
                    self.ao_perdidos(perdidos)
                except Exception as e:
                    self._falha(e)

    def _acao_segura(self, lembrete_id: str, acao: str) -> None:
        try:
            self.acao(lembrete_id, acao)
        except Exception as e:
            self._falha(e)

    def iniciar(self) -> None:
        if self.rodando:
            return
        self._parar.clear()

        def loop():
            while True:
                try:
                    self.verificar_agora()
                except Exception as e:
                    self._falha(e)
                if self._parar.wait(self.intervalo_s):
                    return
        self._thread = threading.Thread(target=loop, daemon=True, name="orbit-lembretes")
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(5)
