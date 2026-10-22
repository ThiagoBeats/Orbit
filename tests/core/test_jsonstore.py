"""Gravação atômica com retentativas e erros em português (I4)."""
import json
import os

import pytest

from orbit.core import jsonstore
from orbit.core.errors import OrbitError
from orbit.core.jsonstore import write_json_atomic


def _replace_falhando(monkeypatch, vezes):
    real = os.replace
    chamadas = []

    def falso(a, b):
        chamadas.append((a, b))
        if len(chamadas) <= vezes:
            raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
        return real(a, b)
    monkeypatch.setattr(jsonstore.os, "replace", falso)
    monkeypatch.setattr(jsonstore, "_ESPERA_S", 0)
    return chamadas


def test_replace_tenta_de_novo_quando_arquivo_em_uso(tmp_path, monkeypatch):
    chamadas = _replace_falhando(monkeypatch, 2)
    p = tmp_path / "projeto.json"
    write_json_atomic(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert len(chamadas) == 3
    assert [f.name for f in tmp_path.iterdir()] == ["projeto.json"]


def test_replace_falha_sempre_vira_orbit_error(tmp_path, monkeypatch):
    _replace_falhando(monkeypatch, 99)
    p = tmp_path / "projeto.json"
    p.write_text('{"antigo": true}', encoding="utf-8")
    with pytest.raises(OrbitError, match="projeto.json") as e:
        write_json_atomic(p, {"a": 1})
    assert "em uso" in str(e.value)
    assert json.loads(p.read_text(encoding="utf-8")) == {"antigo": True}
    assert [f.name for f in tmp_path.iterdir()] == ["projeto.json"]  # temporário removido


def test_pasta_inexistente_vira_orbit_error(tmp_path):
    with pytest.raises(OrbitError, match="Não foi possível gravar"):
        write_json_atomic(tmp_path / "nao" / "x.json", {})
