import copy

from orbit.core.models import Arquivo, Container, Documento, Evento, Revisao
from orbit.core.sync.mesclar import (Divergencia, aplicar_escolha, mesclar_cliente,
                                     mesclar_config, mesclar_container)


def _rev(n, status="Em elaboração", arq=None, arquivada=False):
    return Revisao(n, "2026-10-20", status, "m", "u", "PC", [Arquivo(arq or f"D - Rev{n:02d}.pdf",
                                                                    "principal")], arquivada)


def _container():
    c = Container("c1", "projeto", "001", "Envasadora", "001 - Envasadora", cliente_id="k1")
    c.documentos["diagrama_eletrico"] = Documento("diagrama_eletrico", "Diagrama Elétrico",
                                                  revisoes=[_rev(1, arquivada=True), _rev(2)])
    c.documentos["topologia_rede"] = Documento("topologia_rede", "Topologia de Rede",
                                               revisoes=[_rev(0)])
    c.historico = [Evento("revisao_enviada", "2026-10-20T10:00:00", "u", "PC", {"n": 2})]
    return c.to_dict()


def _revs(d, tipo):
    return {r["numero"]: r for r in d["documentos"][tipo]["revisoes"]}


def test_rev_nova_em_casa_e_status_no_servidor_sem_divergencia():
    base = _container()
    local = copy.deepcopy(base)
    local["documentos"]["diagrama_eletrico"]["revisoes"].append(_rev(3).to_dict())
    local["documentos"]["diagrama_eletrico"]["revisoes"][1]["arquivada"] = True
    local["historico"].append(Evento("revisao_enviada", "2026-10-22T20:00:00", "u", "CASA",
                                     {"n": 3}).to_dict())
    backup = copy.deepcopy(base)
    backup["documentos"]["topologia_rede"]["revisoes"][0]["status"] = "Aprovado"
    backup["historico"].append(Evento("status_alterado", "2026-10-22T09:00:00", "u", "EMP",
                                      {}).to_dict())
    junto, divs = mesclar_container(base, local, backup)
    assert divs == []
    diag = _revs(junto, "diagrama_eletrico")
    assert diag[3]["arquivada"] is False and diag[2]["arquivada"] is True
    assert _revs(junto, "topologia_rede")[0]["status"] == "Aprovado"
    assert [e["tipo"] for e in junto["historico"]] == [
        "revisao_enviada", "status_alterado", "revisao_enviada"]


def test_mesmo_campo_mudado_dos_dois_lados_diverge():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    local["documentos"]["topologia_rede"]["revisoes"][0]["status"] = "Aprovado"
    backup["documentos"]["topologia_rede"]["revisoes"][0]["status"] = "Para aprovação"
    junto, divs = mesclar_container(base, local, backup)
    assert len(divs) == 1
    d = divs[0]
    assert d.tipo == "campo" and d.acoes == ["local", "backup"]
    assert d.chave == "documentos.topologia_rede.revisoes.0.status"
    assert d.local["valor"] == "Aprovado" and d.backup["valor"] == "Para aprovação"
    assert d.escopo_id == "c1"
    assert _revs(junto, "topologia_rede")[0]["status"] == "Aprovado"  # fica o local


def test_campo_do_container_mudado_de_um_lado_so():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    backup["pedido"] = "4500"
    junto, divs = mesclar_container(base, local, backup)
    assert divs == [] and junto["pedido"] == "4500"


def test_mesma_rev_arquivos_diferentes_diverge():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    local["documentos"]["diagrama_eletrico"]["revisoes"].append(_rev(3, arq="A.pdf").to_dict())
    backup["documentos"]["diagrama_eletrico"]["revisoes"].append(_rev(3, arq="B.pdf").to_dict())
    junto, divs = mesclar_container(base, local, backup)
    assert [d.tipo for d in divs] == ["revisao"]
    assert divs[0].acoes == ["local", "backup", "ambos"]
    assert divs[0].chave == "documentos.diagrama_eletrico.revisoes.3"
    assert _revs(junto, "diagrama_eletrico")[3]["arquivos"][0]["nome"] == "A.pdf"


def test_sem_base_toda_diferenca_diverge_mas_novos_entram():
    local, backup = _container(), _container()
    backup["pedido"] = "X"
    backup["documentos"]["topologia_rede"]["revisoes"].append(_rev(1).to_dict())
    junto, divs = mesclar_container(None, local, backup)
    assert [d.chave for d in divs] == ["pedido"]
    assert 1 in _revs(junto, "topologia_rede")


def test_historico_uniao_sem_repeticao():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    ev = Evento("x", "2026-10-21T00:00:00", "u", "PC", {"a": 1}).to_dict()
    local["historico"].append(ev)
    backup["historico"].append(copy.deepcopy(ev))
    junto, _ = mesclar_container(base, local, backup)
    assert len(junto["historico"]) == 2


def test_documento_so_de_um_lado_entra():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    backup["documentos"]["lista_tags"] = Documento("lista_tags", "Lista de Tags").to_dict()
    junto, divs = mesclar_container(base, local, backup)
    assert "lista_tags" in junto["documentos"] and divs == []


def test_cliente_tres_vias():
    base = {"id": "k", "nome": "A", "pasta": "A", "cnpj": "", "contatos": []}
    local = dict(base, cnpj="1")
    backup = dict(base, nome="A Ltda")
    junto, divs = mesclar_cliente(base, local, backup)
    assert divs == [] and junto["cnpj"] == "1" and junto["nome"] == "A Ltda"


def test_config_tipos_uniao():
    base = {"tipos": [{"id": "a", "nome": "A", "pasta": "A", "ativo": True}],
            "status": ["S1"], "logo_empresa": None}
    local = copy.deepcopy(base)
    local["tipos"].append({"id": "b", "nome": "B", "pasta": "B", "ativo": True})
    backup = copy.deepcopy(base)
    backup["tipos"][0]["ativo"] = False
    backup["status"].append("S2")
    junto, divs = mesclar_config(base, local, backup)
    assert divs == []
    assert [(t["id"], t["ativo"]) for t in junto["tipos"]] == [("a", False), ("b", True)]
    assert junto["status"] == ["S1", "S2"]


def test_aplicar_escolha_campo():
    base = _container()
    local, backup = copy.deepcopy(base), copy.deepcopy(base)
    local["documentos"]["topologia_rede"]["revisoes"][0]["status"] = "Aprovado"
    backup["documentos"]["topologia_rede"]["revisoes"][0]["status"] = "Para aprovação"
    local["nome"], backup["nome"] = "L", "B"
    junto, divs = mesclar_container(base, local, backup)
    for d in divs:
        junto = aplicar_escolha(junto, d, "backup", backup)
    assert _revs(junto, "topologia_rede")[0]["status"] == "Para aprovação"
    assert junto["nome"] == "B"


def test_divergencia_ida_e_volta():
    d = Divergencia("i", "campo", "c1", "x/projeto.json", "nome", "Nome diferente",
                    {"valor": "a"}, {"valor": "b"}, ["local", "backup"])
    assert Divergencia.from_dict(d.to_dict()) == d
