import json
import os
import tempfile
from pathlib import Path

from orbit.core.errors import OrbitDataError


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


def write_json_atomic(path: Path, data: dict) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
