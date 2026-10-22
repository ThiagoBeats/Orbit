"""Upload de revisão, mudança de status e "não se aplica".

Regra de ouro: nenhum arquivo do usuário é apagado ou sobrescrito. A única
exclusão permitida é a de um temporário que o próprio Orbit copiou dentro de
uma transação que falhou (ver `_Transacao`).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

from orbit.core.errors import ArquivoEmUso, OrbitError
from orbit.core.models import Arquivo, Container, Documento, Revisao
from orbit.core.naming import build_base_name, build_file_names, fit_base_name
from orbit.core.repository import ARQ_MAQUINA, ARQ_PROJETO, Repository

PASTA_ANTIGOS = "Antigos"
LIMITE_CAMINHO = 240


@dataclass
class UploadPreview:
    numero: int
    nome_principal: str
    nomes_editaveis: list[str]


class _Transacao:
    """Registra cópias e movimentações e sabe desfazê-las em ordem inversa.

    - `copiar` só aceita destinos `~orbit-<uuid>.tmp` criados aqui; desfazer uma
      cópia é a única exclusão que o Orbit faz.
    - `mover`/`renomear` nunca sobrescrevem: o destino é conferido antes, e no
      Windows `os.rename` também falha se o destino existir.
    """

    def __init__(self) -> None:
        self._ops: list[tuple[str, Path, Path | None]] = []
        self.arquivo_atual: str | None = None  # nome do arquivo da operação em curso

    @staticmethod
    def nome_temporario(pasta: Path) -> Path:
        return pasta / f"~orbit-{uuid4().hex}.tmp"

    @staticmethod
    def _exigir_livre(destino: Path) -> None:
        if os.path.lexists(destino):
            raise OrbitError(f"Já existe um arquivo chamado \"{destino.name}\" em "
                             f"{destino.parent.name}. Nada foi sobrescrito.")

    def copiar(self, origem: Path, pasta: Path) -> Path:
        self.arquivo_atual = origem.name
        tmp = self.nome_temporario(pasta)
        self._exigir_livre(tmp)
        self._ops.append(("copia", tmp, None))  # registrado antes: cópia parcial também é desfeita
        shutil.copy2(origem, tmp)
        return tmp

    def mover(self, origem: Path, destino: Path) -> None:
        self.arquivo_atual = origem.name
        self._exigir_livre(destino)
        shutil.move(str(origem), str(destino))
        self._ops.append(("movido", origem, destino))

    def renomear(self, origem: Path, destino: Path) -> None:
        self.arquivo_atual = origem.name
        self._exigir_livre(destino)
        os.rename(origem, destino)
        self._ops.append(("movido", origem, destino))

    def desfazer(self) -> list[str]:
        """Desfaz tudo em ordem inversa. Devolve as falhas (vazio = estado restaurado)."""
        falhas: list[str] = []
        for tipo, a, b in reversed(self._ops):
            try:
                if tipo == "movido":
                    if os.path.lexists(a):
                        raise OSError(f"\"{a.name}\" já existe de novo na origem")
                    os.rename(b, a)
                elif os.path.lexists(a):  # cópia temporária feita por esta transação
                    os.unlink(a)
            except OSError as e:
                alvo = b if tipo == "movido" else a
                falhas.append(f"{alvo}: {e}")
        self._ops.clear()
        return falhas


class RevisionService:
    def __init__(self, repo: Repository):
        self.repo = repo

    # ---------- auxiliares ----------
    @staticmethod
    def _documento(c: Container, tipo_id: str) -> Documento:
        doc = c.documentos.get(tipo_id)
        if doc is None:
            raise OrbitError(f"Tipo de documento não encontrado: {tipo_id}")
        return doc

    def sugerir_numero(self, c: Container, tipo_id: str) -> int:
        atual = self._documento(c, tipo_id).atual
        return atual.numero + 1 if atual else 0

    def _nomes(self, c: Container, tipo_id: str, principal: Path, editaveis: list[Path],
               numero: int, data: date) -> tuple[str, list[str]]:
        tipo = self.repo.config.tipo(tipo_id)
        base = build_base_name(tipo.nome, self.repo.name_parts(c), data, numero)
        ext_p = Path(principal).suffix
        exts_e = [Path(e).suffix for e in editaveis]
        nome_p, nomes_e = build_file_names(base, ext_p, exts_e)
        sufixo_longo = max((n[len(base):] for n in [nome_p] + nomes_e), key=len)
        base = fit_base_name(self.repo.doc_path(c, tipo_id), base, sufixo_longo, LIMITE_CAMINHO)
        return build_file_names(base, ext_p, exts_e)

    def _numero(self, c: Container, tipo_id: str, numero: int | None) -> int:
        return self.sugerir_numero(c, tipo_id) if numero is None else numero

    # ---------- API ----------
    def preview(self, container_id: str, tipo_id: str, principal: Path, editaveis: list[Path],
                numero: int | None = None, data: date | None = None) -> UploadPreview:
        c = self.repo.load_container(container_id)
        n = self._numero(c, tipo_id, numero)
        nome_p, nomes_e = self._nomes(c, tipo_id, principal, list(editaveis), n,
                                      data or self.repo.agora().date())
        return UploadPreview(n, nome_p, nomes_e)

    def enviar_revisao(self, container_id: str, tipo_id: str, principal: Path,
                       editaveis: list[Path], status: str, motivo: str,
                       numero: int | None = None, data: date | None = None) -> Revisao:
        c = self.repo.load_container(container_id)
        doc = self._documento(c, tipo_id)
        atual = doc.atual
        principal = Path(principal)
        editaveis = [Path(e) for e in editaveis]
        data = data or self.repo.agora().date()
        n = self._numero(c, tipo_id, numero)

        # 1. validações (nada é tocado antes delas)
        if n < 0 or (atual is not None and n <= atual.numero):
            raise OrbitError(f"A nova revisão precisa ser maior que a atual "
                             f"(Rev{atual.numero:02d})." if atual else
                             "O número da revisão não pode ser negativo.")
        if not principal.is_file():
            raise OrbitError(f"Arquivo principal não encontrado: {principal}")
        for e in editaveis:
            if not e.is_file():
                raise OrbitError(f"Arquivo editável não encontrado: {e}")
        if status not in self.repo.config.status:
            raise OrbitError(f"Status inválido: {status}")

        pasta = self.repo.doc_path(c, tipo_id)
        antigos = pasta / PASTA_ANTIGOS
        nome_p, nomes_e = self._nomes(c, tipo_id, principal, editaveis, n, data)
        novos = [nome_p] + nomes_e
        a_arquivar = [a.nome for a in atual.arquivos] if atual else []
        conflitos = [nm for nm in novos
                     if os.path.lexists(pasta / nm) or os.path.lexists(antigos / nm)]
        conflitos += [nm for nm in a_arquivar if os.path.lexists(antigos / nm)]
        if conflitos:
            raise OrbitError("Já existe arquivo com o mesmo nome na pasta do documento ou em "
                             f"Antigos: {', '.join(conflitos)}. Nada foi alterado.")
        # arquivos da revisão atual que sumiram da pasta não têm o que mover
        a_mover = [nm for nm in a_arquivar if os.path.lexists(pasta / nm)]

        try:
            antigos.mkdir(parents=True, exist_ok=True)  # tipo criado depois do container
        except OSError as e:
            raise OrbitError(f"Não foi possível criar a pasta \"{doc.pasta}\": {e}")

        # 2. "não se aplica" é desligado (gravado junto com a revisão, no passo d)
        if doc.nao_se_aplica:
            doc.nao_se_aplica = False
            c.historico.append(self.repo.evento("nao_se_aplica_alterado",
                                                {"tipo_id": tipo_id, "valor": False}))

        nova = Revisao(n, data.isoformat(), status, motivo, self.repo.identity.usuario,
                       self.repo.identity.computador,
                       [Arquivo(nome_p, "principal")] + [Arquivo(x, "editavel") for x in nomes_e])

        # 3. transação
        tx = _Transacao()
        try:
            # (a) cópias para temporários (antes de mover: a origem pode ser o arquivo atual)
            temps = [tx.copiar(src, pasta) for src in [principal] + editaveis]
            # (b) revisão atual -> Antigos
            for nm in a_mover:
                tx.mover(pasta / nm, antigos / nm)
            # (c) temporários -> nomes finais
            for tmp, nm in zip(temps, novos):
                tx.renomear(tmp, pasta / nm)
            # (d) JSON
            tx.arquivo_atual = ARQ_PROJETO if c.tipo == "projeto" else ARQ_MAQUINA
            if atual is not None:
                atual.arquivada = True
            doc.revisoes.append(nova)
            c.historico.append(self.repo.evento("revisao_enviada",
                                                {"tipo_id": tipo_id, "numero": n,
                                                 "motivo": motivo}))
            self.repo.save_container(c)
        except BaseException as e:
            falhas = tx.desfazer()
            aviso = ""
            if falhas:
                aviso = (" ATENÇÃO: não foi possível desfazer tudo; confira manualmente: "
                         + "; ".join(falhas))
            if isinstance(e, PermissionError):
                raise ArquivoEmUso(f"O arquivo {tx.arquivo_atual} está aberto em outro programa. "
                                   f"Feche-o e tente de novo.{aviso}") from e
            if isinstance(e, OrbitError):
                if aviso:
                    raise OrbitError(f"{e}{aviso}") from e
                raise
            if isinstance(e, OSError):
                raise OrbitError(f"Não foi possível enviar a revisão ({tx.arquivo_atual}): "
                                 f"{e}. As alterações foram desfeitas.{aviso}") from e
            raise
        return nova

    def alterar_status(self, container_id: str, tipo_id: str, status: str) -> Revisao:
        if status not in self.repo.config.status:
            raise OrbitError(f"Status inválido: {status}")
        c = self.repo.load_container(container_id)
        atual = self._documento(c, tipo_id).atual
        if atual is None:
            raise OrbitError("Este documento ainda não tem revisão enviada.")
        if atual.status != status:
            de = atual.status
            atual.status = status
            c.historico.append(self.repo.evento("status_alterado",
                                                {"tipo_id": tipo_id, "de": de, "para": status}))
            self.repo.save_container(c)
        return atual

    def definir_nao_se_aplica(self, container_id: str, tipo_id: str, valor: bool) -> None:
        c = self.repo.load_container(container_id)
        doc = self._documento(c, tipo_id)
        if doc.nao_se_aplica == bool(valor):
            return
        doc.nao_se_aplica = bool(valor)
        c.historico.append(self.repo.evento("nao_se_aplica_alterado",
                                            {"tipo_id": tipo_id, "valor": bool(valor)}))
        self.repo.save_container(c)
