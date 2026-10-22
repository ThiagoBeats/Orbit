"""Reconciliação: arquivos colocados à mão nas pastas que o JSON não conhece.

Nunca move, renomeia ou apaga arquivos. Só lê as pastas e atualiza o JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orbit.core.errors import OrbitError
from orbit.core.models import Arquivo, Container, Documento, Revisao
from orbit.core.naming import parse_rev
from orbit.core.repository import Repository

PASTA_ANTIGOS = "Antigos"
MOTIVO_REGISTRO = "Registrado a partir de arquivo encontrado na pasta"


@dataclass
class ArquivoNaoRegistrado:
    tipo_id: str
    caminho: Path
    numero: int
    arquivado: bool


def _listar(pasta: Path) -> list[Path]:
    if not pasta.is_dir():
        return []
    return sorted((f for f in pasta.iterdir() if f.is_file()),
                  key=lambda f: f.name.casefold())


def find_untracked(repo: Repository, c: Container) -> list[ArquivoNaoRegistrado]:
    out: list[ArquivoNaoRegistrado] = []
    for tipo_id, doc in c.documentos.items():
        conhecidos = {a.nome.casefold() for r in doc.revisoes for a in r.arquivos}
        pasta = repo.doc_path(c, tipo_id)
        for arquivado, d in ((False, pasta), (True, pasta / PASTA_ANTIGOS)):
            for f in _listar(d):
                if f.name.startswith("~orbit-") and f.suffix.lower() == ".tmp":
                    continue
                n = parse_rev(f.name)
                if n is None or f.name.casefold() in conhecidos:
                    continue
                out.append(ArquivoNaoRegistrado(tipo_id, f, n, arquivado))
    return out


def _principal(arqs: list[Path]) -> Path:
    ordenados = sorted(arqs, key=lambda f: f.name.casefold())
    return next((f for f in ordenados if f.suffix.lower() == ".pdf"), ordenados[0])


def _novos_arquivos(arqs: list[Path], com_principal: bool) -> list[Arquivo]:
    ordenados = sorted(arqs, key=lambda f: f.name.casefold())
    if not com_principal:
        return [Arquivo(f.name, "editavel") for f in ordenados]
    p = _principal(arqs)
    return [Arquivo(p.name, "principal")] + [
        Arquivo(f.name, "editavel") for f in ordenados if f is not p]


def register_untracked(repo: Repository, container_id: str,
                       itens: list[ArquivoNaoRegistrado], status: str) -> None:
    if status not in repo.config.status:
        raise OrbitError(f"Status inválido: {status}")
    c = repo.load_container(container_id)
    grupos: dict[tuple[str, int], list[ArquivoNaoRegistrado]] = {}
    for i in itens:
        if i.tipo_id not in c.documentos:
            raise OrbitError(f"Tipo de documento não encontrado: {i.tipo_id}")
        grupos.setdefault((i.tipo_id, i.numero), []).append(i)
    registrados = []
    for (tipo_id, numero) in sorted(grupos, key=lambda k: (k[0], k[1])):
        grupo = grupos[(tipo_id, numero)]
        doc: Documento = c.documentos[tipo_id]
        existente = next((r for r in doc.revisoes if r.numero == numero), None)
        arqs = list({i.caminho: i.caminho for i in grupo}.values())
        if existente is not None:
            ja = {a.nome.casefold() for a in existente.arquivos}
            existente.arquivos += _novos_arquivos(
                [f for f in arqs if f.name.casefold() not in ja], com_principal=False)
        else:
            atual = doc.atual
            so_antigos = all(i.arquivado for i in grupo)
            if so_antigos:
                arquivada = True
            elif atual is None or numero > atual.numero:
                arquivada = False
                if atual is not None:
                    atual.arquivada = True  # só no JSON; arquivos ficam onde estão
            else:
                arquivada = True  # só no JSON; não move o arquivo
            p = _principal(arqs)
            data = datetime.fromtimestamp(p.stat().st_mtime).date().isoformat()
            doc.revisoes.append(Revisao(
                numero, data, status, MOTIVO_REGISTRO, repo.identity.usuario,
                repo.identity.computador, _novos_arquivos(arqs, True), arquivada))
        registrados.append({"tipo_id": tipo_id, "numero": numero,
                            "arquivos": [f.name for f in arqs]})
    if not registrados:
        return
    c.historico.append(repo.evento("arquivo_registrado", {"registros": registrados}))
    repo.save_container(c)
