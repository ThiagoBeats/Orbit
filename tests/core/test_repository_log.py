from datetime import datetime

import pytest

from orbit.core.actionlog import ActionLog
from orbit.core.config import load_shared_config
from orbit.core.identity import Identity
from orbit.core.repository import Repository
from orbit.core.revisions import RevisionService


@pytest.fixture
def ambiente(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    ident = Identity("thiago", "PC1")
    log = ActionLog(base, ident, tmp_path / "ancoras.json")
    avisos = []
    repo = Repository(base, ident, load_shared_config(base),
                      agora=lambda: datetime(2026, 10, 23, 9, 0), log=log,
                      ao_alterar=lambda escopo, id: avisos.append((escopo, id)))
    return repo, log, avisos, tmp_path


def _projeto(repo):
    cli = repo.create_cliente("Cliente X")
    return cli, repo.create_projeto(cli.id, "001", "Envasadora")


def test_upload_gera_linha_no_log(ambiente):
    repo, log, _, tmp = ambiente
    _, p = _projeto(repo)
    pdf = tmp / "ABCDE.pdf"
    pdf.write_bytes(b"%PDF")
    RevisionService(repo).enviar_revisao(p.id, "diagrama_eletrico", pdf, [], "Em elaboração", "")
    linhas = [l for l in log.ler() if l.acao == "revisao_enviada"]
    assert len(linhas) == 1
    assert linhas[0].detalhes["container_id"] == p.id
    assert linhas[0].detalhes["container_nome"] == "Envasadora"
    assert linhas[0].detalhes["cliente_nome"] == "Cliente X"


def test_criacoes_geram_linhas(ambiente):
    repo, log, _, _ = ambiente
    cli, p = _projeto(repo)
    repo.create_maquina("EC", "Esteira")
    cli.nome = "Cliente Y"
    repo.update_cliente(cli)
    acoes = [l.acao for l in log.ler()]
    assert acoes == ["cliente_criado", "projeto_criado", "maquina_criada", "cliente_alterado"]


def test_eventos_ja_gravados_nao_se_repetem(ambiente):
    repo, log, _, _ = ambiente
    _, p = _projeto(repo)
    repo.update_dados(p.id, pedido="1")
    repo.update_dados(p.id, pedido="2")
    assert [l.acao for l in log.ler()].count("dados_alterados") == 2


def test_ao_alterar_chamado_apos_gravar(ambiente):
    repo, _, avisos, _ = ambiente
    cli, p = _projeto(repo)
    avisos.clear()
    repo.update_dados(p.id, pedido="1")
    assert avisos == [("container", p.id)]
    repo.update_cliente(cli)
    assert avisos[-1] == ("cliente", cli.id)


def test_falha_no_log_nao_desfaz_operacao(ambiente, monkeypatch):
    repo, log, _, _ = ambiente
    _, p = _projeto(repo)
    erros = []
    repo.registrar = erros.append

    def quebra(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(log, "registrar_acao", quebra)
    repo.update_dados(p.id, pedido="99")
    assert repo.load_container(p.id).pedido == "99"
    assert erros and "disco cheio" in str(erros[0])


def test_falha_no_aviso_nao_desfaz_operacao(ambiente):
    repo, _, _, _ = ambiente
    _, p = _projeto(repo)

    def quebra(e, i):
        raise RuntimeError("backup fora")
    repo.ao_alterar = quebra
    repo.registrar = lambda e: None
    repo.update_dados(p.id, pedido="5")
    assert repo.load_container(p.id).pedido == "5"
