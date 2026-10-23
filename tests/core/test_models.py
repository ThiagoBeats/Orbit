import pytest

from orbit.core.errors import OrbitDataError
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.models import (
    Arquivo, Cliente, Container, Contato, Documento, Evento, Revisao,
)


def _container():
    r0 = Revisao(0, "2026-10-01", "Em elaboração", "inicial", "ana", "PC1",
                 [Arquivo("Diagrama - Rev00.pdf", "principal")], arquivada=True)
    r1 = Revisao(1, "2026-10-22", "Aprovado", "ajuste", "ana", "PC1",
                 [Arquivo("Diagrama - Rev01.pdf", "principal"),
                  Arquivo("Diagrama - Rev01.dwg", "editavel")])
    doc = Documento("diagrama_eletrico", "Diagrama Elétrico", revisoes=[r0, r1])
    ev = Evento("revisao_enviada", "2026-10-22T10:00:00", "ana", "PC1", {"numero": 1})
    return Container("c1", "projeto", "P001", "Linha A", "Projetos/P001 - Linha A",
                     cliente_id="cli1", contatos=[Contato("Bo", "bo@x.com")],
                     documentos={"diagrama_eletrico": doc}, historico=[ev])


def test_container_roundtrip():
    c = _container()
    assert Container.from_dict(c.to_dict()) == c
    assert c.documentos["diagrama_eletrico"].atual.numero == 1
    assert c.documentos["diagrama_eletrico"].atual.principal.nome == "Diagrama - Rev01.pdf"


def test_atual_none_sem_revisoes():
    assert Documento("t", "p").atual is None


def test_write_json_atomic_nao_deixa_temporario(tmp_path):
    p = tmp_path / "x.json"
    data = {"nome": "Automação", "n": 1}
    write_json_atomic(p, data)
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]
    assert read_json(p) == data
    assert "Automação" in p.read_text(encoding="utf-8")


def test_read_json_invalido_lanca_orbit_data_error(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{quebrado", encoding="utf-8")
    with pytest.raises(OrbitDataError):
        read_json(p)


def test_read_json_ausente_lanca_orbit_data_error(tmp_path):
    with pytest.raises(OrbitDataError):
        read_json(tmp_path / "nada.json")


def test_from_dict_sem_versao_assume_1():
    d = Cliente("a", "A", "A").to_dict()
    d.pop("versao_formato")
    assert Cliente.from_dict(d).versao_formato == 1
    d = _container().to_dict()
    d.pop("versao_formato")
    assert Container.from_dict(d).versao_formato == 1


def test_defaults_mutaveis_independentes():
    a, b = Cliente("a", "A", "A"), Cliente("b", "B", "B")
    a.contatos.append(Contato("x", "y"))
    assert b.contatos == []
