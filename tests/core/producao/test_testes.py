import random

import pytest

from orbit.core.errors import OrbitError
from orbit.core.producao import etapas, testes as T
from orbit.core.revisions import RevisionService


@pytest.fixture
def op_em_teste(prod, tmp_path):
    svc, repo, p = prod
    f = tmp_path / "d.pdf"
    f.write_bytes(b"x")
    RevisionService(repo).enviar_revisao(p.id, "diagrama_eletrico", f, [], "Aprovado", "")
    op = svc.criar_op(p.id, {"painel": "QGBT-01"})
    etapas.liberar(svc, op["id"])
    etapas.avancar(svc, op["id"])
    etapas.avancar(svc, op["id"])  # em_teste
    return svc, op["id"]


def _linhas(n):
    return [{"origem": f"X1:{i}", "destino": f"K{i}:A1", "fio": f"{i}", "secao": "1,0",
             "cor": "AZ"} for i in range(1, n + 1)]


def _tudo_ok(svc, op_id, operador="João"):
    op = svc.carregar(op_id)
    for it in T.itens_inspecao(svc, op_id):
        T.marcar_inspecao(svc, op_id, it["id"], "ok", operador)
    for l in svc.carregar(op_id)["testes"]["ponto_a_ponto"]["linhas"]:
        T.marcar_ligacao(svc, op_id, l["id"], "ok", "ok", operador)
    c = T.adicionar_circuito(svc, op_id, "Potência L1-L2-L3 x PE", 500)
    T.medir_isolacao(svc, op_id, c["id"], 250.0, operador)
    for s in svc.carregar(op_id)["testes"]["io"]["sinais"]:
        T.marcar_sinal(svc, op_id, s["id"], "ok", operador)


def test_inspecao_usa_o_checklist_iec(op_em_teste):
    svc, op_id = op_em_teste
    itens = T.itens_inspecao(svc, op_id)
    assert len(itens) == 11 and itens[0]["ref"] == "11.2"
    assert T.situacao(svc.carregar(op_id), svc.config())["inspecao"]["estado"] == "nao_iniciado"


def test_nc_na_inspecao_exige_tipo_e_abre_nc(op_em_teste):
    svc, op_id = op_em_teste
    item = T.itens_inspecao(svc, op_id)[5]
    with pytest.raises(OrbitError):
        T.marcar_inspecao(svc, op_id, item["id"], "nc", "João")  # sem tipo
    T.marcar_inspecao(svc, op_id, item["id"], "nc", "João", obs="X1:4 frouxo",
                      nc_tipo="Aperto/borne solto")
    ncs = svc.carregar(op_id)["ncs"]
    assert len(ncs) == 1 and ncs[0]["numero"] == 1 and ncs[0]["situacao"] == "aberta"
    assert ncs[0]["origem"] == {"bloco": "inspecao", "linha_id": item["id"]}


def test_ponto_a_ponto_e_aperto(op_em_teste):
    svc, op_id = op_em_teste
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(3))
    op = svc.carregar(op_id)
    l = op["testes"]["ponto_a_ponto"]["linhas"]
    T.marcar_ligacao(svc, op_id, l[0]["id"], "ok", None, "João")
    st = T.situacao(svc.carregar(op_id), svc.config())["ponto_a_ponto"]
    assert st["estado"] == "em_andamento" and st["feitos"] == 0 and st["total"] == 3
    T.marcar_ligacao(svc, op_id, l[0]["id"], "ok", "ok", "João")
    assert T.situacao(svc.carregar(op_id), svc.config())["ponto_a_ponto"]["feitos"] == 1
    with pytest.raises(OrbitError):
        T.marcar_ligacao(svc, op_id, l[1]["id"], "talvez", "ok", "João")


def test_recarregar_lista_com_marcas_guarda_a_anterior(op_em_teste):
    svc, op_id = op_em_teste
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(2))
    l = svc.carregar(op_id)["testes"]["ponto_a_ponto"]["linhas"]
    T.marcar_ligacao(svc, op_id, l[0]["id"], "ok", "ok", "João")
    with pytest.raises(OrbitError):
        T.carregar_ponto_a_ponto(svc, op_id, _linhas(4))
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(4), substituir=True)
    pp = svc.carregar(op_id)["testes"]["ponto_a_ponto"]
    assert len(pp["linhas"]) == 4 and len(pp["anteriores"]) == 1


def test_isolacao_abaixo_do_criterio_reprova_e_abre_nc(op_em_teste):
    svc, op_id = op_em_teste
    c = T.adicionar_circuito(svc, op_id, "Comando 24V x PE", 500)
    T.medir_isolacao(svc, op_id, c["id"], 0.4, "João")
    op = svc.carregar(op_id)
    assert op["testes"]["isolacao"]["circuitos"][0]["resultado"] == "nc"
    assert op["ncs"][0]["tipo"] == "Isolação"


def test_energizacao_tolerancia(op_em_teste):
    svc, op_id = op_em_teste
    p1 = T.adicionar_ponto_tensao(svc, op_id, "Entrada L1-L2", 380)
    p2 = T.adicionar_ponto_tensao(svc, op_id, "Fonte 24Vcc", 24)
    T.medir_tensao(svc, op_id, p1["id"], 395, "João")
    T.medir_tensao(svc, op_id, p2["id"], 20, "João")
    pts = svc.carregar(op_id)["testes"]["energizacao"]["pontos"]
    assert [p["resultado"] for p in pts] == ["ok", "nc"]
    passos = T.passos_energizacao(svc, op_id)
    assert len(passos) == 5
    T.marcar_passo(svc, op_id, passos[0]["id"], "ok", "João")


def test_io_marcado_por_sinal(op_em_teste):
    svc, op_id = op_em_teste
    T.carregar_io(svc, op_id, [{"tag": "S1", "descricao": "Emergência", "endereco": "I0.0",
                                "tipo": "DI"}])
    s = svc.carregar(op_id)["testes"]["io"]["sinais"][0]
    T.marcar_sinal(svc, op_id, s["id"], "ok", "João")
    assert T.situacao(svc.carregar(op_id), svc.config())["io"]["estado"] == "concluido"


def test_pendencias_bloqueiam_a_verificacao_final(op_em_teste):
    svc, op_id = op_em_teste
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(3))
    with pytest.raises(OrbitError) as e:
        etapas.avancar(svc, op_id)
    assert "Inspeção" in str(e.value) and "Ponto a ponto" in str(e.value)
    _tudo_ok(svc, op_id)
    assert T.pendencias(svc.carregar(op_id), svc.config()) == []
    assert etapas.avancar(svc, op_id)["etapa"] == "verificacao_final"


def test_nc_aberta_bloqueia_e_reteste_libera(op_em_teste):
    svc, op_id = op_em_teste
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(2))
    _tudo_ok(svc, op_id)
    l = svc.carregar(op_id)["testes"]["ponto_a_ponto"]["linhas"][0]
    T.marcar_ligacao(svc, op_id, l["id"], "nc", "ok", "João", obs="trocado com X1:2",
                     nc_tipo="Fio/ligação trocada")
    nc = svc.carregar(op_id)["ncs"][-1]
    assert any("não conformidade" in p for p in T.pendencias(svc.carregar(op_id), svc.config()))
    with pytest.raises(OrbitError):
        T.verificar_nc(svc, op_id, nc["id"], "Maria")  # ainda não corrigida
    T.corrigir_nc(svc, op_id, nc["id"], "João", "religado")
    T.verificar_nc(svc, op_id, nc["id"], "Maria")
    op = svc.carregar(op_id)
    assert op["ncs"][-1]["situacao"] == "verificada"
    assert op["testes"]["ponto_a_ponto"]["linhas"][0]["ligacao"] == "ok"
    assert T.pendencias(op, svc.config()) == []


def _ir_para_verificacao(svc, op_id, n=30):
    T.carregar_ponto_a_ponto(svc, op_id, _linhas(n))
    _tudo_ok(svc, op_id)
    etapas.avancar(svc, op_id)


def test_amostragem_por_outra_pessoa(op_em_teste):
    svc, op_id = op_em_teste
    _ir_para_verificacao(svc, op_id, 30)
    with pytest.raises(OrbitError):
        T.sortear_amostra(svc, op_id, "João")  # quem montou/testou não verifica
    am = T.sortear_amostra(svc, op_id, "Maria", rnd=random.Random(1))
    assert len(am["sorteadas"]) == 10  # 10% de 30 = 3 → mínimo 10
    for lid in am["sorteadas"]:
        T.marcar_amostra(svc, op_id, lid, "ok", "Maria")
    for i in range(len(am["checklist"])):
        T.marcar_checklist_final(svc, op_id, i, "ok", "Maria")
    res = T.concluir_verificacao(svc, op_id, "Maria")
    assert res["testes"]["verificacao"]["aprovada"] is True
    assert etapas.avancar(svc, op_id)["etapa"] == "aprovada"


def test_amostragem_com_falha_volta_e_zera_o_ponto_a_ponto(op_em_teste):
    svc, op_id = op_em_teste
    _ir_para_verificacao(svc, op_id, 12)
    am = T.sortear_amostra(svc, op_id, "Maria", rnd=random.Random(2))
    assert len(am["sorteadas"]) == 10
    T.marcar_amostra(svc, op_id, am["sorteadas"][0], "nc", "Maria", obs="fio trocado")
    for lid in am["sorteadas"][1:]:
        T.marcar_amostra(svc, op_id, lid, "ok", "Maria")
    for i in range(len(am["checklist"])):
        T.marcar_checklist_final(svc, op_id, i, "ok", "Maria")
    op = T.concluir_verificacao(svc, op_id, "Maria")
    assert op["etapa"] == "em_teste" and op["testes"]["verificacao"]["aprovada"] is False
    pp = op["testes"]["ponto_a_ponto"]
    assert all(l["ligacao"] is None and l["aperto"] is None for l in pp["linhas"])
    assert len(pp["anteriores"]) == 1
    assert op["ncs"][-1]["origem"]["bloco"] == "verificacao"


def test_amostragem_incompleta_nao_conclui(op_em_teste):
    svc, op_id = op_em_teste
    _ir_para_verificacao(svc, op_id, 10)
    T.sortear_amostra(svc, op_id, "Maria", rnd=random.Random(3))
    with pytest.raises(OrbitError):
        T.concluir_verificacao(svc, op_id, "Maria")


def test_operador_sem_habilitacao_nao_verifica(op_em_teste):
    svc, op_id = op_em_teste
    with svc.editar_config() as cfg:
        cfg["operadores"] = [{"nome": "Pedro", "verifica": False}, {"nome": "Maria", "verifica": True}]
    _ir_para_verificacao(svc, op_id, 10)
    with pytest.raises(OrbitError):
        T.sortear_amostra(svc, op_id, "pedro")
    assert len(T.sortear_amostra(svc, op_id, "Maria")["sorteadas"]) == 10
