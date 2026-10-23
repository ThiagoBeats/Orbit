"""Anexos sem versionamento: manuais de componentes, NFs, informativos...

Ficam em `<pasta do projeto ou máquina>/Anexos/`, copiados com o nome original,
sem revisão e sem status. Nada é substituído: um nome que já existe ganha
" (2)", " (3)"... O Orbit nunca apaga anexos (quem quiser tira pelo Explorer).
A sincronização do backup trata a pasta como qualquer outra.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from orbit.core.errors import OrbitError
from orbit.core.repository import Repository
from orbit.core.sync.motor import copiar_seguro

PASTA_ANEXOS = "Anexos"


def _pasta(repo: Repository, container_id: str) -> Path:
    c = repo.load_container(container_id)  # OrbitError se não existir
    return repo.container_path(c) / PASTA_ANEXOS


def _nome_livre(pasta: Path, nome: str, reservados: set[str]) -> str:
    base, ext = os.path.splitext(nome)
    candidato, n = nome, 2
    while os.path.lexists(pasta / candidato) or candidato.casefold() in reservados:
        candidato = f"{base} ({n}){ext}"
        n += 1
    return candidato


def adicionar_anexos(repo: Repository, container_id: str, caminhos: list) -> list[str]:
    """Copia os arquivos para a pasta Anexos. Devolve os nomes com que foram salvos."""
    if not caminhos:
        raise OrbitError("Escolha pelo menos um arquivo.")
    origens = []
    for c in caminhos:
        p = Path(c)
        if not p.is_file():
            raise OrbitError(f"Arquivo não encontrado: {p.name or c}")
        origens.append(p)
    pasta = _pasta(repo, container_id)
    try:
        pasta.mkdir(exist_ok=True)
    except OSError as e:
        raise OrbitError(f"Não foi possível criar a pasta Anexos: {e}") from e
    salvos: list[str] = []
    for origem in origens:
        nome = _nome_livre(pasta, origem.name, {s.casefold() for s in salvos})
        copiar_seguro(origem, pasta / nome)  # cópia; nunca sobrescreve
        salvos.append(nome)
    return salvos


def listar_anexos(repo: Repository, container_id: str) -> list[dict]:
    pasta = _pasta(repo, container_id)
    if not pasta.is_dir():
        return []
    out = []
    for f in sorted(pasta.iterdir(), key=lambda x: x.name.casefold()):
        if not f.is_file() or f.name.startswith("~orbit-"):
            continue
        st = f.stat()
        out.append({"nome": f.name, "tamanho": st.st_size,
                    "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")})
    return out


def caminho_anexo(repo: Repository, container_id: str, nome) -> Path:
    """Caminho de um anexo pelo nome — só nomes que existem na pasta (nada vindo do JS)."""
    if not isinstance(nome, str) or not nome:
        raise OrbitError("Anexo inválido.")
    if nome not in {a["nome"] for a in listar_anexos(repo, container_id)}:
        raise OrbitError("Anexo não encontrado.")
    return _pasta(repo, container_id) / nome
