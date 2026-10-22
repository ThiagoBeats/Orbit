"""Classe exposta ao JavaScript (js_api do pywebview).

O pywebview expõe ao JS todo atributo/método público deste objeto. Por isso,
todo o estado interno fica em atributos com "_" na frente.

Convenção: todo método público devolve {"ok": True, "dados": ...} ou
{"ok": False, "erro": "..."}; ver _chamar().
"""
import os
import threading
import traceback
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from orbit.core.config import (TEMAS, load_shared_config, load_user_settings,
                               save_user_settings)
from orbit.core.errors import OrbitError
from orbit.core.identity import current_identity
from orbit.core.models import Contato, Revisao
from orbit.core.reconcile import find_untracked
from orbit.core.repository import Repository
from orbit.core.revisions import PASTA_ANTIGOS, RevisionService
from orbit.ui.fileserver import FileServer

_DIALOGO_ARQUIVO = 10  # webview.FileDialog.OPEN (pywebview 6.x)
_DIALOGO_PASTA = 20  # webview.FileDialog.FOLDER (pywebview 6.x)

VISUALIZAVEIS = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para a busca."""
    sem = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem if not unicodedata.combining(c)).casefold()


def _contatos(lista) -> list[Contato]:
    out = []
    for c in lista or []:
        nome = str(c.get("nome", "")).strip()
        email = str(c.get("email", "")).strip()
        if nome or email:
            out.append(Contato(nome, email))
    return out


SITUACOES = ("ativo", "concluido")


def _validar_situacao(valor) -> str:
    if valor not in SITUACOES:
        raise OrbitError(f"Situação inválida: {valor}")
    return valor


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
        self._repo: Repository | None = None
        self._fileserver: FileServer | None = None
        self._erro_base: str | None = None
        # métodos da Api rodam em threads paralelas: uma escrita por vez
        self._trava_escrita = threading.RLock()
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
        repo = Repository(base, current_identity(), config)
        self._base, self._config, self._fileserver = base, config, fileserver
        self._repo = repo
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

    # --- clientes e projetos ---------------------------------------------

    def _exigir_repo(self) -> Repository:
        self._exigir_base()
        return self._repo

    def listar_clientes(self, busca: str = "") -> dict:
        return self._chamar(self._listar_clientes, busca)

    def _listar_clientes(self, busca):
        repo = self._exigir_repo()
        termo = _normalizar(str(busca or "").strip())
        out = []
        for c in repo.list_clientes():
            projetos = repo.list_projetos(c.id)
            if termo and termo not in _normalizar(c.nome) and not any(
                    termo in _normalizar(p.nome) for p in projetos):
                continue
            datas = [p.ultima_emissao for p in projetos if p.ultima_emissao]
            out.append({
                "id": c.id, "nome": c.nome,
                "projetos_ativos": sum(1 for p in projetos
                                       if not p.erro and p.situacao == "ativo"),
                "ultima_emissao": max(datas) if datas else None,
            })
        return out

    def criar_cliente(self, dados) -> dict:
        return self._chamar(self._criar_cliente, dados)

    def _criar_cliente(self, dados):
        repo = self._exigir_repo()
        c = repo.create_cliente(str(dados.get("nome", "")), str(dados.get("cnpj", "")),
                                _contatos(dados.get("contatos")))
        return c.to_dict()

    def atualizar_cliente(self, id, dados) -> dict:
        return self._chamar(self._atualizar_cliente, id, dados)

    def _atualizar_cliente(self, id, dados):
        repo = self._exigir_repo()
        c = repo.get_cliente(id)
        if "nome" in dados:
            c.nome = str(dados["nome"]).strip()
        if "cnpj" in dados:
            c.cnpj = str(dados["cnpj"]).strip()
        if "contatos" in dados:
            c.contatos = _contatos(dados["contatos"])
        repo.update_cliente(c)
        return c.to_dict()

    def obter_cliente(self, id) -> dict:
        return self._chamar(self._obter_cliente, id)

    def _obter_cliente(self, id):
        repo = self._exigir_repo()
        return {"cliente": repo.get_cliente(id).to_dict(),
                "projetos": [asdict(p) for p in repo.list_projetos(id)]}

    def criar_projeto(self, cliente_id, dados) -> dict:
        return self._chamar(self._criar_projeto, cliente_id, dados)

    def _criar_projeto(self, cliente_id, dados):
        repo = self._exigir_repo()
        situacao = _validar_situacao(dados.get("situacao") or "ativo")
        c = repo.create_projeto(cliente_id, str(dados.get("codigo", "")),
                                str(dados.get("nome", "")), str(dados.get("pedido", "")),
                                str(dados.get("responsavel", "")),
                                _contatos(dados.get("contatos")))
        if situacao != c.situacao:
            c = repo.update_dados(c.id, situacao=situacao)
        return {"id": c.id, "nome": c.nome, "codigo": c.codigo, "situacao": c.situacao}

    def atualizar_projeto(self, id, dados) -> dict:
        return self._chamar(self._atualizar_projeto, id, dados)

    def _atualizar_projeto(self, id, dados):
        repo = self._exigir_repo()
        campos = {k: str(dados[k]).strip()
                  for k in ("codigo", "nome", "pedido", "responsavel") if k in dados}
        for k in ("codigo", "nome"):
            if k in campos and not campos[k]:
                raise OrbitError("Informe o código e o nome do projeto.")
        if "situacao" in dados:
            campos["situacao"] = _validar_situacao(dados["situacao"])
        if "contatos" in dados:
            campos["contatos"] = _contatos(dados["contatos"])
        repo.update_dados(id, **campos)
        return None

    # --- painel do projeto/máquina -------------------------------------------

    def _revisoes(self) -> RevisionService:
        return RevisionService(self._exigir_repo())

    def obter_painel(self, container_id) -> dict:
        return self._chamar(self._obter_painel, container_id)

    def _obter_painel(self, container_id):
        repo = self._exigir_repo()
        c = repo.load_container(container_id)
        cliente = repo.cliente_de(c)
        nomes = {t.id: t.nome for t in repo.config.tipos}
        ordem = {t.id: i for i, t in enumerate(repo.config.tipos)}
        docs = sorted(c.documentos.values(),
                      key=lambda d: (ordem.get(d.tipo_id, len(ordem)), d.tipo_id))
        documentos = []
        for d in docs:
            atual = d.atual
            documentos.append({
                "tipo_id": d.tipo_id,
                "nome": nomes.get(d.tipo_id, d.tipo_id),
                "nao_se_aplica": d.nao_se_aplica,
                "atual": _rev_dict(atual) if atual else None,
                "revisoes": [_rev_dict(r) for r in
                             sorted(d.revisoes, key=lambda r: r.numero, reverse=True)],
            })
        aplic = [d for d in documentos if not d["nao_se_aplica"]]
        atuais = [(d, d["atual"]) for d in documentos if d["atual"]]
        ultimo = max(atuais, key=lambda x: (x[1]["data"], x[1]["numero"]), default=None)
        datas = [r.data for d in c.documentos.values() for r in d.revisoes]
        datas += [e.data_hora[:10] for e in c.historico]
        try:
            nao_registrados = len(find_untracked(repo, c))
        except OSError:
            nao_registrados = 0  # pasta inacessível: o painel abre mesmo assim
        dados = c.to_dict()
        dados.pop("documentos")
        dados.pop("historico")
        return {
            "container": dados,
            "cliente_nome": cliente.nome if cliente else None,
            "resumo": {
                "emitidos": sum(1 for d in aplic if d["atual"]),
                "aplicaveis": len(aplic),
                "ultima_atualizacao": max(datas) if datas else None,
                "ultimo_emitido": {"tipo_id": ultimo[0]["tipo_id"], "nome": ultimo[0]["nome"],
                                   "numero": ultimo[1]["numero"], "data": ultimo[1]["data"]}
                if ultimo else None,
            },
            "documentos": documentos,
            "nao_registrados": nao_registrados,
        }

    def obter_historico(self, container_id) -> dict:
        return self._chamar(self._obter_historico, container_id)

    def _obter_historico(self, container_id):
        c = self._exigir_repo().load_container(container_id)
        # a lista do JSON é cronológica (append); inverter mantém a ordem no mesmo segundo
        return [e.to_dict() for e in reversed(c.historico)]

    def _arquivo_da_revisao(self, container_id, tipo_id, numero, nome) -> Path:
        """Arquivo que pertence à revisão (o caminho nunca é montado com texto do JS)."""
        repo = self._exigir_repo()
        c = repo.load_container(container_id)
        doc = c.documentos.get(tipo_id)
        if doc is None:
            raise OrbitError(f"Tipo de documento não encontrado: {tipo_id}")
        n = _numero_revisao(numero)
        rev = next((r for r in doc.revisoes if r.numero == n), None)
        if rev is None:
            raise OrbitError(f"Revisão Rev{n:02d} não encontrada.")
        arq = next((a for a in rev.arquivos if a.nome == nome), None)
        if arq is None:
            raise OrbitError("O arquivo não pertence a esta revisão.")
        pasta = repo.doc_path(c, tipo_id)
        # a reconciliação pode marcar como arquivada sem mover: procura nos dois lugares
        locais = [pasta / PASTA_ANTIGOS, pasta] if rev.arquivada else [pasta, pasta / PASTA_ANTIGOS]
        for p in locais:
            alvo = p / arq.nome
            if alvo.is_file():
                return alvo
        raise OrbitError(f"O arquivo \"{arq.nome}\" não foi encontrado na pasta "
                         f"\"{doc.pasta}\" (pode ter sido movido ou apagado).")

    def url_arquivo(self, container_id, tipo_id, numero, nome) -> dict:
        return self._chamar(self._url_arquivo, container_id, tipo_id, numero, nome)

    def _url_arquivo(self, container_id, tipo_id, numero, nome):
        alvo = self._arquivo_da_revisao(container_id, tipo_id, numero, nome)
        st = alvo.stat()
        return {
            "url": self._fileserver.url_para(alvo),
            "visualizavel": alvo.suffix.lower() in VISUALIZAVEIS,
            "nome": alvo.name,
            "tamanho": st.st_size,
            "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def abrir_no_programa(self, container_id, tipo_id, numero, nome) -> dict:
        return self._chamar(self._abrir_no_programa, container_id, tipo_id, numero, nome)

    def _abrir_no_programa(self, container_id, tipo_id, numero, nome):
        _abrir_no_windows(self._arquivo_da_revisao(container_id, tipo_id, numero, nome))
        return None

    def abrir_pasta(self, container_id, tipo_id) -> dict:
        return self._chamar(self._abrir_pasta, container_id, tipo_id)

    def _abrir_pasta(self, container_id, tipo_id):
        repo = self._exigir_repo()
        pasta = repo.doc_path(repo.load_container(container_id), tipo_id)
        if not pasta.is_dir():
            raise OrbitError(f"A pasta não foi encontrada: {pasta}")
        _abrir_no_windows(pasta)
        return None

    def escolher_arquivos(self, multiplos=False) -> dict:
        return self._chamar(self._escolher_arquivos, multiplos)

    def _escolher_arquivos(self, multiplos):
        if self._janela is None:
            raise OrbitError("A janela ainda não está pronta.")
        escolha = self._janela.create_file_dialog(_DIALOGO_ARQUIVO,
                                                  allow_multiple=bool(multiplos))
        if not escolha:
            return []
        return [escolha] if isinstance(escolha, str) else [str(x) for x in escolha]

    def preview_upload(self, container_id, tipo_id, principal, editaveis, numero=None) -> dict:
        return self._chamar(self._preview_upload, container_id, tipo_id, principal,
                            editaveis, numero)

    def _preview_upload(self, container_id, tipo_id, principal, editaveis, numero):
        p, eds = _arquivos_upload(principal, editaveis)
        prev = self._revisoes().preview(container_id, tipo_id, p, eds,
                                        _numero_revisao(numero, opcional=True))
        return {"numero": prev.numero, "nome_principal": prev.nome_principal,
                "nomes_editaveis": prev.nomes_editaveis}

    def enviar_revisao(self, container_id, tipo_id, principal, editaveis, status, motivo,
                       numero=None) -> dict:
        return self._chamar(self._enviar_revisao, container_id, tipo_id, principal,
                            editaveis, status, motivo, numero)

    def _enviar_revisao(self, container_id, tipo_id, principal, editaveis, status, motivo,
                        numero):
        p, eds = _arquivos_upload(principal, editaveis)
        n = _numero_revisao(numero, opcional=True)
        with self._trava_escrita:
            rev = self._revisoes().enviar_revisao(container_id, tipo_id, p, eds, str(status),
                                                  str(motivo or "").strip(), n)
        return _rev_dict(rev)

    def alterar_status(self, container_id, tipo_id, status) -> dict:
        return self._chamar(self._alterar_status, container_id, tipo_id, status)

    def _alterar_status(self, container_id, tipo_id, status):
        with self._trava_escrita:
            return _rev_dict(self._revisoes().alterar_status(container_id, tipo_id, status))

    def definir_nao_se_aplica(self, container_id, tipo_id, valor) -> dict:
        return self._chamar(self._definir_nao_se_aplica, container_id, tipo_id, valor)

    def _definir_nao_se_aplica(self, container_id, tipo_id, valor):
        with self._trava_escrita:
            self._revisoes().definir_nao_se_aplica(container_id, tipo_id, bool(valor))
        return None


def _abrir_no_windows(caminho: Path) -> None:
    try:
        os.startfile(str(caminho))
    except OSError as e:
        raise OrbitError(f"Não foi possível abrir \"{caminho.name}\": {e}")


def _numero_revisao(valor, opcional: bool = False) -> int | None:
    """Número de revisão vindo do JS (número ou texto). Vazio = sugestão automática."""
    if opcional and (valor is None or (isinstance(valor, str) and not valor.strip())):
        return None
    try:
        if isinstance(valor, bool) or isinstance(valor, float) and not valor.is_integer():
            raise ValueError
        n = int(valor.strip()) if isinstance(valor, str) else int(valor)
    except (TypeError, ValueError, AttributeError):
        raise OrbitError(f"Número de revisão inválido: {valor}")
    if not 0 <= n <= 99:
        raise OrbitError("O número da revisão deve ficar entre 00 e 99.")
    return n


def _arquivos_upload(principal, editaveis) -> tuple[Path, list[Path]]:
    if not isinstance(principal, str) or not principal.strip():
        raise OrbitError("Escolha o arquivo principal.")
    eds = [Path(e) for e in (editaveis or []) if isinstance(e, str) and e.strip()]
    return Path(principal), eds


def _rev_dict(r: Revisao) -> dict:
    principal = next((a.nome for a in r.arquivos if a.papel == "principal"), None)
    return {
        "numero": r.numero, "data": r.data, "status": r.status, "motivo": r.motivo,
        "usuario": r.usuario, "computador": r.computador, "arquivada": r.arquivada,
        "principal": principal,
        "editaveis": [a.nome for a in r.arquivos if a.papel == "editavel"],
    }
