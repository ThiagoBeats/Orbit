"""Adaptador COM do Outlook clássico. O win32com só é importado dentro das funções."""
from __future__ import annotations


class OutlookClient:
    def disponivel(self) -> bool:
        try:
            import win32com.client
            win32com.client.Dispatch("Outlook.Application")
            return True
        except Exception:
            return False

    def abrir_rascunho(self, d) -> None:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        item = outlook.CreateItem(0)
        item.To = "; ".join(d.destinatarios)
        item.Subject = d.assunto
        item.Body = d.corpo
        for p in d.anexos:
            item.Attachments.Add(str(p))
        item.Display()
