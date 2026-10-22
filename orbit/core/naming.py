"""Regras de nome de arquivos do Orbit."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from orbit.core.errors import OrbitError

_PROIBIDOS = re.compile(r'[\/:*?"<>|]')
_ESPACOS = re.compile(r" {2,}")
_REV_RE = re.compile(r" - Rev(\d{2})(?: - Editavel(?: \d+)?)?\.[^.]+$", re.IGNORECASE)
_FIM_BASE_RE = re.compile(r" - \d{6} - Rev\d{2,}$")

__all__ = [
    "sanitize", "format_data", "format_rev", "build_base_name",
    "build_file_names", "fit_base_name", "parse_rev", "is_editavel",
]


def sanitize(texto: str) -> str:
    texto = _PROIBIDOS.sub("-", texto)
    texto = _ESPACOS.sub(" ", texto)
    return texto.strip(" .")


def format_data(d: date) -> str:
    return d.strftime("%d%m%y")


def format_rev(n: int) -> str:
    return f"Rev{n:02d}"


def build_base_name(tipo: str, partes: list[str], data: date, rev: int) -> str:
    itens = [sanitize(tipo)] + [sanitize(p) for p in partes] + [format_data(data), format_rev(rev)]
    return " - ".join(itens)


def build_file_names(base: str, ext_principal: str, exts_editaveis: list[str]) -> tuple[str, list[str]]:
    principal = base + ext_principal
    contagem: dict[str, int] = {}
    for e in exts_editaveis:
        contagem[e.lower()] = contagem.get(e.lower(), 0) + 1
    colide = {e for e, n in contagem.items() if n > 1 or e == ext_principal.lower()}
    usados: dict[str, int] = {}
    editaveis = []
    for e in exts_editaveis:
        chave = e.lower()
        if chave in colide:
            usados[chave] = usados.get(chave, 0) + 1
            n = usados[chave]
            sufixo = " - Editavel" if n == 1 else f" - Editavel {n}"
            editaveis.append(base + sufixo + e)
        else:
            editaveis.append(base + e)
    return principal, editaveis


def fit_base_name(pasta: Path, base: str, ext_mais_longa: str, limite: int = 240) -> str:
    """Encurta so a parte anterior a ' - DDMMAA - RevNN' para o caminho caber em `limite`."""
    if len(str(pasta / (base + ext_mais_longa))) <= limite:
        return base
    m = _FIM_BASE_RE.search(base)
    if not m:
        raise OrbitError("Nome de arquivo fora do padrão; não foi possível encurtar.")
    prefixo, fim = base[:m.start()], base[m.start():]
    excesso = len(str(pasta / (base + ext_mais_longa))) - limite
    novo = prefixo[:len(prefixo) - excesso].rstrip(" .-")
    if not novo:
        raise OrbitError("O caminho da pasta é longo demais para criar o arquivo.")
    return novo + fim


def parse_rev(nome_arquivo: str) -> int | None:
    m = _REV_RE.search(nome_arquivo)
    return int(m.group(1)) if m else None


def is_editavel(nome_arquivo: str, nome_principal: str) -> bool:
    return nome_arquivo != nome_principal
