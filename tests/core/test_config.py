import pytest

from orbit.core.config import (
    add_tipo, load_shared_config, load_user_settings, save_shared_config,
    save_user_settings, UserSettings,
)
from orbit.core.errors import OrbitError


def test_cria_config_padrao(tmp_path):
    cfg = load_shared_config(tmp_path)
    assert (tmp_path / ".orbit" / "config.json").exists()
    assert [t.nome for t in cfg.tipos][-1] == "Lista de Tags"
    assert len(cfg.tipos) == 9
    assert cfg.status[0] == "Em elaboração"
    assert cfg.tipos[0].id == "diagrama_eletrico"
    assert all(t.pasta == t.nome for t in cfg.tipos)


def test_desativar_tipo_some_de_ativos(tmp_path):
    cfg = load_shared_config(tmp_path)
    cfg.tipo("lista_tags").ativo = False
    save_shared_config(tmp_path, cfg)
    cfg2 = load_shared_config(tmp_path)
    assert "lista_tags" not in [t.id for t in cfg2.tipos_ativos()]
    assert len(cfg2.tipos) == 9


def test_add_tipo(tmp_path):
    cfg = load_shared_config(tmp_path)
    t = add_tipo(cfg, "Lista de Cabos")
    assert t.id == "lista_de_cabos"
    assert t.pasta == "Lista de Cabos"
    assert cfg.tipo("lista_de_cabos") is t
    with pytest.raises(OrbitError):
        add_tipo(cfg, "Lista de Cabos")


def test_add_tipo_remove_acentos(tmp_path):
    cfg = load_shared_config(tmp_path)
    assert add_tipo(cfg, "Instalação Elétrica / Geral").id == "instalacao_eletrica_geral"


def test_tipo_inexistente(tmp_path):
    cfg = load_shared_config(tmp_path)
    with pytest.raises(OrbitError):
        cfg.tipo("nao_existe")


def test_user_settings_padrao_tema_escuro(tmp_path):
    p = tmp_path / "Orbit" / "settings.json"
    s = load_user_settings(p)
    assert s.tema == "escuro" and s.pasta_base is None
    save_user_settings(UserSettings(pasta_base="C:/x", tema="claro"), p)
    s2 = load_user_settings(p)
    assert s2.pasta_base == "C:/x" and s2.tema == "claro"
