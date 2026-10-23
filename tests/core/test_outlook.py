"""OutlookClient: COM inicializado em cada thread (pywebview chama a Api em threads novas)."""
import sys
import threading
import types

import pytest

from orbit.core.email import EmailDraft
from orbit.core.outlook import OutlookClient


@pytest.fixture
def com_falso(monkeypatch):
    """pythoncom e win32com.client falsos: Dispatch só funciona com COM inicializado na thread."""
    estado = threading.local()
    chamadas = {"init": 0, "uninit": 0, "dispatch": 0}

    def co_initialize():
        chamadas["init"] += 1
        estado.n = getattr(estado, "n", 0) + 1

    def co_uninitialize():
        chamadas["uninit"] += 1
        estado.n -= 1

    class Item:
        def __init__(self):
            self.anexos = []
            self.Attachments = types.SimpleNamespace(Add=self.anexos.append)
            self.exibido = False

        def Display(self):
            self.exibido = True

    itens = []

    class App:
        def CreateItem(self, _):
            itens.append(Item())
            return itens[-1]

    def dispatch(nome):
        chamadas["dispatch"] += 1
        if getattr(estado, "n", 0) <= 0:
            raise RuntimeError("(-2147221008, 'CoInitialize não foi chamado.')")
        return App()

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = co_initialize
    pythoncom.CoUninitialize = co_uninitialize
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    client.Dispatch = dispatch
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return chamadas, itens


def _em_thread_nova(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()))
    t.start()
    t.join(5)
    return out.get("r")


def test_disponivel_em_threads_novas_seguidas(com_falso):
    chamadas, _ = com_falso
    o = OutlookClient()
    assert _em_thread_nova(o.disponivel) is True
    assert _em_thread_nova(o.disponivel) is True
    assert chamadas["init"] == 2 and chamadas["uninit"] == 2


def test_abrir_rascunho_inicializa_e_finaliza_com(com_falso, tmp_path):
    chamadas, itens = com_falso
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    d = EmailDraft(["a@x.com", "b@x.com"], "Assunto", "Corpo", [f])
    _em_thread_nova(lambda: OutlookClient().abrir_rascunho(d))
    _em_thread_nova(lambda: OutlookClient().abrir_rascunho(d))
    assert len(itens) == 2 and all(i.exibido for i in itens)
    assert itens[0].To == "a@x.com; b@x.com" and itens[0].anexos == [str(f)]
    assert chamadas["init"] == chamadas["uninit"] == 2


def test_couninitialize_mesmo_com_erro(com_falso, monkeypatch):
    chamadas, _ = com_falso

    def falha(nome):
        raise RuntimeError("classe não registrada")
    monkeypatch.setattr(sys.modules["win32com.client"], "Dispatch", falha)
    assert _em_thread_nova(OutlookClient().disponivel) is False
    with pytest.raises(RuntimeError):
        OutlookClient().abrir_rascunho(EmailDraft([], "", "", []))
    assert chamadas["init"] == chamadas["uninit"] == 2
