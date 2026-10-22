"""Api de importação e reconciliação (Tarefa 13)."""
import os

import pytest

from orbit.core.config import UserSettings, save_user_settings
from orbit.ui.api import Api

from tests.ui.test_api_painel import _arq, _enviar


@pytest.fixture
def caminhos(tmp_path):
    return tmp_path / "appdata" / "settings.json", tmp_path / "appdata" / "orbit.log"


@pytest.fixture
def painel(caminhos, tmp_path):
    base = tmp_path / "Base"
    base.mkdir()
    save_user_settings(UserSettings(str(base), "escuro"), caminhos[0])
    api = Api(settings_path=caminhos[0], log_path=caminhos[1])
    c = api.criar_cliente({"nome": "Alfa"})["dados"]
    p = api.criar_projeto(c["id"], {"codigo": "P-1", "nome": "Esteira"})["dados"]
    origem = tmp_path / "origem"
    origem.mkdir()
    yield api, base, p["id"], origem
    api._fileserver.stop()


def _item(origem, tipo="lista_tags", numero=0, status="Em elaboração", papel="principal",
          data="2024-03-05"):
    return {"origem": str(origem), "tipo_id": tipo, "numero": numero, "status": status,
            "papel": papel, "data": data}


def test_preparar_detecta_revisao_e_data(painel):
    api, _, _, origem = painel
    a = _arq(origem, "Diagrama Rev03.pdf")
    b = _arq(origem, "esquema rev 7 final.dwg")
    c = _arq(origem, "Lista de Tags - Alfa - Esteira - 010126 - Rev05.pdf")
    d = _arq(origem, "sem revisao.txt")
    os.utime(a, (1709640000, 1709640000))
    r = api.preparar_importacao([a, b, c, d])
    assert r["ok"] is True
    linhas = r["dados"]
    assert [x["rev_detectada"] for x in linhas] == [3, 7, 5, None]
    assert linhas[0]["nome"] == "Diagrama Rev03.pdf"
    assert linhas[0]["origem"] == a
    assert linhas[0]["data_mtime"] == "2024-03-05"


def test_preparar_recusa_caminho_inexistente_ou_pasta(painel, tmp_path):
    api, _, _, origem = painel
    assert api.preparar_importacao([str(origem / "nao existe.pdf")])["ok"] is False
    assert api.preparar_importacao([str(origem)])["ok"] is False
    assert api.preparar_importacao("texto")["ok"] is False
    assert api.preparar_importacao([123])["ok"] is False


def test_preparar_recusa_arquivo_dentro_de_dot_orbit(painel):
    api, base, _, _ = painel
    r = api.preparar_importacao([str(base / ".orbit" / "config.json")])
    assert r["ok"] is False and ".orbit" in r["erro"]


def test_validar_e_importar_tres_revisoes(painel):
    api, base, pid, origem = painel
    arqs = [_arq(origem, f"antigo Rev0{n}.pdf", f"c{n}") for n in (1, 2, 3)]
    itens = [_item(a, "diagrama_eletrico", n, "Aprovado") for n, a in zip((1, 2, 3), arqs)]
    assert api.validar_importacao(pid, itens)["dados"] == [None, None, None]
    r = api.importar(pid, itens)
    assert r["ok"] is True, r
    painel_d = api.obter_painel(pid)["dados"]
    d = next(x for x in painel_d["documentos"] if x["tipo_id"] == "diagrama_eletrico")
    assert d["atual"]["numero"] == 3
    assert [x["arquivada"] for x in sorted(d["revisoes"], key=lambda x: x["numero"])] == [True, True, False]
    assert all(os.path.exists(a) for a in arqs)  # originais intactos


def test_validar_numero_repetido_bloqueia_a_linha(painel):
    api, _, pid, origem = painel
    _enviar(api, pid, "lista_tags", _arq(origem, "a.pdf"), numero=2)
    itens = [_item(_arq(origem, "b.pdf"), numero=2)]
    r = api.validar_importacao(pid, itens)["dados"]
    assert r[0] and "já existe" in r[0]
    assert api.importar(pid, itens)["ok"] is False


def test_validar_erros_de_tipo_por_linha(painel):
    api, _, pid, origem = painel
    f = _arq(origem, "a.pdf")
    itens = [_item(f, numero=None), _item(f, numero=100), _item(f, numero=True),
             _item(f, papel="outro"), _item(f, data="05/03/2024"), _item(f, data=None),
             _item(origem / "nao existe.pdf"), _item(f, tipo=5), _item(f, status=3)]
    r = api.validar_importacao(pid, itens)
    assert r["ok"] is True
    erros = r["dados"]
    assert all(erros[i] for i in (0, 1, 2, 3, 4, 6, 7, 8)), erros
    assert erros[5] is None  # data nula = mtime


def test_importar_recusa_item_malformado(painel):
    api, _, pid, origem = painel
    assert api.importar(pid, "x")["ok"] is False
    assert api.importar(pid, ["x"])["ok"] is False
    assert api.importar(pid, [_item(_arq(origem, "a.pdf"), numero="abc")])["ok"] is False


def test_importar_recusa_origem_dentro_de_dot_orbit(painel):
    api, base, pid, _ = painel
    cfg = base / ".orbit" / "config.json"
    itens = [_item(cfg)]
    assert api.importar(pid, itens)["ok"] is False
    r = api.validar_importacao(pid, itens)["dados"]
    assert r[0] and ".orbit" in r[0]


def test_importar_usa_data_informada(painel):
    api, _, pid, origem = painel
    assert api.importar(pid, [_item(_arq(origem, "a.pdf"), numero=1, data="2023-01-02")])["ok"]
    d = next(x for x in api.obter_painel(pid)["dados"]["documentos"] if x["tipo_id"] == "lista_tags")
    assert d["atual"]["data"] == "2023-01-02"


def _nao_reg(base, nome="Lista de Tags - Alfa - Esteira - 010126 - Rev05.pdf"):
    pasta = base / "Clientes" / "Alfa" / "P-1 - Esteira" / "Lista de Tags"
    (pasta / nome).write_text("x")
    return nome


def test_listar_e_registrar_nao_registrados(painel):
    api, base, pid, _ = painel
    nome = _nao_reg(base)
    lista = api.listar_nao_registrados(pid)["dados"]
    assert len(lista) == 1
    assert lista[0]["nome"] == nome and lista[0]["tipo_id"] == "lista_tags"
    assert lista[0]["numero"] == 5 and lista[0]["tipo_nome"] == "Lista de Tags"
    assert "caminho" not in lista[0]
    r = api.registrar(pid, [{"tipo_id": "lista_tags", "nome": nome}], "Aprovado")
    assert r["ok"] is True, r
    assert api.listar_nao_registrados(pid)["dados"] == []
    d = next(x for x in api.obter_painel(pid)["dados"]["documentos"] if x["tipo_id"] == "lista_tags")
    assert d["atual"]["numero"] == 5 and d["atual"]["status"] == "Aprovado"


def test_registrar_nao_confia_no_caminho_do_js(painel, tmp_path):
    api, base, pid, origem = painel
    _nao_reg(base)
    fora = _arq(origem, "Lista de Tags - X - Y - 010126 - Rev09.pdf")
    # arquivo que não está na lista de não registrados: recusado
    r = api.registrar(pid, [{"tipo_id": "lista_tags", "nome": os.path.basename(fora),
                             "caminho": fora}], "Aprovado")
    assert r["ok"] is False
    # nome com separador de caminho: recusado
    r = api.registrar(pid, [{"tipo_id": "lista_tags", "nome": "../x Rev01.pdf"}], "Aprovado")
    assert r["ok"] is False
    # tipo errado para um nome existente: recusado
    r = api.registrar(pid, [{"tipo_id": "memorial_descritivo",
                             "nome": "Lista de Tags - Alfa - Esteira - 010126 - Rev05.pdf"}],
                      "Aprovado")
    assert r["ok"] is False
    assert len(api.listar_nao_registrados(pid)["dados"]) == 1  # nada registrado


def test_registrar_valida_forma(painel):
    api, base, pid, _ = painel
    nome = _nao_reg(base)
    assert api.registrar(pid, [], "Aprovado")["ok"] is False
    assert api.registrar(pid, "x", "Aprovado")["ok"] is False
    assert api.registrar(pid, [{"tipo_id": "lista_tags", "nome": nome}], "Inexistente")["ok"] is False
    assert api.registrar(pid, [{"tipo_id": 1, "nome": nome}], "Aprovado")["ok"] is False
