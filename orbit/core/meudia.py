"""Meu dia: atividades, anotações de projeto e (Tarefa 3) lembretes.

Onde cada item fica (spec Meu dia §3 e §5):
- atividade (com ou sem projeto) e qualquer item sem projeto: arquivo pessoal
  `<base>/.orbit/usuarios/<usuario>/meu_dia.json` (chaves "itens" e "lembretes");
- pesquisar / definição / insight / onde parei COM projeto: anotação compartilhada
  em `<pasta do projeto>/anotacoes.json` (chave "notas").

Nada é apagado: excluir marca `excluido`. Arquivos ilegíveis nunca são regravados
(OrbitDataError sobe e o conteúdo do usuário fica como está).
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from orbit.core.errors import LockHeld, OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.naming import sanitize
from orbit.core.presence import PresenceService
from orbit.core.repository import Repository

TIPOS = ("atividade", "pesquisar", "definicao", "insight", "onde_parei")
TIPOS_COM_OK = ("atividade", "pesquisar", "definicao")
ARQ_PESSOAL = "meu_dia.json"
ARQ_ANOTACOES = "anotacoes.json"
_FORMATO = "%Y-%m-%dT%H:%M:%S"
_ESPERA_TRAVA_S = 5.0
_MAX_IDADE_TRAVA_S = 60
_MANTER = "__manter__"


@dataclass
class Item:
    id: str
    tipo: str
    texto: str
    container_id: str | None
    usuario: str
    computador: str
    criado_em: str
    alterado_em: str
    dia: str
    feito_em: str | None = None
    excluido: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(str(d["id"]), str(d["tipo"]), str(d.get("texto", "")),
                   d.get("container_id") or None, str(d.get("usuario", "")),
                   str(d.get("computador", "")), str(d.get("criado_em", "")),
                   str(d.get("alterado_em", "")), str(d.get("dia", "")),
                   d.get("feito_em") or None, bool(d.get("excluido", False)))


def mesclar_por_id(a: list[dict], b: list[dict]) -> list[dict]:
    """União por id; mesmo id dos dois lados: vence o maior alterado_em (empate: `a`)."""
    por_id: dict[str, dict] = {}
    for d in a or []:
        por_id.setdefault(d["id"], d)
    for d in b or []:
        atual = por_id.get(d["id"])
        if atual is None or str(d.get("alterado_em", "")) > str(atual.get("alterado_em", "")):
            por_id[d["id"]] = d
    return sorted(por_id.values(), key=lambda d: (str(d.get("criado_em", "")), str(d["id"])))


def _travar_com_espera(svc: PresenceService, pasta: Path, nome: str):
    limite = time.monotonic() + _ESPERA_TRAVA_S
    lock = svc.caminho_trava(pasta, nome)
    while True:
        try:
            return svc.travar(pasta, nome)
        except LockHeld:
            if svc.trava_abandonada(lock, _MAX_IDADE_TRAVA_S):
                svc.liberar_abandonada(lock, _MAX_IDADE_TRAVA_S)
                continue
            if time.monotonic() >= limite:
                raise OrbitError("Suas anotações estão sendo gravadas em outro computador; "
                                 "tente de novo em instantes.") from None
            time.sleep(0.05)


class MeuDiaService:
    def __init__(self, repo: Repository, identity: Identity,
                 agora: Callable[[], datetime] = datetime.now, log=None):
        self.repo = repo
        self.identity = identity
        self.agora = agora
        self.log = log

    # ---------- caminhos e leitura ----------
    @property
    def _pasta_usuario(self) -> Path:
        return self.repo.base / ".orbit" / "usuarios" / sanitize(self.identity.usuario)

    @property
    def caminho_pessoal(self) -> Path:
        return self._pasta_usuario / ARQ_PESSOAL

    def _caminho_anotacoes(self, container_id: str) -> Path:
        c = self.repo.load_container(container_id)
        return self.repo.container_path(c) / ARQ_ANOTACOES

    @staticmethod
    def _ler(caminho: Path, chaves: tuple[str, ...]) -> dict:
        if not caminho.exists():
            return {"versao_formato": 1, **{k: [] for k in chaves}}
        d = read_json(caminho)  # OrbitDataError se estiver corrompido
        for k in chaves:
            if not isinstance(d.get(k, []), list):
                raise OrbitDataError(f"Arquivo inválido: {caminho.name} ({k}).")
            d.setdefault(k, [])
        return d

    def _dados_pessoais(self) -> dict:
        return self._ler(self.caminho_pessoal, ("itens", "lembretes"))

    @contextmanager
    def _editar_pessoal(self) -> Iterator[dict]:
        pasta = self._pasta_usuario
        pasta.mkdir(parents=True, exist_ok=True)
        svc = PresenceService(self.identity, agora=datetime.now)
        trava = _travar_com_espera(svc, pasta, "_meu_dia")
        try:
            dados = self._dados_pessoais()  # relido dentro da trava
            yield dados
            write_json_atomic(self.caminho_pessoal, dados)
        finally:
            svc.liberar_varios([trava])

    @contextmanager
    def _editar_anotacoes(self, container_id: str) -> Iterator[dict]:
        with self.repo.trava_container(container_id):
            caminho = self._caminho_anotacoes(container_id)
            dados = self._ler(caminho, ("notas",))
            yield dados
            write_json_atomic(caminho, dados)

    # ---------- utilitários ----------
    def _agora_iso(self) -> str:
        return self.agora().strftime(_FORMATO)

    @staticmethod
    def _destino(tipo: str, container_id: str | None) -> str | None:
        """None = arquivo pessoal; senão, o id do projeto da anotação compartilhada."""
        return None if tipo == "atividade" or not container_id else container_id

    @staticmethod
    def _validar_tipo(tipo) -> str:
        if tipo not in TIPOS:
            raise OrbitError(f"Tipo inválido: {tipo}")
        return tipo

    def _validar_container(self, container_id) -> str | None:
        if not container_id:
            return None
        if not isinstance(container_id, str):
            raise OrbitError("Projeto inválido.")
        self.repo.load_container(container_id)  # OrbitError se não existir
        return container_id

    def _logar(self, acao: str, it: Item) -> None:
        if self.log is None or self._destino(it.tipo, it.container_id) is None:
            return  # itens pessoais não vão para o log de ações
        try:
            self.log.registrar_acao(acao, {"container_id": it.container_id, "tipo": it.tipo,
                                           "texto": it.texto})
        except Exception:
            pass

    def _gravar(self, it: Item) -> None:
        destino = self._destino(it.tipo, it.container_id)
        if destino is None:
            with self._editar_pessoal() as d:
                d["itens"] = [x for x in d["itens"] if x.get("id") != it.id] + [it.to_dict()]
        else:
            with self._editar_anotacoes(destino) as d:
                d["notas"] = [x for x in d["notas"] if x.get("id") != it.id] + [it.to_dict()]

    def _todos_containers(self) -> list[str]:
        ids = []
        for cli in self.repo.list_clientes():
            ids += [r.id for r in self.repo.list_projetos(cli.id) if r.id and not r.erro]
        ids += [r.id for r in self.repo.list_maquinas() if r.id and not r.erro]
        return ids

    def _localizar(self, item_id: str) -> Item:
        for d in self._dados_pessoais()["itens"]:
            if d.get("id") == item_id:
                return Item.from_dict(d)
        for cid in self._todos_containers():
            try:
                notas = self._ler(self._caminho_anotacoes(cid), ("notas",))["notas"]
            except OrbitDataError:
                continue
            for d in notas:
                if d.get("id") == item_id:
                    return Item.from_dict(d)
        raise OrbitError("Anotação não encontrada.")

    # ---------- operações ----------
    def adicionar(self, texto: str, tipo: str = "atividade", container_id: str | None = None,
                  dia: date | None = None) -> Item:
        texto = (texto or "").strip() if isinstance(texto, str) else ""
        if not texto:
            raise OrbitError("Escreva o texto.")
        tipo = self._validar_tipo(tipo)
        container_id = self._validar_container(container_id)
        agora = self._agora_iso()
        it = Item(uuid4().hex, tipo, texto, container_id, self.identity.usuario,
                  self.identity.computador, agora, agora,
                  (dia or self.agora().date()).isoformat())
        self._gravar(it)
        self._logar("anotacao_criada", it)
        return it

    def editar(self, item_id: str, texto: str | None = None, tipo: str | None = None,
               container_id: str | None = _MANTER) -> Item:
        atual = self._localizar(item_id)
        novo = Item.from_dict(atual.to_dict())
        if texto is not None:
            texto = texto.strip() if isinstance(texto, str) else ""
            if not texto:
                raise OrbitError("Escreva o texto.")
            novo.texto = texto
        if tipo is not None:
            novo.tipo = self._validar_tipo(tipo)
            if novo.tipo not in TIPOS_COM_OK:
                novo.feito_em = None
        if container_id != _MANTER:
            novo.container_id = self._validar_container(container_id)
        novo.alterado_em = self._agora_iso()
        if self._destino(atual.tipo, atual.container_id) != self._destino(novo.tipo,
                                                                          novo.container_id):
            self._gravar(novo)  # primeiro no destino: nunca fica sem cópia viva
            velho = Item.from_dict(atual.to_dict())
            velho.excluido = True
            velho.alterado_em = novo.alterado_em
            self._gravar(velho)
        else:
            self._gravar(novo)
        return novo

    def marcar_feito(self, item_id: str, feito: bool) -> Item:
        it = self._localizar(item_id)
        if it.tipo not in TIPOS_COM_OK:
            raise OrbitError("Este tipo de anotação não tem OK.")
        it.feito_em = self._agora_iso() if feito else None
        it.alterado_em = self._agora_iso()
        self._gravar(it)
        if feito:
            self._logar("anotacao_concluida", it)
        return it

    def excluir(self, item_id: str) -> None:
        it = self._localizar(item_id)
        it.excluido = True
        it.alterado_em = self._agora_iso()
        self._gravar(it)
        self._logar("anotacao_excluida", it)

    # ---------- leitura ----------
    def itens_pessoais(self) -> list[Item]:
        return [Item.from_dict(d) for d in self._dados_pessoais()["itens"]
                if not d.get("excluido")]

    def anotacoes(self, container_id: str) -> list[Item]:
        notas = self._ler(self._caminho_anotacoes(container_id), ("notas",))["notas"]
        return [Item.from_dict(d) for d in notas if not d.get("excluido")]

    def todas_anotacoes(self) -> list[Item]:
        out = []
        for cid in self._todos_containers():
            try:
                out += self.anotacoes(cid)
            except OrbitError:
                continue  # projeto com anotações ilegíveis: não derruba o dashboard
        return out

    # ---------- consultas do dashboard ----------
    def _meus(self) -> list[Item]:
        eu = self.identity.usuario
        return self.itens_pessoais() + [n for n in self.todas_anotacoes() if n.usuario == eu]

    def lista_do_dia(self, dia: date) -> list[Item]:
        """Itens com OK do próprio usuário que aparecem no dia (spec Meu dia §3)."""
        hoje = self.agora().date()
        d_iso = dia.isoformat()
        escolhidos: dict[str, Item] = {}
        for it in self._meus():
            if it.tipo not in TIPOS_COM_OK:
                continue
            feito_dia = it.feito_em[:10] if it.feito_em else None
            entra = it.tipo == "atividade" and it.dia == d_iso
            if feito_dia is None:
                if it.tipo == "atividade" and dia == hoje and it.dia < d_iso:
                    entra = True  # não terminada: passa para hoje
                if it.tipo in ("pesquisar", "definicao") and dia >= hoje:
                    entra = True  # pendência fica até receber OK
            elif feito_dia == d_iso:
                entra = True  # riscado no dia do OK
            if entra:
                escolhidos[it.id] = it
        return sorted(escolhidos.values(), key=lambda i: (i.feito_em is not None, i.criado_em))

    def abertas_hoje(self) -> int:
        return sum(1 for i in self.lista_do_dia(self.agora().date()) if i.feito_em is None)

    def _nomes(self, container_id: str) -> tuple[str, str | None]:
        c = self.repo.load_container(container_id)
        cli = self.repo.cliente_de(c)
        return c.nome, cli.nome if cli else None

    def onde_parei(self) -> list[dict]:
        """A anotação "onde parei" mais recente DO PRÓPRIO usuário em cada projeto."""
        eu = self.identity.usuario
        ultimo: dict[str, Item] = {}
        for n in self.todas_anotacoes():
            if n.tipo == "onde_parei" and n.usuario == eu:
                atual = ultimo.get(n.container_id)
                if atual is None or n.alterado_em > atual.alterado_em:
                    ultimo[n.container_id] = n
        out = []
        for cid, it in ultimo.items():
            nome, cliente = self._nomes(cid)
            out.append({"container_id": cid, "container_nome": nome, "cliente_nome": cliente,
                        "item": it})
        return sorted(out, key=lambda x: x["item"].alterado_em, reverse=True)

    def ultimo_onde_parei(self, container_id: str) -> Item | None:
        """A mais recente de qualquer pessoa (faixa no topo do painel do projeto)."""
        notas = [n for n in self.anotacoes(container_id) if n.tipo == "onde_parei"]
        return max(notas, key=lambda n: n.alterado_em) if notas else None

    def ideias(self, limite: int = 50) -> list[dict]:
        insights = sorted((n for n in self.todas_anotacoes() if n.tipo == "insight"),
                          key=lambda n: n.criado_em, reverse=True)[:limite]
        out = []
        for it in insights:
            nome, cliente = self._nomes(it.container_id)
            out.append({"container_id": it.container_id, "container_nome": nome,
                        "cliente_nome": cliente, "item": it})
        return out

    def docs_pendentes(self) -> int:
        total = 0
        for cid in self._todos_containers():
            try:
                c = self.repo.load_container(cid)
            except OrbitError:
                continue
            if c.situacao != "ativo":
                continue
            total += sum(1 for d in c.documentos.values()
                         if not d.nao_se_aplica and d.atual is None)
        return total

    # ---------- lembretes (guardados no arquivo pessoal) ----------
    def lembretes(self) -> list:
        from orbit.core.lembretes import Lembrete
        return [Lembrete.from_dict(d) for d in self._dados_pessoais()["lembretes"]
                if not d.get("excluido")]

    def salvar_lembrete(self, dados: dict):
        from orbit.core.lembretes import Lembrete, ler_data, validar_recorrencia
        if not isinstance(dados, dict):
            raise OrbitError("Lembrete inválido.")
        texto = dados.get("texto")
        texto = texto.strip() if isinstance(texto, str) else ""
        if not texto:
            raise OrbitError("Escreva o texto do lembrete.")
        quando = ler_data(dados.get("quando")).strftime("%Y-%m-%dT%H:%M")
        rec = validar_recorrencia(dados.get("recorrencia"))
        container_id = self._validar_container(dados.get("container_id"))
        agora = self._agora_iso()
        lid = dados.get("id")
        with self._editar_pessoal() as d:
            atual = next((x for x in d["lembretes"] if lid and x.get("id") == lid), None)
            if lid and atual is None:
                raise OrbitError("Lembrete não encontrado.")
            if atual is not None:
                lem = Lembrete.from_dict(atual)
                lem.texto, lem.quando, lem.recorrencia = texto, quando, rec
                lem.container_id = container_id
                lem.adiado_ate, lem.ultimo_disparo, lem.ativo = None, None, True
            else:
                lem = Lembrete(uuid4().hex, texto, container_id, self.identity.usuario, quando,
                               rec, criado_em=agora)
            lem.alterado_em = agora
            d["lembretes"] = [x for x in d["lembretes"] if x.get("id") != lem.id] + [lem.to_dict()]
        return lem

    def excluir_lembrete(self, lembrete_id: str) -> None:
        self.aplicar(lembrete_id, lambda lem: _marcar_excluido(lem))

    def aplicar(self, lembrete_id: str, func):
        """Aplica `func(lembrete) -> lembrete` e grava, sob a trava (adiar, concluir...)."""
        from orbit.core.lembretes import Lembrete
        with self._editar_pessoal() as d:
            atual = next((x for x in d["lembretes"] if x.get("id") == lembrete_id), None)
            if atual is None:
                raise OrbitError("Lembrete não encontrado.")
            novo = func(Lembrete.from_dict(atual))
            novo.alterado_em = self._agora_iso()
            d["lembretes"] = [x for x in d["lembretes"] if x.get("id") != lembrete_id] + [
                novo.to_dict()]
        return novo


def _marcar_excluido(lem):
    lem.excluido = True
    return lem
