import builtins
from datetime import datetime, timedelta

from orbit.core.config import load_shared_config
from orbit.core.identity import Identity
from orbit.core.meudia import MeuDiaService
from orbit.core.repository import Repository
from orbit.ui.notificacoes import AgendaLembretes, ToastNotificador

EU = Identity("thiago", "PC1")


class Falso:
    def __init__(self):
        self.mostrados = []

    def mostrar(self, lem, ao_acao):
        self.mostrados.append((lem, ao_acao))


def _amb(tmp_path, inicio):
    base = tmp_path / "base"
    base.mkdir()
    t = [inicio]
    relogio = lambda: t[0]
    repo = Repository(base, EU, load_shared_config(base), agora=relogio)
    svc = MeuDiaService(repo, EU, agora=relogio)
    return svc, t, relogio


def test_vencido_mostra_e_marca(tmp_path):
    svc, t, relogio = _amb(tmp_path, datetime(2026, 10, 23, 8, 0))
    l = svc.salvar_lembrete({"texto": "Reunião", "quando": "2026-10-23T09:00"})
    falso = Falso()
    perdidos = []
    ag = AgendaLembretes(svc, [falso], agora=relogio, ao_perdidos=perdidos.append)
    ag.verificar_agora()  # primeira rodada: nada vencido
    t[0] = datetime(2026, 10, 23, 9, 0, 10)
    ag.verificar_agora()
    assert [x[0].texto for x in falso.mostrados] == ["Reunião"]
    assert svc.lembretes()[0].ativo is False
    ag.verificar_agora()
    assert len(falso.mostrados) == 1
    assert perdidos == []


def test_perdidos_na_primeira_rodada_nao_viram_toast(tmp_path):
    svc, t, relogio = _amb(tmp_path, datetime(2026, 10, 23, 8, 0))
    svc.salvar_lembrete({"texto": "Antigo", "quando": "2026-10-22T09:00",
                         "recorrencia": {"tipo": "diaria"}})
    falso = Falso()
    perdidos = []
    ag = AgendaLembretes(svc, [falso], agora=relogio, ao_perdidos=perdidos.append)
    ag.verificar_agora()
    assert falso.mostrados == []
    assert [[l.texto for l in lista] for lista in perdidos] == [["Antigo"]]
    assert svc.lembretes()[0].quando == "2026-10-23T09:00"
    ag.verificar_agora()
    assert len(perdidos) == 1


def test_acao_adiar_reagenda(tmp_path):
    svc, t, relogio = _amb(tmp_path, datetime(2026, 10, 23, 8, 0))
    svc.salvar_lembrete({"texto": "x", "quando": "2026-10-23T08:30"})
    falso = Falso()
    ag = AgendaLembretes(svc, [falso], agora=relogio)
    ag.verificar_agora()
    t[0] = datetime(2026, 10, 23, 8, 30, 5)
    ag.verificar_agora()
    lem, ao_acao = falso.mostrados[0]
    ao_acao("adiar10")
    assert svc.lembretes()[0].adiado_ate == "2026-10-23T08:40"
    t[0] = datetime(2026, 10, 23, 8, 40, 1)
    ag.verificar_agora()
    assert len(falso.mostrados) == 2
    falso.mostrados[1][1]("concluir")
    assert svc.lembretes()[0].ativo is False


def test_falha_de_um_notificador_nao_impede_os_outros(tmp_path):
    svc, t, relogio = _amb(tmp_path, datetime(2026, 10, 23, 8, 0))
    svc.salvar_lembrete({"texto": "x", "quando": "2026-10-23T08:30"})

    class Quebrado:
        def mostrar(self, lem, ao_acao):
            raise RuntimeError("toast quebrou")
    falso = Falso()
    ag = AgendaLembretes(svc, [Quebrado(), falso], agora=relogio)
    ag.verificar_agora()
    t[0] = datetime(2026, 10, 23, 8, 31)
    ag.verificar_agora()
    assert len(falso.mostrados) == 1


def test_toast_indisponivel_nao_quebra(monkeypatch):
    original = builtins.__import__

    def sem_toasts(nome, *a, **k):
        if nome.startswith("windows_toasts"):
            raise ImportError("sem winrt")
        return original(nome, *a, **k)
    monkeypatch.setattr(builtins, "__import__", sem_toasts)
    n = ToastNotificador(registrar_aumid=False)
    assert n.disponivel() is False
    n.mostrar(None, lambda a: None)  # não lança


def test_iniciar_e_parar(tmp_path):
    svc, t, relogio = _amb(tmp_path, datetime(2026, 10, 23, 8, 0))
    ag = AgendaLembretes(svc, [Falso()], agora=relogio, intervalo_s=0.05)
    ag.iniciar()
    ag.parar()
    assert not ag.rodando
