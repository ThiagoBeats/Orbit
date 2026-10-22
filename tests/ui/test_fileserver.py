import urllib.error
import urllib.request

import pytest

from orbit.core.errors import OrbitError
from orbit.ui.fileserver import FileServer


@pytest.fixture
def servidor(tmp_path):
    base = tmp_path / "base"
    (base / "Cliente A" / "Diagrama Elétrico").mkdir(parents=True)
    (base / "Cliente A" / "Diagrama Elétrico" / "Diagrama Elétrico - Rev00.pdf").write_bytes(b"%PDF-1.4 teste")
    (tmp_path / "segredo.txt").write_text("fora da base", encoding="utf-8")
    fs = FileServer(base)
    fs.start()
    yield fs, base
    fs.stop()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _status(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_serve_arquivo_dentro_da_base(servidor):
    fs, base = servidor
    url = fs.url_para(base / "Cliente A" / "Diagrama Elétrico" / "Diagrama Elétrico - Rev00.pdf")
    assert url.startswith(f"http://127.0.0.1:{fs.porta}/f/")
    status, tipo, corpo = _get(url)
    assert status == 200
    assert tipo == "application/pdf"
    assert corpo == b"%PDF-1.4 teste"


def test_bloqueia_fora_da_base(servidor):
    fs, _ = servidor
    url = f"http://127.0.0.1:{fs.porta}/f/{fs._token}/..%2F..%2Fsegredo.txt"
    assert _status(url) == 403
    url = f"http://127.0.0.1:{fs.porta}/f/{fs._token}/..%2Fsegredo.txt"
    assert _status(url) == 403


def test_token_errado_403(servidor):
    fs, base = servidor
    url = fs.url_para(base / "Cliente A" / "Diagrama Elétrico" / "Diagrama Elétrico - Rev00.pdf")
    errado = url.replace(fs._token, "tokenerrado")
    assert _status(errado) == 403


def test_arquivo_inexistente_404(servidor):
    fs, _ = servidor
    assert _status(f"http://127.0.0.1:{fs.porta}/f/{fs._token}/nada.pdf") == 404


def test_url_para_fora_da_base_erro(servidor, tmp_path):
    fs, _ = servidor
    with pytest.raises(OrbitError):
        fs.url_para(tmp_path / "segredo.txt")
