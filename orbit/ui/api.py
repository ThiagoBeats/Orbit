"""Classe exposta ao JavaScript (js_api do pywebview).

O pywebview expõe ao JS todo atributo/método público deste objeto. Por isso,
todo o estado interno fica em atributos com "_" na frente.

Convenção: todo método público devolve {"ok": True, "dados": ...} ou
{"ok": False, "erro": "..."}; ver _chamar().
"""
import os
import re
import shutil
import threading
import traceback
import unicodedata
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from orbit.core.config import (TEMAS, add_tipo, load_shared_config, load_user_settings,
                               save_shared_config, save_user_settings)
from orbit.core.connection import pasta_existe, testar_pasta
from orbit.core.email import EmailDraft, EmailService, SelecaoEnvio
from orbit.core.errors import LockHeld, OrbitDataError, OrbitError
from orbit.core.identity import current_identity
from orbit.core.models import Contato, Revisao
from orbit.core.outlook import OutlookClient
from orbit.core.importer import PAPEIS, ImportService, ItemImportacao
from orbit.core.naming import parse_rev, sanitize
from orbit.core.presence import PresenceService
from orbit.core.reconcile import find_untracked, register_untracked
from orbit.core.repository import Repository
from orbit.core.revisions import PASTA_ANTIGOS, RevisionService
from orbit.ui.fileserver import FileServer

_DIALOGO_ARQUIVO = 10  # webview.FileDialog.OPEN (pywebview 6.x)
_DIALOGO_PASTA = 20  # webview.FileDialog.FOLDER (pywebview 6.x)

EXT_LOGO = (".png", ".jpg", ".jpeg", ".svg", ".webp")
TAMANHO_MAX_LOGO = 5 * 1024 * 1024
PREFIXO_LOGO = "logo-empresa"

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


_REV_SOLTO = re.compile(r"REV\s*(\d+)", re.IGNORECASE)

SITUACOES = ("ativo", "concluido")


def _validar_situacao(valor) -> str:
    if valor not in SITUACOES:
        raise OrbitError(f"Situação inválida: {valor}")
    return valor


def caminho_log_padrao() -> Path:
    return Path(os.environ["APPDATA"]) / "Orbit" / "orbit.log"


class Api:
    def __init__(self, settings_path: Path | None = None, log_path: Path | None = None,
                 outlook=None, timeout_conexao: float = 5.0):
        self._timeout_conexao = timeout_conexao
        self._outlook = outlook if outlook is not None else OutlookClient()
        self._settings_path = settings_path
        self._log_path = log_path
        self._janela = None
        self._settings = load_user_settings(settings_path)
        self._base: Path | None = None
        self._config = None
        self._repo: Repository | None = None
        self._fileserver: FileServer | None = None
        self._erro_base: str | None = None
        self._agora = datetime.now  # relógio da presença/travas (testes trocam)
        # containers com presença gravada nesta janela: id -> pasta do container
        self._presencas: dict[str, list] = {}  # id -> [pasta, entradas]
        self._trava_presenca = threading.RLock()
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
        except LockHeld as e:
            # "trava" permite ao JS oferecer "Liberar trava" quando ela está abandonada
            return {"ok": False, "erro": str(e), "trava": {
                "container_id": getattr(e, "container_id", None), "tipo_id": e.tipo_id,
                "abandonada": bool(e.abandonada)}}
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
        try:
            existe = pasta_existe(base, self._timeout_conexao)
        except OrbitError as e:  # tempo esgotado: rede travada
            raise OrbitError(f"A pasta base está inacessível ({e}): {base}")
        if not existe:
            raise OrbitError(f"A pasta base não foi encontrada ou está inacessível: {base}")
        config = load_shared_config(base)  # cria .orbit/config.json na primeira vez
        fileserver = FileServer(base)
        fileserver.start()  # se falhar, o estado anterior continua valendo
        antigo = self._fileserver
        repo = Repository(base, current_identity(), config)
        self._sair_de_todos()  # presenças gravadas na base anterior
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
        dados = self._config.to_dict()
        dados["logo_url"] = self._logo_url()
        return dados

    def _logo_url(self) -> str | None:
        nome = self._config.logo_empresa
        if not nome:
            return None
        arq = self._base / ".orbit" / Path(str(nome)).name  # nunca sai de .orbit
        try:
            mtime = arq.stat().st_mtime_ns
            return f"{self._fileserver.url_para(arq)}?v={mtime}"
        except (OSError, OrbitError):
            return None

    # --- configurações: tipos, status, logo --------------------------------------

    def trocar_pasta_base(self) -> dict:
        """Mesmo caminho seguro de escolher_pasta_base (a nova base abre antes de fechar a antiga)."""
        return self._chamar(self._escolher_pasta_base)

    def _config_atual_do_disco(self):
        """Config compartilhada relida do disco: outra máquina pode ter alterado desde a abertura."""
        self._exigir_base()
        return load_shared_config(self._base)

    def _aplicar_config(self, nova) -> None:
        save_shared_config(self._base, nova)
        # mesmo objeto (o Repository o referencia): atualiza no lugar
        self._config.tipos, self._config.status = nova.tipos, nova.status
        self._config.logo_empresa = nova.logo_empresa

    def salvar_tipos(self, tipos) -> dict:
        return self._chamar(self._salvar_tipos, tipos)

    def _salvar_tipos(self, tipos):
        if not isinstance(tipos, list):
            raise OrbitError("Lista de tipos inválida.")
        with self._trava_escrita:
            cfg = self._config_atual_do_disco()
            existentes = {t.id: t for t in cfg.tipos}
            vistos, novos = set(), []
            for item in tipos:
                if not isinstance(item, dict):
                    raise OrbitError("Lista de tipos inválida.")
                nome, ativo, tid = item.get("nome"), item.get("ativo"), item.get("id")
                if not isinstance(nome, str) or not sanitize(nome):
                    raise OrbitError("Informe o nome de todos os tipos de documento.")
                if not isinstance(ativo, bool):
                    raise OrbitError("Situação do tipo inválida.")
                if tid is None:
                    novos.append((sanitize(nome), ativo))
                    continue
                if not isinstance(tid, str) or tid not in existentes:
                    raise OrbitError(f"Tipo de documento não encontrado: {tid}")
                if tid in vistos:
                    raise OrbitError("Tipo de documento repetido na lista.")
                vistos.add(tid)
                existentes[tid].nome = sanitize(nome)
                existentes[tid].ativo = ativo
            faltando = [t.nome for t in cfg.tipos if t.id not in vistos]
            if faltando:
                raise OrbitError("Tipos de documento não podem ser removidos (desative-os "
                                 f"no lugar): {', '.join(faltando)}")
            for nome, ativo in novos:
                add_tipo(cfg, nome).ativo = ativo
            nomes = [t.nome.casefold() for t in cfg.tipos]
            if len(set(nomes)) != len(nomes):
                raise OrbitError("Já existe um tipo de documento com esse nome.")
            self._aplicar_config(cfg)
        return self._get_config()

    def _status_em_uso(self) -> dict[str, list[str]]:
        """status -> documentos cuja revisão ATUAL o usa ("<container> — <tipo>")."""
        repo = self._exigir_repo()
        nomes = {t.id: t.nome for t in repo.config.tipos}
        resumos = [m for c in repo.list_clientes() for m in repo.list_projetos(c.id)]
        resumos += repo.list_maquinas()
        uso: dict[str, list[str]] = {}
        for m in resumos:
            if m.erro or not m.id:
                continue  # JSON ilegível já aparece marcado com erro nas listas
            c = repo.load_container(m.id)
            _normalizar_numeros(c)
            for d in c.documentos.values():
                atual = d.atual
                if atual is not None:
                    uso.setdefault(atual.status, []).append(
                        f"{c.nome} — {nomes.get(d.tipo_id, d.tipo_id)}")
        return uso

    def salvar_status(self, status) -> dict:
        return self._chamar(self._salvar_status, status)

    def _salvar_status(self, status):
        if not isinstance(status, list) or not status or not all(isinstance(s, str) for s in status):
            raise OrbitError("Lista de status inválida.")
        novos = [" ".join(s.split()) for s in status]
        if not all(novos):
            raise OrbitError("O nome do status não pode ficar vazio.")
        if len({s.casefold() for s in novos}) != len(novos):
            raise OrbitError("Há status repetidos na lista.")
        with self._trava_escrita:
            cfg = self._config_atual_do_disco()
            sumiram = [s for s in cfg.status if s not in novos]  # remover = renomear
            if sumiram:
                uso = self._status_em_uso()
                bloqueados = [s for s in sumiram if uso.get(s)]
                if bloqueados:
                    linhas = []
                    for s in bloqueados:
                        docs = uso[s]
                        linhas.append(f'"{s}": {"; ".join(docs[:10])}'
                                      + (f" e mais {len(docs) - 10}" if len(docs) > 10 else ""))
                    raise OrbitError("Não é possível remover nem renomear um status em uso "
                                     "em revisão atual. " + " | ".join(linhas))
            cfg.status = novos
            self._aplicar_config(cfg)
        return self._get_config()

    def definir_logo_empresa(self) -> dict:
        return self._chamar(self._definir_logo_empresa)

    def _definir_logo_empresa(self):
        base = self._exigir_base()
        if self._janela is None:
            raise OrbitError("A janela ainda não está pronta.")
        escolha = self._janela.create_file_dialog(
            _DIALOGO_ARQUIVO, allow_multiple=False,
            file_types=("Imagens (*.png;*.jpg;*.jpeg;*.svg;*.webp)",))
        if not escolha:
            return None  # cancelado
        origem = Path(escolha if isinstance(escolha, str) else escolha[0])
        ext = origem.suffix.lower()
        if ext not in EXT_LOGO:
            raise OrbitError("Formato de imagem não aceito. Use " + ", ".join(EXT_LOGO) + ".")
        if not origem.is_file():
            raise OrbitError(f"Arquivo não encontrado: {origem}")
        if origem.stat().st_size > TAMANHO_MAX_LOGO:
            raise OrbitError("A imagem é grande demais (máximo de 5 MB).")
        pasta = base / ".orbit"
        nome = f"{PREFIXO_LOGO}{ext}"
        destino = pasta / nome
        with self._trava_escrita:
            cfg = self._config_atual_do_disco()
            pasta.mkdir(parents=True, exist_ok=True)
            if not (destino.exists() and origem.resolve() == destino.resolve()):
                tmp = pasta / f"{nome}.tmp"
                try:
                    shutil.copyfile(origem, tmp)  # cópia: o original nunca é movido
                    os.replace(tmp, destino)
                finally:
                    tmp.unlink(missing_ok=True)  # resto da nossa própria cópia temporária
            cfg.logo_empresa = nome
            self._aplicar_config(cfg)
            # só depois de o novo estar gravado: cópias antigas do Orbit com outra extensão
            for velho in pasta.glob(f"{PREFIXO_LOGO}.*"):
                if velho.name.lower() != nome.lower() and velho.suffix.lower() in EXT_LOGO:
                    try:
                        velho.unlink()
                    except OSError:
                        pass
        return {"logo_url": self._logo_url()}

    # --- teste de conexão (spec §12) -----------------------------------------

    def testar_conexao(self) -> dict:
        return self._chamar(self._testar_conexao)

    def _testar_conexao(self):
        if not self._settings.pasta_base:
            return []  # sem pasta base: a tela de boas-vindas cuida disso
        r = testar_pasta(Path(self._settings.pasta_base), current_identity(),
                         self._timeout_conexao)
        return [asdict(r)]

    def reabrir_base(self) -> dict:
        """Nova tentativa de abrir a pasta base já configurada (ex.: rede voltou)."""
        return self._chamar(self._reabrir_base)

    def _reabrir_base(self):
        if not self._settings.pasta_base:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        try:
            self._abrir_base(Path(self._settings.pasta_base))
        except OrbitError as e:
            self._erro_base = str(e)
            raise
        return self._dados_settings()

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
        with self._trava_escrita:
            c = repo.create_cliente(str(dados.get("nome", "")), str(dados.get("cnpj", "")),
                                    _contatos(dados.get("contatos")))
        return c.to_dict()

    def atualizar_cliente(self, id, dados) -> dict:
        return self._chamar(self._atualizar_cliente, id, dados)

    def _atualizar_cliente(self, id, dados):
        repo = self._exigir_repo()
        with self._trava_escrita:
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
        with self._trava_escrita:
            c = repo.create_projeto(cliente_id, str(dados.get("codigo", "")),
                                    str(dados.get("nome", "")), str(dados.get("pedido", "")),
                                    str(dados.get("responsavel", "")),
                                    _contatos(dados.get("contatos")), situacao=situacao)
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
        with self._trava_escrita:
            repo.update_dados(id, **campos)
        return None

    # --- painel do projeto/máquina -------------------------------------------

    def _revisoes(self) -> RevisionService:
        return RevisionService(self._exigir_repo(), presence=self._presenca())

    # --- presença e travas de upload (spec §12) --------------------------------

    def _presenca(self) -> PresenceService:
        return PresenceService(self._exigir_repo().identity, agora=self._agora,
                               registrar=self._registrar_erro)

    def _pasta_container(self, container_id) -> Path:
        repo = self._exigir_repo()
        return repo.container_path(repo.load_container(str(container_id)))

    # Os métodos da Api rodam em threads paralelas, então as chamadas do JS podem
    # chegar fora de ordem. `_presencas` guarda id -> [pasta, entradas] e é usado
    # sempre sob `_trava_presenca`:
    # - um sinal atrasado depois do último sair não recria a presença;
    # - num sair/entrar rápido (sair chegando depois do novo entrar), a contagem
    #   não chega a zero e o registro novo não é apagado.

    def entrar_container(self, id) -> dict:
        """Grava a presença e devolve quem mais está com o container aberto."""
        return self._chamar(self._entrar_container, id)

    def _entrar_container(self, id):
        pasta = self._pasta_container(id)
        svc = self._presenca()
        with self._trava_presenca:
            registro = self._presencas.setdefault(str(id), [pasta, 0])
            registro[1] += 1
            self._sinalizar(svc, registro[0])
        try:
            outros = svc.outros(pasta)
        except OSError as e:
            self._registrar_erro(e)
            outros = []
        return [{"usuario": o.usuario, "computador": o.computador, "desde": o.desde,
                 "hora": o.desde[11:16]} for o in outros]

    def _sinalizar(self, svc: PresenceService, pasta: Path) -> None:
        """A presença é só um aviso: falha de rede não pode atrapalhar o uso."""
        try:
            svc.sinalizar(pasta)
        except (OSError, OrbitError) as e:
            self._registrar_erro(e)

    def sinalizar_container(self, id) -> dict:
        """Chamado pelo timer de 30 s do JS enquanto o container está aberto."""
        return self._chamar(self._sinalizar_container, id)

    def _sinalizar_container(self, id):
        with self._trava_presenca:
            registro = self._presencas.get(str(id))
            if registro is not None:  # só renova quem entrou e ainda não saiu
                self._sinalizar(self._presenca(), registro[0])
        return None

    def sair_container(self, id) -> dict:
        return self._chamar(self._sair_container, id)

    def _sair_container(self, id):
        with self._trava_presenca:
            registro = self._presencas.get(str(id))
            if registro is None:
                return None
            registro[1] -= 1
            if registro[1] <= 0:
                del self._presencas[str(id)]
                self._apagar_presenca(registro[0])
        return None

    def _apagar_presenca(self, pasta: Path) -> None:
        if self._repo is None:
            return
        try:
            self._presenca().sair(pasta)
        except OSError as e:
            self._registrar_erro(e)

    def _sair_de_todos(self) -> None:
        with self._trava_presenca:
            registros = list(self._presencas.values())
            self._presencas.clear()
            for pasta, _ in registros:
                self._apagar_presenca(pasta)

    def ao_fechar_janela(self) -> None:
        """Handler de window.events.closing: apaga as presenças desta janela."""
        try:
            self._sair_de_todos()
        except Exception as e:  # nunca impede o fechamento
            self._registrar_erro(e)

    ao_fechar_janela._serializable = False

    def liberar_trava(self, id, tipo_id) -> dict:
        """Remove a trava de upload, mas só se ela estiver abandonada (> 10 min).

        A idade é conferida de novo no arquivo que de fato é removido
        (PresenceService.liberar_abandonada), então uma trava nova criada no
        meio-tempo não é apagada.
        """
        return self._chamar(self._liberar_trava, id, tipo_id)

    def _liberar_trava(self, id, tipo_id):
        repo = self._exigir_repo()
        c = repo.load_container(str(id))
        if str(tipo_id) not in c.documentos:
            raise OrbitError(f"Tipo de documento não encontrado: {tipo_id}")
        svc = self._presenca()
        lock = svc.caminho_trava(repo.container_path(c), str(tipo_id))
        if not svc.liberar_abandonada(lock):
            raise OrbitError("A trava ainda está em uso (tem menos de 10 minutos) e não "
                             "pode ser liberada.")
        return None

    def obter_painel(self, container_id) -> dict:
        return self._chamar(self._obter_painel, container_id)

    def _obter_painel(self, container_id):
        repo = self._exigir_repo()
        c = repo.load_container(container_id)
        _normalizar_numeros(c)
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
        _normalizar_numeros(c)
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
            try:
                rev = self._revisoes().enviar_revisao(container_id, tipo_id, p, eds,
                                                      str(status), str(motivo or "").strip(), n)
            except LockHeld as e:
                e.container_id = container_id
                raise
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

    # --- máquinas padrão -----------------------------------------------------

    def listar_maquinas(self) -> dict:
        return self._chamar(self._listar_maquinas)

    def _listar_maquinas(self):
        return [asdict(m) for m in self._exigir_repo().list_maquinas()]

    def criar_maquina(self, dados) -> dict:
        return self._chamar(self._criar_maquina, dados)

    def _criar_maquina(self, dados):
        repo = self._exigir_repo()
        if not isinstance(dados, dict):
            raise OrbitError("Dados da máquina inválidos.")
        with self._trava_escrita:
            c = repo.create_maquina(str(dados.get("codigo") or ""), str(dados.get("nome") or ""),
                                    str(dados.get("descricao") or ""))
        return {"id": c.id, "nome": c.nome, "codigo": c.codigo}

    def atualizar_maquina(self, id, dados) -> dict:
        return self._chamar(self._atualizar_maquina, id, dados)

    def _atualizar_maquina(self, id, dados):
        repo = self._exigir_repo()
        if not isinstance(dados, dict):
            raise OrbitError("Dados da máquina inválidos.")
        if repo.load_container(id).tipo != "maquina":
            raise OrbitError("Este item não é uma máquina padrão.")
        campos = {k: str(dados[k]).strip() for k in ("codigo", "nome", "descricao") if k in dados}
        if "nome" in campos and not campos["nome"]:
            raise OrbitError("Informe o nome da máquina.")
        with self._trava_escrita:
            repo.update_dados(id, **campos)
        return None

    # --- e-mail e envios -------------------------------------------------------

    def montar_email(self, container_id, selecoes) -> dict:
        return self._chamar(self._montar_email, container_id, selecoes)

    def _montar_email(self, container_id, selecoes):
        repo = self._exigir_repo()
        sels = _validar_selecoes(repo, container_id, selecoes)
        svc = EmailService(repo, self._outlook)
        rascunho = svc.montar(container_id, sels)
        c = repo.load_container(container_id)
        anexos = []
        for s in sels:
            principais = {a.nome for r in c.documentos[s.tipo_id].revisoes
                          if r.numero == s.numero for a in r.arquivos if a.papel == "principal"}
            for caminho in svc.montar(container_id, [s]).anexos:
                anexos.append({"nome": caminho.name, "tamanho": caminho.stat().st_size,
                               "tipo_id": s.tipo_id, "numero": s.numero,
                               "papel": "principal" if caminho.name in principais else "editavel"})
        return {"destinatarios": rascunho.destinatarios, "assunto": rascunho.assunto,
                "corpo": rascunho.corpo, "anexos": anexos,
                "tamanho_total": sum(a["tamanho"] for a in anexos)}

    def preparar_email(self, container_id, draft, selecoes) -> dict:
        return self._chamar(self._preparar_email, container_id, draft, selecoes)

    def _preparar_email(self, container_id, draft, selecoes):
        repo = self._exigir_repo()
        sels = _validar_selecoes(repo, container_id, selecoes)
        if not isinstance(draft, dict):
            raise OrbitError("Rascunho de e-mail inválido.")
        lista, assunto, corpo = draft.get("destinatarios"), draft.get("assunto"), draft.get("corpo")
        if (not isinstance(lista, list) or not all(isinstance(x, str) for x in lista)
                or not isinstance(assunto, str) or not isinstance(corpo, str)):
            raise OrbitError("Rascunho de e-mail inválido.")
        destinatarios = [p.strip() for x in lista for p in x.split(";") if p.strip()]
        svc = EmailService(repo, _OutlookAmigavel(self._outlook))
        # os anexos nunca vêm do JS: são refeitos a partir das seleções
        anexos = svc.montar(container_id, sels).anexos
        with self._trava_escrita:
            svc.preparar(container_id, EmailDraft(destinatarios, assunto, corpo, anexos), sels)
        return None

    def listar_envios(self, cliente_id=None) -> dict:
        return self._chamar(self._listar_envios, cliente_id)

    def _listar_envios(self, cliente_id):
        repo = self._exigir_repo()
        if cliente_id in (None, ""):
            cliente_id = None
        elif not isinstance(cliente_id, str):
            raise OrbitError("Cliente inválido.")
        return EmailService(repo, self._outlook).listar_envios(cliente_id)

    # --- importação e reconciliação ----------------------------------------------

    def preparar_importacao(self, caminhos) -> dict:
        return self._chamar(self._preparar_importacao, caminhos)

    def _preparar_importacao(self, caminhos):
        if not isinstance(caminhos, list) or not all(isinstance(c, str) for c in caminhos):
            raise OrbitError("Lista de arquivos inválida.")
        out = []
        for c in caminhos:
            f = self._arquivo_origem(c)
            n = parse_rev(f.name)
            if n is None:
                m = _REV_SOLTO.search(f.name)
                n = int(m.group(1)) if m and int(m.group(1)) <= 99 else None
            out.append({"origem": str(f), "nome": f.name, "rev_detectada": n,
                        "data_mtime": date.fromtimestamp(f.stat().st_mtime).isoformat()})
        return out

    def _arquivo_origem(self, caminho) -> Path:
        """Arquivo de origem vindo do JS: tem de existir e não pode ser interno do Orbit."""
        if not isinstance(caminho, str) or not caminho.strip():
            raise OrbitError("Caminho de arquivo inválido.")
        f = Path(caminho)
        if not f.is_file():
            raise OrbitError(f"Arquivo não encontrado: {caminho}")
        base = self._exigir_base()
        try:
            f.resolve().relative_to((base / ".orbit").resolve())
        except ValueError:
            return f
        raise OrbitError("Não é possível importar arquivos da pasta interna .orbit.")

    def _item_importacao(self, item) -> ItemImportacao:
        """Valida uma linha do popup; levanta OrbitError com a mensagem da linha."""
        if not isinstance(item, dict):
            raise OrbitError("Linha de importação inválida.")
        origem = self._arquivo_origem(item.get("origem"))
        tipo, status, papel = item.get("tipo_id"), item.get("status"), item.get("papel")
        if not isinstance(tipo, str) or not tipo:
            raise OrbitError("Escolha o tipo de documento.")
        if not isinstance(status, str) or not status:
            raise OrbitError("Escolha o status.")
        if papel not in PAPEIS:
            raise OrbitError(f"Papel inválido: {papel}")
        numero = item.get("numero")
        if numero in (None, ""):
            raise OrbitError("Informe o número da revisão.")
        numero = _numero_revisao(numero)
        data = item.get("data")
        if data in (None, ""):
            data = None
        else:
            try:
                if not isinstance(data, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
                    raise ValueError
                data = date.fromisoformat(data)
            except ValueError:
                raise OrbitError("Data inválida. Use o formato dd/mm/aaaa.")
        return ItemImportacao(origem, tipo, numero, status, papel,
                              str(item.get("motivo") or "").strip(), data)

    def validar_importacao(self, container_id, itens) -> dict:
        return self._chamar(self._validar_importacao, container_id, itens)

    def _validar_importacao(self, container_id, itens):
        repo = self._exigir_repo()
        if not isinstance(itens, list):
            raise OrbitError("Lista de importação inválida.")
        erros: list = [None] * len(itens)
        validos: list[ItemImportacao] = []
        posicoes: list[int] = []
        for i, it in enumerate(itens):
            try:
                validos.append(self._item_importacao(it))
                posicoes.append(i)
            except OrbitError as e:
                erros[i] = str(e)
        if validos:
            for i, e in zip(posicoes, ImportService(repo).validar(container_id, validos)):
                erros[i] = e
        return erros

    def importar(self, container_id, itens) -> dict:
        return self._chamar(self._importar, container_id, itens)

    def _importar(self, container_id, itens):
        repo = self._exigir_repo()
        if not isinstance(itens, list) or not itens:
            raise OrbitError("Nenhum arquivo para importar.")
        lista = []
        for i, it in enumerate(itens):
            try:
                lista.append(self._item_importacao(it))
            except OrbitError as e:
                raise OrbitError(f"Linha {i + 1}: {e}")
        with self._trava_escrita:
            try:
                ImportService(repo, presence=self._presenca()).importar(container_id, lista)
            except LockHeld as e:
                e.container_id = container_id
                raise
        return None

    def listar_nao_registrados(self, container_id) -> dict:
        return self._chamar(self._listar_nao_registrados, container_id)

    def _listar_nao_registrados(self, container_id):
        repo = self._exigir_repo()
        c = repo.load_container(container_id)
        nomes = {t.id: t.nome for t in repo.config.tipos}
        return [{"tipo_id": u.tipo_id, "tipo_nome": nomes.get(u.tipo_id, u.tipo_id),
                 "nome": u.caminho.name, "numero": u.numero, "arquivado": u.arquivado}
                for u in find_untracked(repo, c)]

    def registrar(self, container_id, itens, status) -> dict:
        return self._chamar(self._registrar, container_id, itens, status)

    def _registrar(self, container_id, itens, status):
        repo = self._exigir_repo()
        if not isinstance(itens, list) or not itens:
            raise OrbitError("Selecione ao menos um arquivo para registrar.")
        if not isinstance(status, str):
            raise OrbitError(f"Status inválido: {status}")
        pedidos = set()
        for it in itens:
            if (not isinstance(it, dict) or not isinstance(it.get("tipo_id"), str)
                    or not isinstance(it.get("nome"), str)):
                raise OrbitError("Arquivo não registrado inválido.")
            pedidos.add((it["tipo_id"], it["nome"].casefold()))
        with self._trava_escrita:
            # o caminho nunca vem do JS: refaz a busca e casa por (tipo, nome)
            c = repo.load_container(container_id)
            achados = [u for u in find_untracked(repo, c)
                       if (u.tipo_id, u.caminho.name.casefold()) in pedidos]
            if {(u.tipo_id, u.caminho.name.casefold()) for u in achados} != pedidos:
                raise OrbitError("Algum arquivo não está mais na lista de não registrados. "
                                 "Atualize e tente de novo.")
            register_untracked(repo, container_id, achados, status)
        return None


class _OutlookAmigavel:
    """Transforma falhas COM do Outlook (pywintypes.com_error etc.) em OrbitError."""

    def __init__(self, outlook):
        self._o = outlook

    def disponivel(self) -> bool:
        return bool(self._o.disponivel())

    def abrir_rascunho(self, d) -> None:
        try:
            self._o.abrir_rascunho(d)
        except OrbitError:
            raise
        except Exception as e:
            raise OrbitError("Não foi possível criar o e-mail no Outlook. Verifique se o "
                             f"Outlook clássico está instalado e aberto sem janelas pendentes. ({e})")


def _validar_selecoes(repo, container_id, selecoes) -> list[SelecaoEnvio]:
    if not isinstance(selecoes, list) or not selecoes:
        raise OrbitError("Selecione ao menos um documento para enviar.")
    c = repo.load_container(container_id)
    out, vistos = [], set()
    for s in selecoes:
        if not isinstance(s, dict) or not isinstance(s.get("tipo_id"), str):
            raise OrbitError("Seleção de documento inválida.")
        if s["tipo_id"] not in c.documentos:
            raise OrbitError(f"Tipo de documento não encontrado: {s['tipo_id']}")
        ed = s.get("incluir_editaveis", False)
        if not isinstance(ed, bool):
            raise OrbitError("Seleção de documento inválida.")
        numero = _numero_revisao(s.get("numero"))
        if (s["tipo_id"], numero) in vistos:
            continue
        vistos.add((s["tipo_id"], numero))
        out.append(SelecaoEnvio(s["tipo_id"], numero, ed))
    return out


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
    if not isinstance(editaveis, list) or not all(isinstance(e, str) for e in editaveis):
        raise OrbitError("Lista de arquivos editáveis inválida.")
    return Path(principal), [Path(e) for e in editaveis if e.strip()]


def _normalizar_numeros(c) -> None:
    """Garante números de revisão inteiros antes de usar o container.

    O JSON fica numa pasta compartilhada e pode ser editado à mão: "3" vira 3;
    qualquer outra coisa é erro de dados (nunca chega ao HTML como texto livre).
    """
    for doc in c.documentos.values():
        for r in doc.revisoes:
            v = r.numero
            if isinstance(v, int) and not isinstance(v, bool):
                continue
            if isinstance(v, str) and v.strip().isascii() and v.strip().isdigit():
                r.numero = int(v.strip())
                continue
            raise OrbitDataError(f"Dados inválidos ({c.nome}): número de revisão inválido "
                                 f"em \"{doc.pasta}\". Corrija o arquivo de dados do projeto.")


def _rev_dict(r: Revisao) -> dict:
    principal = next((a.nome for a in r.arquivos if a.papel == "principal"), None)
    return {
        "numero": int(r.numero), "data": r.data, "status": r.status, "motivo": r.motivo,
        "usuario": r.usuario, "computador": r.computador, "arquivada": r.arquivada,
        "principal": principal,
        "editaveis": [a.nome for a in r.arquivos if a.papel == "editavel"],
    }
