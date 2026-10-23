import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from orbit.core.errors import OrbitError, OrbitDataError
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.naming import sanitize

VERSAO_FORMATO = 1
TEMAS = ("escuro", "claro")


@dataclass
class TipoDocumento:
    id: str
    nome: str
    pasta: str
    ativo: bool = True

    def to_dict(self) -> dict:
        return {"id": self.id, "nome": self.nome, "pasta": self.pasta, "ativo": self.ativo}

    @classmethod
    def from_dict(cls, d: dict) -> "TipoDocumento":
        return cls(d["id"], d["nome"], d.get("pasta", d["nome"]), d.get("ativo", True))


_DEFAULT_NOMES = [
    ("diagrama_eletrico", "Diagrama Elétrico"),
    ("topologia_rede", "Topologia de Rede"),
    ("memorial_descritivo", "Memorial Descritivo"),
    ("layout_painel", "Layout de Painel"),
    ("planilha_cargas", "Planilha de Cargas"),
    ("consumo_pneumatico", "Consumo Pneumático"),
    ("manual_operacao", "Manual de Operação"),
    ("descritivo_funcional", "Descritivo Funcional"),
    ("lista_tags", "Lista de Tags"),
]

DEFAULT_TIPOS = [TipoDocumento(i, n, n) for i, n in _DEFAULT_NOMES]

DEFAULT_STATUS = ["Em elaboração", "Para aprovação", "Aprovado",
                  "Liberado para fabricação", "As Built"]


@dataclass
class SharedConfig:
    tipos: list[TipoDocumento]
    status: list[str]
    logo_empresa: str | None = None
    versao_formato: int = VERSAO_FORMATO

    def tipos_ativos(self) -> list[TipoDocumento]:
        return [t for t in self.tipos if t.ativo]

    def tipo(self, id: str) -> TipoDocumento:
        for t in self.tipos:
            if t.id == id:
                return t
        raise OrbitError(f"Tipo de documento não encontrado: {id}")

    def to_dict(self) -> dict:
        return {
            "versao_formato": self.versao_formato,
            "tipos": [t.to_dict() for t in self.tipos],
            "status": list(self.status),
            "logo_empresa": self.logo_empresa,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SharedConfig":
        return cls(
            [TipoDocumento.from_dict(t) for t in d["tipos"]],
            list(d["status"]),
            d.get("logo_empresa"),
            d.get("versao_formato", VERSAO_FORMATO),
        )

    @classmethod
    def default(cls) -> "SharedConfig":
        return cls([TipoDocumento(t.id, t.nome, t.pasta, t.ativo) for t in DEFAULT_TIPOS],
                   list(DEFAULT_STATUS))


def _config_path(base: Path) -> Path:
    return Path(base) / ".orbit" / "config.json"


def save_shared_config(base: Path, cfg: SharedConfig) -> None:
    path = _config_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, cfg.to_dict())


def load_shared_config(base: Path) -> SharedConfig:
    path = _config_path(base)
    if not path.exists():
        cfg = SharedConfig.default()
        save_shared_config(base, cfg)
        return cfg
    data = read_json(path)
    try:
        return SharedConfig.from_dict(data)
    except (KeyError, TypeError) as e:
        raise OrbitDataError(f"Configuração inválida ({path.name}): campo ausente ou incorreto: {e}")


def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", sanitize(nome).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def add_tipo(cfg: SharedConfig, nome: str) -> TipoDocumento:
    nome = sanitize(nome)
    tid = _slug(nome)
    if not tid:
        raise OrbitError("Informe um nome válido para o tipo de documento.")
    if any(t.id == tid for t in cfg.tipos):
        raise OrbitError(f"Já existe um tipo de documento com o nome \"{nome}\".")
    tipo = TipoDocumento(tid, nome, nome)
    cfg.tipos.append(tipo)
    return tipo


INTERVALO_BACKUP_PADRAO = 10
INTERVALO_BACKUP_MIN, INTERVALO_BACKUP_MAX = 1, 1440


def limitar_intervalo(valor) -> int:
    """Intervalo de verificação do backup em minutos, entre 1 e 1440."""
    if isinstance(valor, bool):
        return INTERVALO_BACKUP_PADRAO
    try:
        v = int(valor)
    except (TypeError, ValueError):
        return INTERVALO_BACKUP_PADRAO
    return max(INTERVALO_BACKUP_MIN, min(INTERVALO_BACKUP_MAX, v))


@dataclass
class UserSettings:
    pasta_base: str | None = None
    tema: str = "escuro"
    backup: str | None = None  # pasta de backup desta máquina (spec de backup §4)
    intervalo_backup_min: int = INTERVALO_BACKUP_PADRAO

    def to_dict(self) -> dict:
        return {"versao_formato": VERSAO_FORMATO, "pasta_base": self.pasta_base,
                "tema": self.tema, "backup": self.backup,
                "intervalo_backup_min": self.intervalo_backup_min}

    @classmethod
    def from_dict(cls, d: dict) -> "UserSettings":
        tema = d.get("tema", "escuro")
        backup = d.get("backup")
        return cls(d.get("pasta_base"), tema if tema in TEMAS else "escuro",
                   backup if isinstance(backup, str) and backup else None,
                   limitar_intervalo(d.get("intervalo_backup_min", INTERVALO_BACKUP_PADRAO)))


def user_settings_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Orbit" / "settings.json"


def load_user_settings(path: Path | None = None) -> UserSettings:
    path = Path(path) if path else user_settings_path()
    if not path.exists():
        return UserSettings()
    try:
        return UserSettings.from_dict(read_json(path))
    except OrbitDataError:
        return UserSettings()  # preferências corrompidas não devem impedir o programa de abrir


def save_user_settings(s: UserSettings, path: Path | None = None) -> None:
    path = Path(path) if path else user_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, s.to_dict())
