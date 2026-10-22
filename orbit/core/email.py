"""Montagem do e-mail de envio de documentos e registro do envio no histórico."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from orbit.core import eml
from orbit.core.errors import OrbitError
from orbit.core.models import Container
from orbit.core.repository import Repository

STATUS_APROVACAO = "Para aprovação"


@dataclass
class EmailDraft:
    destinatarios: list[str]
    assunto: str
    corpo: str
    anexos: list[Path] = field(default_factory=list)


@dataclass
class SelecaoEnvio:
    tipo_id: str
    numero: int
    incluir_editaveis: bool = False


class EmailService:
    def __init__(self, repo: Repository, outlook):
        self.repo = repo
        self.outlook = outlook

    def _revisao(self, c: Container, sel: SelecaoEnvio):
        doc = c.documentos.get(sel.tipo_id)
        if doc is None:
            raise OrbitError(f"Tipo de documento não encontrado: {sel.tipo_id}")
        for r in doc.revisoes:
            if r.numero == sel.numero:
                return r
        nome = self.repo.config.tipo(sel.tipo_id).nome
        raise OrbitError(f"{nome} não tem a revisão Rev{sel.numero:02d}.")

    def montar(self, container_id: str, selecoes: list[SelecaoEnvio]) -> EmailDraft:
        c = self.repo.load_container(container_id)
        anexos: list[Path] = []
        linhas: list[str] = []
        for sel in selecoes:
            rev = self._revisao(c, sel)
            nome_tipo = self.repo.config.tipo(sel.tipo_id).nome
            arqs = [a for a in rev.arquivos
                    if a.papel == "principal" or sel.incluir_editaveis]
            for a in arqs:
                caminho = self.repo.localizar_arquivo(c, sel.tipo_id, rev, a.nome)
                if caminho is None:
                    raise OrbitError(f"Arquivo não encontrado: {a.nome} "
                                     f"({nome_tipo} - Rev{rev.numero:02d})")
                anexos.append(caminho)
            linhas.append(f"- {nome_tipo} - Rev{rev.numero:02d}")
        corpo = ("Prezados,\n\nSeguem os documentos:\n\n" + "\n".join(linhas)
                 + "\n\nAtenciosamente,")
        return EmailDraft([ct.email for ct in c.contatos if ct.email],
                          self.assunto_sugerido(c, selecoes), corpo, anexos)

    def assunto_sugerido(self, c: Container, selecoes: list[SelecaoEnvio]) -> str:
        cli = self.repo.cliente_de(c)
        if cli is None:
            return f"{c.nome} - Documentos"
        base = f"{cli.nome} - {c.nome}"
        if selecoes and all(self._revisao(c, s).status == STATUS_APROVACAO for s in selecoes):
            return f"{base} - Documentos para aprovação"
        return f"{base} - Documentos"

    def preparar(self, container_id: str, draft: EmailDraft,
                 selecoes: list[SelecaoEnvio]) -> str:
        """Abre o rascunho e registra `email_preparado`. Devolve o meio usado.

        "outlook": Outlook clássico via COM. "eml": sem Outlook clássico, um .eml
        (X-Unsent) com os anexos embutidos, numa pasta nova em %TEMP%/Orbit,
        aberto no programa de e-mail padrão. O evento só é gravado depois que a
        abertura deu certo.
        """
        if self.outlook.disponivel():
            self.outlook.abrir_rascunho(draft)
            meio = "outlook"
        else:
            self._abrir_eml(draft)
            meio = "eml"
        with self.repo.editar_container(container_id) as c:
            c.historico.append(self.repo.evento("email_preparado", {
                "destinatarios": list(draft.destinatarios), "assunto": draft.assunto,
                "itens": [{"tipo_id": s.tipo_id, "numero": s.numero} for s in selecoes]}))
            self.repo.save_container(c)
        return meio

    def _abrir_eml(self, draft: EmailDraft) -> None:
        raiz = eml.raiz_temporaria()
        base = Path(os.path.realpath(self.repo.base))
        if Path(os.path.realpath(raiz)).is_relative_to(base):
            raise OrbitError("A pasta temporária do Windows fica dentro da pasta base; "
                             "o rascunho de e-mail não foi criado.")
        arquivo = eml.escrever_eml(draft, raiz)
        try:
            os.startfile(str(arquivo))
        except OSError as e:
            pasta = arquivo.parent
            try:
                os.startfile(str(pasta))
                aberta = "A pasta com o rascunho foi aberta"
            except OSError:
                aberta = "O rascunho está na pasta"
            raise OrbitError(
                f"Outlook clássico não encontrado e o Windows não conseguiu abrir o "
                f"rascunho de e-mail (.eml) ({e}). {aberta}: {pasta}. Abra o arquivo "
                f"\"{arquivo.name}\" no seu programa de e-mail; os anexos já estão nele.")

    def pastas_dos_documentos(self, container_id: str,
                              selecoes: list[SelecaoEnvio]) -> list[Path]:
        """Pastas onde estão os arquivos das revisões selecionadas, sem repetir.

        Revisão arquivada: Antigos (ou onde o arquivo realmente está).
        """
        c = self.repo.load_container(container_id)
        out: list[Path] = []
        for sel in selecoes:
            pasta = self.repo.pasta_da_revisao(c, sel.tipo_id, self._revisao(c, sel))
            if pasta not in out:
                out.append(pasta)
        return out

    def listar_envios(self, filtro_cliente_id: str | None = None) -> list[dict]:
        pares: list[tuple[str | None, str]] = []  # (nome do cliente, id do container)
        for cli in self.repo.list_clientes():
            if filtro_cliente_id is not None and cli.id != filtro_cliente_id:
                continue
            try:
                resumos = self.repo.list_projetos(cli.id)
            except (OrbitError, OSError):
                continue
            pares += [(cli.nome, r.id) for r in resumos if not r.erro]
        if filtro_cliente_id is None:
            pares += [(None, r.id) for r in self.repo.list_maquinas() if not r.erro]
        envios: list[dict] = []
        for cliente_nome, cid in pares:
            try:
                c = self.repo.load_container(cid)
            except (OrbitError, OSError):
                continue
            for ev in c.historico:
                if ev.tipo != "email_preparado":
                    continue
                envios.append({
                    "data_hora": ev.data_hora, "cliente_nome": cliente_nome,
                    "container_id": c.id, "container_nome": c.nome,
                    "destinatarios": ev.dados.get("destinatarios", []),
                    "assunto": ev.dados.get("assunto", ""),
                    "itens": ev.dados.get("itens", [])})
        envios.sort(key=lambda e: e["data_hora"], reverse=True)
        return envios
