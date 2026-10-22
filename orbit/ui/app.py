"""Cria a janela do Orbit (pywebview 6.x, WebView2)."""
from pathlib import Path

import webview

from orbit.ui.api import Api

WEB = Path(__file__).resolve().parent / "web"


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
    webview.start(gui="edgechromium")
