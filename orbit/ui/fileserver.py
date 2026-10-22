"""Servidor HTTP local que entrega ao visualizador os arquivos da pasta base.

Só responde em 127.0.0.1, exige um token aleatório na URL e recusa (403)
qualquer caminho que saia da pasta base.
"""
import mimetypes
import os
import secrets
import shutil
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from orbit.core.errors import OrbitError

_PREFIXO = "/f/"


class FileServer:
    def __init__(self, base: Path):
        self._base = Path(base).resolve()
        self._token = secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.porta: int | None = None

    def start(self) -> int:
        if self._httpd is not None:
            return self.porta
        servidor = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                servidor._responder(self, corpo=True)

            def do_HEAD(self):
                servidor._responder(self, corpo=False)

            def log_message(self, *args):  # silencioso
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self.porta = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="orbit-fileserver", daemon=True)
        self._thread.start()
        return self.porta

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def url_para(self, caminho: Path) -> str:
        if self.porta is None:
            raise OrbitError("O servidor de arquivos não está ativo.")
        alvo = Path(caminho).resolve()
        if not alvo.is_relative_to(self._base):
            raise OrbitError(f"O arquivo não está dentro da pasta base: {caminho}")
        partes = alvo.relative_to(self._base).parts
        rel = "/".join(urllib.parse.quote(p, safe="") for p in partes)
        return f"http://127.0.0.1:{self.porta}{_PREFIXO}{self._token}/{rel}"

    # --- interno -------------------------------------------------------

    def _resolver(self, caminho_url: str) -> Path | None:
        """Devolve o arquivo pedido, ou None se o pedido não é permitido."""
        caminho_url = caminho_url.split("?", 1)[0].split("#", 1)[0]
        if not caminho_url.startswith(_PREFIXO):
            return None
        token, _, resto = caminho_url[len(_PREFIXO):].partition("/")
        # compara bytes: compare_digest com str não-ASCII lança TypeError
        token_ok = secrets.compare_digest(token.encode("utf-8", "replace"), self._token.encode("ascii"))
        if not token_ok or not resto:
            return None
        rel = urllib.parse.unquote(resto)
        partes = [p for p in rel.replace("\\", "/").split("/") if p]
        if not partes or any(p in ("..", ".") or ":" in p for p in partes):
            return None
        alvo = self._base.joinpath(*partes).resolve()
        if not alvo.is_relative_to(self._base):
            return None
        return alvo

    def _responder(self, req: BaseHTTPRequestHandler, corpo: bool) -> None:
        alvo = self._resolver(req.path)
        if alvo is None:
            req.send_error(HTTPStatus.FORBIDDEN)
            return
        if not alvo.is_file():
            req.send_error(HTTPStatus.NOT_FOUND)
            return
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        try:
            f = open(alvo, "rb")
            tamanho = os.fstat(f.fileno()).st_size
        except OSError:
            req.send_error(HTTPStatus.NOT_FOUND)
            return
        with f:
            req.send_response(HTTPStatus.OK)
            req.send_header("Content-Type", tipo)
            req.send_header("Content-Length", str(tamanho))
            req.send_header("Cache-Control", "no-store")
            req.end_headers()
            if corpo:
                try:
                    shutil.copyfileobj(f, req.wfile)
                except OSError:
                    pass  # o visualizador fechou a conexão ou a rede caiu
