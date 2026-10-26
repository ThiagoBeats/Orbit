"""Métodos da Api para o módulo Produção (spec Produção §5).

`ProducaoApiMixin` é herdado pela classe Api. O operador da bancada é
escolhido na tela e o último usado fica guardado nesta máquina
(`producao_local.json`, junto das preferências), nunca na pasta base.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from orbit.core.errors import OrbitDataError, OrbitError
from orbit.core.jsonstore import read_json, write_json_atomic
from orbit.core.producao import apontamentos as A
from orbit.core.producao import etapas, gestao, importar, materiais, relatorio
from orbit.core.producao import testes as T
from orbit.core.producao.config import validar_config
from orbit.core.producao.modelo import ETAPAS, NOMES_ETAPAS, PRIORIDADES, ProducaoService

_DIALOGO_ARQUIVO = 10  # webview.FileDialog.OPEN
EXT_PLANILHA = (".xlsx", ".xlsm", ".csv", ".txt")


def _abrir(caminho: Path) -> None:
    try:
        os.startfile(str(caminho))
    except OSError as e:
        raise OrbitError(f"Não foi possível abrir \"{Path(caminho).name}\": {e}") from e


def _texto(v, rotulo: str, obrigatorio: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise OrbitError(f"Campo inválido: {rotulo}.")
    v = v.strip()
    if obrigatorio and not v:
        raise OrbitError(f"Informe {rotulo}.")
    return v


def _id(v) -> str:
    if not isinstance(v, str) or not v:
        raise OrbitError("Identificador inválido.")
    return v


class ProducaoApiMixin:
    # ---------- infraestrutura ----------
    def _iniciar_estado_producao(self, pasta_prefs: Path) -> None:
        self._producao: ProducaoService | None = None
        self._prod_local = pasta_prefs / "producao_local.json"

    def _criar_producao(self, repo, ident, log) -> None:
        self._producao = ProducaoService(repo, ident, log=log)

    def _prod(self) -> ProducaoService:
        if self._producao is None:
            raise OrbitError("Escolha a pasta base primeiro (em Configurações).")
        return self._producao

    def _operador(self, nome) -> str:
        nome = _texto(nome, "o operador", obrigatorio=True)
        try:
            dados = read_json(self._prod_local) if self._prod_local.exists() else {}
        except OrbitDataError:
            dados = {}
        if dados.get("ultimo_operador") != nome:
            try:
                self._prod_local.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(self._prod_local, {**dados, "ultimo_operador": nome})
            except OSError as e:
                self._registrar_erro(e)
        return nome

    def _ultimo_operador(self) -> str | None:
        try:
            return (read_json(self._prod_local) if self._prod_local.exists() else {}).get(
                "ultimo_operador")
        except OrbitDataError:
            return None

    def _hoje(self) -> date:
        return self._prod().agora().date()

    # ---------- configuração ----------
    def prod_config(self) -> dict:
        return self._chamar(self._prod_config)

    def _prod_config(self):
        svc = self._prod()
        cfg = svc.config()
        return {**cfg, "ultimo_operador": self._ultimo_operador(),
                "etapas": [{"id": e, "nome": NOMES_ETAPAS[e]} for e in ETAPAS],
                "prioridades": list(PRIORIDADES), "usuario": svc.identity.usuario,
                "situacoes_material": [{"id": s, "nome": materiais.NOMES_SITUACOES[s]}
                                       for s in materiais.SITUACOES],
                "blocos": T.NOMES_BLOCOS}

    def prod_salvar_config(self, dados) -> dict:
        return self._chamar(self._prod_salvar_config, dados)

    def _prod_salvar_config(self, dados):
        novos = validar_config(dados)
        with self._prod().editar_config() as cfg:
            cfg.update(novos)
        self._logar("configuracao_alterada", {"producao": sorted(novos)})
        return self._prod_config()

    # ---------- fila, OPs do projeto, gestão ----------
    def prod_fila(self, incluir_expedidas=False) -> dict:
        return self._chamar(lambda: gestao.fila(self._prod(), self._hoje(),
                                                bool(incluir_expedidas)))

    def prod_ops_projeto(self, container_id) -> dict:
        def fn():
            svc = self._prod()
            cfg = svc.config()
            return [gestao.cartao(svc, op, self._hoje(), cfg)
                    for op in svc.listar_ops(_id(container_id))]
        return self._chamar(fn)

    def prod_gestao(self) -> dict:
        return self._chamar(lambda: gestao.indicadores(self._prod()))

    # ---------- OP ----------
    def prod_criar_op(self, container_id, dados) -> dict:
        return self._chamar(lambda: self._prod().criar_op(_id(container_id), dados))

    def prod_editar_op(self, op_id, dados) -> dict:
        return self._chamar(lambda: self._prod().editar_dados(_id(op_id), dados))

    def prod_obter_op(self, op_id) -> dict:
        return self._chamar(self._prod_obter_op, op_id)

    def _prod_obter_op(self, op_id):
        svc = self._prod()
        op = svc.carregar(_id(op_id))
        cfg = svc.config()
        c = svc.repo.load_container(op["container_id"])
        cli = svc.repo.cliente_de(c)
        op["container_nome"] = c.nome
        op["cliente_nome"] = cli.nome if cli else None
        try:
            disponiveis = list(etapas._documentos_atuais(svc, op["container_id"]).values())
        except OrbitError:
            disponiveis = []
        return {
            "op": op, "cartao": gestao.cartao(svc, op, self._hoje(), cfg),
            "container": {"id": c.id, "tipo": c.tipo, "codigo": c.codigo, "nome": c.nome,
                          "cliente_id": c.cliente_id},
            "alertas": etapas.alertas_revisao(svc, op), "disponiveis": disponiveis,
            "situacao": T.situacao(op, cfg), "pendencias": T.pendencias(op, cfg),
            "materiais": materiais.resumo(op),
            "horas": A.totais([op], svc.agora()),
            "pasta": str(svc.pasta_op(op["id"])),
        }

    def prod_liberar(self, op_id, tipos=None) -> dict:
        return self._chamar(lambda: etapas.liberar(self._prod(), _id(op_id), tipos))

    def prod_atualizar_pacote(self, op_id, tipos=None) -> dict:
        return self._chamar(lambda: etapas.atualizar_pacote(self._prod(), _id(op_id), tipos))

    def prod_abrir_documento(self, op_id, tipo_id) -> dict:
        def fn():
            _abrir(etapas.arquivo_do_pacote(self._prod(), _id(op_id), _id(tipo_id)))
        return self._chamar(fn)

    def prod_avancar(self, op_id, operador=None) -> dict:
        return self._chamar(lambda: etapas.avancar(
            self._prod(), _id(op_id), self._operador(operador) if operador else None))

    def prod_voltar(self, op_id, destino, motivo, operador=None) -> dict:
        return self._chamar(lambda: etapas.voltar(
            self._prod(), _id(op_id), destino, motivo,
            self._operador(operador) if operador else None))

    def prod_bloquear(self, op_id, motivo) -> dict:
        return self._chamar(lambda: etapas.bloquear(self._prod(), _id(op_id), motivo))

    def prod_desbloquear(self, op_id) -> dict:
        return self._chamar(lambda: etapas.desbloquear(self._prod(), _id(op_id)))

    def prod_abrir_pasta_op(self, op_id) -> dict:
        return self._chamar(lambda: _abrir(self._prod().pasta_op(_id(op_id))))

    def prod_relatorio(self, op_id, abrir=True) -> dict:
        def fn():
            caminho = relatorio.gerar(self._prod(), _id(op_id))
            if abrir:
                _abrir(caminho)
            return str(caminho)
        return self._chamar(fn)

    # ---------- apontamentos ----------
    def prod_meu_trabalho(self, operador=None) -> dict:
        return self._chamar(self._prod_meu_trabalho, operador)

    def _prod_meu_trabalho(self, operador):
        svc = self._prod()
        ops = svc.todas_ops()
        cfg = svc.config()
        hoje = self._hoje()
        disponiveis = [gestao.cartao(svc, op, hoje, cfg, alertas=False) for op in ops
                       if op["etapa"] in A.ETAPAS_COM_APONTAMENTO]
        aberto = None
        hoje_meu = None
        if operador:
            nome = _texto(operador, "o operador")
            for op in ops:
                for ap in op.get("apontamentos") or []:
                    if ap.get("operador") == nome and ap.get("fim") is None:
                        aberto = {"op": gestao.cartao(svc, op, hoje, cfg), "apontamento": ap}
            from datetime import datetime
            inicio = datetime.combine(hoje, datetime.min.time())
            meus = [{**op, "apontamentos": [a for a in op.get("apontamentos") or []
                                            if a.get("operador") == nome]} for op in ops]
            hoje_meu = A.totais(meus, svc.agora(), desde=inicio)
        return {"aberto": aberto, "disponiveis": disponiveis, "hoje": hoje_meu,
                "agora": svc.agora_iso()}

    def prod_iniciar(self, op_id, operador, obs="") -> dict:
        return self._chamar(lambda: A.iniciar(self._prod(), _id(op_id), self._operador(operador),
                                              _texto(obs, "a observação")))

    def prod_pausar(self, operador, motivo, obs="") -> dict:
        return self._chamar(lambda: A.pausar(self._prod(), self._operador(operador), motivo,
                                             _texto(obs, "a observação")))

    def prod_retomar(self, operador) -> dict:
        return self._chamar(lambda: A.retomar(self._prod(), self._operador(operador)))

    def prod_encerrar(self, operador, obs="") -> dict:
        return self._chamar(lambda: A.encerrar(self._prod(), self._operador(operador),
                                               _texto(obs, "a observação")))

    def prod_editar_apontamento(self, op_id, ap_id, inicio, fim) -> dict:
        return self._chamar(lambda: A.editar(self._prod(), _id(op_id), _id(ap_id), inicio,
                                             fim or None, self._prod().identity.usuario))

    # ---------- planilhas (materiais, ponto a ponto, I/O) ----------
    def prod_escolher_planilha(self, destino) -> dict:
        return self._chamar(self._prod_escolher_planilha, destino)

    def _prod_escolher_planilha(self, destino):
        if self._janela is None:
            raise OrbitError("A janela ainda não está pronta.")
        escolha = self._janela.create_file_dialog(
            _DIALOGO_ARQUIVO, allow_multiple=False,
            file_types=("Planilhas (*.xlsx;*.xlsm;*.csv;*.txt)", "Todos os arquivos (*.*)"))
        if not escolha:
            return None
        return self._prod_ler_planilha(escolha if isinstance(escolha, str) else escolha[0],
                                       destino)

    def prod_ler_planilha(self, caminho, destino) -> dict:
        return self._chamar(self._prod_ler_planilha, caminho, destino)

    def _prod_ler_planilha(self, caminho, destino):
        caminho = Path(_texto(caminho, "o arquivo", obrigatorio=True))
        if caminho.suffix.lower() not in EXT_PLANILHA:
            raise OrbitError("Use uma planilha .xlsx ou .csv.")
        tab = importar.ler_tabela(caminho)
        campos, obrig = importar.CAMPOS.get(destino if isinstance(destino, str) else "",
                                            (None, None))
        if campos is None:
            raise OrbitError("Destino da importação inválido.")
        return {"caminho": str(caminho), "nome": caminho.name, "cabecalho": tab["cabecalho"],
                "amostra": tab["linhas"][:5], "total": len(tab["linhas"]),
                "campos": [{"id": c, "nome": importar.NOMES_CAMPOS[c], "obrigatorio": c in obrig}
                           for c in campos],
                "sugestao": importar.sugerir_mapa(tab["cabecalho"], destino)}

    def prod_importar_planilha(self, op_id, destino, caminho, mapa, substituir=False) -> dict:
        return self._chamar(self._prod_importar_planilha, op_id, destino, caminho, mapa,
                            substituir)

    def _prod_importar_planilha(self, op_id, destino, caminho, mapa, substituir):
        if not isinstance(destino, str) or destino not in importar.CAMPOS                 or not isinstance(mapa, dict):
            raise OrbitError("Importação inválida.")
        campos, obrig = importar.CAMPOS[destino]
        mapa = {c: mapa.get(c) for c in campos}
        if destino == "materiais" and mapa["codigo"] is None and mapa["descricao"] is None:
            raise OrbitError("Escolha a coluna de código ou de descrição.")
        tab = importar.ler_tabela(Path(_texto(caminho, "o arquivo", obrigatorio=True)))
        linhas = importar.mapear(tab, mapa, obrig)
        svc, op_id, subst = self._prod(), _id(op_id), bool(substituir)
        if destino == "materiais":
            return materiais.importar(svc, op_id, linhas, subst)
        if destino == "ponto_a_ponto":
            return T.carregar_ponto_a_ponto(svc, op_id, linhas, subst)
        return T.carregar_io(svc, op_id, linhas, subst)

    # ---------- materiais ----------
    def prod_adicionar_material(self, op_id, dados) -> dict:
        return self._chamar(lambda: materiais.adicionar(self._prod(), _id(op_id), dados))

    def prod_situacao_materiais(self, op_id, ids, situacao, obs="", previsao=None) -> dict:
        return self._chamar(lambda: materiais.mudar_situacao(
            self._prod(), _id(op_id), ids, situacao, self._prod().identity.usuario,
            _texto(obs, "a observação"), previsao or None))

    # ---------- testes ----------
    def prod_preparar_testes(self, op_id) -> dict:
        def fn():
            svc, oid = self._prod(), _id(op_id)
            T.itens_inspecao(svc, oid)
            T.passos_energizacao(svc, oid)
            return svc.carregar(oid)["testes"]
        return self._chamar(fn)

    def prod_marcar(self, op_id, bloco, item_id, dados) -> dict:
        return self._chamar(self._prod_marcar, op_id, bloco, item_id, dados)

    def _prod_marcar(self, op_id, bloco, item_id, dados):
        if not isinstance(dados, dict):
            raise OrbitError("Dados inválidos.")
        svc, oid, iid = self._prod(), _id(op_id), _id(item_id)
        operador = self._operador(dados.get("operador"))
        obs = _texto(dados.get("obs"), "a observação")
        nc_tipo = dados.get("nc_tipo") or None
        if bloco == "inspecao":
            return T.marcar_inspecao(svc, oid, iid, dados.get("resultado"), operador, obs, nc_tipo)
        if bloco == "ponto_a_ponto":
            return T.marcar_ligacao(svc, oid, iid, dados.get("ligacao"), dados.get("aperto"),
                                    operador, obs, nc_tipo)
        if bloco == "passo":
            return T.marcar_passo(svc, oid, iid, dados.get("resultado"), operador, obs, nc_tipo)
        if bloco == "sinal":
            return T.marcar_sinal(svc, oid, iid, dados.get("resultado"), operador, obs, nc_tipo)
        if bloco == "isolacao":
            return T.medir_isolacao(svc, oid, iid, dados.get("valor"), operador, obs)
        if bloco == "tensao":
            return T.medir_tensao(svc, oid, iid, dados.get("valor"), operador, obs)
        raise OrbitError("Bloco de teste inválido.")

    def prod_adicionar_circuito(self, op_id, nome, tensao_v) -> dict:
        return self._chamar(lambda: T.adicionar_circuito(self._prod(), _id(op_id), nome, tensao_v))

    def prod_adicionar_ponto_tensao(self, op_id, nome, esperado_v) -> dict:
        return self._chamar(lambda: T.adicionar_ponto_tensao(self._prod(), _id(op_id), nome,
                                                             esperado_v))

    # ---------- NCs ----------
    def prod_abrir_nc(self, op_id, tipo, descricao, operador) -> dict:
        return self._chamar(lambda: T.abrir_nc(self._prod(), _id(op_id), tipo,
                                               _texto(descricao, "a descrição"),
                                               self._operador(operador)))

    def prod_corrigir_nc(self, op_id, nc_id, operador, correcao="") -> dict:
        return self._chamar(lambda: T.corrigir_nc(self._prod(), _id(op_id), _id(nc_id),
                                                  self._operador(operador),
                                                  _texto(correcao, "a correção")))

    def prod_verificar_nc(self, op_id, nc_id, operador) -> dict:
        return self._chamar(lambda: T.verificar_nc(self._prod(), _id(op_id), _id(nc_id),
                                                   self._operador(operador)))

    # ---------- verificação final ----------
    def prod_sortear_amostra(self, op_id, verificador) -> dict:
        return self._chamar(lambda: T.sortear_amostra(self._prod(), _id(op_id),
                                                      self._operador(verificador)))

    def prod_marcar_amostra(self, op_id, linha_id, resultado, verificador, obs="") -> dict:
        return self._chamar(lambda: T.marcar_amostra(self._prod(), _id(op_id), _id(linha_id),
                                                     resultado, self._operador(verificador),
                                                     _texto(obs, "a observação")))

    def prod_marcar_checklist_final(self, op_id, indice, resultado, verificador) -> dict:
        return self._chamar(lambda: T.marcar_checklist_final(
            self._prod(), _id(op_id), indice, resultado, self._operador(verificador)))

    def prod_concluir_verificacao(self, op_id, verificador) -> dict:
        return self._chamar(lambda: T.concluir_verificacao(self._prod(), _id(op_id),
                                                           self._operador(verificador)))
