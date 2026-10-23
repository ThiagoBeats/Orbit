from datetime import date, datetime, timedelta

import pytest

from orbit.core.actionlog import ActionLog
from orbit.core.config import load_shared_config
from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json
from orbit.core.meudia import MeuDiaService, mesclar_por_id
from orbit.core.repository import Repository

EU = Identity("thiago", "PC1")
COLEGA = Identity("ana", "PC2")


class Relogio:
    def __init__(self, t=datetime(2026, 10, 23, 9, 0, 0)):
        self.t = t

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


@pytest.fixture
def amb(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    relogio = Relogio()
    log = ActionLog(base, EU, tmp_path / "anc.json", agora=relogio)
    repo = Repository(base, EU, load_shared_config(base), agora=relogio)
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    svc = MeuDiaService(repo, EU, agora=relogio, log=log)
    return svc, repo, p, log, relogio, base


def _colega(amb):
    svc, repo, p, log, relogio, base = amb
    r2 = Repository(base, COLEGA, load_shared_config(base), agora=relogio)
    return MeuDiaService(r2, COLEGA, agora=relogio)


def test_atividade_com_projeto_fica_no_arquivo_pessoal(amb):
    svc, repo, p, *_ = amb
    it = svc.adicionar("Revisar intertravamento", "atividade", p.id)
    assert it.container_id == p.id and it.usuario == "thiago"
    assert [i.id for i in svc.itens_pessoais()] == [it.id]
    assert svc.anotacoes(p.id) == []
    assert svc.caminho_pessoal.parent.name == "thiago"


def test_pesquisar_com_projeto_vai_para_anotacoes_do_projeto(amb):
    svc, repo, p, *_ = amb
    it = svc.adicionar("STO no CFW500?", "pesquisar", p.id)
    assert [i.id for i in svc.anotacoes(p.id)] == [it.id]
    assert svc.itens_pessoais() == []
    arq = repo.container_path(repo.load_container(p.id)) / "anotacoes.json"
    assert read_json(arq)["notas"][0]["texto"] == "STO no CFW500?"


def test_item_sem_projeto_e_pessoal(amb):
    svc, *_ = amb
    it = svc.adicionar("Ideia geral", "insight")
    assert [i.id for i in svc.itens_pessoais()] == [it.id]


def test_mudar_projeto_move_o_item(amb):
    svc, repo, p, *_ = amb
    it = svc.adicionar("Nota", "pesquisar")
    movido = svc.editar(it.id, container_id=p.id)
    assert movido.id == it.id and movido.container_id == p.id
    assert svc.itens_pessoais() == []
    assert [i.id for i in svc.anotacoes(p.id)] == [it.id]
    bruto = read_json(svc.caminho_pessoal)["itens"]
    assert bruto[0]["id"] == it.id and bruto[0]["excluido"] is True


def test_ok_so_nos_tipos_que_tem_ok(amb):
    svc, repo, p, *_ = amb
    a = svc.adicionar("Fazer", "atividade")
    assert svc.marcar_feito(a.id, True).feito_em is not None
    assert svc.marcar_feito(a.id, False).feito_em is None
    i = svc.adicionar("Insight", "insight", p.id)
    with pytest.raises(OrbitError):
        svc.marcar_feito(i.id, True)


def test_excluir_esconde_sem_apagar(amb):
    svc, *_ = amb
    a = svc.adicionar("Fazer", "atividade")
    svc.excluir(a.id)
    assert svc.itens_pessoais() == []
    assert read_json(svc.caminho_pessoal)["itens"][0]["excluido"] is True


def test_validacoes(amb):
    svc, *_ = amb
    with pytest.raises(OrbitError):
        svc.adicionar("   ", "atividade")
    with pytest.raises(OrbitError):
        svc.adicionar("x", "kanban")
    with pytest.raises(OrbitError):
        svc.adicionar("x", "pesquisar", "nao-existe")


def test_mesclar_por_id_vence_o_mais_recente():
    a = [{"id": "1", "texto": "casa", "alterado_em": "2026-10-23T20:00:00", "criado_em": "1"},
         {"id": "2", "texto": "só local", "alterado_em": "2026-10-23T08:00:00", "criado_em": "2"}]
    b = [{"id": "1", "texto": "empresa", "alterado_em": "2026-10-23T09:00:00", "criado_em": "1"},
         {"id": "3", "texto": "só backup", "alterado_em": "2026-10-23T08:00:00", "criado_em": "3"}]
    junto = mesclar_por_id(a, b)
    assert [(d["id"], d["texto"]) for d in junto] == [("1", "casa"), ("2", "só local"),
                                                      ("3", "só backup")]
    empate = mesclar_por_id([{"id": "1", "texto": "L", "alterado_em": "x"}],
                            [{"id": "1", "texto": "B", "alterado_em": "x"}])
    assert empate[0]["texto"] == "L"


def test_json_corrompido_nao_e_regravado(amb):
    svc, *_ = amb
    svc.caminho_pessoal.parent.mkdir(parents=True, exist_ok=True)
    svc.caminho_pessoal.write_text("{quebrado", encoding="utf-8")
    with pytest.raises(OrbitDataError):
        svc.adicionar("x", "atividade")
    with pytest.raises(OrbitDataError):
        svc.itens_pessoais()
    assert svc.caminho_pessoal.read_text(encoding="utf-8") == "{quebrado"


def test_log_so_para_anotacao_de_projeto(amb):
    svc, repo, p, log, *_ = amb
    antes = len(log.ler())
    a = svc.adicionar("Pessoal", "atividade", p.id)
    svc.marcar_feito(a.id, True)
    n = svc.adicionar("Pesquisar X", "pesquisar", p.id)
    svc.marcar_feito(n.id, True)
    svc.excluir(n.id)
    acoes = [l.acao for l in log.ler()][antes:]
    assert acoes == ["anotacao_criada", "anotacao_concluida", "anotacao_excluida"]


def test_anotacao_de_colega_e_visivel_e_atividade_nao(amb):
    svc, repo, p, *_ = amb
    outro = _colega(amb)
    outro.adicionar("Atividade da Ana", "atividade", p.id)
    outro.adicionar("Definir IHM", "definicao", p.id)
    assert [i.texto for i in svc.anotacoes(p.id)] == ["Definir IHM"]
    assert svc.itens_pessoais() == []


# ---------- Tarefa 2: consultas do dashboard ----------

def _ids(itens):
    return [i.texto for i in itens]


def test_lista_inclui_atividades_do_dia_e_pendencias(amb):
    svc, repo, p, log, relogio, base = amb
    hoje = relogio.t.date()
    svc.adicionar("Atividade de hoje", "atividade")
    svc.adicionar("Atividade de amanhã", "atividade", dia=hoje + timedelta(days=1))
    svc.adicionar("Pesquisar X", "pesquisar", p.id)
    svc.adicionar("Um insight", "insight", p.id)
    assert _ids(svc.lista_do_dia(hoje)) == ["Atividade de hoje", "Pesquisar X"]
    assert _ids(svc.lista_do_dia(hoje + timedelta(days=1))) == ["Atividade de amanhã",
                                                                "Pesquisar X"]
    assert svc.abertas_hoje() == 2


def test_atividade_nao_feita_passa_para_hoje(amb):
    svc, repo, p, log, relogio, base = amb
    relogio.t = datetime(2026, 10, 23, 23, 59, 0)
    svc.adicionar("Terminar memorial", "atividade")
    relogio.t = datetime(2026, 10, 24, 0, 1, 0)
    lista = svc.lista_do_dia(date(2026, 10, 24))
    assert _ids(lista) == ["Terminar memorial"]
    assert _ids(svc.lista_do_dia(date(2026, 10, 23))) == ["Terminar memorial"]


def test_feito_aparece_riscado_no_dia_do_ok(amb):
    svc, repo, p, log, relogio, base = amb
    relogio.t = datetime(2026, 10, 22, 10, 0, 0)
    a = svc.adicionar("Antiga", "atividade")
    b = svc.adicionar("Outra", "atividade")
    relogio.t = datetime(2026, 10, 23, 10, 0, 0)
    svc.marcar_feito(a.id, True)
    hoje = svc.lista_do_dia(date(2026, 10, 23))
    assert _ids(hoje) == ["Outra", "Antiga"]  # não feitos primeiro
    assert hoje[1].feito_em is not None
    assert svc.abertas_hoje() == 1


def test_pendencias_de_colegas_nao_entram(amb):
    svc, repo, p, log, relogio, base = amb
    _colega(amb).adicionar("Pesquisa da Ana", "pesquisar", p.id)
    assert svc.lista_do_dia(relogio.t.date()) == []


def test_onde_parei_usa_o_meu_e_o_banner_usa_qualquer_um(amb):
    svc, repo, p, log, relogio, base = amb
    svc.adicionar("Parei no M3", "onde_parei", p.id)
    _colega(amb).adicionar("Ana parou no painel", "onde_parei", p.id)
    meu = svc.onde_parei()
    assert [(x["container_id"], x["item"].texto) for x in meu] == [(p.id, "Parei no M3")]
    assert meu[0]["container_nome"] == "Envasadora" and meu[0]["cliente_nome"] == "Cliente X"
    assert svc.ultimo_onde_parei(p.id).texto == "Ana parou no painel"


def test_ideias_de_todos_os_projetos(amb):
    svc, repo, p, log, relogio, base = amb
    m = repo.create_maquina("EC", "Esteira")
    svc.adicionar("Bloco de alarmes", "insight", p.id)
    _colega(amb).adicionar("Régua por cor", "insight", m.id)
    ideias = svc.ideias()
    assert [(x["item"].texto, x["container_nome"]) for x in ideias] == [
        ("Régua por cor", "Esteira"), ("Bloco de alarmes", "Envasadora")]


def test_docs_pendentes_conta_so_ativos_e_aplicaveis(amb, tmp_path):
    svc, repo, p, log, relogio, base = amb
    from orbit.core.revisions import RevisionService
    total_tipos = len(repo.load_container(p.id).documentos)
    assert svc.docs_pendentes() == total_tipos
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    rs = RevisionService(repo)
    rs.enviar_revisao(p.id, "diagrama_eletrico", pdf, [], "Em elaboração", "")
    rs.definir_nao_se_aplica(p.id, "consumo_pneumatico", True)
    assert svc.docs_pendentes() == total_tipos - 2
    cli = repo.create_cliente("Outro")
    p2 = repo.create_projeto(cli.id, "9", "Concluído")
    repo.update_dados(p2.id, situacao="concluido")
    assert svc.docs_pendentes() == total_tipos - 2


# ---------- revisão final ----------

def test_ok_e_edicao_depois_de_mudar_de_arquivo(amb):
    svc, repo, p, *_ = amb
    a = svc.adicionar("Era atividade", "atividade", p.id)
    svc.editar(a.id, tipo="pesquisar")          # atividade pessoal → anotação do projeto
    svc.marcar_feito(a.id, True)
    assert svc.anotacoes(p.id)[0].feito_em is not None
    b = svc.adicionar("Nota solta", "pesquisar")
    svc.editar(b.id, container_id=p.id)
    svc.editar(b.id, texto="novo")
    assert [n.texto for n in svc.anotacoes(p.id) if n.id == b.id] == ["novo"]
    svc.excluir(b.id)
    assert [n.id for n in svc.anotacoes(p.id)] == [a.id]


def test_nao_move_anotacao_de_colega_para_o_meu_arquivo(amb):
    svc, repo, p, *_ = amb
    nota = _colega(amb).adicionar("Da Ana", "pesquisar", p.id)
    with pytest.raises(OrbitError):
        svc.editar(nota.id, tipo="definicao", container_id=None)
    assert [n.texto for n in svc.anotacoes(p.id)] == ["Da Ana"]
    svc.editar(nota.id, tipo="definicao")       # mudar o tipo no mesmo projeto pode
    assert svc.anotacoes(p.id)[0].tipo == "definicao"


def test_lembrete_semanal_comeca_no_primeiro_dia_escolhido(amb):
    svc, *_ = amb
    l = svc.salvar_lembrete({"texto": "x", "quando": "2026-10-22T10:00",   # quinta
                             "recorrencia": {"tipo": "semanal", "dias": [2, 4]}})
    assert l.quando == "2026-10-23T10:00"                                   # sexta
    u = svc.salvar_lembrete({"texto": "y", "quando": "2026-10-24T08:00",   # sábado
                             "recorrencia": {"tipo": "dias_uteis"}})
    assert u.quando == "2026-10-26T08:00"


def test_editar_mensal_do_dia_31_mantem_o_dia(amb):
    from datetime import datetime as D
    from orbit.core.lembretes import marcar_disparado
    svc, *_ = amb
    l = svc.salvar_lembrete({"texto": "x", "quando": "2026-01-31T10:00",
                             "recorrencia": {"tipo": "mensal"}})
    svc.aplicar(l.id, lambda x: marcar_disparado(x, D(2026, 1, 31, 10, 0, 5)))
    atual = svc.lembretes()[0]
    assert atual.quando == "2026-02-28T10:00"
    svc.salvar_lembrete({"id": l.id, "texto": "só o texto", "quando": atual.quando,
                         "recorrencia": {"tipo": "mensal"}})
    svc.aplicar(l.id, lambda x: marcar_disparado(x, D(2026, 2, 28, 10, 0, 5)))
    assert svc.lembretes()[0].quando == "2026-03-31T10:00"


def test_item_malformado_nao_derruba_a_juncao():
    junto = mesclar_por_id([{"id": "1", "alterado_em": "a"}, "lixo", {"sem_id": 1}],
                           [{"id": "2", "alterado_em": "b"}, None])
    assert sorted(d["id"] for d in junto) == ["1", "2"]
