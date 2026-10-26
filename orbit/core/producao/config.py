"""Configuração da produção em `<base>/.orbit/producao.json` (spec Produção §4/§5).

Guarda também o próximo número de OP. Leitura tolerante: campos ausentes
recebem os padrões; arquivo ilegível vira OrbitDataError (nunca é regravado).
"""
from __future__ import annotations

import copy
from pathlib import Path

from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.jsonstore import read_json, write_json_atomic

MOTIVOS_PARADA = ["Falta de material", "Aguardando projeto/informação", "Aguardando cliente",
                  "Retrabalho", "Manutenção/ferramenta", "Outro"]
TIPOS_NC = ["Fio/ligação trocada", "Aperto/borne solto", "Identificação", "Componente divergente",
            "Dano/montagem mecânica", "Isolação", "Função/lógica", "Documentação", "Outro"]
# IEC 61439-1 §11 — verificação de rotina
CHECKLIST_IEC = [
    {"ref": "11.2", "texto": "Grau de proteção e vedações (IP) conforme projeto"},
    {"ref": "11.3", "texto": "Distâncias de isolação e de escoamento"},
    {"ref": "11.4", "texto": "Continuidade do condutor de proteção (PE) e aterramento das portas"},
    {"ref": "11.5", "texto": "Componentes instalados conforme projeto (modelo, corrente, curva)"},
    {"ref": "11.6", "texto": "Fiação interna conforme diagrama"},
    {"ref": "11.6", "texto": "Aperto das conexões de potência e comando conferido e marcado"},
    {"ref": "11.6", "texto": "Identificação de fios, bornes e componentes"},
    {"ref": "11.7", "texto": "Terminais para condutores externos (cabos de campo)"},
    {"ref": "11.8", "texto": "Operação mecânica: portas, fechaduras, intertravamentos, manoplas"},
    {"ref": "11.10", "texto": "Documentação no painel (diagrama na porta, placa de identificação)"},
    {"ref": "—", "texto": "Limpeza interna (sem cavacos, sobras de fio ou ferramentas)"},
]
PASSOS_ENERGIZACAO = [
    "Proteções gerais abertas e teste de isolação concluído",
    "Conferir tensão de alimentação na entrada antes de fechar o disjuntor geral",
    "Fechar o disjuntor geral e conferir tensões nos barramentos",
    "Energizar circuitos de comando um a um, conferindo as fontes 24 Vcc",
    "Conferir sinalizações, botões de emergência e intertravamentos",
]

PADRAO = {
    "versao_formato": 1,
    "proximo_numero": 1,
    "operadores": [],
    "motivos_parada": MOTIVOS_PARADA,
    "tipos_nc": TIPOS_NC,
    "checklist_iec": CHECKLIST_IEC,
    "passos_energizacao": PASSOS_ENERGIZACAO,
    "isolacao_min_mohm": 1.0,
    "isolacao_tensao_v": 500,
    "tolerancia_tensao_pct": 10,
    "amostragem_pct": 10,
    "amostragem_min": 10,
}


def caminho_config(base: Path) -> Path:
    return Path(base) / ".orbit" / "producao.json"


def carregar_config(base: Path) -> dict:
    arq = caminho_config(base)
    dados = read_json(arq) if arq.exists() else {}
    if not isinstance(dados, dict):
        raise OrbitDataError("Configuração da produção inválida.")
    cfg = copy.deepcopy(PADRAO)
    cfg.update({k: v for k, v in dados.items() if k in PADRAO})
    return cfg


def salvar_config(base: Path, cfg: dict) -> None:
    arq = caminho_config(base)
    arq.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(arq, {k: cfg.get(k, PADRAO[k]) for k in PADRAO})


def _lista_textos(v, rotulo: str, minimo: int = 1) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise OrbitError(f"Lista inválida: {rotulo}.")
    out, vistos = [], set()
    for x in v:
        x = x.strip()
        if x and x.casefold() not in vistos:
            vistos.add(x.casefold())
            out.append(x)
    if len(out) < minimo:
        raise OrbitError(f"Informe ao menos um item em {rotulo}.")
    return out


def _numero(v, rotulo: str, minimo: float, maximo: float, inteiro: bool = False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not minimo <= v <= maximo:
        raise OrbitError(f"Valor inválido: {rotulo}.")
    return int(v) if inteiro else v


def validar_config(dados: dict) -> dict:
    """Campos editáveis em Configurações → Produção (o número da próxima OP não muda aqui)."""
    if not isinstance(dados, dict):
        raise OrbitError("Configuração inválida.")
    out = {}
    if "operadores" in dados:
        ops, vistos = [], set()
        for o in dados["operadores"] if isinstance(dados["operadores"], list) else [None]:
            if not isinstance(o, dict) or not isinstance(o.get("nome"), str):
                raise OrbitError("Lista de operadores inválida.")
            nome = o["nome"].strip()
            if nome and nome.casefold() not in vistos:
                vistos.add(nome.casefold())
                ops.append({"nome": nome, "verifica": bool(o.get("verifica"))})
        out["operadores"] = ops
    if "motivos_parada" in dados:
        out["motivos_parada"] = _lista_textos(dados["motivos_parada"], "motivos de parada")
    if "tipos_nc" in dados:
        out["tipos_nc"] = _lista_textos(dados["tipos_nc"], "tipos de não conformidade")
    if "passos_energizacao" in dados:
        out["passos_energizacao"] = _lista_textos(dados["passos_energizacao"],
                                                  "passos da energização")
    if "checklist_iec" in dados:
        itens = dados["checklist_iec"]
        if not isinstance(itens, list):
            raise OrbitError("Checklist inválido.")
        lista = []
        for i in itens:
            if not isinstance(i, dict) or not isinstance(i.get("texto"), str):
                raise OrbitError("Checklist inválido.")
            if i["texto"].strip():
                lista.append({"ref": str(i.get("ref") or "—").strip() or "—",
                              "texto": i["texto"].strip()})
        if not lista:
            raise OrbitError("O checklist de inspeção precisa de ao menos um item.")
        out["checklist_iec"] = lista
    if "isolacao_min_mohm" in dados:
        out["isolacao_min_mohm"] = _numero(dados["isolacao_min_mohm"], "isolação mínima",
                                           0.01, 10000)
    if "isolacao_tensao_v" in dados:
        out["isolacao_tensao_v"] = _numero(dados["isolacao_tensao_v"], "tensão de ensaio",
                                           50, 5000, True)
    if "tolerancia_tensao_pct" in dados:
        out["tolerancia_tensao_pct"] = _numero(dados["tolerancia_tensao_pct"],
                                               "tolerância de tensão", 0.5, 50)
    if "amostragem_pct" in dados:
        out["amostragem_pct"] = _numero(dados["amostragem_pct"], "percentual da amostragem",
                                        1, 100)
    if "amostragem_min" in dados:
        out["amostragem_min"] = _numero(dados["amostragem_min"], "mínimo da amostragem",
                                        1, 10000, True)
    return out
