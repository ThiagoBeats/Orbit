# Orbit: Backup, Sincronização, Log de Ações e Abertura: Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** acrescentar ao Orbit:
- backup configurável com espelhamento automático;
- sincronização em duas vias com popups de divergência;
- indicador de status do backup;
- log de ações com detecção de adulteração;
- recuperação (junção e PC novo);
- espaço LOGO oculto sem logo configurada;
- animação de abertura.

**Arquitetura:**
- **Núcleo novo em `orbit/core/`, sem dependência da interface:**
  - `actionlog.py`: log encadeado com âncora local.
  - `sync/`: varredura, retrato, junção de JSON, motor e resolução.
  - `backup.py`: configuração, espelhamento, status e recuperação.
- **Integração com o código existente:**
  - O `Repository` passa a avisar mudanças e a registrar no log os eventos novos de cada container, no `save_container`.
  - A `Api` liga tudo e expõe métodos novos ao JS.

**Tecnologias:** as mesmas do Orbit: Python 3.14, pywebview 6.2.1 e pytest 9.1.1. Hash com `hashlib.sha256` da biblioteca padrão. Nenhuma dependência nova.

**Spec:** [docs/superpowers/specs/2026-10-23-orbit-backup-design.md](../specs/2026-10-23-orbit-backup-design.md). Leia-a inteira antes da primeira tarefa. O design original ([2026-10-22-orbit-design.md](../specs/2026-10-22-orbit-design.md)) continua valendo. Referência visual da animação: `.superpowers/brainstorm/844-1792756537/content/abertura.html`, cartão **A**.

## Restrições globais

- **Nenhum arquivo do usuário é apagado ou sobrescrito, em nenhum dos lados.**
  - As exclusões permitidas são só estas: temporários `~orbit-*` do próprio Orbit dentro de uma transação que falhou, e travas e presença do próprio Orbit.
  - Mover para `Antigos` e para `_Divergências` é permitido.
- Toda cópia de arquivo entre lados usa temporário `~orbit-<uuid>.tmp` na pasta de destino + `os.rename`, que nunca sobrescreve. Uma interrupção no meio nunca deixa arquivo pela metade.
- **Exclusões nunca se propagam:** um arquivo que sumiu de um lado é restaurado a partir do outro.
- **Ficam fora da sincronização:**
  - `.orbit/presenca/` e `.orbit/travas/`;
  - arquivos `~orbit-*`;
  - pastas `_Divergências` em qualquer nível.
- **Clientes, projetos e máquinas são identificados pelo `id` do JSON**, não pelo nome da pasta.
- A operação local nunca espera nem falha por causa do backup: falhas no backup viram pendência.
- **Valores fixos:**
  - verificação periódica padrão de **10 minutos**;
  - trava de sincronização em `<backup>\.orbit\travas\_sincronizacao.lock`;
  - trava do log em `<base>\.orbit\travas\_log.lock`;
  - log em `<base>\.orbit\log\acoes.log`;
  - retrato em `%APPDATA%\Orbit\sync\<par>\`;
  - âncoras em `%APPDATA%\Orbit\ancoras.json`;
  - descartes em `<lado>\_Divergências\<AAAA-MM-DD_HHMMSS>\<caminho relativo>`.
- **Código de linha do log:** `sha256` do JSON canônico da linha sem o campo `codigo` (`sort_keys=True`, `ensure_ascii=False`, `separators=(",",":")`), em hexadecimal. A primeira linha de cada corrente usa `anterior = "0"*64`.
- Interface em pt-BR, com `esc()` em todo texto dinâmico. Sem animações fora da abertura.
- Testes nunca tocam o `%APPDATA%` real, nunca abrem programas (`os.startfile` com monkeypatch) e nunca fazem captura de tela inteira.
- Os commits terminam com uma linha em branco seguida de `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Foco de revisão

1. **Backup some no meio da sincronização** (HD desconectado): nenhum arquivo fica pela metade, os itens restantes ficam pendentes e o status passa a "inacessível". O teste fica na Tarefa 5.
2. **Arquivo aberto no Acrobat do lado do backup** na hora de mover para `Antigos`: o item é pulado como pendente e a sincronização não quebra. O teste fica na Tarefa 5.
3. **Mudanças diferentes no mesmo projeto, uma em cada lado** (Rev03 nova em casa e status de outro documento alterado no servidor): a junção acontece sem popup. O teste fica na Tarefa 4.
4. **Colega com upload em andamento no servidor**, usando a pasta ao vivo, durante a sincronização: o projeto é pulado e fica pendente, e os outros sincronizam. O teste fica na Tarefa 5.
5. **Pasta grande:** arquivos com tamanho e data de modificação inalterados não são reprocessados para calcular o hash. O teste fica na Tarefa 3.

---

## Estrutura de arquivos

```
orbit/core/actionlog.py        ← log encadeado, âncora, verificação, junção de logs
orbit/core/sync/__init__.py
orbit/core/sync/varredura.py   ← varrer árvore, exclusões, cache de hash, retrato (Retrato)
orbit/core/sync/mesclar.py     ← junção por item de projeto/máquina, cliente e config
orbit/core/sync/motor.py       ← SyncEngine: comparar, aplicar, travas, cancelamento, progresso
orbit/core/sync/resolver.py    ← resolução de divergências e _Divergências
orbit/core/backup.py           ← BackupService: configurar, espelhar, status, recuperar
orbit/core/config.py           ← (mod) UserSettings.backup, intervalo_backup_min
orbit/core/repository.py       ← (mod) ganchos de log e de mudança
orbit/ui/api.py                ← (mod) métodos de backup, sync, divergências, log, recuperação
orbit/ui/web/js/views/log.js           ← tela "Log de ações"
orbit/ui/web/js/popups/divergencia.js  ← popups de divergência
orbit/ui/web/js/popups/backup.js       ← status/progresso/recuperação
orbit/ui/web/js/abertura.js            ← animação de abertura
orbit/ui/web/js/app.js, views/clientes.js, views/config.js, index.html, css/orbit.css ← (mod)
tests/core/test_actionlog.py, test_varredura.py, test_mesclar.py, test_motor.py,
           test_resolver.py, test_backup.py
tests/ui/test_api_backup.py, test_api_log.py
```

---

## Marco 1: Log de ações

### Tarefa 1: Log encadeado com âncora local

**Arquivos:**
- Criar: `orbit/core/actionlog.py`
- Teste: `tests/core/test_actionlog.py`

**Interfaces:**
- **Consome:**
  - `PresenceService(identity, agora, registrar)` e `.travar(dir, tipo_id)` / `.liberar(trava)` / `.trava_abandonada` / `.liberar_abandonada` de `presence.py`. A trava do log é `travar(base, "_log")`, o que dá `base/.orbit/travas/_log.lock`.
  - `Identity`; `write_json_atomic` e `read_json` de `jsonstore.py`.
- **Produz:**
  - `LinhaLog`: dataclass com os campos `seq: str` (`"<computador>-<n>"`), `n: int`, `computador: str`, `usuario: str`, `data_hora: str` (ISO, segundos), `acao: str`, `detalhes: dict`, `anterior: str` e `codigo: str`.
    - Métodos `to_dict()`, `from_dict()` e `calcular_codigo() -> str`.
  - `ProblemaLog(computador: str, a_partir_de_n: int, descricao: str)`
  - `RelatorioLog(integro: bool, problemas: list[ProblemaLog])`
  - `class ActionLog(base: Path, identity: Identity, ancoras_path: Path, agora=datetime.now, registrar=None)`:
    - `caminho -> Path`: devolve `<base>/.orbit/log/acoes.log`.
    - `registrar_acao(acao: str, detalhes: dict) -> LinhaLog`. Acrescenta uma linha sob a trava do log, com `n` igual ao da última linha deste computador + 1, encadeada nela. Depois de gravar, atualiza a âncora em `ancoras_path`, na chave do caminho resolvido da base em minúsculas, com o valor `{computador: {"n", "codigo"}}`.
    - `ler() -> list[LinhaLog]`. Linhas ilegíveis viram `ProblemaLog` na verificação e não exceção.
    - `verificar() -> RelatorioLog`.
    - `alertar_se_adulterado() -> RelatorioLog`. Chama `verificar()` e, para cada problema **novo**, grava uma linha `"adulteracao_detectada"` com `{"computador", "a_partir_de_n", "descricao"}` e `anterior = "0"*64`. Isso reinicia a corrente deste computador.
  - `mesclar_logs(a: list[LinhaLog], b: list[LinhaLog]) -> tuple[list[LinhaLog], list[str]]`. Devolve a união por `seq`, ordenada por `(data_hora, seq)`, e a lista de `seq` em conflito (mesmo `seq` com conteúdo diferente).
- **Regras de verificação, por computador, em ordem de `n`:**
  - o `codigo` de cada linha bate com `calcular_codigo()`;
  - o `anterior` é o `codigo` da linha anterior desse computador;
  - os `n` são consecutivos.
  - Uma corrente reiniciada (`anterior` igual a `"0"*64`) só é legítima se for a 1ª linha do computador ou se a linha imediatamente anterior desse computador for `adulteracao_detectada`.
  - Âncora: se `ancoras_path` tem `{n, codigo}` para este computador e esta base, a linha `n` precisa existir com esse `codigo`.
  - "Problema novo" = ainda não existe uma linha `adulteracao_detectada` com o mesmo `(computador, a_partir_de_n)`.

- [ ] **Passo 1: escrever os testes que falham**

```python
def test_registra_e_encadeia(log):
    a = log.registrar_acao("revisao_enviada", {"x": 1}); b = log.registrar_acao("status_alterado", {})
    assert a.seq == "PC1-1" and b.seq == "PC1-2" and b.anterior == a.codigo and a.anterior == "0"*64
    assert log.verificar().integro

def test_editar_linha_e_detectado(log): ...        # muda "detalhes" no arquivo → integro False, a_partir_de_n == 1
def test_apagar_linha_do_meio_e_detectado(log): ... # 3 linhas, remove a 2ª → problema a partir de 2
def test_recalcular_corrente_inteira_pego_pela_ancora(log): ...  # reescreve tudo com códigos recalculados → integro False
def test_alerta_registra_uma_vez(log): ...          # alertar 2x → só 1 linha adulteracao_detectada; depois verificar() integro True
def test_dois_computadores_no_mesmo_arquivo(tmp_path): ...  # PC1 e PC2 intercalados → correntes separadas, integro
def test_mesclar_logs_uniao_e_conflito(): ...       # mesma seq com conteúdo diferente aparece em conflitos
def test_linha_ilegivel_nao_quebra(log): ...        # linha "lixo" → verificar() lista problema, ler() não lança
```

A fixture `log` usa `ActionLog(tmp_path/"base", Identity("thiago","PC1"), tmp_path/"ancoras.json", agora=<relógio fixo que avança 1 s>)`.

- [ ] **Passo 2:** `pytest tests/core/test_actionlog.py -v`. Esperado: FAIL (ImportError).
- [ ] **Passo 3:** implementar. A gravação abre o arquivo em modo `"a"`, com `encoding="utf-8"` e `newline="\n"`, grava uma linha e faz `flush` + `os.fsync`, tudo dentro da trava. Use retentativas em `PermissionError`, como em `presence._com_retentativas`.
- [ ] **Passo 4:** `pytest tests/core -v`. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: log de ações encadeado com âncora local`.

---

### Tarefa 2: Ganchos no Repository e na Api (log + aviso de mudança)

**Arquivos:**
- Modificar: `orbit/core/repository.py`, `orbit/ui/api.py`
- Teste: `tests/core/test_repository.py` (acréscimos), `tests/ui/test_api_log.py`

**Interfaces:**
- **Consome:** `ActionLog` (Tarefa 1).
- **Produz:**
  - `Repository.__init__(..., log: ActionLog | None = None, ao_alterar: Callable[[str, str | None], None] | None = None)`.
    - `ao_alterar(escopo, id)` recebe `escopo` em `"container" | "cliente" | "config"`. Ele é chamado **depois** de uma gravação bem-sucedida, e exceções dele são engolidas e registradas pelo `registrar` da Api.
  - `save_container` lê, dentro da trava, quantos eventos o JSON tinha no disco. Depois de gravar, chama `log.registrar_acao(ev.tipo, {**ev.dados, "container_id", "container_nome", "cliente_nome"})` para cada evento novo, e então `ao_alterar("container", c.id)`.
  - `create_cliente` / `update_cliente` registram `cliente_criado` / `cliente_alterado` e chamam `ao_alterar("cliente", id)`.
  - `create_projeto` / `create_maquina` registram `projeto_criado` / `maquina_criada`.
  - **Api:**
    - cria o `ActionLog` em `_abrir_base`, com âncoras em `%APPDATA%\Orbit\ancoras.json` (caminho injetável nos testes) e passa o log ao `Repository`;
    - registra `configuracao_alterada` em `salvar_tipos`, `salvar_status`, `definir_logo_empresa` e `set_tema`, e também `trava_liberada` em `liberar_trava`;
    - expõe `ler_log(filtros: dict) -> {"linhas": [...], "integridade": {...}}`, com filtros `de`, `ate` (ISO date), `usuario`, `container_id`, `acao` e `texto`;
    - expõe `verificar_log() -> RelatorioLog dict`, que chama `alertar_se_adulterado()`.
- Falha ao gravar no log **não** desfaz a operação: ela é registrada em `orbit.log`, e a operação devolve sucesso.

- [ ] **Passo 1: escrever os testes que falham.**
  - `test_upload_gera_linha_no_log`: `enviar_revisao` → existe uma linha `revisao_enviada` com `container_id`.
  - `test_eventos_ja_gravados_nao_se_repetem`: duas alterações seguidas geram 2 linhas, não 3.
  - `test_ao_alterar_chamado_apos_gravar`.
  - `test_falha_no_log_nao_desfaz_operacao`.
  - `test_api_ler_log_filtra_por_acao` e `test_api_verificar_log_alerta`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: tudo PASS.
- [ ] **Passo 5:** commit `feat: log de ações ligado ao repositório e à api`.

---

## Marco 2: Sincronização (núcleo)

### Tarefa 3: Varredura e retrato

**Arquivos:**
- Criar: `orbit/core/sync/__init__.py`, `orbit/core/sync/varredura.py`
- Teste: `tests/core/test_varredura.py`

**Interfaces:**
- **Produz:**
  - `InfoArquivo(tamanho: int, mtime_ns: int, hash: str)`
  - `excluido(rel: str) -> bool`. Aplica as exclusões das restrições globais, sem diferenciar maiúsculas. `rel` usa `/`.
  - `varrer(raiz: Path, cache: dict[str, InfoArquivo] | None = None, cancelar: Callable[[], bool] = lambda: False) -> dict[str, InfoArquivo]`.
    - Reaproveita o `hash` do cache quando `tamanho` e `mtime_ns` não mudaram.
    - Lê em blocos de 1 MiB.
  - `id_par(base: Path, backup: Path) -> str`: os primeiros 16 hexadecimais do `sha256` de `str(base.resolve()).lower() + "|" + str(backup.resolve()).lower()`.
  - `class Retrato(pasta: Path)`, com pasta = `%APPDATA%\Orbit\sync\<par>`:
    - `existe() -> bool`
    - `arquivos() -> dict[str, InfoArquivo]`
    - `json_base(rel: str) -> dict | None`: o conteúdo do JSON daquele caminho na última sincronização.
    - `salvar(arquivos: dict[str, InfoArquivo], jsons: dict[str, dict]) -> None`: grava de forma atômica `estado.json` e cada JSON em `json/<rel>`.
    - `divergencias_pendentes() -> list[dict]` e `salvar_divergencias(lista: list[dict]) -> None`.
    - `ultima_sync() -> str | None`.
- "JSON do Orbit" = `cliente.json`, `projeto.json`, `maquina.json`, `.orbit/config.json` e `.orbit/log/acoes.log`. O log é guardado como lista de linhas.

- [ ] **Passo 1: escrever os testes que falham.**
  - `test_exclusoes`: `.orbit/travas/x.lock`, `.orbit/presenca/a.json`, `P/~orbit-1.tmp` e `C/_Divergências/x.pdf` são excluídos; `.orbit/config.json` e `.orbit/log/acoes.log` não são.
  - `test_cache_evita_rehash`: monkeypatch de `hashlib.sha256` contando chamadas; a 2ª varredura sem mudanças tem 0 chamadas. Esse é o Foco de revisão 5.
  - `test_retrato_ida_e_volta`.
  - `test_id_par_estavel_e_insensivel_a_caixa`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: varredura e retrato da sincronização`.

---

### Tarefa 4: Junção por item dos JSONs

**Arquivos:**
- Criar: `orbit/core/sync/mesclar.py`
- Teste: `tests/core/test_mesclar.py`

**Interfaces:**
- **Consome:** `Container`, `Cliente`, `Revisao`, `Evento` (models) e `SharedConfig` (config).
- **Produz:**
  - `Divergencia`: dataclass com os campos:
    - `id: str`: uuid4 hex;
    - `tipo: str`: `"campo" | "revisao" | "arquivo" | "pasta_id" | "log"`;
    - `escopo_id: str | None`: o id do container ou do cliente;
    - `caminho: str`: o relativo, quando houver;
    - `chave: str`: por exemplo `"documentos.diagrama_eletrico.revisoes.3.status"`;
    - `descricao: str`: pt-BR;
    - `local: dict` e `backup: dict`: valor ou arquivo, mais `usuario`, `computador` e `data_hora`, quando houver;
    - `acoes: list[str]`: subconjunto de `"local"`, `"backup"`, `"ambos"`, `"juntar"`.

    Tem `to_dict()` e `from_dict()`.
  - `mesclar_container(base: dict | None, local: dict, backup: dict) -> tuple[dict, list[Divergencia]]`. Trabalha sobre dicionários `to_dict()` e devolve o JSON juntado, com as divergências **deixando o valor local** no resultado.
    - **Revisões:** união pelo `numero`. Uma revisão que só existe de um lado entra. O mesmo número com nomes de arquivo diferentes vira `Divergencia(tipo="revisao", acoes=["local","backup","ambos"])`.
    - **Campos de revisão** (`status`, `motivo`) e **campos do documento** (`nao_se_aplica`) e do container (`codigo`, `nome`, `pedido`, `responsavel`, `descricao`, `situacao`, `contatos`): regra de 3 vias. Igual ao `base` de um lado → vale o outro. Mudou dos dois lados com valores diferentes → `Divergencia(tipo="campo", acoes=["local","backup"])`. Sem `base` e com valores diferentes → divergência.
    - **`historico`:** união sem repetir, com a chave `(tipo, data_hora, usuario, computador, json canônico de dados)`, ordenada por `data_hora`.
    - **`arquivada`:** depois da união, só a revisão de maior número continua com `arquivada=False`. Essa regra domina a de 3 vias.
  - `mesclar_cliente(base, local, backup)` usa as mesmas regras, para `nome`, `cnpj` e `contatos`.
  - `mesclar_config(base, local, backup)`:
    - **tipos:** união por `id`, com 3 vias em `nome` e `ativo`;
    - **status:** união na ordem local, com os que só existem no backup no final;
    - **logo_empresa:** 3 vias.
  - `aplicar_escolha(juntado: dict, div: Divergencia, escolha: str, backup: dict) -> dict`. Para `"local"`/`"backup"` em divergências de `campo`, grava o valor escolhido na `chave`. A resolução de `revisao` e `arquivo` fica na Tarefa 6.

- [ ] **Passo 1: escrever os testes que falham.** Usam dicionários montados com `Container(...).to_dict()`.
  - `test_rev_nova_em_casa_e_status_no_servidor_sem_divergencia`: base tem Rev02; local tem Rev03 do Diagrama; backup mudou o status da Topologia. Resultado: Rev03 atual e Rev02 arquivada, status novo da Topologia, `divs == []`. Esse é o Foco de revisão 3.
  - `test_mesmo_campo_mudado_dos_dois_lados_diverge`.
  - `test_mesma_rev_arquivos_diferentes_diverge` (acoes `["local","backup","ambos"]`).
  - `test_sem_base_toda_diferenca_diverge_mas_novos_entram`.
  - `test_historico_uniao_sem_repeticao`.
  - `test_config_tipos_uniao`.
  - `test_aplicar_escolha_campo`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: junção por item dos JSONs`.

---

### Tarefa 5: Motor de sincronização

**Arquivos:**
- Criar: `orbit/core/sync/motor.py`
- Teste: `tests/core/test_motor.py`

**Interfaces:**
- **Consome:**
  - `varrer`, `Retrato`, `id_par` e `excluido` (Tarefa 3);
  - `mesclar_*` e `Divergencia` (Tarefa 4);
  - `mesclar_logs` (Tarefa 1);
  - `Repository` (`trava_container`) de **cada lado**, com um `Repository` para a base e outro para o backup;
  - `PresenceService.travar` / `liberar` / `caminho_trava`, e o `_Transacao` de `revisions.py` para mover arquivos para `Antigos`.
- **Produz:**
  - `Comparacao(enviar: list[str], receber: list[str], restaurar_local: list[str], restaurar_backup: list[str], containers: list[str], divergencias: list[Divergencia], identico: bool)`
  - `ResultadoSync(enviados: int, recebidos: int, restaurados: int, divergencias: list[Divergencia], pulados: list[str], cancelado: bool, erro: str | None)`
  - `class SyncEngine(base: Path, backup: Path, identity: Identity, retrato: Retrato, log: ActionLog, agora=datetime.now, registrar=None)`:
    - `comparar(cancelar=..., progresso: Callable[[str, int, int], None] = ...) -> Comparacao`. Só lê; não copia nada.
    - `sincronizar(cancelar=..., progresso=..., somente_container: str | None = None) -> ResultadoSync`:
      1. Pega a trava `_sincronizacao` no backup. Se ela estiver ocupada, lança `LockHeld("<usuario> (<computador>) está sincronizando com este backup; tente em instantes.")`.
      2. Varre os dois lados e o retrato.
      3. Containers, um por vez, identificados pelo `id`:
         - pega a trava do container **nos dois lados**; se um container estiver com uma trava de upload ativa de qualquer tipo ou não puder ser travado em 2 s, vai para `pulados`;
         - relê os dois JSONs dentro da trava;
         - aplica `mesclar_container`;
         - copia os arquivos de revisão que faltam para o local indicado pelo estado juntado;
         - move para `Antigos` os que passaram a arquivados;
         - grava o JSON juntado nos dois lados.
      4. Clientes e config (`mesclar_cliente`, `mesclar_config`).
      5. Log: `mesclar_logs`; os conflitos viram `Divergencia(tipo="log")` e o resultado é gravado de forma atômica nos dois lados.
      6. Demais arquivos (os não referenciados):
         - novo → copia;
         - sumiu de um lado e existia no retrato → restaura e registra `arquivo_restaurado`;
         - conteúdo diferente → `Divergencia(tipo="arquivo")`.
      7. Salva o retrato e as divergências pendentes. Registra `sincronizacao` com o resumo.
    - `somente_container`: limita os passos 3 e 6 ao container. É usado pelo espelhamento.
  - **Mesmo caminho de pasta com `id` diferente:** vira `Divergencia(tipo="pasta_id", acoes=["ambos","juntar"])`, e nenhum dos dois é tocado nesta rodada.
  - **Cópia entre lados:** `copiar_seguro(origem, destino)` usa temporário na pasta de destino + `os.rename`. Se o destino existir, lança `OrbitError` e nunca sobrescreve.
  - **Erros por item:**
    - `ArquivoEmUso`, `PermissionError` e `OrbitError` vão para `pulados`, com a mensagem, e a sincronização continua;
    - um `OSError` de "caminho não encontrado" no backup no meio do processo interrompe com `erro="Backup inacessível: ..."`, mantendo o que já foi concluído;
    - em ambos os casos o retrato só é atualizado para os itens concluídos.
  - O cancelamento é verificado entre itens.

- [ ] **Passo 1: escrever os testes que falham.** Os dois lados são pastas em `tmp_path` com `Repository` real.
  - `test_primeira_sync_backup_vazio_copia_tudo`.
  - `test_novo_de_cada_lado_vai_para_o_outro`.
  - `test_upload_em_casa_move_antiga_para_antigos_no_backup`.
  - `test_arquivo_apagado_pelo_explorer_e_restaurado`.
  - `test_nada_sobrescrito_nem_apagado`: snapshot de hashes de todos os arquivos antes e depois. Todo arquivo de antes existe depois, no mesmo lugar ou em `Antigos`.
  - `test_backup_some_no_meio` (Foco 1): monkeypatch de `copiar_seguro` que lança `FileNotFoundError` no 3º item → `erro` preenchido, sem `~orbit-*` nos dois lados, e uma nova `comparar()` ainda lista o resto.
  - `test_arquivo_em_uso_no_backup_vira_pulado` (Foco 2): handle aberto em um PDF do backup que precisa ir para `Antigos` → o container fica em `pulados` e os outros sincronizam.
  - `test_upload_ativo_no_servidor_pula_container` (Foco 4): uma trava de upload criada com `PresenceService` de outra identidade no backup → o container fica em `pulados`.
  - `test_trava_de_sincronizacao_ocupada`.
  - `test_pasta_mesma_com_ids_diferentes_diverge`.
  - `test_comparar_nao_altera_nada`.
  - `test_somente_container`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: motor de sincronização em duas vias`.

---

### Tarefa 6: Resolução de divergências

**Arquivos:**
- Criar: `orbit/core/sync/resolver.py`
- Teste: `tests/core/test_resolver.py`

**Interfaces:**
- **Consome:** `SyncEngine`, `Divergencia`, `aplicar_escolha`, `Retrato.divergencias_pendentes`, e o `RevisionService._nomes` / `_nomes_finais` para nomear revisões.
- **Produz:** `resolver(engine: SyncEngine, div_id: str, escolha: str) -> None`. A `escolha` precisa estar em `div.acoes`; caso contrário, `OrbitError`.
  - **`campo`:** grava o valor escolhido nos dois lados, sob a trava do container.
  - **`revisao` / `arquivo`:**
    - `"local"`: os arquivos do backup daquela revisão (ou o arquivo) vão para `<backup>\_Divergências\<data>\<rel>`, e os locais são copiados para o backup.
    - `"backup"`: o inverso.
    - `"ambos"`: os arquivos do backup entram nos dois lados como **próxima revisão livre** do documento, renomeados no padrão, com motivo `"Divergência de sincronização"`. Se ela for a maior, a atual vai para `Antigos`.
  - **`pasta_id`:**
    - `"ambos"`: o container do backup é copiado para a base numa pasta `<nome> (2)`, e o local é copiado para o backup numa pasta `<nome> (2)`. Os ids continuam diferentes.
    - `"juntar"`: une os dois com `mesclar_container(None, local, backup)`, mantendo o `id` local. A pasta do backup com o outro id vai inteira para `_Divergências`.
  - **`log`:** marcar como ciente; não há escolha de lado. A versão adulterada continua em `_Divergências`.
  - Remove a divergência das pendentes, registra `divergencia_resolvida` com `{div.tipo, chave/caminho, escolha}` e atualiza o retrato do item.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_resolver_campo_backup`;
  - `test_resolver_revisao_local_guarda_a_do_backup_em_divergencias`;
  - `test_resolver_ambos_vira_proxima_revisao`;
  - `test_resolver_pasta_id_ambos`;
  - `test_escolha_invalida`;
  - `test_nada_apagado_apos_resolver`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: resolução de divergências`.

---

### Tarefa 7: BackupService (configuração, espelhamento, status, recuperação)

**Arquivos:**
- Criar: `orbit/core/backup.py`
- Modificar: `orbit/core/config.py`
- Teste: `tests/core/test_backup.py`, `tests/core/test_config.py` (acréscimo)

**Interfaces:**
- **Consome:** `SyncEngine`, `Retrato`, `id_par`, `ActionLog`, `pasta_existe` (de `connection.py`) e `UserSettings`.
- **Produz:**
  - `UserSettings` ganha `backup: str | None = None` e `intervalo_backup_min: int = 10`, o intervalo limitado entre 1 e 1440.
  - `StatusBackup(estado: str, pendentes: int, divergencias: int, ultima_sync: str | None, erro: str | None)`, com `estado` em `"desativado" | "em_dia" | "diferente" | "inacessivel" | "sincronizando"`.
  - `class BackupService(base: Path, settings: UserSettings, identity, log: ActionLog, sync_dir: Path, agora=..., registrar=...)`:
    - `analisar_caminho(caminho: Path) -> str`. Devolve `"vazio"`, `"orbit"` ou `"estranho"`. Lança `OrbitError` se o backup estiver dentro da base, se a base estiver dentro do backup, ou se o caminho for inacessível.
    - `aviso_nuvem(caminho: Path) -> str | None`. Devolve a mensagem quando o caminho fica sob `OneDrive`, `Google Drive`, `Dropbox` ou `iCloudDrive`, comparando sem diferenciar maiúsculas e pelos componentes do caminho.
    - `configurar(caminho: Path) -> ResultadoSync`:
      - `"vazio"` → sincroniza, o que dá a cópia completa;
      - `"orbit"` → sincroniza sem retrato (junção);
      - `"estranho"` → `OrbitError("A pasta escolhida tem arquivos que não são do Orbit. Escolha uma pasta vazia ou um backup do Orbit.")`.

      Em seguida salva `settings.backup`.
    - `desativar() -> None`.
    - `espelhar(escopo: str, id: str | None) -> None`:
      - roda em thread daemon;
      - chama `SyncEngine.sincronizar(somente_container=id)` para containers ou uma sincronização de config/clientes para os outros escopos;
      - **não** abre popups;
      - divergências e falhas viram pendências;
      - nunca lança;
      - pedidos simultâneos são enfileirados, um de cada vez.
    - `status(forcar_comparacao: bool = False) -> StatusBackup`. Usa `pasta_existe` com tempo limite. `comparar()` é chamado no máximo a cada `intervalo_backup_min`, a menos que `forcar_comparacao`.
    - `enviar_pendencias_locais() -> None`. Quando o backup volta a ficar acessível, envia sozinho as alterações locais **sem divergência**, com `sincronizar` restrito aos containers que mudaram só no local.
    - `recuperar_juntando(caminho: Path) -> ResultadoSync`. Faz junção sem retrato com o caminho indicado e não muda `settings.backup`.
    - `restaurar_pc_novo(caminho_backup: Path, nova_base: Path) -> ResultadoSync`:
      - `nova_base` precisa estar vazia; caso contrário, `OrbitError`;
      - copia tudo (exceto exclusões) com `copiar_seguro`;
      - confere os hashes;
      - verifica o log.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_analisar_caminho_tres_casos_e_aninhado`;
  - `test_aviso_nuvem`;
  - `test_configurar_estranho_recusa`;
  - `test_espelhar_com_backup_fora_vira_pendente_e_nao_lanca`;
  - `test_status_estados`;
  - `test_enviar_pendencias_locais`;
  - `test_restaurar_pc_novo_pasta_nao_vazia_recusa`;
  - `test_restaurar_pc_novo_copia_e_confere`;
  - `test_recuperar_juntando_nao_muda_backup_configurado`;
  - `test_intervalo_limites` (config).
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: serviço de backup`.

---

## Marco 3: Interface

Os passos manuais rodam `python main.py` com APPDATA e base temporários. Nunca tire captura de tela inteira e nunca mexa em processos Orbit que já estavam abertos.

### Tarefa 8: Api e telas de backup (config, indicador, sincronizar, divergências, recuperação)

**Arquivos:**
- Criar: `js/popups/backup.js`, `js/popups/divergencia.js`
- Modificar: `orbit/ui/api.py`, `js/app.js`, `js/views/clientes.js`, `js/views/config.js`, `css/orbit.css`
- Teste: `tests/ui/test_api_backup.py`

**Interfaces:**
- **Consome:** `BackupService` (Tarefa 7) e `resolver` (Tarefa 6).
- **Produz** os métodos da Api, todos no padrão `_chamar`:
  - `status_backup(forcar=False)`;
  - `escolher_backup()`: diálogo de pasta; devolve `{caminho, analise, aviso_nuvem}`;
  - `configurar_backup(caminho)`;
  - `desativar_backup()`;
  - `sincronizar_backup()`: roda em thread; devolve na hora `{iniciado: true}`;
  - `progresso_backup()`: devolve `{fase, atual, total, rodando, resultado|null}`;
  - `cancelar_sincronizacao()`;
  - `listar_divergencias()`;
  - `resolver_divergencia(div_id, escolha)`;
  - `abrir_arquivo_divergencia(div_id, lado)`: o arquivo é resolvido pelo servidor a partir da divergência, nunca por caminho vindo do JS;
  - `recuperar_juntando()` (diálogo + junção);
  - `restaurar_pc_novo()` (diálogo do backup + diálogo da nova base; ao final pergunta se vira o backup configurado);
  - `definir_intervalo_backup(min)`.
- **Ligações:**
  - `_abrir_base` cria o `BackupService` e passa `ao_alterar=lambda e, i: backup.espelhar(e, i)` ao `Repository`.
  - Na abertura: `status_backup()` e `enviar_pendencias_locais()`, ambos em segundo plano.
- **UI:**
  - **Indicador** no cabeçalho, ao lado de `#conexao`, só com backup configurado. Textos: "Backup em dia" (`--ok`), "Backup diferente (N)" (`--warn`), "Backup inacessível" (`--pend`), "Sincronizando…" (`--info`). Clicar abre o popup de resumo, com o botão "Sincronizar agora".
  - **Timer JS** que chama `status_backup()` a cada `intervalo_backup_min`.
  - **Tela Clientes:** botão **Sincronizar** no topo (visível com backup configurado).
  - **Progresso** num popup com barra, "Comparando…" / "Copiando N de M…" e botão Cancelar. Ao fim, mostra o resumo e, se houver divergências, abre a primeira.
  - **Popup de divergência:** dois cartões lado a lado ("Nesta máquina" e "No backup") com valor ou arquivo, usuário, computador e data; botão Abrir para arquivos; botões só das `acoes` disponíveis, com os textos "Manter o desta máquina", "Manter o do backup", "Manter os dois" e "Juntar num só"; botão "Resolver depois". O cabeçalho mostra "Divergência 2 de 5".
  - **Configurações:** seção "Backup" com caminho, Escolher, Sincronizar agora, Desativar, intervalo (min), aviso de nuvem, "Recuperar backup" (Juntar com a pasta base / Restaurar num PC novo) e a hora da última sincronização.
  - **Boas-vindas** (sem pasta base): botão "Recuperar de um backup", que leva ao fluxo de PC novo.

- [ ] **Passo 1: escrever os testes de Api que falham:**
  - `test_status_desativado_sem_backup`;
  - `test_configurar_e_status_em_dia`;
  - `test_upload_espelha_no_backup` (espera o espelhamento com `join` exposto para teste);
  - `test_sincronizar_progresso_e_resultado`;
  - `test_resolver_divergencia_valida_escolha`;
  - `test_abrir_arquivo_divergencia_nao_aceita_caminho_do_js`;
  - `test_restaurar_pc_novo_api`.
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar a Api e o JS/CSS.
- [ ] **Passo 4:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 5: verificação manual.**
  - Configurar uma pasta temporária como backup, criar um projeto e subir um PDF: o arquivo aparece no backup e o indicador mostra "Backup em dia".
  - Renomear a pasta de backup: o indicador vira "inacessível".
  - Editar `projeto.json` do backup para criar uma divergência de status e clicar em Sincronizar: aparece o popup de divergência.
- [ ] **Passo 6:** commit `feat: telas de backup, sincronização e divergências`.

---

### Tarefa 9: Tela "Log de ações" e alerta de adulteração

**Arquivos:**
- Criar: `js/views/log.js`
- Modificar: `js/app.js` (rota `#/log`, item "Log" na navegação, chamada de `verificar_log` na abertura), `index.html`, `css/orbit.css`
- Teste: `tests/ui/test_api_log.py` (acréscimos, se a Api mudar)

**Interfaces:**
- **Consome:** `ler_log` e `verificar_log` (Tarefa 2).
- **Tela:**
  - Selo no topo: "Íntegro" (`--ok`) ou "Alterado fora do Orbit" (`--pend`), com o detalhe por computador.
  - Filtros por período, usuário, projeto/máquina e ação, mais um campo de busca.
  - Tabela com data/hora, usuário, computador, ação (rótulo pt-BR por `acao`) e detalhes resumidos.
  - **Sem** nenhum botão de editar ou apagar.
- **Abertura:** se `verificar_log` encontrar problemas, aparece o popup "O log de ações foi alterado fora do Orbit a partir da linha N (data aproximada)", com o botão "Ver log".

- [ ] **Passo 1:** escrever `test_ler_log_paginado`, que limita a 500 linhas por página e devolve `total`. Esperado: FAIL. Implementar. `pytest -q`: PASS.
- [ ] **Passo 2: verificação manual.** Registrar ações e conferir a tela. Editar `acoes.log` no Bloco de Notas e reabrir: aparecem o popup e o selo vermelho.
- [ ] **Passo 3:** commit `feat: tela do log de ações e alerta de adulteração`.

---

### Tarefa 10: LOGO oculto e animação de abertura

**Arquivos:**
- Criar: `js/abertura.js`
- Modificar: `index.html`, `css/orbit.css`, `js/app.js`

**Interfaces:**
- **LOGO:** `#logo-empresa` sem `.tem-logo` recebe `display:none`, incluindo a borda tracejada e o texto "LOGO". Com logo, fica como hoje.
- **Abertura:**
  - **Estrutura:** `abertura.js` exporta `iniciarAbertura(): { concluir(): Promise<void> }`. Uma camada `#abertura` (posição fixa, tela cheia, `background:var(--bg)`, `z-index` acima de tudo) já fica no `index.html` para aparecer no primeiro quadro.
  - **Sequência (A), ≈2,5 s, igual ao cartão A do rascunho:**
    1. a folha entra com `rotateY(-540deg) scale(.6)` → `none` em 1,2 s, com `cubic-bezier(.3,.7,.2,1)`;
    2. a órbita se desenha (`stroke-dasharray 0 300` → `20.3 7.5`) a partir de 0,5 s, com duração de 0,9 s, e depois passa a rodar (`stroke-dashoffset` até `-55.6` a cada 2,5 s, sem parar);
    3. o satélite aparece em 1,1 s e percorre a elipse com `animateMotion` em 2,5 s;
    4. "ORBIT" é digitado a partir de 1,5 s, à razão de 90 ms por letra, com cursor piscando.
  - **Cores:** as variáveis do tema; a logo usa as mesmas variáveis `--logo-*` do `orbit-logo.svg`.
  - **Fim:** `concluir()` espera o fim da sequência e então faz `opacity` de 1 para 0 em 300 ms e remove a camada. `app.js` chama `concluir()` depois do primeiro `recarregar()`. Se a carga demorar mais que a sequência, a órbita continua rodando até o `concluir()`.
  - **Pular:** clique ou qualquer tecla.
  - **`prefers-reduced-motion: reduce`:** logo parada e texto completo por 0,5 s.
  - **Escopo:** a animação aparece só na abertura do programa, não em `recarregar()` posteriores.

- [ ] **Passo 1: verificação manual.**
  - Abrir com APPDATA temporário: a sequência confere com o cartão A, e um clique pula a animação.
  - Tema claro: as cores seguem o tema.
  - Sem logo de empresa, o espaço LOGO não aparece; com logo, aparece.
  - Rodar `pytest -q` (sem regressão).
- [ ] **Passo 2:** commit `feat: abertura animada e espaço da logo oculto`.

---

### Tarefa 11: Executável e README

**Arquivos:**
- Modificar: `README.md`, `orbit.spec` (só se precisar)

- [ ] **Passo 1:** atualizar o README com as seções "Backup e sincronização", "Log de ações" e "Recuperação" (texto curto, como as demais), e atualizar o resumo de funcionalidades.
- [ ] **Passo 2:** `.venv\Scripts\pyinstaller orbit.spec --noconfirm`. Abrir `dist\Orbit\Orbit.exe` com APPDATA temporário: a animação toca e não aparece `orbit.log`.
- [ ] **Passo 3:** `pytest -q`. Esperado: tudo PASS.
- [ ] **Passo 4:** commit `docs: README com backup, log e recuperação`.
