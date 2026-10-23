import json

import pytest

from orbit.core.config import UserSettings, load_user_settings, save_user_settings
from orbit.ui import api as api_mod
from orbit.ui.api import Api


class JanelaSeq:
    """create_file_dialog devolve as respostas na ordem."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)

    def create_file_dialog(self, *a, **k):
        return self.respostas.pop(0) if self.respostas else None


@pytest.fixture
def amb(tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    settings = tmp_path / "appdata" / "settings.json"
    save_user_settings(UserSettings(str(base), "escuro"), settings)
    a = Api(settings_path=settings, log_path=tmp_path / "appdata" / "orbit.log")
    c = a.criar_cliente({"nome": "Alfa"})["dados"]
    p = a.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    origem = tmp_path / "origem"
    origem.mkdir()
    bk = tmp_path / "bk"
    bk.mkdir()
    yield a, base, p["id"], origem, bk, settings
    a._fileserver.stop()


def _enviar(a, pid, origem, nome="d.pdf", conteudo="x", tipo="diagrama_eletrico"):
    f = origem / nome
    f.write_text(conteudo, encoding="utf-8")
    r = a.enviar_revisao(pid, tipo, str(f), [], "Em elaboração", "m", None)
    assert r["ok"], r


def _configurar(a, bk):
    r = a.configurar_backup(str(bk))
    assert r["ok"], r
    assert a._aguardar_job(30)
    res = a.progresso_backup()["dados"]["resultado"]
    assert res and res.get("erro") is None, res
    return res


def test_status_desativado_sem_backup(amb):
    a = amb[0]
    st = a.status_backup()["dados"]
    assert st["estado"] == "desativado" and st["caminho"] is None


def test_configurar_e_status_em_dia(amb):
    a, base, pid, origem, bk, settings = amb
    _enviar(a, pid, origem)
    _configurar(a, bk)
    assert load_user_settings(settings).backup == str(bk)
    assert a.status_backup(True)["dados"]["estado"] == "em_dia"
    assert len(list(bk.rglob("*.pdf"))) == 1


def test_escolher_backup_analisa(amb):
    a, base, pid, origem, bk, _ = amb
    a.definir_janela(JanelaSeq(str(bk)))
    r = a.escolher_backup()["dados"]
    assert r == {"caminho": str(bk), "analise": "vazio", "aviso_nuvem": None}
    a.definir_janela(JanelaSeq(None))
    assert a.escolher_backup()["dados"] is None


def test_upload_espelha_no_backup(amb):
    a, base, pid, origem, bk, _ = amb
    _configurar(a, bk)
    _enviar(a, pid, origem)
    assert a._backup.aguardar_espelhamento(30)
    assert len(list(bk.rglob("*.pdf"))) == 1


def test_sincronizar_progresso_e_resultado(amb):
    a, base, pid, origem, bk, _ = amb
    _configurar(a, bk)
    a._backup.settings.backup = None  # sem espelhar
    _enviar(a, pid, origem)
    a._backup.settings.backup = str(bk)
    assert a.sincronizar_backup()["ok"]
    assert a._aguardar_job(30)
    p = a.progresso_backup()["dados"]
    assert p["rodando"] is False and p["resultado"]["enviados"] >= 1
    assert a.sincronizar_backup()["ok"]  # pode iniciar de novo depois de terminar
    a._aguardar_job(30)


def test_sincronizar_sem_backup_configurado(amb):
    a = amb[0]
    r = a.sincronizar_backup()
    assert r["ok"] is False and "backup" in r["erro"].lower()


def _criar_divergencia(a, base, pid, origem, bk):
    _enviar(a, pid, origem)
    _configurar(a, bk)
    a._backup.settings.backup = None
    assert a.alterar_status(pid, "diagrama_eletrico", "Aprovado")["ok"]
    a._backup.settings.backup = str(bk)
    arq = next(bk.rglob("projeto.json"))
    d = json.loads(arq.read_text(encoding="utf-8"))
    d["documentos"]["diagrama_eletrico"]["revisoes"][0]["status"] = "Para aprovação"
    arq.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    a.sincronizar_backup()
    a._aguardar_job(30)
    return a.listar_divergencias()["dados"]


def test_resolver_divergencia_valida_escolha(amb):
    a, base, pid, origem, bk, _ = amb
    divs = _criar_divergencia(a, base, pid, origem, bk)
    assert len(divs) == 1
    assert a.resolver_divergencia(divs[0]["id"], "ambos")["ok"] is False
    assert a.resolver_divergencia(divs[0]["id"], "../x")["ok"] is False
    r = a.resolver_divergencia(divs[0]["id"], "backup")
    assert r["ok"], r
    assert r["dados"] == []
    painel = a.obter_painel(pid)["dados"]
    doc = next(d for d in painel["documentos"] if d["tipo_id"] == "diagrama_eletrico")
    assert doc["atual"]["status"] == "Para aprovação"


def test_abrir_arquivo_divergencia_nao_aceita_caminho_do_js(amb, monkeypatch):
    a, base, pid, origem, bk, _ = amb
    abertos = []
    monkeypatch.setattr(api_mod.os, "startfile", lambda p: abertos.append(p), raising=False)
    solto = base / "Clientes" / "Alfa" / "notas.txt"
    solto.write_text("v1", encoding="utf-8")
    _configurar(a, bk)
    solto.write_text("casa", encoding="utf-8")
    (bk / "Clientes" / "Alfa" / "notas.txt").write_text("servidor", encoding="utf-8")
    a._backup.settings.backup = str(bk)
    a.sincronizar_backup()
    a._aguardar_job(30)
    [d] = a.listar_divergencias()["dados"]
    assert a.abrir_arquivo_divergencia(d["id"], "../../Windows")["ok"] is False
    assert a.abrir_arquivo_divergencia("x" * 32, "backup")["ok"] is False
    assert a.abrir_arquivo_divergencia(d["id"], "backup")["ok"]
    assert len(abertos) == 1 and str(abertos[0]).startswith(str(bk))


def test_restaurar_pc_novo_api(amb, tmp_path):
    a, base, pid, origem, bk, settings = amb
    _enviar(a, pid, origem)
    _configurar(a, bk)
    nova = tmp_path / "nova"
    nova.mkdir()
    a.definir_janela(JanelaSeq(str(bk), str(nova)))
    r = a.restaurar_pc_novo()
    assert r["ok"], r
    assert a._aguardar_job(30)
    res = a.progresso_backup()["dados"]["resultado"]
    assert res["erro"] is None and res["nova_base"] == str(nova)
    assert len(list(nova.rglob("*.pdf"))) == 1
    r = a.concluir_restauracao(str(nova), str(bk), True)
    assert r["ok"], r
    s = load_user_settings(settings)
    assert s.pasta_base == str(nova) and s.backup == str(bk)


def test_definir_intervalo(amb):
    a, *_ , settings = amb
    assert a.definir_intervalo_backup(30)["dados"] == 30
    assert load_user_settings(settings).intervalo_backup_min == 30
    assert a.definir_intervalo_backup(0)["dados"] == 1
