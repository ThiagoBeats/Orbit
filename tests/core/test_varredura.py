import hashlib
import os

from orbit.core.sync import varredura
from orbit.core.sync.varredura import InfoArquivo, Retrato, excluido, id_par, varrer


def test_exclusoes():
    assert excluido(".orbit/travas/x.lock")
    assert excluido(".orbit/presenca/a.json")
    assert excluido("Clientes/C/P/~orbit-1.tmp")
    assert excluido("Clientes/C/_Divergências/x.pdf")
    assert excluido("_DIVERGÊNCIAS/2026/x.pdf")
    assert excluido(".ORBIT/TRAVAS/y.lock")
    assert excluido("Clientes/C/P/.orbit/travas/_container.lock")
    assert not excluido(".orbit/config.json")
    assert not excluido(".orbit/log/acoes.log")
    assert not excluido("Clientes/C/P/Diagrama/x.pdf")


def test_varrer_lista_arquivos_com_hash(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.pdf").write_bytes(b"abc")
    (tmp_path / ".orbit" / "travas").mkdir(parents=True)
    (tmp_path / ".orbit" / "travas" / "t.lock").write_text("{}")
    r = varrer(tmp_path)
    assert list(r) == ["a/x.pdf"]
    assert r["a/x.pdf"].tamanho == 3
    assert r["a/x.pdf"].hash == hashlib.sha256(b"abc").hexdigest()


def test_cache_evita_rehash(tmp_path, monkeypatch):
    (tmp_path / "x.pdf").write_bytes(b"abc" * 1000)
    primeira = varrer(tmp_path)
    chamadas = []
    original = hashlib.sha256

    def contando(*a, **k):
        chamadas.append(1)
        return original(*a, **k)
    monkeypatch.setattr(varredura.hashlib, "sha256", contando)
    segunda = varrer(tmp_path, cache=primeira)
    assert chamadas == [] and segunda == primeira
    (tmp_path / "x.pdf").write_bytes(b"outro")
    varrer(tmp_path, cache=primeira)
    assert chamadas  # mudou: recalcula


def test_varrer_cancelado(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.pdf").write_bytes(b"x")
    import pytest
    from orbit.core.errors import OrbitError
    with pytest.raises(OrbitError):
        varrer(tmp_path, cancelar=lambda: True)


def test_retrato_ida_e_volta(tmp_path):
    ret = Retrato(tmp_path / "sync" / "par")
    assert not ret.existe() and ret.ultima_sync() is None
    arqs = {"a/x.pdf": InfoArquivo(3, 123, "h")}
    jsons = {"Clientes/C/cliente.json": {"id": "1", "nome": "C"},
             ".orbit/log/acoes.log": [{"seq": "PC1-1"}]}
    ret.salvar(arqs, jsons, "2026-10-23T09:00:00")
    ret2 = Retrato(tmp_path / "sync" / "par")
    assert ret2.existe() and ret2.arquivos() == arqs
    assert ret2.json_base("Clientes/C/cliente.json") == {"id": "1", "nome": "C"}
    assert ret2.json_base(".orbit/log/acoes.log") == [{"seq": "PC1-1"}]
    assert ret2.json_base("nao/existe.json") is None
    assert ret2.ultima_sync() == "2026-10-23T09:00:00"
    ret2.salvar_divergencias([{"id": "d1"}])
    assert Retrato(tmp_path / "sync" / "par").divergencias_pendentes() == [{"id": "d1"}]


def test_id_par_estavel_e_insensivel_a_caixa(tmp_path):
    a, b = tmp_path / "Base", tmp_path / "Backup"
    assert id_par(a, b) == id_par(tmp_path / "base", tmp_path / "BACKUP")
    assert len(id_par(a, b)) == 16
    assert id_par(a, b) != id_par(b, a)


def test_temporarios_do_office_e_do_windows_nao_sao_sincronizados():
    assert excluido("Clientes/C/P/Memorial/~$Memorial.docx")
    assert excluido("Clientes/C/P/Thumbs.db")
    assert excluido("Clientes/C/desktop.ini")
    assert excluido("Clientes/C/P/x.TMP")
    assert excluido("Clientes/C/P/.~lock.Planilha.xlsx#")
    assert not excluido("Clientes/C/P/Memorial/Memorial - Rev00.docx")
