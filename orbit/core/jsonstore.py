import json
import os
import tempfile
import time
from pathlib import Path

from orbit.core.errors import OrbitDataError, OrbitError

# os.replace no Windows falha com PermissionError (WinError 5/32) enquanto outro
# processo (outro Orbit lendo, antivírus, OneDrive) está com o destino aberto.
_TENTATIVAS = 5
_ESPERA_S = 0.1


def read_json(path: Path) -> dict:
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise OrbitDataError(f"Arquivo de dados não encontrado: {path.name}")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise OrbitDataError(f"Arquivo de dados inválido ({path.name}): {e}")
    except OSError as e:
        raise OrbitDataError(f"Não foi possível ler {path.name}: {e}")
    if not isinstance(data, dict):
        raise OrbitDataError(f"Arquivo de dados inválido ({path.name}): esperado um objeto JSON")
    return data


def _replace_com_retentativas(tmp: str, path: Path) -> None:
    for i in range(_TENTATIVAS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == _TENTATIVAS - 1:
                raise
            time.sleep(_ESPERA_S)


def write_json_atomic(path: Path, data: dict) -> None:
    """Grava num temporário da mesma pasta e troca com os.replace.

    Falhas de disco viram OrbitError com mensagem em português; o arquivo
    anterior continua intacto e o temporário é removido.
    """
    path = Path(path)
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    except OSError as e:
        raise OrbitError(f"Não foi possível gravar {path.name} em {path.parent}: {e}") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _replace_com_retentativas(tmp, path)
    except BaseException as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(e, PermissionError):
            raise OrbitError(f"Não foi possível gravar {path.name}: o arquivo está em uso por "
                             "outro programa (outro Orbit, antivírus ou OneDrive). Nada foi "
                             "alterado; tente de novo em instantes.") from e
        if isinstance(e, OSError):
            raise OrbitError(f"Não foi possível gravar {path.name}: {e}") from e
        raise
