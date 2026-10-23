# Orbit: Meu dia, Anotações e Lembretes: Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** a tela inicial vira um dashboard com a lista "Meu dia", anotações de projeto e lembretes com notificação nativa do Windows (recorrência e adiar).

**Arquitetura:**
- **Núcleo novo em `orbit/core/`:**
  - `meudia.py`: modelos, armazenamento e regras da lista e das anotações;
  - `lembretes.py`: regras de recorrência, vencimento e adiar.
- **Interface:**
  - `orbit/ui/notificacoes.py`: toast do Windows e o verificador em segundo plano;
  - a `Api` ganha um mixin, `api_meudia.py`.
- **Sincronização:** o motor passa a juntar `anotacoes.json` e `meu_dia.json` por `id`.

**Tecnologias:** Python 3.14, pywebview 6.2.1, pytest e a dependência nova **`windows-toasts==1.3.1`** (puxa os pacotes `winrt-*` 3.2.1, que têm versão para cp314).

**Spec:** [docs/superpowers/specs/2026-10-23-orbit-meu-dia-design.md](../specs/2026-10-23-orbit-meu-dia-design.md). Leia-a inteira antes da primeira tarefa. Rascunho aprovado da tela: `.superpowers/brainstorm/844-1792756537/content/dashboard-dia.html`.

## Restrições globais

- **Tipos de item:** `atividade`, `pesquisar`, `definicao`, `insight`, `onde_parei`. Os que têm OK são `atividade`, `pesquisar` e `definicao`.
- **Onde cada item é guardado:**
  - **atividade** (com ou sem projeto) e qualquer item **sem projeto** são pessoais. Ficam em `<base>\.orbit\usuarios\<usuario>\meu_dia.json`, onde `<usuario>` é `naming.sanitize(identity.usuario)`.
  - pesquisar, definição, insight e onde parei **com projeto** são compartilhados. Ficam em `<pasta do container>\anotacoes.json`.
- **Nada é apagado:** excluir marca `excluido=True`.
- **Sincronização:** junta por `id`. Se o mesmo `id` existe dos dois lados, vence o maior `alterado_em` (ISO, segundos); empate, vence o local. Nunca vira divergência.
- **Lembretes:**
  - recorrências `nenhuma`, `diaria`, `dias_uteis`, `semanal` (com `dias`, 0=segunda … 6=domingo) e `mensal`; no mensal, se o dia não existir no mês, cai no último dia;
  - adiar 10 min ou 60 min;
  - verificação a cada **20 s**;
  - só disparam com o Orbit aberto.
- **Notificação:** toast nativo do Windows com os botões "Adiar 10 min", "Adiar 1 h" e "Concluir", e também um popup dentro do Orbit.
- **Log de ações:** registra `anotacao_criada`, `anotacao_concluida` e `anotacao_excluida` só para anotações de projeto, nunca para itens pessoais.
- **Gravação:** JSONs com `write_json_atomic`.
  - `meu_dia.json` grava sob a trava `PresenceService.travar(<pasta do usuário>, "_meu_dia")`;
  - `anotacoes.json` grava sob `repo.trava_container(cid)`;
  - nos dois casos o arquivo é relido dentro da trava.
- **Geral:** interface em pt-BR, com `esc()` em todo texto dinâmico.
- **Testes:** nunca tocam o `%APPDATA%` real nem mostram toasts de verdade (o notificador é injetado).
- **Commits:** terminam com uma linha em branco seguida de `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Foco de revisão

1. **Virada da meia-noite com o Orbit aberto:** atividades não feitas aparecem no novo dia, sem duplicar. Teste na Tarefa 2.
2. **Recorrência mensal no dia 31:** um lembrete do dia 31 dispara em 30/04 e em 28/02 (29 em ano bissexto). Teste na Tarefa 3.
3. **O mesmo item editado em casa e na empresa:** depois de sincronizar, uma cópia só, com o texto mais recente. Teste na Tarefa 4.
4. **`meu_dia.json` corrompido:**
   - o dashboard mostra o erro e não quebra;
   - o Orbit **não** regrava o arquivo (o conteúdo do usuário não some).

   Teste na Tarefa 1.
5. **Computador suspenso por horas:**
   - um lembrete diário vencido vira **um** aviso, e o próximo disparo pula para a próxima data futura, sem disparar várias vezes;
   - um lembrete vencido antes da abertura aparece só como perdido.

   Testes na Tarefa 3.

---

## Estrutura de arquivos

```
orbit/core/meudia.py          ← Item, stores (pessoal e por projeto), MeuDiaService
orbit/core/lembretes.py       ← Lembrete, proximo(), vencidos(), disparar/adiar/concluir
orbit/core/sync/motor.py      ← (mod) junta anotacoes.json e meu_dia.json por id
orbit/ui/notificacoes.py      ← ToastNotificador (windows-toasts) e AgendaLembretes (thread)
orbit/ui/api_meudia.py        ← MeuDiaApiMixin
orbit/ui/api.py, app.py       ← (mod) liga o mixin, a agenda e o push para o JS
orbit/ui/web/js/views/inicio.js, js/popups/lembrete.js, js/views/painel.js (mod),
  js/app.js (mod), index.html (mod), css/orbit.css (mod)
tests/core/test_meudia.py, test_lembretes.py, test_motor.py (acréscimo)
tests/ui/test_api_meudia.py, test_notificacoes.py
```

---

### Tarefa 1: Itens e armazenamento

**Arquivos:**
- Criar: `orbit/core/meudia.py`
- Teste: `tests/core/test_meudia.py`

**Interfaces:**
- **Consome:** `Repository` (`container_path`, `trava_container`, `load_container`, `list_clientes`, `list_projetos`, `list_maquinas`), `PresenceService.travar` / `liberar_varios`, `jsonstore` e `naming.sanitize`.
- **Produz:**
  - `TIPOS`, `TIPOS_COM_OK`
  - `Item` (dataclass): `id`, `tipo`, `texto`, `container_id: str | None`, `usuario`, `computador`, `criado_em`, `alterado_em`, `dia` (ISO date), `feito_em: str | None = None`, `excluido: bool = False`, mais `to_dict()` e `from_dict()`.
  - `mesclar_por_id(a: list[dict], b: list[dict]) -> list[dict]`: a regra das restrições globais, na ordem de `criado_em`.
  - `class MeuDiaService(repo: Repository, identity, agora=datetime.now, log=None)`:
    - `adicionar(texto: str, tipo: str = "atividade", container_id: str | None = None, dia: date | None = None) -> Item`
    - `editar(item_id: str, texto: str | None = None, tipo: str | None = None, container_id: str | None = "__manter__") -> Item`. Se o destino mudar (pessoal ↔ projeto ou outro projeto), o item é **movido**: grava no destino e marca `excluido` na origem.
    - `marcar_feito(item_id: str, feito: bool) -> Item`, que lança `OrbitError` para os tipos sem OK.
    - `excluir(item_id: str) -> None`
    - `itens_pessoais() -> list[Item]`, `anotacoes(container_id: str) -> list[Item]` e `todas_anotacoes() -> list[Item]` (todos os containers legíveis). Nenhum deles devolve excluídos.
    - `caminho_pessoal -> Path`
  - **Validações:**
    - texto vazio → `OrbitError("Escreva o texto.")`;
    - tipo inválido → `OrbitError`;
    - container inexistente → `OrbitError`.
  - **Log:** com `log` presente, anotações de projeto geram `anotacao_criada`, `anotacao_concluida` e `anotacao_excluida`, com `container_id`, `tipo` e `texto`.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_atividade_com_projeto_fica_no_arquivo_pessoal`
  - `test_pesquisar_com_projeto_vai_para_anotacoes_do_projeto`
  - `test_item_sem_projeto_e_pessoal`
  - `test_mudar_projeto_move_o_item` (origem com `excluido`, destino com o mesmo `id`)
  - `test_ok_so_nos_tipos_que_tem_ok`
  - `test_excluir_esconde_sem_apagar`
  - `test_mesclar_por_id_vence_o_mais_recente`
  - `test_json_corrompido_nao_e_regravado` (Foco 4): `meu_dia.json` com `{quebrado` → `adicionar` lança `OrbitDataError` e o arquivo continua com `{quebrado`
  - `test_log_so_para_anotacao_de_projeto`
- [ ] **Passo 2:** `pytest tests/core/test_meudia.py -v`. Esperado: FAIL (ImportError).
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: tudo PASS.
- [ ] **Passo 5:** commit `feat: itens do Meu dia e anotações de projeto`.

---

### Tarefa 2: Consultas do dashboard

**Arquivos:**
- Modificar: `orbit/core/meudia.py`
- Teste: `tests/core/test_meudia.py`

**Interfaces:**
- **Produz** (métodos de `MeuDiaService`):
  - `lista_do_dia(dia: date) -> list[Item]`: itens do próprio usuário (pessoais e anotações de projeto que ele criou), sem os excluídos. Entra:
    - (a) atividade com `dia == D`;
    - (b) se `D` é hoje: atividades não feitas com `dia < D`;
    - (c) se `D >= hoje`: pesquisar e definição não feitos, de qualquer data;
    - (d) itens com `feito_em` no dia `D`.

    Sem repetir. A ordem é: não feitos primeiro, pela data de criação; depois os feitos.
  - `abertas_hoje() -> int`: não feitos de `lista_do_dia(hoje)`.
  - `onde_parei() -> list[dict]`: `[{container_id, container_nome, cliente_nome, item}]`, com o `onde_parei` mais recente **do próprio usuário** em cada container, do mais recente para o mais antigo.
  - `ultimo_onde_parei(container_id) -> Item | None`: de qualquer autor.
  - `ideias(limite: int = 50) -> list[dict]`: insights de todos, do mais recente para o mais antigo, com o nome do projeto de origem.
  - `docs_pendentes() -> int`: nos projetos e máquinas ativos, os documentos sem revisão atual e sem "não se aplica".
  - **Hoje** = `agora().date()`.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_lista_inclui_atividades_do_dia_e_pendencias`
  - `test_atividade_nao_feita_passa_para_hoje` (Foco 1): relógio em 23/10 23:59 adiciona; relógio em 24/10 00:01 → aparece uma vez em `lista_do_dia(24/10)`
  - `test_feito_aparece_riscado_no_dia_do_ok`
  - `test_pendencias_de_colegas_nao_entram`
  - `test_onde_parei_usa_o_meu_e_o_banner_usa_qualquer_um`
  - `test_ideias_de_todos_os_projetos`
  - `test_docs_pendentes_conta_so_ativos_e_aplicaveis`
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: consultas do dashboard`.

---

### Tarefa 3: Regras dos lembretes

**Arquivos:**
- Criar: `orbit/core/lembretes.py`
- Modificar: `orbit/core/meudia.py` (os lembretes ficam em `meu_dia.json`, na chave `lembretes`)
- Teste: `tests/core/test_lembretes.py`

**Interfaces:**
- **Produz:**
  - `Lembrete` (dataclass): `id`, `texto`, `container_id: str | None`, `usuario`, `quando` (ISO datetime, minutos), `recorrencia: dict` (`{"tipo": ..., "dias": [...]}`), `adiado_ate: str | None`, `ultimo_disparo: str | None`, `ativo: bool = True`, `excluido: bool = False`, `criado_em`, `alterado_em`, mais `to_dict()`, `from_dict()` e a propriedade `efetivo -> datetime` (é `adiado_ate`, se houver; senão, `quando`).
  - `proximo(quando: datetime, rec: dict) -> datetime | None`: `None` para `nenhuma`.
  - `avancar_ate_futuro(quando: datetime, rec: dict, agora: datetime) -> datetime | None`: aplica `proximo` até passar de `agora`.
  - `vencidos(lista: list[Lembrete], agora: datetime) -> list[Lembrete]`: ativos, não excluídos, com `efetivo <= agora` e (`ultimo_disparo` vazio ou anterior a `efetivo`).
  - `marcar_disparado(l: Lembrete, agora: datetime) -> Lembrete`: grava `ultimo_disparo` e limpa `adiado_ate`. Com recorrência, `quando` passa a ser `avancar_ate_futuro(...)`; sem recorrência, `ativo=False`.
  - `adiar(l, minutos: int, agora) -> Lembrete`: `adiado_ate = agora + minutos` e `ativo=True`. Os únicos valores aceitos são 10 e 60.
  - `concluir(l, agora) -> Lembrete`: com recorrência, mantém o próximo; sem recorrência, `ativo=False`.
  - **Métodos novos de `MeuDiaService`:**
    - `lembretes() -> list[Lembrete]`
    - `salvar_lembrete(dados: dict) -> Lembrete`, que cria ou edita conforme `id`. Valida o texto, `quando` no formato ISO, a recorrência e os `dias` de 0 a 6.
    - `excluir_lembrete(id)`
    - `aplicar(id, func)`, que grava o resultado de `marcar_disparado`, `adiar` ou `concluir` sob a trava.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_proximo_diario_e_dias_uteis` (sexta → segunda)
  - `test_semanal_nos_dias_escolhidos`
  - `test_mensal_dia_31_vai_para_o_ultimo_dia` (Foco 2): 31/03 → 30/04 → 31/05; 31/01/2028 → 29/02/2028
  - `test_vencido_uma_vez_so`
  - `test_suspenso_por_horas_dispara_uma_vez_e_avanca` (Foco 5): diário às 09:00, agora três dias depois às 15:00 → `vencidos` tem 1 item; depois de `marcar_disparado`, `quando` é amanhã às 09:00
  - `test_adiar_10_e_60`
  - `test_adiar_valor_invalido`
  - `test_concluir_nao_recorrente_desativa`
  - `test_salvar_lembrete_valida`
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: regras dos lembretes`.

---

### Tarefa 4: Sincronização de anotações e do Meu dia

**Arquivos:**
- Modificar: `orbit/core/sync/motor.py`
- Teste: `tests/core/test_motor.py`

**Interfaces:**
- **Consome:** `mesclar_por_id` (Tarefa 1).
- **Regra:** no passo "demais arquivos", um arquivo chamado `anotacoes.json` (em qualquer pasta) ou um `.orbit/usuarios/<x>/meu_dia.json` existente nos dois lados com conteúdo diferente **não** vira divergência:
  - os dois lados são lidos e juntados com `mesclar_por_id`, separadamente para as listas `notas`, `itens` e `lembretes`;
  - o resultado é gravado nos dois lados com `write_json_atomic`;
  - um arquivo ilegível de um lado é tratado como divergência de arquivo comum, sem juntar.
  - Se o arquivo existe só de um lado, é copiado como hoje.

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_anotacoes_dos_dois_lados_sao_unidas`
  - `test_mesmo_item_editado_nos_dois_lados_fica_o_mais_recente` (Foco 3)
  - `test_meu_dia_unido_sem_divergencia`
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: anotações e Meu dia unidos por id na sincronização`.

---

### Tarefa 5: Notificação do Windows e verificador

**Arquivos:**
- Criar: `orbit/ui/notificacoes.py`
- Modificar: `requirements.txt` (`windows-toasts==1.3.1`)
- Teste: `tests/ui/test_notificacoes.py`

**Interfaces:**
- **Produz:**
  - `class ToastNotificador`, com:
    - `disponivel() -> bool`
    - `mostrar(l: Lembrete, ao_acao: Callable[[str], None]) -> None`, onde a ação é `"adiar10"`, `"adiar60"` ou `"concluir"`.

    O import de `windows_toasts` fica dentro dos métodos. Qualquer exceção vira `False` ou é ignorada (registrada por um `registrar` opcional).
  - `class AgendaLembretes(servico: MeuDiaService, notificadores: list, agora=datetime.now, intervalo_s: float = 20, ao_perdidos: Callable[[list[Lembrete]], None] = ...)`:
    - `iniciar()` e `parar()`, numa thread daemon;
    - `verificar_agora()`, a rodada única, que existe para os testes.
  - **Primeira rodada:** os vencidos com `efetivo` anterior ao início da agenda vão para `ao_perdidos`, uma vez, e são marcados com `marcar_disparado`. Não viram toast.
  - **Demais rodadas:** cada vencido chama `mostrar` em todos os notificadores e depois `marcar_disparado`.
  - **Ações:** `ao_acao` chama `servico.aplicar(id, adiar/concluir)`.

- [ ] **Passo 1: escrever os testes que falham.** Usam um notificador falso que guarda as chamadas.
  - `test_vencido_mostra_e_marca`
  - `test_perdidos_na_primeira_rodada_nao_viram_toast`
  - `test_acao_adiar_reagenda`
  - `test_toast_indisponivel_nao_quebra` (com o import de `windows_toasts` falhando)
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar. Instalar a dependência no venv.
- [ ] **Passo 4:** rodar os testes. Esperado: PASS.
- [ ] **Passo 5: verificação manual.** Rodar `python -c` com um `ToastNotificador().mostrar(...)` de exemplo e conferir que o toast aparece com os 3 botões. É o único passo que mostra um toast de verdade; descreva o resultado no relatório.
- [ ] **Passo 6:** commit `feat: notificação do Windows para lembretes`.

---

### Tarefa 6: Api do Meu dia

**Arquivos:**
- Criar: `orbit/ui/api_meudia.py`
- Modificar: `orbit/ui/api.py` (herda o mixin; `_abrir_base` cria o `MeuDiaService` com o log e inicia a `AgendaLembretes`), `orbit/ui/app.py` (push para o JS)
- Teste: `tests/ui/test_api_meudia.py`

**Interfaces:**
- **Produz** os métodos da Api, todos no padrão `_chamar`:
  - `dashboard(dia_iso: str | None = None)`: devolve `{usuario, hoje, dia, numeros: {abertas_hoje, projetos_ativos, docs_pendentes}, itens: [...], lembretes: [próximos 10 ativos], onde_parei: [...], ideias: [...], erro_meu_dia: str | None}`. Com `meu_dia.json` corrompido, `itens`/`lembretes` vêm vazios e `erro_meu_dia` traz a mensagem.
  - `adicionar_item(dados)`, `editar_item(id, dados)`, `marcar_item(id, feito)`, `excluir_item(id)`: validam os tipos que chegam do JS.
  - `anotacoes_projeto(container_id)`: devolve `{anotacoes: [...], onde_parei: item | null}`.
  - `listar_lembretes()`, `salvar_lembrete(dados)`, `excluir_lembrete(id)`.
  - `acao_lembrete(id, acao)`, com `acao` em `adiar10`, `adiar60` ou `concluir`.
  - **Push para o JS:** a `AgendaLembretes` recebe um notificador "na janela", que chama `janela.evaluate_js("orbitLembrete(<json>)")`. Os perdidos vão por `orbitLembretesPerdidos(<json>)`. Os dois só disparam com a janela definida.
  - **Fechamento:** `ao_fechar_janela` para a agenda.
  - **Projetos ativos:** são os containers com `situacao == "ativo"` (clientes e máquinas).

- [ ] **Passo 1: escrever os testes que falham:**
  - `test_dashboard_basico`
  - `test_adicionar_e_marcar_pela_api`
  - `test_tipos_invalidos_do_js`
  - `test_dashboard_com_meu_dia_corrompido`
  - `test_lembrete_pela_api_e_acao`
  - `test_anotacoes_projeto_com_onde_parei`
- [ ] **Passo 2:** rodar os testes. Esperado: FAIL.
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 5:** commit `feat: api do Meu dia e lembretes`.

---

### Tarefa 7: Telas (dashboard, anotações no projeto, lembretes)

**Arquivos:**
- Criar: `js/views/inicio.js`, `js/popups/lembrete.js`
- Modificar: `js/app.js`, `js/views/painel.js`, `index.html`, `css/orbit.css`

**Interfaces:**
- **Menu e rota:** `#/inicio` passa a ser a rota padrão e o primeiro item do menu, "Início". "Clientes" continua como está.
- **Início** (igual ao rascunho aprovado):
  - **topo:** "Bom dia/Boa tarde/Boa noite, <usuário>", a data por extenso e os quatro números; o do backup usa `Orbit.backup`;
  - **coluna esquerda:**
    - **Meu dia:** campo com Enter para adicionar e seletores de tipo e projeto (a lista vem de `listar_clientes` / `obter_cliente` / `listar_maquinas`); a navegação ‹ › entre dias;
    - itens com caixinha de OK (só nos tipos com OK), etiqueta do tipo e projeto clicável;
    - clicar no texto edita na linha (Enter salva, Esc cancela);
    - menu ⋯ com excluir e mudar tipo/projeto;
    - **Lembretes**, com o botão "+ Lembrete";
  - **coluna direita:** **Onde parei** (clicar abre o projeto) e **Ideias para replicar**.
  - **Recarregamento:** o dashboard é recarregado à meia-noite, por um timer que calcula o tempo até a virada.
- **Painel do projeto:**
  - faixa "Onde parei: <texto> — <autor>, <data>" no topo;
  - seção "Anotações" com adição rápida (projeto fixo, tipo padrão "onde parei") e a lista agrupada por tipo.
- **Popup de lembrete:** texto, data, hora, recorrência (nenhuma / diária / dias úteis / semanal com os 7 dias marcáveis / mensal) e projeto opcional.
- **Avisos no Orbit:**
  - `window.orbitLembrete(l)` abre um popup "Lembrete" com os botões Adiar 10 min, Adiar 1 h e Concluir;
  - `window.orbitLembretesPerdidos(lista)` abre "Lembretes perdidos", com a lista e um botão Concluir por item.

- [ ] **Passo 1:** implementar. Conferir com `node --check` em todos os JS alterados.
- [ ] **Passo 2: verificação manual.** Abrir `python main.py` com APPDATA e base temporários e conferir:
  - o Início aparece primeiro e adicionar com Enter funciona;
  - o OK risca o item;
  - a anotação no projeto aparece no painel e no dashboard;
  - um lembrete para daqui a 1 min aparece como toast e popup, também com o Orbit minimizado.
- [ ] **Passo 3:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 4:** commit `feat: dashboard Meu dia, anotações no projeto e lembretes`.

---

### Tarefa 8: Executável e README

**Arquivos:**
- Modificar: `orbit.spec` (`hiddenimports` dos módulos `winrt` se o PyInstaller não achar), `README.md`

- [ ] **Passo 1:** README:
  - nova seção "Meu dia, anotações e lembretes";
  - "Início" no resumo de funcionalidades;
  - limitação: lembretes só com o Orbit aberto.
- [ ] **Passo 2:** `pyinstaller orbit.spec --noconfirm`. Abrir `dist\Orbit\Orbit.exe` com APPDATA temporário, criar um lembrete para 1 min e conferir o toast. Registrar o resultado.
- [ ] **Passo 3:** `pytest -q`. Esperado: PASS.
- [ ] **Passo 4:** commit `docs: README com Meu dia e lembretes`.
