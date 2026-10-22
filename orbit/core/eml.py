"""Rascunho de e-mail em arquivo .eml (RFC 5322), para quando não há Outlook clássico.

O cabeçalho `X-Unsent: 1` faz o Outlook (clássico ou novo) e outros programas de
e-mail abrirem o arquivo como rascunho editável. Os anexos vão embutidos no .eml.
O arquivo fica numa pasta nova em %TEMP%\\Orbit, nunca dentro da pasta base.

Módulo separado de `orbit.core.email` para não confundir com o pacote `email`
da biblioteca padrão, usado aqui.
"""
from __future__ import annotations

import mimetypes
import re
import tempfile
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

from orbit.core.errors import OrbitError

_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def raiz_temporaria() -> Path:
    """Onde ficam as pastas dos rascunhos: %TEMP%\\Orbit."""
    return Path(tempfile.gettempdir()) / "Orbit"


def _nome_arquivo(assunto: str) -> str:
    nome = _PROIBIDOS.sub(" ", assunto)
    nome = re.sub(r"\s+", " ", nome).strip(" .")[:80].rstrip(" .")
    return (nome or "Rascunho") + ".eml"


def montar_mensagem(draft) -> EmailMessage:
    msg = EmailMessage()
    msg["X-Unsent"] = "1"
    if draft.destinatarios:
        msg["To"] = ", ".join(draft.destinatarios)
    msg["Subject"] = draft.assunto
    msg.set_content(draft.corpo)
    for p in draft.anexos:
        tipo, codificacao = mimetypes.guess_type(p.name)
        if tipo is None or codificacao is not None or "/" not in tipo:
            tipo = "application/octet-stream"
        principal, sub = tipo.split("/", 1)
        try:
            dados = p.read_bytes()
        except OSError as e:
            raise OrbitError(f"Não foi possível ler o anexo \"{p.name}\": {e}")
        # bytes sempre: o anexo vai em base64, idêntico ao arquivo original
        msg.add_attachment(dados, maintype=principal, subtype=sub, filename=p.name)
    return msg


def escrever_eml(draft, raiz: Path) -> Path:
    """Grava o rascunho numa pasta nova dentro de `raiz` e devolve o caminho do .eml."""
    msg = montar_mensagem(draft)
    try:
        raiz.mkdir(parents=True, exist_ok=True)
        pasta = Path(tempfile.mkdtemp(prefix=f"Envio {datetime.now():%Y-%m-%d %H%M%S} ",
                                      dir=raiz))
        destino = pasta / _nome_arquivo(draft.assunto)
        with open(destino, "xb") as f:
            f.write(msg.as_bytes(policy=SMTP))
    except OSError as e:
        raise OrbitError(f"Não foi possível criar o rascunho de e-mail em {raiz}: {e}")
    return destino
