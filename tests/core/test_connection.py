import builtins
import time

from orbit.core import connection
from orbit.core.connection import ResultadoConexao, testar_pasta
from orbit.core.identity import Identity

ID = Identity("ana", "PC1")


def test_pasta_ok(tmp_path):
    r = testar_pasta(tmp_path, ID)
    assert r == ResultadoConexao(str(tmp_path), True, True, True, None, r.ms)
    assert isinstance(r.ms, int) and r.ms >= 0
    # o arquivo de teste não fica para trás
    assert list((tmp_path / ".orbit").glob(".teste-conexao-*")) == []


def test_pasta_inexistente(tmp_path):
    r = testar_pasta(tmp_path / "nao-existe", ID)
    assert not r.ok and not r.leitura and not r.escrita
    assert r.erro


def test_sem_escrita(tmp_path, monkeypatch):
    real = builtins.open

    def falso(arq, modo="r", *a, **k):
        if "w" in modo or "a" in modo or "x" in modo:
            raise PermissionError("negado")
        return real(arq, modo, *a, **k)

    monkeypatch.setattr(builtins, "open", falso)
    r = testar_pasta(tmp_path, ID)
    assert r.leitura and not r.escrita and not r.ok
    assert r.erro


def test_tempo_esgotado(tmp_path, monkeypatch):
    monkeypatch.setattr(connection, "_verificar", lambda *a: time.sleep(2))
    t0 = time.perf_counter()
    r = testar_pasta(tmp_path, ID, timeout=0.1)
    assert time.perf_counter() - t0 < 1.5
    assert not r.ok and r.erro == "Tempo esgotado"


def test_usuario_sanitizado(tmp_path):
    r = testar_pasta(tmp_path, Identity("a/b:c", "PC"))
    assert r.ok


def test_arquivo_de_teste_removido_mesmo_se_leitura_falha(tmp_path, monkeypatch):
    real = builtins.open

    def falso(arq, modo="r", *a, **k):
        if "r" in modo and ".teste-conexao" in str(arq):
            raise OSError("falha de leitura")
        return real(arq, modo, *a, **k)

    monkeypatch.setattr(builtins, "open", falso)
    r = testar_pasta(tmp_path, ID)
    assert not r.ok and "falha de leitura" in r.erro
    assert list((tmp_path / ".orbit").glob(".teste-conexao-*")) == []


def test_pasta_existe_timeout(tmp_path, monkeypatch):
    import pytest
    from orbit.core.errors import OrbitError
    monkeypatch.setattr(connection.Path, "is_dir", lambda self: time.sleep(2) or True)
    t0 = time.perf_counter()
    with pytest.raises(OrbitError, match="Tempo esgotado"):
        connection.pasta_existe(tmp_path, 0.1)
    assert time.perf_counter() - t0 < 1.5
