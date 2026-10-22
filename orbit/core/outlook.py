"""Adaptador COM do Outlook clássico. O win32com só é importado dentro das funções.

O pywebview chama a Api numa thread nova a cada chamada do JS, e o COM precisa
ser inicializado em cada thread que o usa: todo uso fica entre
`pythoncom.CoInitialize()` e `pythoncom.CoUninitialize()` (ver `_com`).
"""
from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def _com():
    import pythoncom
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


class OutlookClient:
    def instalado(self) -> bool:
        """Outlook clássico registrado no Windows (sem abrir o Outlook)."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
                return True
        except OSError:
            return False

    def disponivel(self) -> bool:
        try:
            with _com():
                import win32com.client
                win32com.client.Dispatch("Outlook.Application")
            return True
        except Exception:
            return False

    def abrir_rascunho(self, d) -> None:
        with _com():
            import win32com.client
            outlook = win32com.client.Dispatch("Outlook.Application")
            item = outlook.CreateItem(0)
            item.To = "; ".join(d.destinatarios)
            item.Subject = d.assunto
            item.Body = d.corpo
            for p in d.anexos:
                item.Attachments.Add(str(p))
            item.Display()
