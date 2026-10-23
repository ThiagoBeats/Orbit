import json
from datetime import datetime, timedelta

import pytest

from orbit.core.actionlog import ActionLog, LinhaLog, mesclar_logs
from orbit.core.identity import Identity


class Relogio:
    def __init__(self):
        self.t = datetime(2026, 10, 23, 8, 0, 0)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


def _log(tmp_path, computador="PC1", relogio=None):
    return ActionLog(tmp_path / "base", Identity("thiago", computador),
                     tmp_path / f"ancoras-{computador}.json", agora=relogio or Relogio())


@pytest.fixture
def log(tmp_path):
    return _log(tmp_path)


def _linhas_brutas(log):
    return log.caminho.read_text(encoding="utf-8").splitlines()


def _gravar_brutas(log, linhas):
    log.caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def test_registra_e_encadeia(log):
    a = log.registrar_acao("revisao_enviada", {"x": 1})
    b = log.registrar_acao("status_alterado", {})
    assert a.seq == "PC1-1" and b.seq == "PC1-2"
    assert a.anterior == "0" * 64 and b.anterior == a.codigo
    assert a.codigo == a.calcular_codigo()
    assert [l.seq for l in log.ler()] == ["PC1-1", "PC1-2"]
    assert log.verificar().integro


def test_editar_linha_e_detectado(log):
    log.registrar_acao("revisao_enviada", {"x": 1})
    log.registrar_acao("status_alterado", {})
    brutas = _linhas_brutas(log)
    d = json.loads(brutas[0])
    d["detalhes"] = {"x": 2}
    brutas[0] = json.dumps(d, ensure_ascii=False)
    _gravar_brutas(log, brutas)
    rel = log.verificar()
    assert not rel.integro
    assert rel.problemas[0].computador == "PC1" and rel.problemas[0].a_partir_de_n == 1


def test_apagar_linha_do_meio_e_detectado(log):
    for i in range(3):
        log.registrar_acao("status_alterado", {"i": i})
    brutas = _linhas_brutas(log)
    _gravar_brutas(log, [brutas[0], brutas[2]])
    rel = log.verificar()
    assert not rel.integro and rel.problemas[0].a_partir_de_n == 2


def test_recalcular_corrente_inteira_pego_pela_ancora(log):
    for i in range(3):
        log.registrar_acao("status_alterado", {"i": i})
    # reescreve a corrente inteira com outro conteúdo e códigos recalculados
    novas = []
    anterior = "0" * 64
    for linha in log.ler():
        linha.detalhes = {"i": "forjado"}
        linha.anterior = anterior
        linha.codigo = linha.calcular_codigo()
        anterior = linha.codigo
        novas.append(json.dumps(linha.to_dict(), ensure_ascii=False))
    _gravar_brutas(log, novas)
    assert not log.verificar().integro


def test_alerta_registra_uma_vez(log):
    log.registrar_acao("status_alterado", {})
    log.registrar_acao("status_alterado", {})
    brutas = _linhas_brutas(log)
    _gravar_brutas(log, brutas[:1] + [brutas[1].replace("status_alterado", "outro")])
    log.alertar_se_adulterado()
    log.alertar_se_adulterado()
    alertas = [l for l in log.ler() if l.acao == "adulteracao_detectada"]
    assert len(alertas) == 1
    assert alertas[0].detalhes["a_partir_de_n"] == 2
    assert log.verificar().integro


def test_dois_computadores_no_mesmo_arquivo(tmp_path):
    rel = Relogio()
    a, b = _log(tmp_path, "PC1", rel), _log(tmp_path, "PC2", rel)
    a.registrar_acao("x", {})
    b.registrar_acao("x", {})
    a.registrar_acao("x", {})
    assert [l.seq for l in a.ler()] == ["PC1-1", "PC2-1", "PC1-2"]
    assert a.verificar().integro and b.verificar().integro


def test_mesclar_logs_uniao_e_conflito():
    def linha(seq, n, hora, acao="x"):
        l = LinhaLog(seq, n, seq.split("-")[0], "u", hora, acao, {}, "0" * 64, "")
        l.codigo = l.calcular_codigo()
        return l
    a = [linha("PC1-1", 1, "2026-10-23T08:00:01"), linha("PC1-2", 1, "2026-10-23T08:00:03")]
    b = [linha("PC1-1", 1, "2026-10-23T08:00:01"), linha("PC2-1", 1, "2026-10-23T08:00:02"),
         linha("PC1-2", 1, "2026-10-23T08:00:03", acao="y")]
    juntas, conflitos = mesclar_logs(a, b)
    assert [l.seq for l in juntas] == ["PC1-1", "PC2-1", "PC1-2"]
    assert conflitos == ["PC1-2"]


def test_linha_ilegivel_nao_quebra(log):
    log.registrar_acao("x", {})
    with open(log.caminho, "a", encoding="utf-8") as f:
        f.write("lixo\n")
    assert len(log.ler()) == 1
    assert not log.verificar().integro
