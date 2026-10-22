"""Repositório: clientes, projetos, máquinas padrão e suas pastas."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from orbit.core.config import SharedConfig
from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.models import Cliente, Contato, Container, Documento, Evento
from orbit.core.naming import sanitize

PASTA_CLIENTES = "Clientes"
PASTA_MAQUINAS = "Máquinas Padrão"
ARQ_CLIENTE = "cliente.json"
ARQ_PROJETO = "projeto.json"
ARQ_MAQUINA = "maquina.json"

LIMITE_PASTA = 60

CAMPOS_EDITAVEIS = ("codigo", "nome", "pedido", "responsavel", "descricao", "situacao", "contatos")


@dataclass
class ContainerResumo:
    id: str
    nome: str
    codigo: str
    situacao: str
    emitidos: int
    aplicaveis: int
    ultima_emissao: str | None
    erro: str | None


def _arquivo_de(tipo: str) -> str:
    return ARQ_PROJETO if tipo == "projeto" else ARQ_MAQUINA


class Repository:
    def __init__(self, base: Path, identity: Identity, config: SharedConfig,
                 agora: Callable[[], datetime] = datetime.now):
        self.base = Path(base)
        self.identity = identity
        self.config = config
        self.agora = agora
        self._idx_containers: dict[str, Path] = {}  # id -> caminho do JSON
        self._idx_clientes: dict[str, Path] = {}

    # ---------- utilitários ----------
    def evento(self, tipo: str, dados: dict) -> Evento:
        return Evento(tipo, self.agora().strftime("%Y-%m-%dT%H:%M:%S"),
                      self.identity.usuario, self.identity.computador, dict(dados))

    @staticmethod
    def _nome_pasta(texto: str, rotulo: str) -> str:
        nome = sanitize(texto)
        if not nome:
            raise OrbitError(f"Informe {rotulo}.")
        return Repository._limitar(nome, rotulo)

    @staticmethod
    def _limitar(nome: str, rotulo: str) -> str:
        nome = nome[:LIMITE_PASTA].rstrip(" .-")
        if not nome:
            raise OrbitError(f"Informe {rotulo} válido.")
        return nome

    @staticmethod
    def _criar_pasta(pasta: Path, descricao: str) -> None:
        pasta.parent.mkdir(parents=True, exist_ok=True)
        try:
            pasta.mkdir()
        except FileExistsError:
            raise OrbitError(f"Já existe uma pasta para {descricao} com este nome ({pasta.name}). "
                             "Escolha outro nome.")
        except OSError as e:
            raise OrbitError(f"Não foi possível criar a pasta de {descricao} ({pasta.name}): {e}")

    @staticmethod
    def _desfazer_pastas(raiz: Path, subpastas: list[Path]) -> None:
        """Remove as pastas VAZIAS que o Orbit acabou de criar (falha na criação).

        Só usa os.rmdir, que nunca apaga pasta com conteúdo: se algo apareceu
        lá dentro, a pasta fica (e as que a contêm também).
        """
        for pasta in [*subpastas, raiz]:
            try:
                os.rmdir(pasta)
            except OSError:
                pass

    @staticmethod
    def _raw_id(path: Path) -> str | None:
        try:
            dados = read_json(path)
        except OrbitDataError:
            return None
        i = dados.get("id") if isinstance(dados, dict) else None
        return i if isinstance(i, str) else None

    # ---------- índices id -> caminho ----------
    def _scan_clientes(self) -> None:
        self._idx_clientes = {}
        raiz = self.base / PASTA_CLIENTES
        if raiz.is_dir():
            for f in raiz.glob(f"*/{ARQ_CLIENTE}"):
                i = self._raw_id(f)
                if i:
                    self._idx_clientes[i] = f

    def _scan_containers(self) -> None:
        self._idx_containers = {}
        arquivos: list[Path] = []
        raiz = self.base / PASTA_CLIENTES
        if raiz.is_dir():
            arquivos += raiz.glob(f"*/*/{ARQ_PROJETO}")
        maq = self.base / PASTA_MAQUINAS
        if maq.is_dir():
            arquivos += maq.glob(f"*/{ARQ_MAQUINA}")
        for f in arquivos:
            i = self._raw_id(f)
            if i:
                self._idx_containers[i] = f

    def _find(self, idx_name: str, scan: Callable[[], None], id: str, rotulo: str) -> Path:
        caminho = getattr(self, idx_name).get(id)
        if caminho is None or not caminho.exists():
            scan()
            caminho = getattr(self, idx_name).get(id)
        if caminho is None:
            raise OrbitError(f"{rotulo} não encontrado (pode ter sido removido "
                             "ou o arquivo de dados está ilegível).")
        return caminho

    # ---------- clientes ----------
    def create_cliente(self, nome: str, cnpj: str = "",
                       contatos: list[Contato] | None = None) -> Cliente:
        pasta = self._nome_pasta(nome, "o nome do cliente")
        cliente = Cliente(uuid4().hex, nome.strip(), pasta, cnpj, list(contatos or []))
        raiz = self.base / PASTA_CLIENTES / pasta
        self._criar_pasta(raiz, "o cliente")
        try:
            write_json_atomic(raiz / ARQ_CLIENTE, cliente.to_dict())
        except BaseException:
            self._desfazer_pastas(raiz, [])  # sem o JSON, a pasta vazia impediria nova tentativa
            raise
        self._idx_clientes[cliente.id] = raiz / ARQ_CLIENTE
        return cliente

    @staticmethod
    def _load_cliente(path: Path) -> Cliente:
        data = read_json(path)
        try:
            return Cliente.from_dict(data)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise OrbitDataError(f"Dados do cliente inválidos ({path.parent.name}): "
                                 f"campo ausente ou incorreto: {e}")

    def list_clientes(self) -> list[Cliente]:
        raiz = self.base / PASTA_CLIENTES
        out = []
        if raiz.is_dir():
            for f in sorted(raiz.glob(f"*/{ARQ_CLIENTE}")):
                try:
                    c = self._load_cliente(f)
                except OrbitDataError:
                    continue
                self._idx_clientes[c.id] = f
                out.append(c)
        return sorted(out, key=lambda c: c.nome.casefold())

    def get_cliente(self, cliente_id: str) -> Cliente:
        return self._load_cliente(
            self._find("_idx_clientes", self._scan_clientes, cliente_id, "Cliente"))

    def update_cliente(self, cliente: Cliente) -> None:
        caminho = self._find("_idx_clientes", self._scan_clientes, cliente.id, "Cliente")
        if not sanitize(cliente.nome):
            raise OrbitError("Informe o nome do cliente.")
        write_json_atomic(caminho, cliente.to_dict())  # a pasta não é renomeada

    # ---------- containers ----------
    def _novo_container(self, raiz: Path, c: Container) -> Container:
        self._criar_pasta(raiz, "o projeto" if c.tipo == "projeto" else "a máquina")
        criadas: list[Path] = []  # em ordem de remoção (de dentro para fora)
        try:
            for t in self.config.tipos_ativos():
                c.documentos[t.id] = Documento(t.id, t.pasta)
                try:
                    for pasta in (raiz / t.pasta, raiz / t.pasta / "Antigos"):
                        if not pasta.is_dir():
                            pasta.mkdir()
                            criadas.insert(0, pasta)
                except OSError as e:
                    raise OrbitError(f"Não foi possível criar a pasta \"{t.pasta}\" em "
                                     f"{raiz.name} (caminho longo demais?): {e}")
            caminho = raiz / _arquivo_de(c.tipo)
            write_json_atomic(caminho, c.to_dict())
        except BaseException:
            # sem o JSON, a pasta vazia impediria uma nova tentativa com o mesmo nome
            self._desfazer_pastas(raiz, criadas)
            raise
        self._idx_containers[c.id] = caminho
        return c

    def _pasta_cliente(self, cliente: Cliente) -> Path:
        return self.base / PASTA_CLIENTES / cliente.pasta

    def create_projeto(self, cliente_id: str, codigo: str, nome: str, pedido: str = "",
                       responsavel: str = "", contatos: list[Contato] | None = None,
                       situacao: str = "ativo") -> Container:
        cliente = self.get_cliente(cliente_id)
        cod = self._nome_pasta(codigo, "o código do projeto")
        nm = self._nome_pasta(nome, "o nome do projeto")
        pasta = self._limitar(f"{cod} - {nm}", "o nome do projeto")
        c = Container(uuid4().hex, "projeto", codigo.strip(), nome.strip(), pasta,
                      cliente_id=cliente.id, pedido=pedido, responsavel=responsavel,
                      contatos=list(contatos or []), situacao=situacao)
        return self._novo_container(self._pasta_cliente(cliente) / pasta, c)

    def create_maquina(self, codigo: str, nome: str, descricao: str = "") -> Container:
        pasta = self._nome_pasta(nome, "o nome da máquina")
        c = Container(uuid4().hex, "maquina", codigo.strip(), nome.strip(), pasta,
                      descricao=descricao)
        return self._novo_container(self.base / PASTA_MAQUINAS / pasta, c)

    def _load_path(self, path: Path) -> Container:
        data = read_json(path)
        try:
            c = Container.from_dict(data)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise OrbitDataError(f"Dados inválidos ({path.parent.name}): "
                                 f"campo ausente ou incorreto: {e}")
        for t in self.config.tipos_ativos():
            if t.id not in c.documentos:
                c.documentos[t.id] = Documento(t.id, t.pasta)  # pasta criada no primeiro upload
        return c

    def load_container(self, container_id: str) -> Container:
        return self._load_path(self._find("_idx_containers", self._scan_containers,
                                          container_id, "Projeto ou máquina"))

    def save_container(self, c: Container) -> None:
        caminho = self._find("_idx_containers", self._scan_containers, c.id,
                             "Projeto ou máquina")
        write_json_atomic(caminho, c.to_dict())

    def container_path(self, c: Container) -> Path:
        if c.tipo == "projeto":
            if not c.cliente_id:
                raise OrbitDataError(f"Projeto {c.nome} sem cliente.")
            return self._pasta_cliente(self.get_cliente(c.cliente_id)) / c.pasta
        return self.base / PASTA_MAQUINAS / c.pasta

    def doc_path(self, c: Container, tipo_id: str) -> Path:
        doc = c.documentos.get(tipo_id)
        if doc is None:
            raise OrbitError(f"Tipo de documento não encontrado: {tipo_id}")
        return self.container_path(c) / doc.pasta

    def cliente_de(self, c: Container) -> Cliente | None:
        return self.get_cliente(c.cliente_id) if c.cliente_id else None

    def name_parts(self, c: Container) -> list[str]:
        cli = self.cliente_de(c)
        return [cli.nome, c.nome] if cli else [c.nome]

    def update_dados(self, container_id: str, **campos) -> Container:
        invalidos = [k for k in campos if k not in CAMPOS_EDITAVEIS]
        if invalidos:
            raise OrbitError(f"Campo não editável: {', '.join(invalidos)}")
        c = self.load_container(container_id)
        alterados = {}
        for k, v in campos.items():
            antigo = getattr(c, k)
            if k == "contatos":
                v = list(v)
                antigo_j, novo_j = [x.to_dict() for x in antigo], [x.to_dict() for x in v]
            else:
                antigo_j, novo_j = antigo, v
            if antigo_j != novo_j:
                alterados[k] = [antigo_j, novo_j]
                setattr(c, k, v)
        if alterados:
            c.historico.append(self.evento("dados_alterados", {"alterados": alterados}))
            self.save_container(c)  # pastas não são renomeadas
        return c

    # ---------- listagens ----------
    @staticmethod
    def _resumo(c: Container) -> ContainerResumo:
        aplic = [d for d in c.documentos.values() if not d.nao_se_aplica]
        emitidos = sum(1 for d in aplic if d.atual is not None)
        datas = [r.data for d in c.documentos.values() for r in d.revisoes]
        return ContainerResumo(c.id, c.nome, c.codigo, c.situacao, emitidos, len(aplic),
                               max(datas) if datas else None, None)

    def _resumos(self, pastas: list[Path], arquivo: str) -> list[ContainerResumo]:
        out = []
        for pasta in sorted(pastas, key=lambda p: p.name.casefold()):
            caminho = pasta / arquivo
            try:
                c = self._load_path(caminho)
            except (OrbitError, OSError) as e:
                out.append(ContainerResumo("", pasta.name, "", "", 0, 0, None, str(e)))
                continue
            self._idx_containers[c.id] = caminho
            out.append(self._resumo(c))
        return out

    def list_projetos(self, cliente_id: str) -> list[ContainerResumo]:
        raiz = self._pasta_cliente(self.get_cliente(cliente_id))
        pastas = [p for p in raiz.iterdir() if p.is_dir()] if raiz.is_dir() else []
        return self._resumos(pastas, ARQ_PROJETO)

    def list_maquinas(self) -> list[ContainerResumo]:
        raiz = self.base / PASTA_MAQUINAS
        pastas = [p for p in raiz.iterdir() if p.is_dir()] if raiz.is_dir() else []
        return self._resumos(pastas, ARQ_MAQUINA)
