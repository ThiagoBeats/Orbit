"""Métodos da Api para o Meu dia, anotações de projeto e lembretes (spec Meu dia).

`MeuDiaApiMixin` é herdado pela classe Api. A agenda de lembretes só começa
quando a janela existe (definir_janela) e a pasta base está aberta; os avisos
vão para o Windows (toast) e para a janela (popup), via evaluate_js.
"""
import json
import sys
from datetime import date
from pathlib import Path

from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.meudia import MeuDiaService
from orbit.ui.notificacoes import AgendaLembretes, ToastNotificador

ACOES_LEMBRETE = ("adiar10", "adiar60", "concluir")


def _icone() -> Path:
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return raiz / "orbit" / "ui" / "web" / "img" / "orbit-icon.ico"


class _JanelaNotificador:
    """Popup do lembrete dentro do Orbit (também quando o toast é bloqueado)."""

    def __init__(self, api):
        self._api = api

    def mostrar(self, lem, ao_acao) -> None:
        janela = self._api._janela
        if janela is None:
            return
        dados = {"id": lem.id, "texto": lem.texto, "container_id": lem.container_id}
        janela.evaluate_js(f"orbitLembrete({json.dumps(dados, ensure_ascii=False)})")


class MeuDiaApiMixin:
    # ---------- infraestrutura ----------
    def _iniciar_estado_meudia(self) -> None:
        self._meudia: MeuDiaService | None = None
        self._agenda: AgendaLembretes | None = None
        self._toast = None

    def _criar_meudia(self, repo, ident, log) -> None:
        self._meudia = MeuDiaService(repo, ident, log=log)
        self._reiniciar_agenda()

    def _reiniciar_agenda(self) -> None:
        if self._agenda is not None:
            self._agenda.parar()
            self._agenda = None
        if self._meudia is None or self._janela is None:
            return  # sem janela (ex.: testes) não há a quem avisar
        if self._toast is None:
            self._toast = ToastNotificador(icone=_icone(), registrar=self._registrar_erro)
        self._agenda = AgendaLembretes(
            self._meudia, [_JanelaNotificador(self), self._toast],
            ao_perdidos=self._avisar_perdidos, registrar=self._registrar_erro)
        self._agenda.iniciar()

    def _avisar_perdidos(self, lista) -> None:
        if self._janela is None:
            return
        dados = [{"id": l.id, "texto": l.texto, "quando": l.quando} for l in lista]
        self._janela.evaluate_js(f"orbitLembretesPerdidos({json.dumps(dados, ensure_ascii=False)})")

    def _parar_agenda(self) -> None:
        if self._agenda is not None:
            self._agenda.parar()

    def _exigir_meudia(self) -> MeuDiaService:
        if self._meudia is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        return self._meudia

    def _nome_container(self, cid) -> str | None:
        if not cid:
            return None
        try:
            return self._repo.load_container(cid).nome
        except OrbitError:
            return None

    def _item_dict(self, it) -> dict:
        d = it.to_dict()
        d["container_nome"] = self._nome_container(it.container_id)
        return d

    @staticmethod
    def _texto_ou_none(v, campo):
        if v is None:
            return None
        if not isinstance(v, str):
            raise OrbitError(f"Campo inválido: {campo}")
        return v

    @staticmethod
    def _dia(v) -> date | None:
        if v in (None, ""):
            return None
        if not isinstance(v, str):
            raise OrbitError("Data inválida.")
        try:
            return date.fromisoformat(v)
        except ValueError:
            raise OrbitError("Data inválida.") from None

    # ---------- dashboard ----------
    def dashboard(self, dia_iso=None) -> dict:
        return self._chamar(self._dashboard, dia_iso)

    def _dashboard(self, dia_iso):
        svc = self._exigir_meudia()
        hoje = svc.agora().date()
        dia = self._dia(dia_iso) or hoje
        erro = None
        try:
            itens = [self._item_dict(i) for i in svc.lista_do_dia(dia)]
            lembretes = sorted((l for l in svc.lembretes() if l.ativo),
                               key=lambda l: l.efetivo)[:10]
            lembretes = [dict(l.to_dict(), container_nome=self._nome_container(l.container_id))
                         for l in lembretes]
            abertas = sum(1 for i in itens if not i["feito_em"]) if dia == hoje \
                else svc.abertas_hoje()
        except OrbitDataError as e:
            erro = f"Não foi possível ler suas anotações pessoais: {e}"
            itens, lembretes, abertas = [], [], 0
        repo = self._repo
        ativos = sum(1 for c in repo.list_clientes() for r in repo.list_projetos(c.id)
                     if r.situacao == "ativo" and not r.erro)
        ativos += sum(1 for r in repo.list_maquinas() if r.situacao == "ativo" and not r.erro)
        return {
            "usuario": svc.identity.usuario, "hoje": hoje.isoformat(), "dia": dia.isoformat(),
            "numeros": {"abertas_hoje": abertas, "projetos_ativos": ativos,
                        "docs_pendentes": svc.docs_pendentes()},
            "itens": itens, "lembretes": lembretes,
            "onde_parei": [dict(x, item=x["item"].to_dict()) for x in svc.onde_parei()],
            "ideias": [dict(x, item=x["item"].to_dict()) for x in svc.ideias()],
            "erro_meu_dia": erro,
        }

    # ---------- itens ----------
    def adicionar_item(self, dados) -> dict:
        return self._chamar(self._adicionar_item, dados)

    def _adicionar_item(self, dados):
        if not isinstance(dados, dict):
            raise OrbitError("Dados inválidos.")
        texto = self._texto_ou_none(dados.get("texto"), "texto") or ""
        tipo = self._texto_ou_none(dados.get("tipo"), "tipo") or "atividade"
        cid = self._texto_ou_none(dados.get("container_id"), "projeto") or None
        it = self._exigir_meudia().adicionar(texto, tipo, cid, self._dia(dados.get("dia")))
        return self._item_dict(it)

    def editar_item(self, item_id, dados) -> dict:
        return self._chamar(self._editar_item, item_id, dados)

    def _editar_item(self, item_id, dados):
        if not isinstance(item_id, str) or not isinstance(dados, dict):
            raise OrbitError("Dados inválidos.")
        kw = {}
        if "texto" in dados:
            kw["texto"] = self._texto_ou_none(dados["texto"], "texto") or ""
        if "tipo" in dados:
            kw["tipo"] = self._texto_ou_none(dados["tipo"], "tipo")
        if "container_id" in dados:
            kw["container_id"] = self._texto_ou_none(dados["container_id"], "projeto") or None
        return self._item_dict(self._exigir_meudia().editar(item_id, **kw))

    def marcar_item(self, item_id, feito) -> dict:
        return self._chamar(self._marcar_item, item_id, feito)

    def _marcar_item(self, item_id, feito):
        if not isinstance(item_id, str) or not isinstance(feito, bool):
            raise OrbitError("Dados inválidos.")
        return self._item_dict(self._exigir_meudia().marcar_feito(item_id, feito))

    def excluir_item(self, item_id) -> dict:
        return self._chamar(self._excluir_item, item_id)

    def _excluir_item(self, item_id):
        if not isinstance(item_id, str):
            raise OrbitError("Dados inválidos.")
        self._exigir_meudia().excluir(item_id)
        return None

    def anotacoes_projeto(self, container_id) -> dict:
        return self._chamar(self._anotacoes_projeto, container_id)

    def _anotacoes_projeto(self, container_id):
        if not isinstance(container_id, str):
            raise OrbitError("Projeto inválido.")
        svc = self._exigir_meudia()
        ultimo = svc.ultimo_onde_parei(container_id)
        return {"anotacoes": [i.to_dict() for i in sorted(svc.anotacoes(container_id),
                                                         key=lambda i: i.criado_em, reverse=True)],
                "onde_parei": ultimo.to_dict() if ultimo else None}

    # ---------- lembretes ----------
    def listar_lembretes(self) -> dict:
        return self._chamar(lambda: [dict(l.to_dict(),
                                          container_nome=self._nome_container(l.container_id))
                                     for l in self._exigir_meudia().lembretes()])

    def salvar_lembrete(self, dados) -> dict:
        return self._chamar(lambda: self._exigir_meudia().salvar_lembrete(dados).to_dict())

    def excluir_lembrete(self, lembrete_id) -> dict:
        def excluir():
            if not isinstance(lembrete_id, str):
                raise OrbitError("Dados inválidos.")
            self._exigir_meudia().excluir_lembrete(lembrete_id)
        return self._chamar(excluir)

    def acao_lembrete(self, lembrete_id, acao) -> dict:
        return self._chamar(self._acao_lembrete, lembrete_id, acao)

    def _acao_lembrete(self, lembrete_id, acao):
        if not isinstance(lembrete_id, str) or acao not in ACOES_LEMBRETE:
            raise OrbitError("Ação inválida.")
        svc = self._exigir_meudia()
        agenda = self._agenda or AgendaLembretes(svc, [])
        agenda.acao(lembrete_id, acao)
        return None
