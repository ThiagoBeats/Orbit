from datetime import datetime

import pytest

from orbit.core.config import load_shared_config
from orbit.core.identity import Identity
from orbit.core.repository import Repository


@pytest.fixture
def repo(tmp_path):
    return Repository(tmp_path, Identity("thiago", "PC1"), load_shared_config(tmp_path),
                      agora=lambda: datetime(2026, 10, 22, 14, 32))
