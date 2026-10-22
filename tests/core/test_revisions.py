import shutil
from datetime import date
from pathlib import Path

import pytest

from orbit.core.errors import ArquivoEmUso, OrbitError
from orbit.core.revisions import RevisionService

TIPO = "diagrama_eletrico"
BASE0 = "Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 221026 - Rev00"
BASE1 = "Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 221026 - Rev01"


@pytest.fixture
def ctx(repo, tmp_path):
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora Linha 2")
    origem = tmp_path / "origem"
    origem.mkdir()
    return RevisionService(repo), p, origem


def _arq(pasta: Path, nome: str, conteudo: str) -> Path:
    f = pasta / nome
    f.write_text(conteudo, encoding="utf-8")
    return f


def _snapshot(pasta: Path) -> dict[str, str]:
    return {str(f.relative_to(pasta)): f.read_text(encoding="utf-8")
            for f in sorted(pasta.rglob("*")) if f.is_file()}


def test_primeira_revisao_rev00(ctx, repo):
    svc, p, origem = ctx
    src = _arq(origem, "ABCDE.pdf", "pdf0")
    assert svc.sugerir_numero(p, TIPO) == 0
    pv = svc.preview(p.id, TIPO, src, [])
    assert pv.numero == 0
    assert pv.nome_principal == f"{BASE0}.pdf"
    assert pv.nomes_editaveis == []
    rev = svc.enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "Primeira emissão")
    pasta = repo.doc_path(p, TIPO)
    assert (pasta / "Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 221026 - Rev00.pdf"
            ).read_text(encoding="utf-8") == "pdf0"
    assert rev.numero == 0
    assert rev.data == "2026-10-22"
    assert rev.status == "Em elaboração"
    assert rev.motivo == "Primeira emissão"
    assert (rev.usuario, rev.computador) == ("thiago", "PC1")
    assert rev.principal.nome == f"{BASE0}.pdf"
    c = repo.load_container(p.id)
    doc = c.documentos[TIPO]
    assert doc.atual.numero == 0
    ev = c.historico[-1]
    assert ev.tipo == "revisao_enviada"
    assert ev.dados == {"tipo_id": TIPO, "numero": 0, "motivo": "Primeira emissão"}
    assert svc.sugerir_numero(c, TIPO) == 1
    assert not list(pasta.glob("~orbit-*"))


def test_segunda_revisao_move_anterior_para_antigos(ctx, repo):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "pdf0"), [], "Em elaboração", "")
    rev = svc.enviar_revisao(p.id, TIPO, _arq(origem, "b.pdf", "pdf1"), [], "Aprovado", "Ajustes")
    pasta = repo.doc_path(p, TIPO)
    assert rev.numero == 1
    assert _snapshot(pasta) == {
        f"{BASE1}.pdf": "pdf1",
        str(Path("Antigos") / f"{BASE0}.pdf"): "pdf0",
    }
    doc = repo.load_container(p.id).documentos[TIPO]
    assert [(r.numero, r.arquivada) for r in doc.revisoes] == [(0, True), (1, False)]
    assert doc.atual.numero == 1


def test_editaveis_seguem_revisao_e_vao_juntos_para_antigos(ctx, repo):
    svc, p, origem = ctx
    pv = svc.preview(p.id, TIPO, origem / "x.pdf", [origem / "x.drawio"])
    assert pv.nomes_editaveis == [f"{BASE0}.drawio"]
    rev0 = svc.enviar_revisao(p.id, TIPO, _arq(origem, "x.pdf", "pdf0"),
                              [_arq(origem, "x.drawio", "dio0")], "Em elaboração", "")
    assert [(a.nome, a.papel) for a in rev0.arquivos] == [
        (f"{BASE0}.pdf", "principal"), (f"{BASE0}.drawio", "editavel")]
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "y.pdf", "pdf1"),
                       [_arq(origem, "y.drawio", "dio1")], "Em elaboração", "")
    pasta = repo.doc_path(p, TIPO)
    assert _snapshot(pasta) == {
        f"{BASE1}.pdf": "pdf1",
        f"{BASE1}.drawio": "dio1",
        str(Path("Antigos") / f"{BASE0}.pdf"): "pdf0",
        str(Path("Antigos") / f"{BASE0}.drawio"): "dio0",
    }


def test_principal_xlsx_sem_editavel(ctx, repo):
    svc, p, origem = ctx
    rev = svc.enviar_revisao(p.id, "planilha_cargas", _arq(origem, "cargas.xlsx", "x"), [],
                             "Em elaboração", "")
    nome = "Planilha de Cargas - Cliente X - Envasadora Linha 2 - 221026 - Rev00.xlsx"
    assert [(a.nome, a.papel) for a in rev.arquivos] == [(nome, "principal")]
    assert (repo.doc_path(p, "planilha_cargas") / nome).read_text(encoding="utf-8") == "x"


def test_numero_menor_ou_igual_ao_atual_recusado(ctx, repo, tmp_path):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "0"), [], "Em elaboração", "", numero=1)
    pasta = repo.doc_path(p, TIPO)
    antes = _snapshot(pasta)
    json_antes = (repo.container_path(p) / "projeto.json").read_bytes()
    for n in (0, 1):
        with pytest.raises(OrbitError):
            svc.enviar_revisao(p.id, TIPO, _arq(origem, "b.pdf", "1"), [], "Em elaboração", "",
                               numero=n)
    assert _snapshot(pasta) == antes
    assert (repo.container_path(p) / "projeto.json").read_bytes() == json_antes


def test_pular_numero_maior_permitido(ctx, repo):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "0"), [], "Em elaboração", "")
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "b.pdf", "1"), [], "Em elaboração", "")
    rev = svc.enviar_revisao(p.id, TIPO, _arq(origem, "c.pdf", "3"), [], "Em elaboração", "",
                             numero=3)
    assert rev.numero == 3
    pasta = repo.doc_path(p, TIPO)
    nome3 = "Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 221026 - Rev03.pdf"
    assert (pasta / nome3).read_text(encoding="utf-8") == "3"
    assert (pasta / "Antigos" / f"{BASE1}.pdf").exists()
    assert svc.sugerir_numero(repo.load_container(p.id), TIPO) == 4


def test_origem_nao_e_alterada(ctx):
    svc, p, origem = ctx
    src = _arq(origem, "ABCDE.pdf", "original")
    ed = _arq(origem, "ABCDE.dwg", "editavel")
    svc.enviar_revisao(p.id, TIPO, src, [ed], "Em elaboração", "")
    assert src.read_text(encoding="utf-8") == "original"
    assert ed.read_text(encoding="utf-8") == "editavel"
    assert sorted(f.name for f in origem.iterdir()) == ["ABCDE.dwg", "ABCDE.pdf"]


def test_origem_e_o_arquivo_atual_da_pasta(ctx, repo):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "conteudo0"),
                       [_arq(origem, "a.drawio", "dio0")], "Em elaboração", "")
    pasta = repo.doc_path(p, TIPO)
    atual_pdf = pasta / f"{BASE0}.pdf"
    atual_dio = pasta / f"{BASE0}.drawio"
    rev = svc.enviar_revisao(p.id, TIPO, atual_pdf, [atual_dio], "Aprovado", "Mesma base")
    assert rev.numero == 1
    assert _snapshot(pasta) == {
        f"{BASE1}.pdf": "conteudo0",
        f"{BASE1}.drawio": "dio0",
        str(Path("Antigos") / f"{BASE0}.pdf"): "conteudo0",
        str(Path("Antigos") / f"{BASE0}.drawio"): "dio0",
    }


def test_arquivo_em_uso_desfaz_tudo(ctx, repo, monkeypatch):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "pdf0"),
                       [_arq(origem, "a.drawio", "dio0")], "Em elaboração", "")
    pasta = repo.doc_path(p, TIPO)
    json_path = repo.container_path(p) / "projeto.json"
    antes = _snapshot(pasta)
    json_antes = json_path.read_bytes()

    real_move = shutil.move
    chamadas = []

    def move_falha(src, dst, *a, **k):
        chamadas.append((src, dst))
        if len(chamadas) == 2:
            raise PermissionError(13, "Acesso negado", str(src))
        return real_move(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "move", move_falha)
    with pytest.raises(ArquivoEmUso) as exc:
        svc.enviar_revisao(p.id, TIPO, _arq(origem, "b.pdf", "pdf1"),
                           [_arq(origem, "b.drawio", "dio1")], "Aprovado", "")
    assert len(chamadas) == 2  # falhou no meio do passo (b)
    assert "está aberto em outro programa. Feche-o e tente de novo." in str(exc.value)
    assert _snapshot(pasta) == antes
    assert json_path.read_bytes() == json_antes
    assert not list(pasta.rglob("~orbit-*"))
    assert (origem / "b.pdf").read_text(encoding="utf-8") == "pdf1"


def test_alterar_status_sem_mudar_revisao(ctx, repo):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "0"), [], "Em elaboração", "")
    pasta = repo.doc_path(p, TIPO)
    antes = _snapshot(pasta)
    rev = svc.alterar_status(p.id, TIPO, "Aprovado")
    assert (rev.numero, rev.status) == (0, "Aprovado")
    c = repo.load_container(p.id)
    doc = c.documentos[TIPO]
    assert len(doc.revisoes) == 1
    assert doc.atual.status == "Aprovado"
    assert c.historico[-1].tipo == "status_alterado"
    assert c.historico[-1].dados == {"tipo_id": TIPO, "de": "Em elaboração", "para": "Aprovado"}
    assert _snapshot(pasta) == antes
    with pytest.raises(OrbitError):
        svc.alterar_status(p.id, TIPO, "Inexistente")
    with pytest.raises(OrbitError):
        svc.alterar_status(p.id, "lista_tags", "Aprovado")  # sem revisão


def test_upload_desliga_nao_se_aplica(ctx, repo):
    svc, p, origem = ctx
    svc.definir_nao_se_aplica(p.id, TIPO, True)
    c = repo.load_container(p.id)
    assert c.documentos[TIPO].nao_se_aplica is True
    assert c.historico[-1].tipo == "nao_se_aplica_alterado"
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "0"), [], "Em elaboração", "m")
    c = repo.load_container(p.id)
    assert c.documentos[TIPO].nao_se_aplica is False
    tipos = [e.tipo for e in c.historico]
    assert tipos[-2:] == ["nao_se_aplica_alterado", "revisao_enviada"]
    assert c.historico[-2].dados == {"tipo_id": TIPO, "valor": False}


def test_renomear_cliente_afeta_so_arquivos_novos(ctx, repo):
    svc, p, origem = ctx
    svc.enviar_revisao(p.id, TIPO, _arq(origem, "a.pdf", "0"), [], "Em elaboração", "")
    cli = repo.get_cliente(p.cliente_id)
    cli.nome = "Cliente Y"
    repo.update_cliente(cli)
    rev = svc.enviar_revisao(p.id, TIPO, _arq(origem, "b.pdf", "1"), [], "Em elaboração", "")
    novo = "Diagrama Elétrico - Cliente Y - Envasadora Linha 2 - 221026 - Rev01.pdf"
    assert rev.principal.nome == novo
    pasta = repo.doc_path(p, TIPO)
    assert (pasta / novo).exists()
    assert (pasta / "Antigos" / f"{BASE0}.pdf").exists()
    doc = repo.load_container(p.id).documentos[TIPO]
    assert doc.revisoes[0].principal.nome == f"{BASE0}.pdf"


def test_validacoes(ctx, repo):
    svc, p, origem = ctx
    with pytest.raises(OrbitError):
        svc.enviar_revisao(p.id, TIPO, origem / "nao_existe.pdf", [], "Em elaboração", "")
    src = _arq(origem, "a.pdf", "0")
    with pytest.raises(OrbitError):
        svc.enviar_revisao(p.id, TIPO, src, [], "Status inventado", "")
    # destino já existente (arquivo solto na pasta) é recusado, nada é sobrescrito
    pasta = repo.doc_path(p, TIPO)
    _arq(pasta, f"{BASE0}.pdf", "solto")
    with pytest.raises(OrbitError):
        svc.enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "")
    assert (pasta / f"{BASE0}.pdf").read_text(encoding="utf-8") == "solto"
    _arq(pasta / "Antigos", f"{BASE1}.pdf", "antigo")
    with pytest.raises(OrbitError):
        svc.enviar_revisao(p.id, TIPO, src, [], "Em elaboração", "", numero=1)
    assert repo.load_container(p.id).documentos[TIPO].revisoes == []


def test_data_explicita_e_caminho_longo(ctx, repo):
    svc, p, origem = ctx
    src = _arq(origem, "a.pdf", "0")
    pv = svc.preview(p.id, TIPO, src, [], data=date(2026, 1, 5))
    assert pv.nome_principal == f"{BASE0.replace('221026', '050126')}.pdf"
    longo = repo.create_projeto(p.cliente_id, "002", "P" * 60)
    pv = svc.preview(longo.id, TIPO, src, [origem / "a.pdf", origem / "b.pdf"])
    pasta = repo.doc_path(repo.load_container(longo.id), TIPO)
    nomes = [pv.nome_principal] + pv.nomes_editaveis
    assert nomes[1].endswith(" - 221026 - Rev00 - Editavel.pdf")
    assert nomes[2].endswith(" - 221026 - Rev00 - Editavel 2.pdf")
    assert "P" * 60 not in nomes[0]  # o nome foi encurtado
    assert len({n[:-len(n.split(' - 221026')[-1])] for n in nomes}) == 1  # mesma base
    for nome in nomes:
        assert len(str(pasta / nome)) <= 240
