from datetime import date
from pathlib import Path
from orbit.core.naming import *

def test_sanitize_troca_proibidos_e_mantem_acentos():
    assert sanitize('A/B Automação: "Ltda"') == "A-B Automação- -Ltda-"
    assert sanitize("  Nome   com  espaços. ") == "Nome com espaços"

def test_data_e_rev():
    assert format_data(date(2026, 10, 22)) == "221026"
    assert format_rev(2) == "Rev02"

def test_base_name_projeto_e_maquina():
    assert build_base_name("Diagrama Elétrico", ["Cliente X", "Envasadora Linha 2"], date(2026,10,20), 2) \
        == "Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 201026 - Rev02"
    assert build_base_name("Diagrama Elétrico", ["Esteira Compacta EC-200"], date(2026,9,14), 4) \
        == "Diagrama Elétrico - Esteira Compacta EC-200 - 140926 - Rev04"

def test_nomes_editaveis():
    b = "Topologia de Rede - C - P - 221026 - Rev01"
    assert build_file_names(b, ".pdf", [".drawio"]) == (b + ".pdf", [b + ".drawio"])
    assert build_file_names(b, ".xlsx", [".xlsx"]) == (b + ".xlsx", [b + " - Editavel.xlsx"])
    assert build_file_names(b, ".pdf", [".dwg", ".dwg"]) == \
        (b + ".pdf", [b + " - Editavel.dwg", b + " - Editavel 2.dwg"])

def test_parse_rev():
    assert parse_rev("Diagrama Elétrico - C - P - 201026 - Rev02.pdf") == 2
    assert parse_rev("Diagrama Elétrico - C - P - 201026 - Rev02 - Editavel 2.DWG") == 2
    assert parse_rev("ABCDE.pdf") is None

def test_fit_base_name_respeita_240(tmp_path):
    base = build_base_name("Diagrama Elétrico", ["Cliente", "P" * 300], date(2026,10,22), 0)
    curto = fit_base_name(tmp_path, base, " - Editavel 2.drawio")
    assert len(str(tmp_path / (curto + " - Editavel 2.drawio"))) <= 240
    assert curto.endswith(" - 221026 - Rev00")

def test_sanitize_barra_invertida():
    assert sanitize("a\\b") == "a-b"
