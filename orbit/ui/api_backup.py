"""Métodos da Api para backup, sincronização, divergências e recuperação.

`BackupApiMixin` é herdado pela classe Api (api.py). Segue a mesma convenção:
todo método público devolve {"ok": ..., "dados"/"erro": ...} via self._chamar,
e o estado interno fica em atributos com "_".

Sincronizações, configuração e recuperação podem demorar: rodam numa thread
("job") e o JS acompanha com progresso_backup().
"""
import os
import threading
from pathlib import Path

from orbit.core.backup import BackupService, restaurar_pc_novo
from orbit.core.config import limitar_intervalo, save_user_settings
from orbit.core.errors import LockHeld, OrbitError
from orbit.core.identity import current_identity
from orbit.core.jsonstore import read_json
from orbit.core.sync.mesclar import Divergencia
from orbit.core.sync.motor import _Lado
from orbit.core.sync.resolver import _localizar, resolver

LADOS = ("local", "backup")
_DIALOGO_PASTA = 20  # webview.FileDialog.FOLDER (pywebview 6.x)


class BackupApiMixin:
    # ---------- infraestrutura ----------
    def _iniciar_estado_backup(self) -> None:
        self._backup: BackupService | None = None
        self._job: dict | None = None
        self._job_thread: threading.Thread | None = None
        self._job_cancelar = threading.Event()
        self._trava_job = threading.Lock()

    def _criar_backup_service(self, base: Path, ident, log, repo) -> BackupService:
        svc = BackupService(base, self._settings, ident, log, self._sync_dir,
                            registrar=self._registrar_erro,
                            salvar_settings=self._salvar_settings)
        repo.ao_alterar = svc.espelhar
        return svc

    def _ao_abrir_backup(self) -> None:
        """Na abertura, em segundo plano: envia pendências locais sem divergência."""
        svc = self._backup
        if svc is None or svc.backup is None:
            return
        try:
            svc.enviar_pendencias_locais()
        except Exception as e:
            self._registrar_erro(e)

    def _salvar_settings(self) -> None:
        save_user_settings(self._settings, self._settings_path)

    def _exigir_backup(self) -> BackupService:
        if self._backup is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        if self._backup.backup is None:
            raise OrbitError("Nenhum backup configurado. Escolha a pasta de backup em "
                             "Configurações.")
        return self._backup

    def _iniciar_job(self, fn, extra: dict | None = None) -> dict:
        with self._trava_job:
            if self._job is not None and self._job["rodando"]:
                raise OrbitError("Já existe uma sincronização em andamento.")
            job = {"fase": "Preparando…", "atual": 0, "total": 0, "rodando": True,
                   "resultado": None}
            self._job = job
            self._job_cancelar = cancelar = threading.Event()

        def progresso(fase, atual, total):
            job.update(fase=fase, atual=atual, total=total)

        def rodar():
            try:
                res = fn(progresso, cancelar.is_set)
                dados = res.to_dict() if hasattr(res, "to_dict") else dict(res or {})
                dados.update(extra or {})
            except (LockHeld, OrbitError) as e:
                dados = {"erro": str(e)}
            except Exception as e:
                self._registrar_erro(e)
                dados = {"erro": f"Erro inesperado: {type(e).__name__}. Veja o log."}
            job["resultado"] = dados
            job["rodando"] = False

        self._job_thread = threading.Thread(target=rodar, daemon=True, name="orbit-backup")
        self._job_thread.start()
        return {"iniciado": True}

    def _aguardar_job(self, timeout: float = 30.0) -> bool:
        t = self._job_thread
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    def _escolher_pasta(self, inicial: str = "") -> str | None:
        if self._janela is None:
            raise OrbitError("A janela ainda não está pronta.")
        escolha = self._janela.create_file_dialog(_DIALOGO_PASTA, inicial)
        if not escolha:
            return None
        return escolha if isinstance(escolha, str) else escolha[0]

    # ---------- status e configuração ----------
    def status_backup(self, forcar=False) -> dict:
        return self._chamar(self._status_backup, forcar)

    def _status_backup(self, forcar):
        if self._backup is None:
            dados = {"estado": "desativado", "pendentes": 0, "divergencias": 0,
                     "ultima_sync": None, "erro": None}
        else:
            dados = self._backup.status(bool(forcar)).to_dict()
        caminho = self._settings.backup
        dados.update({"caminho": caminho,
                      "intervalo": self._settings.intervalo_backup_min,
                      "aviso_nuvem": BackupService.aviso_nuvem(Path(caminho)) if caminho else None,
                      "rodando": bool(self._job and self._job["rodando"])})
        if dados["rodando"]:
            dados["estado"] = "sincronizando"
        return dados

    def escolher_backup(self) -> dict:
        return self._chamar(self._escolher_backup)

    def _escolher_backup(self):
        if self._backup is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        caminho = self._escolher_pasta(self._settings.backup or "")
        if caminho is None:
            return None
        return {"caminho": caminho, "analise": self._backup.analisar_caminho(Path(caminho)),
                "aviso_nuvem": BackupService.aviso_nuvem(Path(caminho))}

    def configurar_backup(self, caminho) -> dict:
        return self._chamar(self._configurar_backup, caminho)

    def _configurar_backup(self, caminho):
        if not isinstance(caminho, str) or not caminho.strip():
            raise OrbitError("Caminho de backup inválido.")
        if self._backup is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        svc, alvo = self._backup, Path(caminho)
        return self._iniciar_job(lambda p, c: svc.configurar(alvo, p, c))

    def desativar_backup(self) -> dict:
        return self._chamar(self._desativar_backup)

    def _desativar_backup(self):
        if self._backup is not None:
            self._backup.desativar()
        else:
            self._settings.backup = None
            self._salvar_settings()
        return None

    def definir_intervalo_backup(self, minutos) -> dict:
        return self._chamar(self._definir_intervalo_backup, minutos)

    def _definir_intervalo_backup(self, minutos):
        self._settings.intervalo_backup_min = limitar_intervalo(minutos)
        self._salvar_settings()
        return self._settings.intervalo_backup_min

    # ---------- sincronização ----------
    def sincronizar_backup(self) -> dict:
        return self._chamar(self._sincronizar_backup)

    def _sincronizar_backup(self):
        svc = self._exigir_backup()
        return self._iniciar_job(lambda p, c: svc.sincronizar(p, c))

    def progresso_backup(self) -> dict:
        return self._chamar(lambda: dict(self._job) if self._job else
                            {"fase": "", "atual": 0, "total": 0, "rodando": False,
                             "resultado": None})

    def cancelar_sincronizacao(self) -> dict:
        return self._chamar(lambda: self._job_cancelar.set())

    # ---------- divergências ----------
    def _pendentes(self) -> list[dict]:
        if self._backup is None or self._backup.backup is None:
            return []
        return self._backup.engine().retrato.divergencias_pendentes()

    def listar_divergencias(self) -> dict:
        return self._chamar(self._pendentes)

    def resolver_divergencia(self, div_id, escolha) -> dict:
        return self._chamar(self._resolver_divergencia, div_id, escolha)

    def _resolver_divergencia(self, div_id, escolha):
        if not isinstance(div_id, str) or not isinstance(escolha, str):
            raise OrbitError("Divergência inválida.")
        svc = self._exigir_backup()
        with self._trava_escrita:
            resolver(svc.engine(), div_id, escolha)
        svc._ultimo_status = None
        return self._pendentes()

    def abrir_arquivo_divergencia(self, div_id, lado) -> dict:
        return self._chamar(self._abrir_arquivo_divergencia, div_id, lado)

    def _abrir_arquivo_divergencia(self, div_id, lado):
        if lado not in LADOS or not isinstance(div_id, str):
            raise OrbitError("Pedido inválido.")
        svc = self._exigir_backup()
        bruta = next((d for d in self._pendentes() if d.get("id") == div_id), None)
        if bruta is None:
            raise OrbitError("Divergência não encontrada.")
        div = Divergencia.from_dict(bruta)
        raiz = Path(self._base if lado == "local" else svc.backup)
        caminho = None
        if div.tipo == "arquivo":
            caminho = raiz / div.caminho
        elif div.tipo == "revisao":
            lado_obj = _Lado(raiz, lado)
            lado_obj.descobrir()
            achado = lado_obj.containers.get(div.escopo_id)
            rev = (div.local if lado == "local" else div.backup).get("revisao") or {}
            principal = next((a for a in rev.get("arquivos") or []
                              if a.get("papel") == "principal"), None)
            if achado and principal:
                rel, nome_json = achado
                tipo = div.chave.split(".")[1]
                doc = (read_json(raiz / rel / nome_json).get("documentos") or {}).get(tipo) or {}
                caminho = _localizar(lado_obj, rel, doc.get("pasta", ""), principal["nome"])
        if caminho is None:
            raise OrbitError("Esta divergência não tem arquivo para abrir.")
        caminho = Path(caminho).resolve()
        if not caminho.is_relative_to(raiz.resolve()) or not caminho.is_file():
            raise OrbitError("Arquivo não encontrado.")
        os.startfile(str(caminho))
        return None

    # ---------- recuperação ----------
    def recuperar_juntando(self) -> dict:
        return self._chamar(self._recuperar_juntando)

    def _recuperar_juntando(self):
        if self._backup is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        caminho = self._escolher_pasta()
        if caminho is None:
            return None
        svc, alvo = self._backup, Path(caminho)
        return self._iniciar_job(lambda p, c: svc.recuperar_juntando(alvo, p, c),
                                 extra={"caminho_backup": caminho})

    def restaurar_pc_novo(self) -> dict:
        return self._chamar(self._restaurar_pc_novo)

    def _restaurar_pc_novo(self):
        origem = self._escolher_pasta()
        if origem is None:
            return None
        nova = self._escolher_pasta()
        if nova is None:
            return None
        ancoras = self._ancoras_path
        return self._iniciar_job(
            lambda p, c: restaurar_pc_novo(Path(origem), Path(nova), current_identity(),
                                           ancoras, progresso=p, cancelar=c),
            extra={"caminho_backup": origem, "nova_base": nova})

    def concluir_restauracao(self, nova_base, caminho_backup, usar_backup) -> dict:
        return self._chamar(self._concluir_restauracao, nova_base, caminho_backup, usar_backup)

    def _concluir_restauracao(self, nova_base, caminho_backup, usar_backup):
        if not isinstance(nova_base, str) or not isinstance(caminho_backup, str) \
                or not isinstance(usar_backup, bool):
            raise OrbitError("Pedido inválido.")
        self._abrir_base(Path(nova_base))
        self._settings.pasta_base = nova_base
        if usar_backup:
            self._settings.backup = caminho_backup
        self._salvar_settings()
        return self._dados_settings()
