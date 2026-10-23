from datetime import datetime
from pathlib import Path

import pytest

from orbit.core.actionlog import ActionLog
from orbit.core.backup import BackupService, restaurar_pc_novo
from orbit.core.config import UserSettings, load_shared_config
from orbit.core.errors import OrbitError
from orbit.core.identity import Identity
from orbit.core.repository import Repository
from orbit.core.revisions import RevisionService

PC1 = Identity("thiago", "PC1")


class Amb:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.base = tmp / "base"
        self.base.mkdir()
        self.settings = UserSettings(str(self.base))
        self.salvos = 0
        self.log = ActionLog(self.base, PC1, tmp / "ancoras.json")
        self.repo = Repository(self.base, PC1, load_shared_config(self.base), log=self.log)
        self.svc = BackupService(self.base, self.settings, PC1, self.log, tmp / "sync",
                                 salvar_settings=self._salvar)
        self.n = 0

    def _salvar(self):
        self.salvos += 1

    def projeto(self):
        cli = self.repo.create_cliente("Cliente X")
        return self.repo.create_projeto(cli.id, "001", "Envasadora")

    def subir(self, cid):
        self.n += 1
        f = self.tmp / f"A{self.n}.pdf"
        f.write_bytes(f"pdf {self.n}".encode())
        RevisionService(self.repo).enviar_revisao(cid, "diagrama_eletrico", f, [],
                                                  "Em elaboração", "m")


@pytest.fixture
def amb(tmp_path):
    return Amb(tmp_path)


def test_analisar_caminho_tres_casos_e_aninhado(amb, tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    assert amb.svc.analisar_caminho(vazio) == "vazio"
    estranho = tmp_path / "estranho"
    estranho.mkdir()
    (estranho / "x.txt").write_text("x")
    assert amb.svc.analisar_caminho(estranho) == "estranho"
    orbit = tmp_path / "outro"
    (orbit / ".orbit").mkdir(parents=True)
    (orbit / ".orbit" / "config.json").write_text("{}")
    assert amb.svc.analisar_caminho(orbit) == "orbit"
    dentro = amb.base / "sub"
    dentro.mkdir()
    with pytest.raises(OrbitError):
        amb.svc.analisar_caminho(dentro)
    with pytest.raises(OrbitError):
        amb.svc.analisar_caminho(tmp_path)  # a base fica dentro dele
    with pytest.raises(OrbitError):
        amb.svc.analisar_caminho(tmp_path / "nao_existe")


def test_aviso_nuvem(amb):
    assert amb.svc.aviso_nuvem(Path(r"C:\Users\x\OneDrive - Empresa\Backup")) is not None
    assert amb.svc.aviso_nuvem(Path(r"C:\Users\x\Dropbox\Orbit")) is not None
    assert amb.svc.aviso_nuvem(Path(r"\\servidor\projetos\orbit")) is None


def test_configurar_estranho_recusa(amb, tmp_path):
    estranho = tmp_path / "estranho"
    estranho.mkdir()
    (estranho / "x.txt").write_text("x")
    with pytest.raises(OrbitError) as e:
        amb.svc.configurar(estranho)
    assert "não são do Orbit" in str(e.value)
    assert amb.settings.backup is None


def test_configurar_vazio_copia_e_salva(amb, tmp_path):
    p = amb.projeto()
    amb.subir(p.id)
    destino = tmp_path / "bk"
    destino.mkdir()
    res = amb.svc.configurar(destino)
    assert res.erro is None and amb.settings.backup == str(destino) and amb.salvos == 1
    assert len(list(destino.rglob("*.pdf"))) == 1
    assert amb.svc.status(forcar_comparacao=True).estado == "em_dia"


def test_espelhar_copia_alteracao(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.subir(p.id)
    amb.svc.espelhar("container", p.id)
    amb.svc.aguardar_espelhamento(10)
    assert len(list(destino.rglob("*.pdf"))) == 1
    assert amb.svc.status(forcar_comparacao=True).estado == "em_dia"


def test_espelhar_com_backup_fora_vira_pendente_e_nao_lanca(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    destino.rename(tmp_path / "bk_fora")
    amb.subir(p.id)
    amb.svc.espelhar("container", p.id)
    amb.svc.aguardar_espelhamento(10)
    assert ("container", p.id) in amb.svc.pendentes()
    st = amb.svc.status(forcar_comparacao=True)
    assert st.estado == "inacessivel" and st.erro


def test_status_estados(amb, tmp_path):
    assert amb.svc.status().estado == "desativado"
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    assert amb.svc.status(forcar_comparacao=True).estado == "em_dia"
    amb.subir(p.id)  # sem espelhar
    st = amb.svc.status(forcar_comparacao=True)
    assert st.estado == "diferente" and st.pendentes > 0
    assert st.ultima_sync is not None


def test_status_nao_compara_antes_do_intervalo(amb, tmp_path, monkeypatch):
    amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.svc.status(forcar_comparacao=True)
    chamadas = []
    original = amb.svc._comparar
    monkeypatch.setattr(amb.svc, "_comparar", lambda: chamadas.append(1) or original())
    amb.svc.status()
    assert chamadas == []
    amb.svc.status(forcar_comparacao=True)
    assert chamadas == [1]


def test_enviar_pendencias_locais(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    destino.rename(tmp_path / "bk_fora")
    amb.subir(p.id)
    amb.svc.espelhar("container", p.id)
    amb.svc.aguardar_espelhamento(10)
    (tmp_path / "bk_fora").rename(destino)
    amb.svc.enviar_pendencias_locais()
    assert len(list(destino.rglob("*.pdf"))) == 1
    assert amb.svc.pendentes() == set()


def test_recuperar_juntando_nao_muda_backup_configurado(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    outro = tmp_path / "outro_backup"
    outro.mkdir()
    # um backup antigo com dados do Orbit
    b2 = Repository(outro, PC1, load_shared_config(outro))
    c2 = b2.create_cliente("Cliente Antigo")
    res = amb.svc.recuperar_juntando(outro)
    assert res.erro is None
    assert (amb.base / "Clientes" / "Cliente Antigo" / "cliente.json").is_file()
    assert amb.settings.backup == str(destino)


def test_restaurar_pc_novo_pasta_nao_vazia_recusa(amb, tmp_path):
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.projeto()
    amb.svc.configurar(destino)
    nova = tmp_path / "nova"
    nova.mkdir()
    (nova / "algo.txt").write_text("x")
    with pytest.raises(OrbitError):
        restaurar_pc_novo(destino, nova, PC1, tmp_path / "anc2.json")


def test_restaurar_pc_novo_copia_e_confere(amb, tmp_path):
    p = amb.projeto()
    amb.subir(p.id)
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    nova = tmp_path / "nova"
    nova.mkdir()
    res = restaurar_pc_novo(destino, nova, PC1, tmp_path / "anc2.json")
    assert res.erro is None and res.recebidos > 0
    assert len(list(nova.rglob("*.pdf"))) == 1
    assert (nova / "Clientes" / "Cliente X" / "001 - Envasadora" / "projeto.json").is_file()
    acoes = [l.acao for l in ActionLog(nova, PC1, tmp_path / "anc2.json").ler()]
    assert "recuperacao" in acoes


def test_enviar_pendencias_apos_reiniciar(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.subir(p.id)  # alteração local, sem espelhar (programa fechado/reaberto)
    novo = BackupService(amb.base, amb.settings, PC1, amb.log, tmp_path / "sync")
    assert novo.pendentes() == set()
    novo.enviar_pendencias_locais()
    assert len(list(destino.rglob("*.pdf"))) == 1


def test_nao_envia_sozinho_se_o_backup_tambem_mudou(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.subir(p.id)
    (destino / "Clientes" / "Cliente X" / "nota.txt").write_text("do servidor")
    novo = BackupService(amb.base, amb.settings, PC1, amb.log, tmp_path / "sync")
    novo.enviar_pendencias_locais()
    assert list(destino.rglob("*.pdf")) == []


def test_status_repetido_nao_recalcula_hash(amb, tmp_path, monkeypatch):
    from orbit.core.sync import varredura
    p = amb.projeto()
    amb.subir(p.id)
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.svc.status(forcar_comparacao=True)
    chamadas = []
    original = varredura.calcular_hash
    monkeypatch.setattr(varredura, "calcular_hash", lambda c: chamadas.append(c) or original(c))
    amb.svc.status(forcar_comparacao=True)
    amb.svc.espelhar("container", p.id)
    amb.svc.aguardar_espelhamento(10)
    # só o log de ações muda de verdade a cada sincronização
    assert [c for c in chamadas if not str(c).endswith("acoes.log")] == []


def test_recuperar_juntando_ignora_o_retrato_do_backup_configurado(amb, tmp_path):
    from orbit.core.jsonstore import read_json
    p = amb.projeto()
    amb.repo.update_dados(p.id, pedido="ORIGINAL")
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    amb.svc.settings.backup = None             # sem espelhar o dano
    amb.repo.update_dados(p.id, pedido="DANIFICADO")  # só o lado local mudou (dano)
    amb.svc.settings.backup = str(destino)
    res = amb.svc.recuperar_juntando(destino)
    # sem retrato, a diferença vira divergência em vez de levar o dano para o backup
    assert any(dv.chave == "pedido" for dv in res.divergencias)
    assert read_json(next(destino.rglob("projeto.json")))["pedido"] == "ORIGINAL"


def test_backup_trocado_no_mesmo_caminho_usa_outro_retrato(amb, tmp_path):
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.projeto()
    amb.svc.configurar(destino)
    r1 = amb.svc.engine().retrato.pasta
    destino.rename(tmp_path / "hd1")
    destino.mkdir()  # outro HD no mesmo caminho
    amb.svc.configurar(destino)
    r2 = amb.svc.engine().retrato.pasta
    assert r1 != r2


def test_backup_que_volta_na_mesma_sessao_recebe_as_pendencias(amb, tmp_path):
    p = amb.projeto()
    destino = tmp_path / "bk"
    destino.mkdir()
    amb.svc.configurar(destino)
    destino.rename(tmp_path / "bk_fora")
    amb.subir(p.id)
    amb.svc.espelhar("container", p.id)
    amb.svc.aguardar_espelhamento(10)
    assert amb.svc.status(forcar_comparacao=True).estado == "inacessivel"
    (tmp_path / "bk_fora").rename(destino)  # VPN/HD de volta, sem reiniciar
    amb.svc.status(forcar_comparacao=True)
    assert amb.svc.aguardar_reenvio(10)
    assert len(list(destino.rglob("*.pdf"))) == 1
