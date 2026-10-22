"""Importação de documentos antigos para um container já cadastrado (spec §10).

Os arquivos de origem são só **copiados**: nunca são alterados, movidos ou
apagados. Tudo acontece numa única `_Transacao` (a mesma do upload): se algo
falhar, as cópias são desfeitas, a revisão atual volta da `Antigos` e o JSON
não é gravado.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from orbit.core.errors import OrbitError
from orbit.core.models import Arquivo, Container, Revisao
from orbit.core.repository import ARQ_MAQUINA, ARQ_PROJETO, Repository
from orbit.core.revisions import PASTA_ANTIGOS, _nomes_finais, _reerguer_falha, _Transacao

if TYPE_CHECKING:
    from orbit.core.presence import PresenceService

PAPEIS = ("principal", "editavel")


@dataclass
class ItemImportacao:
    origem: Path
    tipo_id: str
    numero: int
    status: str
    papel: str = "principal"
    motivo: str = ""
    data: date | None = None  # None = data de modificação da origem


@dataclass
class _Grupo:
    """Uma revisão importada: um principal e os editáveis associados a ele."""
    tipo_id: str
    numero: int
    indices: list[int]           # posição de cada item em `itens`
    principal: ItemImportacao
    editaveis: list[ItemImportacao]
    data: date
    nome_p: str
    nomes_e: list[str]


class ImportService:
    def __init__(self, repo: Repository, presence: PresenceService | None = None):
        self.repo = repo
        self.presence = presence  # None: sem trava de upload (uso local/testes antigos)

    # ---------- validação ----------
    def validar(self, container_id: str, itens: list[ItemImportacao]) -> list[str | None]:
        c = self.repo.load_container(container_id)
        return self._validar(c, itens)[0]

    @staticmethod
    def _data(item: ItemImportacao) -> date:
        if item.data is not None:
            return item.data
        return date.fromtimestamp(Path(item.origem).stat().st_mtime)

    def _validar(self, c: Container, itens: list[ItemImportacao]
                 ) -> tuple[list[str | None], list[_Grupo]]:
        erros: list[str | None] = [None] * len(itens)

        def marcar(i: int, msg: str) -> None:
            if erros[i] is None:
                erros[i] = msg

        tipos_validos = {t.id for t in self.repo.config.tipos}
        indices_por_grupo: dict[tuple[str, int], list[int]] = {}
        for i, it in enumerate(itens):
            rev = f"Rev{it.numero:02d}" if isinstance(it.numero, int) and it.numero >= 0 else ""
            if it.tipo_id not in tipos_validos or it.tipo_id not in c.documentos:
                marcar(i, f"Tipo de documento não encontrado: {it.tipo_id}")
            if not isinstance(it.numero, int) or it.numero < 0:
                marcar(i, "O número da revisão não pode ser negativo.")
            if it.status not in self.repo.config.status:
                marcar(i, f"Status inválido: {it.status}")
            if it.papel not in PAPEIS:
                marcar(i, f"Papel inválido: {it.papel}")
            if not Path(it.origem).is_file():
                marcar(i, f"Arquivo de origem não encontrado: {it.origem}")
            doc = c.documentos.get(it.tipo_id)
            if doc is not None and rev and any(r.numero == it.numero for r in doc.revisoes):
                nome_tipo = self.repo.config.tipo(it.tipo_id).nome
                marcar(i, f"A {rev} de \"{nome_tipo}\" já existe neste container. "
                          "Escolha outro número.")
            indices_por_grupo.setdefault((it.tipo_id, it.numero), []).append(i)

        for (tipo_id, numero), idx in indices_por_grupo.items():
            principais = [i for i in idx if itens[i].papel == "principal"]
            if len(principais) != 1:
                msg = ("A revisão não tem arquivo principal. Marque um arquivo como principal."
                       if not principais else
                       "A revisão tem mais de um arquivo principal. Marque só um.")
                for i in idx:
                    marcar(i, msg)

        # nomes finais e conflitos no disco, só para os grupos sem erro
        grupos: list[_Grupo] = []
        for (tipo_id, numero), idx in indices_por_grupo.items():
            if any(erros[i] is not None for i in idx):
                continue
            principal = next(itens[i] for i in idx if itens[i].papel == "principal")
            editaveis = [itens[i] for i in idx if itens[i].papel == "editavel"]
            try:
                data = self._data(principal)
                nome_p, nomes_e = _nomes_finais(
                    self.repo, c, tipo_id, Path(principal.origem),
                    [Path(e.origem) for e in editaveis], numero, data)
            except (OrbitError, OSError) as e:
                for i in idx:
                    marcar(i, str(e))
                continue
            pasta = self.repo.doc_path(c, tipo_id)
            existentes = [nm for nm in [nome_p] + nomes_e
                          if os.path.lexists(pasta / nm)
                          or os.path.lexists(pasta / PASTA_ANTIGOS / nm)]
            if existentes:
                for i in idx:
                    marcar(i, "Já existe arquivo com o mesmo nome na pasta do documento ou em "
                              f"Antigos: {', '.join(existentes)}. Escolha outro número.")
                continue
            grupos.append(_Grupo(tipo_id, numero, idx, principal, editaveis, data,
                                 nome_p, nomes_e))
        return erros, grupos

    # ---------- importação ----------
    def importar(self, container_id: str, itens: list[ItemImportacao]) -> None:
        if not itens:
            raise OrbitError("Nenhum arquivo para importar.")
        if self.presence is None:
            return self._importar(container_id, itens)
        c = self.repo.load_container(container_id)
        # uma trava por tipo envolvido (em ordem; se uma falhar, as outras são soltas).
        # Tipos inexistentes não ganham trava: a validação recusa a importação.
        travas = self.presence.travar_varios(
            self.repo.container_path(c),
            [it.tipo_id for it in itens if it.tipo_id in c.documentos])
        try:
            return self._importar(container_id, itens)  # recarrega já com as travas
        finally:
            self.presence.liberar_varios(travas)

    def _importar(self, container_id: str, itens: list[ItemImportacao]) -> None:
        c = self.repo.load_container(container_id)
        erros, grupos = self._validar(c, itens)
        linhas = [f"linha {i + 1}: {e}" for i, e in enumerate(erros) if e is not None]
        if linhas:
            raise OrbitError("A importação não foi feita. Corrija: " + "; ".join(linhas))

        # 1. planejamento: destino de cada grupo e revisão atual a arquivar
        destino: dict[int, bool] = {}  # id(grupo) -> vai para Antigos?
        a_arquivar: list[tuple[str, Revisao]] = []
        por_tipo: dict[str, list[_Grupo]] = {}
        for g in grupos:
            por_tipo.setdefault(g.tipo_id, []).append(g)
        mover: list[tuple[Path, Path]] = []
        for tipo_id, gs in por_tipo.items():
            atual = c.documentos[tipo_id].atual
            maior = max(gs, key=lambda g: g.numero)
            nova_atual = maior if atual is None or maior.numero > atual.numero else None
            for g in gs:
                destino[id(g)] = g is not nova_atual
            if nova_atual is not None and atual is not None:
                a_arquivar.append((tipo_id, atual))
                pasta = self.repo.doc_path(c, tipo_id)
                for a in atual.arquivos:
                    if os.path.lexists(pasta / PASTA_ANTIGOS / a.nome):
                        raise OrbitError(f"Já existe \"{a.nome}\" em Antigos. "
                                         "Nada foi alterado.")
                    if os.path.lexists(pasta / a.nome):  # arquivo sumido: nada a mover
                        mover.append((pasta / a.nome, pasta / PASTA_ANTIGOS / a.nome))

        for tipo_id in por_tipo:
            antigos = self.repo.doc_path(c, tipo_id) / PASTA_ANTIGOS
            try:
                antigos.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OrbitError(f"Não foi possível criar a pasta \"{antigos}\": {e}")

        # 2. "não se aplica" é desligado (gravado junto, no passo d)
        for tipo_id in por_tipo:
            doc = c.documentos[tipo_id]
            if doc.nao_se_aplica:
                doc.nao_se_aplica = False
                c.historico.append(self.repo.evento("nao_se_aplica_alterado",
                                                    {"tipo_id": tipo_id, "valor": False}))

        # 3. transação
        tx = _Transacao()
        try:
            # (a) cópias para temporários, já na pasta final de cada revisão
            renomes: list[tuple[Path, Path]] = []
            for g in grupos:
                pasta = self.repo.doc_path(c, g.tipo_id)
                if destino[id(g)]:
                    pasta = pasta / PASTA_ANTIGOS
                for it, nm in zip([g.principal] + g.editaveis, [g.nome_p] + g.nomes_e):
                    renomes.append((tx.copiar(Path(it.origem), pasta), pasta / nm))
            # (b) revisão atual anterior -> Antigos
            for origem, dest in mover:
                tx.mover(origem, dest)
            # (c) temporários -> nomes finais
            for tmp, final in renomes:
                tx.renomear(tmp, final)
            # (d) JSON
            tx.arquivo_atual = ARQ_PROJETO if c.tipo == "projeto" else ARQ_MAQUINA
            for _, atual in a_arquivar:
                atual.arquivada = True
            for g in grupos:
                p = g.principal
                c.documentos[g.tipo_id].revisoes.append(Revisao(
                    g.numero, g.data.isoformat(), p.status, p.motivo,
                    self.repo.identity.usuario, self.repo.identity.computador,
                    [Arquivo(g.nome_p, "principal")]
                    + [Arquivo(nm, "editavel") for nm in g.nomes_e],
                    arquivada=destino[id(g)]))
            for tipo_id in por_tipo:
                c.documentos[tipo_id].revisoes.sort(key=lambda r: r.numero)
            c.historico.append(self.repo.evento("importacao", {"revisoes": [
                {"tipo_id": g.tipo_id, "numero": g.numero} for g in grupos]}))
            self.repo.save_container(c)
        except BaseException as e:
            _reerguer_falha(e, tx, "importar os arquivos")
