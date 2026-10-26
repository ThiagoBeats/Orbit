"""OPs (Ordens de Produção): criação, leitura e gravação (spec Produção §4/§6).

Cada OP é um `op.json` em `<pasta do projeto>/Produção/OP-NNNN - <painel>/`.
Gravações sob a trava da OP, com releitura dentro da trava. A numeração é
única na pasta base (`.orbit/producao.json`, sob trava própria).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.meudia import _travar_com_espera
from orbit.core.naming import sanitize
from orbit.core.presence import PresenceService
from orbit.core.producao.config import carregar_config, salvar_config
from orbit.core.repository import Repository

PASTA_PRODUCAO = "Produção"
ARQ_OP = "op.json"
ETAPAS = ("planejada", "liberada", "em_montagem", "em_teste", "verificacao_final", "aprovada",
          "expedida")
NOMES_ETAPAS = {"planejada": "Planejada", "liberada": "Liberada", "em_montagem": "Em montagem",
                "em_teste": "Em teste", "verificacao_final": "Verificação final",
                "aprovada": "Aprovada", "expedida": "Expedida"}
PRIORIDADES = ("normal", "alta", "urgente")
_FMT = "%Y-%m-%dT%H:%M:%S"
# ações da OP que também vão para o log de ações geral
ACOES_LOG = {"op_criada", "pacote_liberado", "pacote_atualizado", "etapa_avancada",
             "etapa_voltada", "op_bloqueada", "op_desbloqueada"}


def testes_vazios() -> dict:
    return {
        "inspecao": {"itens": []},
        "ponto_a_ponto": {"linhas": [], "importado_em": None, "anteriores": []},
        "isolacao": {"circuitos": []},
        "energizacao": {"passos": [], "pontos": []},
        "io": {"sinais": [], "importado_em": None},
        "verificacao": {"sorteadas": [], "verificador": None, "resultados": {},
                        "checklist": [], "concluida": False, "aprovada": None, "historico": []},
    }


class ProducaoService:
    def __init__(self, repo: Repository, identity: Identity,
                 agora: Callable[[], datetime] = datetime.now, log=None):
        self.repo = repo
        self.identity = identity
        self.agora = agora
        self.log = log
        self._indice: dict[str, Path] = {}

    # ---------- utilitários ----------
    def agora_iso(self) -> str:
        return self.agora().strftime(_FMT)

    def config(self) -> dict:
        return carregar_config(self.repo.base)

    def _svc_trava(self) -> PresenceService:
        return PresenceService(self.identity, agora=datetime.now)

    def registrar(self, op: dict, acao: str, detalhes: dict | None = None,
                  usuario: str | None = None) -> None:
        op.setdefault("historico", []).append({
            "quando": self.agora_iso(), "usuario": usuario or self.identity.usuario,
            "acao": acao, "detalhes": dict(detalhes or {})})
        if self.log is not None and acao in ACOES_LOG:
            try:
                self.log.registrar_acao(acao, {"op": op.get("numero"), "painel": op.get("painel"),
                                               "container_id": op.get("container_id"),
                                               **(detalhes or {})})
            except Exception:
                pass

    def _pasta_producao(self, container_id: str) -> Path:
        c = self.repo.load_container(container_id)  # OrbitError se não existir
        return self.repo.container_path(c) / PASTA_PRODUCAO

    # ---------- configuração com numeração ----------
    @contextmanager
    def editar_config(self) -> Iterator[dict]:
        pasta = self.repo.base / ".orbit"
        pasta.mkdir(parents=True, exist_ok=True)
        svc = self._svc_trava()
        trava = _travar_com_espera(svc, self.repo.base, "_producao")
        try:
            cfg = carregar_config(self.repo.base)
            yield cfg
            salvar_config(self.repo.base, cfg)
        finally:
            svc.liberar_varios([trava])

    # ---------- criação ----------
    @staticmethod
    def _validar_dados(dados: dict, parcial: bool = False) -> dict:
        if not isinstance(dados, dict):
            raise OrbitError("Dados da OP inválidos.")
        out = {}
        if "painel" in dados or not parcial:
            painel = dados.get("painel")
            painel = painel.strip() if isinstance(painel, str) else ""
            if not painel or not sanitize(painel):
                raise OrbitError("Informe o nome/tag do painel.")
            out["painel"] = painel
        for campo in ("descricao", "responsavel"):
            if campo in dados or not parcial:
                v = dados.get(campo) or ""
                if not isinstance(v, str):
                    raise OrbitError(f"Campo inválido: {campo}")
                out[campo] = v.strip()
        if "prioridade" in dados or not parcial:
            pr = dados.get("prioridade") or "normal"
            if pr not in PRIORIDADES:
                raise OrbitError("Prioridade inválida.")
            out["prioridade"] = pr
        if "prazo" in dados or not parcial:
            prazo = dados.get("prazo") or None
            if prazo is not None:
                try:
                    date.fromisoformat(prazo)
                except (TypeError, ValueError):
                    raise OrbitError("Prazo inválido.") from None
            out["prazo"] = prazo
        if "quantidade" in dados or not parcial:
            q = dados.get("quantidade", 1)
            if isinstance(q, bool) or not isinstance(q, int) or q < 1:
                raise OrbitError("Quantidade inválida.")
            out["quantidade"] = q
        return out

    def criar_op(self, container_id: str, dados: dict) -> dict:
        campos = self._validar_dados(dados)
        pasta_prod = self._pasta_producao(container_id)
        with self.editar_config() as cfg:
            n = int(cfg.get("proximo_numero", 1))
            cfg["proximo_numero"] = n + 1
        numero = f"OP-{n:04d}"
        pasta = pasta_prod / f"{numero} - {sanitize(campos['painel'])[:40].rstrip(' .-')}"
        try:
            pasta.mkdir(parents=True)
        except FileExistsError:
            raise OrbitError(f"Já existe a pasta {pasta.name}.") from None
        except OSError as e:
            raise OrbitError(f"Não foi possível criar a pasta da OP: {e}") from e
        op = {"versao_formato": 1, "id": uuid4().hex, "numero": numero,
              "container_id": container_id, **campos, "criada_em": self.agora_iso(),
              "criada_por": self.identity.usuario, "etapa": "planejada", "bloqueio": None,
              "pacote": [], "pacote_liberado_em": None, "materiais": [], "apontamentos": [],
              "testes": testes_vazios(), "ncs": [], "historico": []}
        self.registrar(op, "op_criada", {"painel": campos["painel"]})
        write_json_atomic(pasta / ARQ_OP, op)
        self._indice[op["id"]] = pasta / ARQ_OP
        return op

    def editar_dados(self, op_id: str, dados: dict) -> dict:
        """Altera painel, descrição, responsável, prioridade, prazo e quantidade.

        A pasta da OP não é renomeada (o número continua identificando a OP)."""
        campos = self._validar_dados(dados, parcial=True)
        with self.editar(op_id) as op:
            antes = {k: op.get(k) for k in campos}
            op.update(campos)
            mudou = {k: {"de": antes[k], "para": v} for k, v in campos.items() if antes[k] != v}
            if mudou:
                self.registrar(op, "op_editada", mudou)
        return op

    # ---------- leitura e gravação ----------
    def _arquivos(self, container_id: str | None = None) -> list[tuple[str, Path]]:
        ids = [container_id] if container_id else self._containers()
        out = []
        for cid in ids:
            try:
                pasta = self._pasta_producao(cid)
            except OrbitError:
                continue
            if pasta.is_dir():
                out += [(cid, f) for f in sorted(pasta.glob(f"*/{ARQ_OP}"))]
        return out

    def _containers(self) -> list[str]:
        ids = []
        for cli in self.repo.list_clientes():
            ids += [r.id for r in self.repo.list_projetos(cli.id) if r.id and not r.erro]
        ids += [r.id for r in self.repo.list_maquinas() if r.id and not r.erro]
        return ids

    @staticmethod
    def _ler(arq: Path) -> dict:
        d = read_json(arq)
        if not isinstance(d.get("id"), str):
            raise OrbitDataError(f"OP inválida: {arq.parent.name}")
        d.setdefault("testes", testes_vazios())
        for k, v in testes_vazios().items():
            d["testes"].setdefault(k, v)
        return d

    def _caminho(self, op_id: str) -> Path:
        arq = self._indice.get(op_id)
        if arq is not None and arq.is_file():
            return arq
        for _, f in self._arquivos():
            try:
                if read_json(f).get("id") == op_id:
                    self._indice[op_id] = f
                    return f
            except OrbitDataError:
                continue
        raise OrbitError("OP não encontrada.")

    def pasta_op(self, op_id: str) -> Path:
        return self._caminho(op_id).parent

    def carregar(self, op_id: str) -> dict:
        if not isinstance(op_id, str):
            raise OrbitError("OP inválida.")
        return self._ler(self._caminho(op_id))

    @contextmanager
    def editar(self, op_id: str) -> Iterator[dict]:
        arq = self._caminho(op_id)
        svc = self._svc_trava()
        trava = _travar_com_espera(svc, arq.parent, "_op")
        try:
            op = self._ler(arq)  # relida dentro da trava
            yield op
            write_json_atomic(arq, op)
        finally:
            svc.liberar_varios([trava])

    def listar_ops(self, container_id: str) -> list[dict]:
        out = []
        for _, f in self._arquivos(container_id):
            try:
                op = self._ler(f)
            except OrbitDataError:
                continue
            self._indice[op["id"]] = f
            out.append(op)
        return sorted(out, key=lambda o: o["numero"])

    def todas_ops(self) -> list[dict]:
        out = []
        for cid in self._containers():
            try:
                c = self.repo.load_container(cid)
            except OrbitError:
                continue
            cli = self.repo.cliente_de(c)
            for op in self.listar_ops(cid):
                op["container_nome"] = c.nome
                op["cliente_nome"] = cli.nome if cli else None
                out.append(op)
        return sorted(out, key=lambda o: o["numero"])
