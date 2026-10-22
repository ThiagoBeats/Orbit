"""Classe exposta ao JavaScript (js_api do pywebview).

O pywebview expõe ao JS todo atributo/método público deste objeto. Por isso,
todo o estado interno fica em atributos com "_" na frente.

Convenção: todo método público devolve {"ok": True, "dados": ...} ou
{"ok": False, "erro": "..."}; ver _chamar().
"""
import os
import traceback
from datetime import datetime
from pathlib import Path

from orbit.core.config import (TEMAS, load_shared_config, load_user_settings,
                               save_user_settings)
from orbit.core.errors import OrbitError
from orbit.ui.fileserver import FileServer

_DIALOGO_PASTA = 20  # webview.FileDialog.FOLDER (pywebview 6.x)


def caminho_log_padrao() -> Path:
    return Path(os.environ["APPDATA"]) / "Orbit" / "orbit.log"


class Api:
    def __init__(self, settings_path: Path | None = None, log_path: Path | None = None):
        self._settings_path = settings_path
        self._log_path = log_path
        self._janela = None
        self._settings = load_user_settings(settings_path)
        self._base: Path | None = None
        self._config = None
        self._fileserver: FileServer | None = None
        self._erro_base: str | None = None
        if self._settings.pasta_base:
            try:
                self._abrir_base(Path(self._settings.pasta_base))
            except OrbitError as e:
                self._erro_base = str(e)
            except Exception as e:
                self._registrar_erro(e)
                self._erro_base = f"Erro inesperado: {type(e).__name__}. Veja o log."

    # --- infraestrutura -------------------------------------------------

    def definir_janela(self, janela) -> None:
        """Chamado pelo app.py depois de criar a janela (necessário para diálogos)."""
        self._janela = janela

    # O pywebview pula atributos com _serializable = False ao montar a API do JS.
    definir_janela._serializable = False

    def _chamar(self, fn, *args) -> dict:
        try:
            return {"ok": True, "dados": fn(*args)}
        except OrbitError as e:
            return {"ok": False, "erro": str(e)}
        except Exception as e:
            self._registrar_erro(e)
            return {"ok": False, "erro": f"Erro inesperado: {type(e).__name__}. Veja o log."}

    def _registrar_erro(self, e: BaseException) -> None:
        try:
            path = Path(self._log_path) if self._log_path else caminho_log_padrao()
            path.parent.mkdir(parents=True, exist_ok=True)
            texto = "".join(traceback.format_exception(e))
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {texto}\n")
        except Exception:
            pass  # o log nunca pode derrubar o programa

    def _abrir_base(self, base: Path) -> None:
        if not base.is_dir():
            raise OrbitError(f"A pasta base não foi encontrada ou está inacessível: {base}")
        config = load_shared_config(base)  # cria .orbit/config.json na primeira vez
        fileserver = FileServer(base)
        fileserver.start()  # se falhar, o estado anterior continua valendo
        antigo = self._fileserver
        self._base, self._config, self._fileserver = base, config, fileserver
        if antigo is not None:
            antigo.stop()
        self._erro_base = None

    def _exigir_base(self) -> Path:
        if self._base is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        return self._base

    def _dados_settings(self) -> dict:
        return {
            "pasta_base": self._settings.pasta_base,
            "tema": self._settings.tema,
            "base_ok": self._base is not None,
            "erro_base": self._erro_base,
        }

    # --- métodos expostos ao JS ----------------------------------------

    def get_settings(self) -> dict:
        return self._chamar(self._dados_settings)

    def escolher_pasta_base(self) -> dict:
        return self._chamar(self._escolher_pasta_base)

    def _escolher_pasta_base(self):
        if self._janela is None:
            raise OrbitError("A janela ainda não está pronta.")
        inicial = self._settings.pasta_base or ""
        escolha = self._janela.create_file_dialog(_DIALOGO_PASTA, inicial)
        if not escolha:
            return None  # cancelado
        pasta = escolha if isinstance(escolha, str) else escolha[0]
        self._abrir_base(Path(pasta))
        self._settings.pasta_base = str(pasta)
        save_user_settings(self._settings, self._settings_path)
        return self._dados_settings()

    def set_tema(self, tema) -> dict:
        return self._chamar(self._set_tema, tema)

    def _set_tema(self, tema):
        if tema not in TEMAS:
            raise OrbitError(f"Tema inválido: {tema}")
        self._settings.tema = tema
        save_user_settings(self._settings, self._settings_path)
        return self._dados_settings()

    def get_config(self) -> dict:
        return self._chamar(self._get_config)

    def _get_config(self):
        self._exigir_base()
        return self._config.to_dict()
