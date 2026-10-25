from datetime import datetime, timedelta

import pytest

from orbit.core.config import load_shared_config
from orbit.core.identity import Identity
from orbit.core.repository import Repository

EU = Identity("thiago", "PC1")


class Relogio:
    def __init__(self, t=datetime(2026, 10, 24, 8, 0, 0)):
        self.t = t

    def __call__(self):
        return self.t

    def avancar(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def prod(tmp_path, relogio):
    from orbit.core.producao.modelo import ProducaoService
    base = tmp_path / "base"
    base.mkdir()
    repo = Repository(base, EU, load_shared_config(base), agora=relogio)
    cli = repo.create_cliente("Cliente X")
    p = repo.create_projeto(cli.id, "001", "Envasadora")
    return ProducaoService(repo, EU, agora=relogio), repo, p
