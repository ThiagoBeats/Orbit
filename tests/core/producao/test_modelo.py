import pytest

from orbit.core.errors import OrbitError
from orbit.core.jsonstore import read_json
from orbit.core.producao.config import carregar_config, salvar_config
from orbit.core.producao.modelo import ProducaoService


def test_config_padrao(prod):
    svc, repo, p = prod
    cfg = carregar_config(repo.base)
    assert cfg["isolacao_min_mohm"] == 1.0 and cfg["tolerancia_tensao_pct"] == 10
    assert cfg["amostragem_pct"] == 10 and cfg["amostragem_min"] == 10
    assert "Falta de material" in cfg["motivos_parada"]
    assert "Aperto/borne solto" in cfg["tipos_nc"]
    refs = [i["ref"] for i in cfg["checklist_iec"]]
    assert "11.6" in refs and "11.4" in refs and "11.10" in refs
    cfg["operadores"] = [{"nome": "João", "verificador": False}]
    salvar_config(repo.base, cfg)
    assert carregar_config(repo.base)["operadores"][0]["nome"] == "João"


def test_criar_op_numera_e_cria_pasta(prod):
    svc, repo, p = prod
    a = svc.criar_op(p.id, {"painel": "QGBT-01", "prazo": "2026-11-10", "prioridade": "alta"})
    b = svc.criar_op(p.id, {"painel": "CCM/02"})
    assert a["numero"] == "OP-0001" and b["numero"] == "OP-0002"
    assert a["etapa"] == "planejada" and a["bloqueio"] is None
    pasta = repo.container_path(repo.load_container(p.id)) / "Produção"
    assert (pasta / "OP-0001 - QGBT-01" / "op.json").is_file()
    assert (pasta / "OP-0002 - CCM-02" / "op.json").is_file()
    assert [o["numero"] for o in svc.listar_ops(p.id)] == ["OP-0001", "OP-0002"]
    assert read_json(repo.base / ".orbit" / "producao.json")["proximo_numero"] == 3


def test_validacoes(prod):
    svc, repo, p = prod
    with pytest.raises(OrbitError):
        svc.criar_op(p.id, {"painel": "  "})
    with pytest.raises(OrbitError):
        svc.criar_op("nao-existe", {"painel": "X"})
    with pytest.raises(OrbitError):
        svc.criar_op(p.id, {"painel": "X", "prioridade": "maxima"})
    with pytest.raises(OrbitError):
        svc.criar_op(p.id, {"painel": "X", "prazo": "amanhã"})


def test_carregar_e_editar_com_historico(prod):
    svc, repo, p = prod
    op = svc.criar_op(p.id, {"painel": "QGBT-01"})
    with svc.editar(op["id"]) as d:
        d["descricao"] = "Quadro geral"
        svc.registrar(d, "dados_alterados", {"descricao": "Quadro geral"})
    op2 = svc.carregar(op["id"])
    assert op2["descricao"] == "Quadro geral"
    assert [h["acao"] for h in op2["historico"]] == ["op_criada", "dados_alterados"]
    with pytest.raises(OrbitError):
        svc.carregar("nao-existe")


def test_todas_as_ops_de_varios_projetos(prod):
    svc, repo, p = prod
    cli = repo.create_cliente("Outro")
    p2 = repo.create_projeto(cli.id, "9", "Outro projeto")
    svc.criar_op(p.id, {"painel": "A"})
    svc.criar_op(p2.id, {"painel": "B"})
    todas = svc.todas_ops()
    assert sorted(o["painel"] for o in todas) == ["A", "B"]
    assert {o["container_nome"] for o in todas} == {"Envasadora", "Outro projeto"}
