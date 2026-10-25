"""Configuração da produção em `<base>/.orbit/producao.json` (spec Produção §4/§5).

Guarda também o próximo número de OP. Leitura tolerante: campos ausentes
recebem os padrões; arquivo ilegível vira OrbitDataError (nunca é regravado).
"""
from __future__ import annotations

import copy
from pathlib import Path

from orbit.core.errors import OrbitDataError
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
