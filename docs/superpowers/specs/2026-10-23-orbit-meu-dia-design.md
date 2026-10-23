# Orbit: "Meu dia", anotações de projeto e lembretes

Documento de design. Data: 23/10/2026. Pedido de: Thiago Carlos.

Este documento complementa os designs anteriores ([2026-10-22-orbit-design.md](2026-10-22-orbit-design.md) e [2026-10-23-orbit-backup-design.md](2026-10-23-orbit-backup-design.md)), cujas regras continuam valendo.

Convenção: decisões do Thiago aparecem sem marcação. Decisões tomadas por mim (Claude), que ele pode revisar, aparecem marcadas com **[decisão do Claude]**.

---

## 1. Intenção e o porquê

O Thiago trabalha em vários projetos no mesmo dia e troca de um para outro algumas vezes. Ele quer que o Orbit também sirva para se organizar:

- **Lista do dia simples**, sem kanban: ele anota o que vai fazer e marca OK no que terminou.
- **Anotações por projeto**, para retomar rápido depois de trocar de projeto:
  - **insight**: uma ideia que dá para replicar em outros projetos;
  - **onde parei**: em que parte ele estava;
  - **pesquisar depois**;
  - **definição futura**: algo que ainda precisa ser decidido.
- **Anotações em qualquer lugar:** dá para anotar tanto na tela inicial (sobre qualquer projeto ou sobre nenhum) quanto dentro de um projeto. "Pesquisar depois" e "definição futura" também aparecem na lista do dia.
- **Lembretes** com data e hora, que aparecem como **notificação do Windows** mesmo com o Orbit minimizado. Podem ser recorrentes e têm botão de adiar.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos
- A tela inicial vira um **dashboard** (rascunho aprovado: `.superpowers/brainstorm/844-1792756537/content/dashboard-dia.html`).
- Lista "Meu dia" com adição rápida, tipos, projeto opcional e OK.
- Seção de anotações dentro do painel de cada projeto (e de cada máquina padrão).
- Lembretes únicos e recorrentes, com notificação nativa do Windows e botão de adiar.

### Não-objetivos
- **Kanban**, colunas, prioridades, estimativas ou responsáveis.
- **Lembretes com o Orbit fechado.** Só disparam com o programa aberto, inclusive minimizado.
- Compartilhar o "Meu dia" com outras pessoas: ele é pessoal.
- Calendário, integração com Outlook ou agenda.

### Anti-objetivos
- Ficar burocrático: adicionar uma atividade deve ser **digitar e apertar Enter**.
- Perder anotações na sincronização entre casa e empresa.
- Notificações que não aparecem quando o Orbit está minimizado (o motivo principal do pedido).

## 3. Conceitos

### Item (atividade ou anotação)
Um único tipo de registro, com estes campos:
- `id` (uuid);
- `tipo`: `atividade`, `pesquisar`, `definicao`, `insight` ou `onde_parei`;
- `texto`;
- `container_id`: o projeto ou máquina, ou vazio;
- `autor` (usuário e computador);
- `criado_em`, `alterado_em`;
- `dia`: a data em que foi criado ou planejado;
- `feito_em`: vazio até receber OK;
- `excluido` [decisão do Claude]: o item nunca é apagado de verdade, para a sincronização não "ressuscitar" itens. Ele só some das telas.

Quais tipos têm OK:
- **Têm OK:** atividade, pesquisar, definição.
- **Não têm OK:** insight e onde parei, que são anotações [decisão do Claude].

### Onde cada item aparece
- **Meu dia (dia D):**
  - atividades do dia D;
  - atividades **não feitas** de dias anteriores, que passam sozinhas para hoje [decisão do Claude];
  - todos os "pesquisar" e "definição" ainda sem OK, de qualquer projeto e de qualquer data.
  - Os itens feitos aparecem riscados no dia em que receberam OK.
- **Onde parei (dashboard):** a anotação "onde parei" mais recente de cada projeto, com data e hora.
- **Ideias para replicar (dashboard):** os insights de todos os projetos, do mais recente para o mais antigo, com o projeto de origem.
- **Painel do projeto:** todas as anotações daquele projeto, agrupadas por tipo, com o autor.
  - Ao abrir o projeto, a última anotação "onde parei" aparece numa faixa no topo [decisão do Claude].

### Quem vê o quê
- **Identidade:** o usuário é o nome de usuário do Windows. O Thiago confirmou que é o mesmo na empresa e em casa.
- **Atividades são sempre pessoais**, mesmo marcadas com um projeto. Nesse caso o projeto é só uma etiqueta [decisão do Claude].
- **Anotações de projeto são compartilhadas.** São os tipos pesquisar, definição, insight e onde parei, quando têm projeto. Ficam visíveis para quem abrir o projeto, com o autor.
- **Anotações sem projeto** são pessoais.
- **Mudar o projeto de uma anotação** move o registro de lugar, como uma única operação.
- **Meu dia:** mostra só os itens do próprio usuário, incluindo os pesquisar/definição que ele mesmo criou em projetos. Pendências de colegas não entram [decisão do Claude].
- **Onde parei (dashboard):** usa a anotação mais recente **do próprio usuário** em cada projeto [decisão do Claude]. A faixa no topo do painel do projeto mostra a mais recente de qualquer pessoa, com o autor.
- **Ideias para replicar:** aparecem os insights de todos.

## 4. Lembretes

- **Campos:**
  - `id`, `texto`;
  - `container_id` (opcional);
  - `quando` (data e hora);
  - `recorrencia`: nenhuma, diária, dias úteis, semanal (dias escolhidos) ou mensal (mesmo dia do mês) [decisão do Claude, sobre quais tipos];
  - `adiado_ate`, `ultimo_disparo`;
  - `ativo`, `excluido`.
- **Disparo:** com o Orbit aberto, um verificador em segundo plano confere a cada ~20 s se algum lembrete venceu. Quando vence:
  - mostra uma **notificação nativa do Windows** (toast), que aparece com a janela minimizada ou em segundo plano, com o texto, o projeto (se houver) e os botões **Adiar 10 min**, **Adiar 1 h** e **Concluir**;
  - mostra também um popup dentro do Orbit, caso a notificação do Windows falhe ou esteja bloqueada pelo "Não perturbe" [decisão do Claude].
- **Recorrência:** depois de disparar (ou de ser concluído), o próximo `quando` é calculado pela recorrência. Um lembrete sem recorrência fica concluído.
- **Lembretes perdidos:** um lembrete que venceu com o Orbit fechado aparece num popup "Lembretes perdidos" na próxima abertura [decisão do Claude]. Não há toast atrasado em série.
- **Vários computadores** [decisão do Claude]:
  - o lembrete dispara em qualquer computador onde o Orbit do usuário estiver aberto;
  - disparar, adiar ou concluir grava o estado, e a última alteração vence na sincronização;
  - um lembrete só conta como "perdido" se nenhum computador o tratou: o `ultimo_disparo` gravado é anterior ao vencimento;
  - com o Orbit aberto em dois computadores ao mesmo tempo, os dois podem avisar. Isso é aceito.
- **Pessoais:** os lembretes são só do usuário que os criou [decisão do Claude].
- **Telas:**
  - lista "Lembretes" no dashboard, com os próximos;
  - botão "+ Lembrete", que abre um popup com texto, data, hora, recorrência e projeto;
  - editar e excluir.

## 5. Armazenamento e sincronização

- **Anotações de projeto** ficam num arquivo próprio dentro da pasta do projeto, `anotacoes.json`, e não dentro de `projeto.json` [decisão do Claude].
  - Assim uma versão antiga do Orbit, que regrava `projeto.json` só com os campos que conhece, nunca apaga anotações.
  - O arquivo viaja com o projeto no backup e aparece para quem usa a pasta do servidor ao vivo.
- **Itens pessoais e lembretes** ficam em `<pasta base>\.orbit\usuarios\<usuario>\meu_dia.json` [decisão do Claude]. Ficar na pasta base faz o "Meu dia" acompanhar o Thiago da empresa para casa pela sincronização.
- **Junção na sincronização:** `anotacoes.json`, `meu_dia.json` e os lembretes são unidos **por `id`**, sem popup. A cópia com o `alterado_em` mais recente vence [decisão do Claude]. A sincronização de backup precisa tratar esses itens assim, e não como arquivos ou campos que viram divergência.
- **Gravação:** as alterações usam as mesmas travas e a releitura dentro da trava que o resto do Orbit já usa.
- **Log de ações:** registra criar, concluir e excluir **anotações de projeto**, mas não os itens pessoais [decisão do Claude].

## 6. Telas

- **Início (nova rota padrão `#/inicio`)**, conforme o rascunho aprovado:
  - **topo:** saudação com o nome do usuário do Windows, a data e quatro números:
  - **abertas hoje:** itens sem OK na lista "Meu dia" de hoje [decisão do Claude];
  - projetos ativos;
  - documentos pendentes;
  - estado do backup;
  - **coluna esquerda:**
    - **Meu dia:** campo de adição rápida, com o tipo (padrão: atividade) e o projeto (padrão: nenhum); Enter adiciona;
    - a lista com caixinha de OK e o nome do projeto embaixo;
    - navegação ontem ‹ › amanhã;
    - **Lembretes**;
  - **coluna direita:** **Onde parei** e **Ideias para replicar**.
- **"Clientes"** continua no menu, como hoje. O item **"Início"** entra no menu como primeiro.
- **Interações nos itens:**
  - clicar no texto edita na própria linha;
  - um menu ⋯ oferece excluir e mudar tipo ou projeto;
  - clicar no nome do projeto abre o painel dele.
- **Painel do projeto:**
  - nova seção "Anotações", com a mesma adição rápida (o projeto já vem preenchido) e a lista por tipo;
  - faixa "Onde parei: …" no topo quando houver.
- **"Documentos pendentes"** no dashboard é a soma, nos projetos ativos, dos documentos sem nenhuma revisão e que não estão marcados como "não se aplica" [decisão do Claude].

## 7. Restrições

- Mesma plataforma do Orbit: Windows, Python 3.14, pywebview 6.2.1, núcleo em `orbit/core` sem dependência da interface.
- **Notificação nativa do Windows:** precisa funcionar tanto rodando pelo Python quanto no `.exe`, com os botões de ação tratados pelo Orbit aberto. A biblioteca é escolha de quem constrói; sugestão: `windows-toasts`.
- Testes automáticos para:
  - regras de lista (o que aparece em cada dia, passagem para o dia seguinte);
  - recorrência (próximo disparo, dias úteis, fim de mês);
  - adiar;
  - lembretes perdidos;
  - junção por `id`.

## 8. O que fica com quem vai construir

- A biblioteca de notificação e o identificador de aplicativo (AppUserModelID) do `.exe`.
- O layout fino dentro do estilo aprovado.
- A frequência exata do verificador de lembretes.
- O formato interno de `meu_dia.json` e de `anotacoes.json`.
