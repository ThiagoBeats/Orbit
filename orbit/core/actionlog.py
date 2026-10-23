"""Log de ações da pasta base, com detecção de adulteração (spec de backup §7).

Arquivo `<base>/.orbit/log/acoes.log`: uma linha JSON por ação, sempre
acrescentada no fim. Cada computador tem sua própria corrente: a linha leva o
código (sha256) da linha anterior *do mesmo computador* e o seu próprio código.
Editar, apagar ou inserir uma linha quebra a corrente.

Além da corrente, cada computador guarda fora da pasta base (âncora em
`%APPDATA%/Orbit/ancoras.json`) o número e o código da última linha que ele
mesmo gravou: quem reescreve a corrente inteira com códigos recalculados é pego
porque a âncora não confere mais.

Uma adulteração detectada vira uma linha `adulteracao_detectada`, que reinicia
a corrente deste computador (`anterior` = zeros). As linhas antigas nunca são
corrigidas nem apagadas.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from orbit.core.errors import LockHeld, OrbitDataError, OrbitError
from orbit.core.identity import Identity
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.presence import PresenceService

ZEROS = "0" * 64
ACAO_ADULTERACAO = "adulteracao_detectada"
NOME_TRAVA = "_log"
ESPERA_TRAVA_S = 5.0
MAX_IDADE_TRAVA_LOG_S = 60
_INTERVALO_S = 0.05
_TENTATIVAS = 5
_FORMATO = "%Y-%m-%dT%H:%M:%S"
DESCONHECIDO = "?"


@dataclass
class LinhaLog:
    seq: str
    n: int
    computador: str
    usuario: str
    data_hora: str
    acao: str
    detalhes: dict = field(default_factory=dict)
    anterior: str = ZEROS
    codigo: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LinhaLog":
        if not isinstance(d, dict):
            raise ValueError("linha não é um objeto")
        detalhes = d.get("detalhes", {})
        if not isinstance(detalhes, dict):
            raise ValueError("detalhes inválidos")
        n = d["n"]
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError("n inválido")
        return cls(str(d["seq"]), n, str(d["computador"]), str(d["usuario"]),
                   str(d["data_hora"]), str(d["acao"]), detalhes,
                   str(d["anterior"]), str(d["codigo"]))

    def calcular_codigo(self) -> str:
        d = self.to_dict()
        d.pop("codigo", None)
        texto = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@dataclass
class ProblemaLog:
    computador: str
    a_partir_de_n: int
    descricao: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RelatorioLog:
    integro: bool
    problemas: list[ProblemaLog]

    def to_dict(self) -> dict:
        return {"integro": self.integro, "problemas": [p.to_dict() for p in self.problemas]}


def _ler_arquivo(caminho: Path) -> tuple[list[LinhaLog], list[int]]:
    """Linhas válidas e os números (1-based) das linhas ilegíveis do arquivo."""
    linhas: list[LinhaLog] = []
    ilegiveis: list[int] = []
    try:
        texto = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return linhas, ilegiveis
    except (OSError, UnicodeDecodeError) as e:
        raise OrbitDataError(f"Não foi possível ler o log de ações: {e}") from e
    for i, bruta in enumerate(texto.splitlines(), start=1):
        if not bruta.strip():
            continue
        try:
            linhas.append(LinhaLog.from_dict(json.loads(bruta)))
        except (ValueError, KeyError, TypeError):
            ilegiveis.append(i)
    return linhas, ilegiveis


def verificar_linhas(linhas: list[LinhaLog], ilegiveis: list[int] | None = None,
                     ancora: tuple[str, dict] | None = None) -> list[ProblemaLog]:
    """Todos os problemas (inclusive os já alertados). Ordem: por computador, depois n."""
    problemas: list[ProblemaLog] = []
    for k in ilegiveis or []:
        problemas.append(ProblemaLog(DESCONHECIDO, k, f"Linha {k} do arquivo está ilegível."))
    por_pc: dict[str, list[LinhaLog]] = {}
    for l in linhas:
        por_pc.setdefault(l.computador, []).append(l)
    for pc, seq in por_pc.items():
        anterior: LinhaLog | None = None
        quebrado = False  # segmento atual já tem problema: pula até o próximo reinício
        for l in seq:
            reinicio = l.anterior == ZEROS and (anterior is None or l.acao == ACAO_ADULTERACAO)
            if reinicio:
                quebrado = False
            if quebrado:
                anterior = l
                continue
            problema = None
            if l.codigo != l.calcular_codigo():
                problema = ProblemaLog(pc, l.n, f"A linha {l.seq} foi alterada.")
            elif anterior is not None and not reinicio and l.n != anterior.n + 1:
                problema = ProblemaLog(pc, anterior.n + 1,
                                       f"Faltam linhas de {pc} a partir da nº {anterior.n + 1}.")
            elif anterior is None and not reinicio:
                problema = ProblemaLog(pc, l.n, f"A corrente de {pc} não começa no início.")
            elif anterior is not None and not reinicio and l.anterior != anterior.codigo:
                problema = ProblemaLog(pc, l.n, f"A linha {l.seq} não segue a anterior.")
            if problema is not None:
                problemas.append(problema)
                quebrado = True
            anterior = l
    if ancora is not None:
        pc, a = ancora
        try:
            n_anc, cod_anc = int(a["n"]), str(a["codigo"])
        except (KeyError, TypeError, ValueError):
            n_anc, cod_anc = None, None
        if n_anc is not None:
            alvo = [l for l in por_pc.get(pc, []) if l.n == n_anc]
            if not alvo or alvo[-1].codigo != cod_anc:
                problemas.append(ProblemaLog(
                    pc, n_anc, f"A linha nº {n_anc} de {pc} não confere com o registro "
                               f"guardado neste computador."))
    return problemas


def _alertados(linhas: list[LinhaLog]) -> set[tuple[str, int]]:
    chaves = set()
    for l in linhas:
        if l.acao == ACAO_ADULTERACAO:
            try:
                chaves.add((str(l.detalhes["computador"]), int(l.detalhes["a_partir_de_n"])))
            except (KeyError, TypeError, ValueError):
                pass
    return chaves


def mesclar_logs(a: list[LinhaLog], b: list[LinhaLog]) -> tuple[list[LinhaLog], list[str]]:
    """União por `seq` (ordenada por data/hora, seq) e os `seq` em conflito.

    Em conflito (mesmo seq, conteúdo diferente), fica a linha de `a`.
    """
    por_seq: dict[str, LinhaLog] = {}
    conflitos: list[str] = []
    for l in a:
        por_seq.setdefault(l.seq, l)
    for l in b:
        atual = por_seq.get(l.seq)
        if atual is None:
            por_seq[l.seq] = l
        elif atual.to_dict() != l.to_dict() and l.seq not in conflitos:
            conflitos.append(l.seq)
    juntas = sorted(por_seq.values(), key=lambda l: (l.data_hora, l.seq))
    return juntas, conflitos


class ActionLog:
    def __init__(self, base: Path, identity: Identity, ancoras_path: Path,
                 agora: Callable[[], datetime] = datetime.now,
                 registrar: Callable[[BaseException], None] | None = None):
        self.base = Path(base)
        self.identity = identity
        self.ancoras_path = Path(ancoras_path)
        self.agora = agora
        self.registrar = registrar

    @property
    def caminho(self) -> Path:
        return self.base / ".orbit" / "log" / "acoes.log"

    # ---------- âncora ----------
    def _chave_base(self) -> str:
        try:
            return str(self.base.resolve()).lower()
        except OSError:
            return str(self.base).lower()

    def _ler_ancoras(self) -> dict:
        try:
            return read_json(self.ancoras_path)
        except OrbitDataError:
            return {}

    def _ancora(self) -> dict | None:
        a = self._ler_ancoras().get(self._chave_base(), {})
        v = a.get(self.identity.computador) if isinstance(a, dict) else None
        return v if isinstance(v, dict) else None

    def _gravar_ancora(self, linha: LinhaLog) -> None:
        dados = self._ler_ancoras()
        por_base = dados.get(self._chave_base())
        if not isinstance(por_base, dict):
            por_base = {}
        por_base[self.identity.computador] = {"n": linha.n, "codigo": linha.codigo}
        dados[self._chave_base()] = por_base
        self.ancoras_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.ancoras_path, dados)

    # ---------- trava ----------
    def _travar(self, svc: PresenceService):
        limite = time.monotonic() + ESPERA_TRAVA_S
        lock = svc.caminho_trava(self.base, NOME_TRAVA)
        while True:
            try:
                return svc.travar(self.base, NOME_TRAVA)
            except LockHeld:
                if svc.trava_abandonada(lock, MAX_IDADE_TRAVA_LOG_S):
                    svc.liberar_abandonada(lock, MAX_IDADE_TRAVA_LOG_S)
                    continue
                if time.monotonic() >= limite:
                    raise OrbitError("O log de ações está ocupado por outra pessoa; "
                                     "tente de novo em instantes.") from None
                time.sleep(_INTERVALO_S)

    # ---------- escrita / leitura ----------
    def registrar_acao(self, acao: str, detalhes: dict, _reiniciar: bool = False) -> LinhaLog:
        svc = PresenceService(self.identity, agora=self.agora, registrar=self.registrar)
        trava = self._travar(svc)
        try:
            linhas, _ = _ler_arquivo(self.caminho)
            minhas = [l for l in linhas if l.computador == self.identity.computador]
            ultima = minhas[-1] if minhas else None
            n = max((l.n for l in minhas), default=0) + 1
            linha = LinhaLog(
                seq=f"{self.identity.computador}-{n}", n=n,
                computador=self.identity.computador, usuario=self.identity.usuario,
                data_hora=self.agora().strftime(_FORMATO), acao=acao,
                detalhes=dict(detalhes),
                anterior=ZEROS if (_reiniciar or ultima is None) else ultima.codigo)
            linha.codigo = linha.calcular_codigo()
            self._acrescentar(json.dumps(linha.to_dict(), ensure_ascii=False))
        finally:
            svc.liberar_varios([trava])
        self._gravar_ancora(linha)
        return linha

    def _acrescentar(self, texto: str) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        for tentativa in range(_TENTATIVAS):
            try:
                with open(self.caminho, "a", encoding="utf-8", newline="\n") as f:
                    f.write(texto + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                return
            except PermissionError as e:
                if tentativa == _TENTATIVAS - 1:
                    raise OrbitError(f"Não foi possível gravar no log de ações: {e}") from e
                time.sleep(0.1)
            except OSError as e:
                raise OrbitError(f"Não foi possível gravar no log de ações: {e}") from e

    def ler(self) -> list[LinhaLog]:
        return _ler_arquivo(self.caminho)[0]

    def _todos_problemas(self) -> tuple[list[LinhaLog], list[ProblemaLog]]:
        linhas, ilegiveis = _ler_arquivo(self.caminho)
        ancora = self._ancora()
        problemas = verificar_linhas(
            linhas, ilegiveis,
            (self.identity.computador, ancora) if ancora is not None else None)
        return linhas, problemas

    def verificar(self) -> RelatorioLog:
        linhas, problemas = self._todos_problemas()
        ja = _alertados(linhas)
        novos = [p for p in problemas if (p.computador, p.a_partir_de_n) not in ja]
        return RelatorioLog(not novos, novos)

    def alertar_se_adulterado(self) -> RelatorioLog:
        rel = self.verificar()
        for p in rel.problemas:
            self.registrar_acao(ACAO_ADULTERACAO, {
                "computador": p.computador, "a_partir_de_n": p.a_partir_de_n,
                "descricao": p.descricao}, _reiniciar=True)
        return rel
