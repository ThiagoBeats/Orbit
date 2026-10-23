import hashlib
from pathlib import Path

import pytest

from orbit.core.config import load_shared_config
from orbit.core.errors import OrbitError
from orbit.core.jsonstore import read_json
from orbit.core.repository import Repository
from orbit.core.revisions import RevisionService
from orbit.core.sync.resolver import resolver
from tests.core.test_motor import PC1, PC2, Ambiente, _projeto


@pytest.fixture
def amb(tmp_path):
    return Ambiente(tmp_path)


def _container(raiz, cid):
    return Repository(raiz, PC1, load_shared_config(raiz)).load_container(cid)


def _hashes(raiz: Path) -> set[str]:
    return {hashlib.sha256(p.read_bytes()).hexdigest() for p in raiz.rglob("*.pdf")}


def _status_divergente(amb):
    r, cli, p = _projeto(amb)
    amb.subir(r, p.id)
    amb.engine().sincronizar()
    RevisionService(r).alterar_status(p.id, "diagrama_eletrico", "Aprovado")
    RevisionService(amb.repo("backup", PC2)).alterar_status(p.id, "diagrama_eletrico",
                                                            "Para aprovação")
    res = amb.engine().sincronizar()
    return p, res


def _rev_divergente(amb):
    r, cli, p = _projeto(amb)
    amb.engine().sincronizar()
    amb.subir(r, p.id)                         # Rev00 em casa
    amb.subir(amb.repo("backup", PC2), p.id)   # outra Rev00 no servidor
    res = amb.engine().sincronizar()
    return p, res


def test_resolver_campo_backup(amb):
    p, res = _status_divergente(amb)
    [d] = res.divergencias
    eng = amb.engine()
    resolver(eng, d.id, "backup")
    for lado in (amb.base, amb.backup):
        assert _container(lado, p.id).documentos["diagrama_eletrico"].atual.status == \
            "Para aprovação"
    assert eng.retrato.divergencias_pendentes() == []
    assert "divergencia_resolvida" in [l.acao for l in eng.log.ler()]
    assert amb.engine().comparar().identico


def test_escolha_invalida(amb):
    p, res = _status_divergente(amb)
    with pytest.raises(OrbitError):
        resolver(amb.engine(), res.divergencias[0].id, "ambos")
    with pytest.raises(OrbitError):
        resolver(amb.engine(), "nao-existe", "local")


def test_resolver_revisao_local_guarda_a_do_backup_em_divergencias(amb):
    p, res = _rev_divergente(amb)
    [d] = [x for x in res.divergencias if x.tipo == "revisao"]
    hash_backup = _hashes(amb.backup)
    resolver(amb.engine(), d.id, "local")
    docs_b = {h for h in (hashlib.sha256(f.read_bytes()).hexdigest()
                          for f in amb.backup.rglob("*.pdf") if "_Divergências" not in str(f))}
    assert docs_b == _hashes(amb.base)
    guardados = {hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in (amb.backup / "_Divergências").rglob("*.pdf")}
    assert hash_backup <= guardados
    assert amb.engine().comparar().identico


def test_resolver_ambos_vira_proxima_revisao(amb):
    p, res = _rev_divergente(amb)
    [d] = [x for x in res.divergencias if x.tipo == "revisao"]
    h_local, h_backup = _hashes(amb.base), _hashes(amb.backup)
    resolver(amb.engine(), d.id, "ambos")
    for lado in (amb.base, amb.backup):
        doc = _container(lado, p.id).documentos["diagrama_eletrico"]
        assert [r.numero for r in doc.revisoes] == [0, 1]
        assert doc.atual.numero == 1 and doc.atual.motivo == "Divergência de sincronização"
        nomes = {f.name for f in lado.rglob("*.pdf") if "_Divergências" not in str(f)}
        assert any(n.endswith("Rev01.pdf") for n in nomes)
        assert any(f.parent.name == "Antigos" and f.name.endswith("Rev00.pdf")
                   for f in lado.rglob("*.pdf") if "_Divergências" not in str(f))
    vivos = lambda lado: {hashlib.sha256(f.read_bytes()).hexdigest()
                          for f in lado.rglob("*.pdf") if "_Divergências" not in str(f)}
    assert vivos(amb.base) == vivos(amb.backup) == h_local | h_backup
    assert amb.engine().comparar().identico


def test_resolver_arquivo_backup(amb):
    _projeto(amb)
    solto = amb.base / "Clientes" / "Cliente X" / "notas.txt"
    solto.write_text("v1", encoding="utf-8")
    amb.engine().sincronizar()
    solto.write_text("casa", encoding="utf-8")
    (amb.backup / "Clientes" / "Cliente X" / "notas.txt").write_text("servidor", encoding="utf-8")
    [d] = amb.engine().sincronizar().divergencias
    resolver(amb.engine(), d.id, "backup")
    assert solto.read_text(encoding="utf-8") == "servidor"
    [g] = list((amb.base / "_Divergências").rglob("notas.txt"))
    assert g.read_text(encoding="utf-8") == "casa"


def test_resolver_pasta_id_ambos(amb):
    _, _, p_l = _projeto(amb)
    _, _, p_b = _projeto(amb, "backup", PC2)
    res = amb.engine().sincronizar()
    eng = amb.engine()
    for d in [x for x in res.divergencias if x.tipo == "pasta_id"]:
        resolver(eng, d.id, "ambos")
    res2 = amb.engine().sincronizar()
    assert res2.divergencias == []
    for lado in (amb.base, amb.backup):
        ids = {read_json(f)["id"] for f in lado.rglob("projeto.json")}
        assert ids == {p_l.id, p_b.id}


def test_resolver_pasta_id_juntar(amb):
    r, _, p_l = _projeto(amb)
    rb, _, p_b = _projeto(amb, "backup", PC2)
    amb.subir(rb, p_b.id, "topologia_rede")
    res = amb.engine().sincronizar()
    eng = amb.engine()
    for d in [x for x in res.divergencias if x.tipo == "pasta_id"]:
        resolver(eng, d.id, "juntar")
    res2 = amb.engine().sincronizar()
    assert res2.divergencias == []
    for lado in (amb.base, amb.backup):
        ids = {read_json(f)["id"] for f in lado.rglob("projeto.json")
               if "_Divergências" not in str(f)}
        assert ids == {p_l.id}
        doc = _container(lado, p_l.id).documentos["topologia_rede"]
        assert doc.atual is not None
    assert list((amb.backup / "_Divergências").rglob("projeto.json"))


def test_nada_apagado_apos_resolver(amb):
    p, res = _rev_divergente(amb)
    antes = {lado: _hashes(lado) for lado in (amb.base, amb.backup)}
    resolver(amb.engine(), [x for x in res.divergencias if x.tipo == "revisao"][0].id, "backup")
    for lado in (amb.base, amb.backup):
        assert antes[lado] <= _hashes(lado)


def test_resolver_revisao_pode_ser_repetida_apos_falha(amb, monkeypatch):
    from orbit.core.sync import resolver as mod
    p, res = _rev_divergente(amb)
    [d] = [x for x in res.divergencias if x.tipo == "revisao"]
    original = mod.copiar_seguro
    falhas = []

    def falha_uma_vez(origem, destino):
        if not falhas:
            falhas.append(1)
            raise PermissionError(13, "arquivo em uso")
        return original(origem, destino)
    monkeypatch.setattr(mod, "copiar_seguro", falha_uma_vez)
    with pytest.raises(OSError):
        resolver(amb.engine(), d.id, "local")
    resolver(amb.engine(), d.id, "local")  # tenta de novo
    assert amb.engine().comparar().identico


def test_juntar_cliente_pode_ser_repetido_apos_falha(amb, monkeypatch):
    from orbit.core.sync import resolver as mod
    _, cli_l, p_l = _projeto(amb)
    rb, cli_b, p_b = _projeto(amb, "backup", PC2, nome="Outro")
    res = amb.engine().sincronizar()
    [d] = [x for x in res.divergencias if x.tipo == "pasta_id" and x.chave == "cliente"]
    original = mod.write_json_atomic
    falhas = []

    def falha_no_projeto(caminho, dados):
        if str(caminho).endswith("projeto.json") and not falhas:
            falhas.append(1)
            raise OSError("rede caiu")
        return original(caminho, dados)
    monkeypatch.setattr(mod, "write_json_atomic", falha_no_projeto)
    with pytest.raises(OSError):
        resolver(amb.engine(), d.id, "juntar")
    resolver(amb.engine(), d.id, "juntar")
    j = read_json(amb.backup / "Clientes/Cliente X/001 - Outro/projeto.json")
    assert j["cliente_id"] == cli_l.id
