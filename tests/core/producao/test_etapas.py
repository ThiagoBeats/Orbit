import pytest

from orbit.core.errors import OrbitError
from orbit.core.producao import etapas
from orbit.core.revisions import RevisionService


def _subir(repo, pid, tipo, origem):
    origem.mkdir(exist_ok=True)
    f = origem / f"{tipo}-{len(list(origem.iterdir()))}.pdf"
    f.write_bytes(b"pdf")
    return RevisionService(repo).enviar_revisao(pid, tipo, f, [], "Liberado para fabricação", "")


@pytest.fixture
def op_liberavel(prod, tmp_path):
    svc, repo, p = prod
    _subir(repo, p.id, "diagrama_eletrico", tmp_path / "o")
    _subir(repo, p.id, "layout_painel", tmp_path / "o")
    op = svc.criar_op(p.id, {"painel": "QGBT-01"})
    return svc, repo, p, op, tmp_path / "o"


def test_liberar_congela_as_revisoes_atuais(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    op = etapas.liberar(svc, op["id"])
    assert op["etapa"] == "liberada" and op["pacote_liberado_em"]
    assert sorted((d["tipo_id"], d["numero"]) for d in op["pacote"]) == [
        ("diagrama_eletrico", 0), ("layout_painel", 0)]
    assert op["pacote"][0]["principal"].endswith(".pdf")


def test_liberar_so_alguns_documentos(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    op = etapas.liberar(svc, op["id"], ["diagrama_eletrico"])
    assert [d["tipo_id"] for d in op["pacote"]] == ["diagrama_eletrico"]


def test_liberar_sem_documento_emitido_recusa(prod):
    svc, repo, p = prod
    op = svc.criar_op(p.id, {"painel": "X"})
    with pytest.raises(OrbitError):
        etapas.liberar(svc, op["id"])


def test_alerta_de_revisao_nova_e_atualizar_pacote(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    etapas.liberar(svc, op["id"])
    assert etapas.alertas_revisao(svc, svc.carregar(op["id"])) == []
    _subir(repo, p.id, "diagrama_eletrico", origem)  # Rev01 depois da liberação
    alertas = etapas.alertas_revisao(svc, svc.carregar(op["id"]))
    assert [(a["tipo_id"], a["liberada"], a["atual"]) for a in alertas] == [
        ("diagrama_eletrico", 0, 1)]
    op = etapas.atualizar_pacote(svc, op["id"])
    assert {d["tipo_id"]: d["numero"] for d in op["pacote"]}["diagrama_eletrico"] == 1
    assert etapas.alertas_revisao(svc, op) == []
    assert op["historico"][-1]["acao"] == "pacote_atualizado"


def test_avancar_e_voltar(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    with pytest.raises(OrbitError):
        etapas.avancar(svc, op["id"])  # planejada sem pacote liberado
    etapas.liberar(svc, op["id"])
    assert etapas.avancar(svc, op["id"])["etapa"] == "em_montagem"
    assert etapas.avancar(svc, op["id"])["etapa"] == "em_teste"
    with pytest.raises(OrbitError):
        etapas.voltar(svc, op["id"], "em_montagem", "  ")  # motivo obrigatório
    with pytest.raises(OrbitError):
        etapas.voltar(svc, op["id"], "aprovada", "x")  # só para trás
    op = etapas.voltar(svc, op["id"], "em_montagem", "faltou régua de bornes")
    assert op["etapa"] == "em_montagem"
    assert op["historico"][-1]["detalhes"]["motivo"] == "faltou régua de bornes"


def test_bloqueio_impede_avancar(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    etapas.liberar(svc, op["id"])
    op = etapas.bloquear(svc, op["id"], "Falta de material")
    assert op["bloqueio"]["motivo"] == "Falta de material" and op["etapa"] == "liberada"
    with pytest.raises(OrbitError):
        etapas.avancar(svc, op["id"])
    op = etapas.desbloquear(svc, op["id"])
    assert op["bloqueio"] is None
    assert etapas.avancar(svc, op["id"])["etapa"] == "em_montagem"


def test_documento_do_pacote_resolve_o_arquivo_mesmo_em_antigos(op_liberavel):
    svc, repo, p, op, origem = op_liberavel
    op = etapas.liberar(svc, op["id"])
    _subir(repo, p.id, "diagrama_eletrico", origem)  # Rev00 vai para Antigos
    caminho = etapas.arquivo_do_pacote(svc, op["id"], "diagrama_eletrico")
    assert caminho.is_file() and caminho.parent.name == "Antigos"
    with pytest.raises(OrbitError):
        etapas.arquivo_do_pacote(svc, op["id"], "memorial_descritivo")
