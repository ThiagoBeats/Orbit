"""Cria a janela do Orbit (pywebview 6.x, WebView2)."""
import json
import sys
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from orbit.ui.api import Api



def pasta_web() -> Path:
    """Pasta `web/`: dentro do pacote do PyInstaller quando congelado, senão ao lado do módulo."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "orbit" / "ui" / "web"
    return Path(__file__).resolve().parent / "web"


WEB = pasta_web()
ICONE = WEB / "img" / "orbit-icon.ico"


def caminhos_do_drop(evento) -> list[str]:
    """Caminhos completos dos arquivos soltos (só existem via evento DOM do Python)."""
    dt = (evento or {}).get("dataTransfer") or {}
    return [f["pywebviewFullPath"] for f in dt.get("files") or []
            if isinstance(f, dict) and f.get("pywebviewFullPath")]


def _ligar_arrastar_e_soltar(janela) -> None:
    """Registra o drop no documento. O JS sabe sobre qual cartão foi o drop.

    Só o drop passa pelo Python (o dragover com preventDefault fica no JS, para
    não mandar uma mensagem ao Python a cada movimento do mouse).
    """
    def ao_soltar(evento):
        caminhos = caminhos_do_drop(evento)
        janela.evaluate_js(f"window.orbitDrop && window.orbitDrop({json.dumps(caminhos)})")

    janela.dom.document.events.drop += DOMEventHandler(ao_soltar, prevent_default=True)


def run() -> None:
    api = Api()
    # Caminho absoluto: o pywebview resolve caminhos relativos a partir da pasta
    # do script (sys.argv[0]) e serve a pasta "web" num servidor HTTP próprio.
    janela = webview.create_window(
        "Orbit",
        str(WEB / "index.html"),
        js_api=api,
        width=1400,
        height=900,
        min_size=(1100, 700),
        background_color="#1b2129",
    )
    api.definir_janela(janela)
    # "loaded" roda numa thread própria a cada carga da página (os handlers DOM se perdem)
    janela.events.loaded += lambda: _ligar_arrastar_e_soltar(janela)
    # apaga a presença ao fechar (síncrono; o JS já pode não responder nessa hora).
    # O handler devolve None: devolver False cancelaria o fechamento.
    janela.events.closing += lambda: api.ao_fechar_janela()
    webview.start(gui="edgechromium", icon=str(ICONE))
