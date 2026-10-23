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


def _status_bruto(porta, caminho):
    """GET com o caminho exatamente como dado (bytes), sem normalização do cliente."""
    import socket
    with socket.create_connection(("127.0.0.1", porta), timeout=5) as s:
        s.sendall(b"GET " + caminho + b" HTTP/1.0\r\nHost: x\r\n\r\n")
        resposta = b""
        while chunk := s.recv(4096):
            resposta += chunk
    assert resposta, "servidor fechou a conexão sem responder"
    return int(resposta.split(b" ", 2)[1]), resposta


def test_token_nao_ascii_403(servidor):
    fs, _ = servidor
    status, _ = _status_bruto(fs.porta, "/f/é/a.txt".encode("utf-8"))
    assert status == 403
    status, _ = _status_bruto(fs.porta, "/f/é/a.txt".encode("latin-1"))
    assert status == 403
    assert _status(f"http://127.0.0.1:{fs.porta}/f/%C3%A9/a.txt") == 403


def test_bloqueia_barra_invertida(servidor):
    fs, _ = servidor
    for rel in ("..%5C..%5Csegredo.txt", "..%5Csegredo.txt", "Cliente%20A%5C..%5C..%5Csegredo.txt"):
        status, corpo = _status_bruto(fs.porta, f"/f/{fs._token}/{rel}".encode())
        assert status in (403, 404)
        assert b"fora da base" not in corpo


def test_bloqueia_ads_e_unidade(servidor, tmp_path):
    fs, base = servidor
    alvo = "Cliente%20A/Diagrama%20El%C3%A9trico/Diagrama%20El%C3%A9trico%20-%20Rev00.pdf"
    for rel in (alvo + ":stream", alvo + "%3A%3A%24DATA", "C%3A%2FWindows%2Fwin.ini",
                tmp_path.as_posix().replace(":", "%3A") + "/segredo.txt"):
        status, corpo = _status_bruto(fs.porta, f"/f/{fs._token}/{rel}".encode())
        assert status in (403, 404)
        assert b"fora da base" not in corpo


def _criar_link_dir(link, alvo):
    import os
    import subprocess
    try:
        os.symlink(alvo, link, target_is_directory=True)
        return
    except OSError:
        pass
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(alvo)],
                       capture_output=True)
    if r.returncode != 0 or not link.exists():
        pytest.skip("não foi possível criar symlink nem junção neste ambiente")


def test_bloqueia_link_dentro_da_base_para_fora(servidor, tmp_path):
    fs, base = servidor
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "segredo.txt").write_text("fora da base", encoding="utf-8")
    _criar_link_dir(base / "atalho", fora)
    assert (base / "atalho" / "segredo.txt").exists()
    status, corpo = _status_bruto(fs.porta, f"/f/{fs._token}/atalho/segredo.txt".encode())
    assert status in (403, 404)
    assert b"fora da base" not in corpo
    with pytest.raises(OrbitError):
        fs.url_para(base / "atalho" / "segredo.txt")
