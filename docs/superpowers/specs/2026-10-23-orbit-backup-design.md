# Orbit: Backup, sincronização, log de ações e abertura animada

Documento de design. Data: 23/10/2026. Pedido de: Thiago Carlos.

Este documento complementa o design original ([2026-10-22-orbit-design.md](2026-10-22-orbit-design.md)), cujas regras continuam valendo. A principal delas: **nenhum arquivo do usuário é apagado ou sobrescrito, nunca**.

Convenção: decisões do Thiago aparecem sem marcação. Decisões tomadas por mim (Claude), que ele pode revisar, aparecem marcadas com **[decisão do Claude]**.

---

## 1. Intenção e o porquê

O Thiago vai manter um **backup da pasta base num servidor da empresa**. A pasta também pode ficar num HD externo ou numa pasta de nuvem.

Ele trabalha na empresa e às vezes em casa. Em casa o servidor fica inacessível, mas ele continua alterando documentos normalmente. Ao voltar para a empresa, ele quer **sincronizar**: o que mudou em casa vai para o servidor, e o que mudou no servidor (inclusive por colegas que também sincronizam com ele) vem para a máquina dele. O resultado esperado é ter sempre os dados atualizados, nos dois lugares.

Além disso:
- Ele quer um **log de ações** que ninguém consiga adulterar sem ser descoberto, para saber quem substituiu um documento.
- Ele quer poder **recuperar** dados a partir de um backup: tanto juntando com a pasta base atual quanto montando tudo do zero num PC novo.
- O espaço vazio "LOGO" no cabeçalho deve sumir quando não houver logo de empresa configurada.
- Ao abrir o programa, ele quer uma **animação da logo do Orbit**.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos
- Caminho de backup configurável em Configurações.
- **Espelhamento automático:** cada alteração feita pelo Orbit também é aplicada no backup.
- **Sincronização em duas vias**, sob demanda e verificada periodicamente, com popups para as divergências.
- **Indicador de status do backup** no cabeçalho.
- **Recuperação** em dois modos: junção com a pasta base atual, ou restauração completa numa pasta base nova.
- **Log de ações** à prova de adulteração silenciosa: detecta e alerta.
- Espaço LOGO escondido sem logo configurada.
- Animação de abertura (opção A aprovada).

### Não-objetivos
- **Impedir** a edição ou exclusão do log. Numa pasta comum isso não é possível sem servidor ou banco. O Thiago aceitou **detectar e alertar**.
- **Monitorar ações feitas pelo Explorer.** Se alguém apagar ou trocar arquivos fora do Orbit, o Orbit não vigia isso em tempo real. A sincronização vai mostrar as diferenças, mas não identifica o autor.
- Versionamento de backup no tempo, como "voltar o backup para o dia 10". O backup é um espelho que se junta com a pasta base, não um histórico de cópias.
- Agendamento de backup fora do Orbit (serviço do Windows). A verificação só roda com o programa aberto.

### Anti-objetivos
- **Sobrescrever ou apagar dados**, de qualquer um dos lados, numa sincronização ou recuperação.
- **Transformar toda diferença em popup.** Se só um lado mudou algo, o Orbit aplica sozinho. Popup é só para quando os dois lados mudaram a mesma coisa.
- Sincronização que trava o programa ou deixa o backup pela metade sem avisar.
- Animação de abertura que atrasa quem abre o programa várias vezes por dia.

## 3. Restrições

- Mesma plataforma do Orbit atual: Windows, Python 3.14 e pywebview 6.2.1, com núcleo em `orbit/core` sem dependência da interface.
- O backup é **uma pasta comum** (rede/SMB, HD externo ou pasta sincronizada de nuvem). Nada de serviço próprio no servidor.
- Várias máquinas podem sincronizar com o **mesmo** backup. O servidor funciona como ponto de encontro.
- **A pasta de backup pode ser, ao mesmo tempo, a pasta base "ao vivo" de outras pessoas.** Elas abrem a pasta do servidor direto no Orbit e trabalham nela enquanto outras máquinas sincronizam com ela. Toda a sincronização tem de funcionar com o backup mudando durante o processo (seção 5, "Concorrência").
- A pasta base e o backup podem ficar inacessíveis a qualquer momento (rede caiu, HD desconectado).
- **Pastas de nuvem (OneDrive etc.):** funcionam como backup de **uma** máquina. Com várias máquinas sincronizando pela mesma pasta de nuvem, as travas chegam atrasadas aos outros computadores. Por isso o Orbit mostra um aviso ao configurar um caminho dentro de uma pasta de nuvem conhecida, mas não bloqueia [decisão do Claude].

## 4. Backup: configuração e espelhamento

### Configuração
- Em **Configurações** há a seção "Backup", com o caminho da pasta de backup, os botões "Escolher", "Sincronizar agora" e "Desativar", e o intervalo de verificação.
- O caminho do backup é uma **preferência da máquina**, salva em `%APPDATA%\Orbit\settings.json` junto com a pasta base [decisão do Claude]. Cada computador aponta para o backup do seu jeito, por exemplo com uma letra de unidade diferente.
- O backup não pode ficar dentro da pasta base, nem a pasta base dentro do backup. Ambos são recusados com mensagem clara.
- **Ao configurar:**
  - Se o caminho estiver vazio, o Orbit faz a primeira cópia completa.
  - Se já tiver dados do Orbit (existe `.orbit/config.json`), ele **não sobrescreve nada**: oferece apenas **"Juntar"**, a sincronização em duas vias da seção 5.
  - Se tiver arquivos que não são do Orbit, ele recusa e pede uma pasta vazia ou um backup do Orbit [decisão do Claude].

### Espelhamento automático
- Toda operação que altera a pasta base (upload, importação, registro, status, "não se aplica", dados, e-mail preparado, configurações, criação de cliente/projeto/máquina) é **também aplicada no backup** logo depois de concluída localmente, com as mesmas regras de nunca sobrescrever.
- **A operação local nunca espera nem falha por causa do backup** [decisão do Claude]. Se o backup estiver inacessível ou a cópia falhar, a alteração fica registrada como **pendente**. O indicador mostra "Backup diferente", e a próxima sincronização resolve.
- O espelhamento é uma "mini-sincronização" restrita ao container (ou à configuração) que mudou [decisão do Claude]. Assim ele segue as mesmas regras da seção 5 e não precisa de uma lógica separada.

## 5. Sincronização em duas vias

### Princípio
Para saber **quem mudou o quê**, o Orbit guarda localmente um **retrato da última sincronização**: o conteúdo dos JSONs e a lista de arquivos com tamanho e código de conteúdo (hash). Ele fica em `%APPDATA%\Orbit\sync\<identificador do par pasta base + backup>\` [decisão do Claude]. Fica fora da pasta base para não ser copiado para o backup.

Comparando cada lado com esse retrato:

| Situação | O que o Orbit faz |
| :--- | :--- |
| Mudou só na pasta base | Copia para o backup, sem perguntar |
| Mudou só no backup | Traz para a pasta base, sem perguntar |
| Existe só de um lado (novo) | Copia para o outro, sem perguntar |
| Mudou dos dois lados, e de forma diferente | **Divergência**: popup |
| Mudou dos dois lados, e de forma igual | Nada a fazer |

Sem retrato (primeira junção de um backup que já tinha dados, ou recuperação por junção), toda diferença entre os dois lados é tratada como divergência, com exceção dos itens que só existem de um lado. Esses são copiados.

### Como os itens são identificados [decisão do Claude]
- **Clientes, projetos e máquinas são identificados pelo `id`** gravado no JSON, não pelo nome da pasta. Um projeto com o mesmo `id` em pastas de nomes diferentes nos dois lados é o mesmo projeto. Ele é sincronizado, e cada lado mantém o nome de pasta que já tinha.
- **Mesmo caminho de pasta com `id` diferente** (dois projetos criados separadamente com o mesmo código e nome): vira divergência. As opções são "Manter os dois" (o que vem do outro lado entra numa pasta com sufixo ` (2)`) ou "Juntar num só", que une revisões e histórico pela regra dos JSONs e mantém o `id` desta máquina.
- **Arquivos de documento são guiados pelo JSON.** A posição de cada arquivo de revisão (pasta do tipo ou `Antigos`) segue o estado juntado da revisão (atual ou arquivada). Uma revisão que ficou arquivada de um lado tem seus arquivos **movidos** para `Antigos` do outro lado também. Mover para `Antigos` é permitido; apagar, não.

### Arquivos de documento
- Arquivos de revisão nunca são sobrescritos. Um arquivo que existe só de um lado é **copiado** para o outro, no lugar indicado pelo estado juntado da revisão.
- **O mesmo caminho com conteúdo diferente nos dois lados é sempre uma divergência.** Exemplo: as duas máquinas criaram uma `Rev03` diferente do mesmo documento.
- **Arquivo que sumiu de um lado** e estava lá na última sincronização: se não foi para `Antigos` pelo Orbit, alguém apagou ou moveu pelo Explorer. O Orbit **copia de volta** a partir do outro lado e registra no log "arquivo restaurado na sincronização". Exclusões nunca se propagam [decisão do Claude].
- **Arquivos que o Orbit não controla** dentro da pasta base (por exemplo um `.txt` solto numa pasta de projeto) também são sincronizados, com as mesmas regras: novo é copiado, sumido é restaurado, diferente vira divergência [decisão do Claude]. Ficam de fora apenas os arquivos de presença, as travas, os temporários `~orbit-*` e a pasta `_Divergências`.

### JSONs (projeto, máquina, cliente, config)
A junção é **por item**, não pelo arquivo inteiro [decisão do Claude]:
- **Revisões** de um documento: são unidas pelo número. Uma revisão que existe só de um lado é acrescentada. O mesmo número com arquivos diferentes vira divergência.
- **Histórico (eventos):** sempre unido, sem perguntar, porque eventos só são acrescentados. A ordem é pela data/hora, e eventos repetidos não entram de novo.
- **Campos simples** (status de uma revisão, "não se aplica", dados do projeto, contatos, nome do cliente, tipos e status da configuração): mudou de um lado só, vale essa mudança; mudou dos dois lados com valores diferentes, vira divergência.
- **Revisão atual:** depois da junção, a atual de cada documento é a de maior número não arquivada. Se cada lado tinha uma atual diferente, a de número menor passa a "arquivada" e seus arquivos vão para `Antigos` com as regras de sempre.

### Divergências: os popups
- Cada divergência é mostrada num popup com os **dois lados lado a lado**: valor ou arquivo, data, usuário e computador da última alteração, quando disponível. Arquivos têm botão para abrir.
- As ações oferecidas dependem do caso:
  - **Campo simples:** "Manter o desta máquina" ou "Manter o do backup".
  - **Mesma revisão com arquivos diferentes:** "Manter o desta máquina", "Manter o do backup" ou "Manter os dois". "Manter os dois" faz a versão do backup virar a **próxima revisão livre** do documento, com o motivo "Divergência de sincronização". Se essa revisão for a de maior número, a atual vai para `Antigos`, com as regras de sempre.
- A versão descartada **nunca é apagada**. Ela vai para `<lado onde foi descartada>\_Divergências\<data-hora>\<caminho relativo original>` [decisão do Claude].
- O usuário pode resolver as divergências agora, uma a uma, ou **"Resolver depois"**. Nesse caso elas ficam listadas e o indicador continua "Backup diferente".
- Toda resolução vira uma linha no log de ações (seção 7).

### Quando roda
- **Sob demanda:** o botão **Sincronizar** na tela principal (Clientes), o clique no indicador e "Sincronizar agora" em Configurações.
- **Verificação periódica:** a cada **10 minutos** [decisão do Claude], configurável em Configurações, e também na abertura do programa.
  - A verificação **só compara** e atualiza o indicador. Ela não copia nada sozinha.
  - **Exceção:** alterações pendentes desta máquina que não têm divergência são enviadas automaticamente quando o backup volta a ficar acessível [decisão do Claude], porque são o espelhamento atrasado.

### Concorrência
- A sincronização usa as travas que já existem, **nos dois lados**: a trava de gravação por projeto durante a junção do JSON de cada projeto, e a trava de upload por documento durante a cópia de arquivos.
  - Como o backup pode ser a pasta base ao vivo de outras pessoas, cada projeto é **relido dentro da trava** antes da junção.
  - Um projeto que está com upload em andamento por outra pessoa é **pulado nesta rodada** e fica como pendente. A sincronização não espera.
- Uma trava de sincronização por backup (`<backup>\.orbit\travas\_sincronizacao.lock`) impede que duas máquinas sincronizem com o mesmo backup ao mesmo tempo. A segunda recebe "Fulano está sincronizando; tente em instantes". Ela **não bloqueia** quem usa o backup como pasta base ao vivo, porque essas pessoas são coordenadas pelas travas por projeto e por documento.
- Arquivos de presença e de trava nunca são copiados entre os lados.
- A sincronização mostra progresso: "Comparando…", "Copiando 12 de 40…". Ela pode ser cancelada entre um item e outro, sem deixar nada pela metade: cada item é uma transação, como o upload.

## 6. Indicador de status do backup

- Só aparece com backup configurado. Fica no cabeçalho, ao lado do indicador de conexão, com o mesmo estilo (ponto colorido + texto):
  - **Backup em dia** (verde): os dois lados estão iguais;
  - **Backup diferente** (âmbar): há pendências ou divergências, com o número delas;
  - **Backup inacessível** (vermelho): não foi possível acessar a pasta de backup;
  - **Sincronizando…** (azul).
- Clicar abre um popup com o resumo (o que vai para o backup, o que vem do backup, as divergências e a hora da última sincronização) e o botão "Sincronizar agora".

## 7. Log de ações

### Onde e o quê
- Fica em um arquivo geral da pasta base, `<base>\.orbit\log\acoes.log`, com **uma linha JSON por ação**, sempre acrescentada no final e nunca reescrita.
- Cada linha tem:
  - número sequencial;
  - data/hora;
  - usuário e computador;
  - tipo da ação;
  - detalhes (cliente, projeto/máquina, tipo de documento, revisão e nomes de arquivo, quando houver);
  - o **código da linha anterior** e o **código desta linha**.
- **Ações registradas:**
  - envio de revisão;
  - importação;
  - registro de arquivo encontrado;
  - mudança de status;
  - "não se aplica";
  - dados de cliente, projeto ou máquina;
  - criação de cliente, projeto ou máquina;
  - e-mail preparado;
  - mudanças em Configurações;
  - liberação de trava;
  - sincronização (início e fim, com o resumo);
  - cada divergência resolvida, com a escolha feita;
  - recuperação;
  - **adulteração detectada**.
- Os históricos por projeto que já existem continuam iguais. O log geral é uma visão adicional, central e protegida.

### Detecção de adulteração
- O código de cada linha é um SHA-256 do conteúdo da linha somado ao código da linha anterior, formando uma corrente.
- Editar, apagar ou inserir uma linha quebra a corrente daquele ponto em diante.
- O Orbit **verifica a corrente**:
  - na abertura;
  - antes de cada sincronização;
  - ao abrir a tela do log.
- Se encontrar quebra, mostra um **alerta**: "O log de ações foi alterado fora do Orbit a partir da linha N (data aproximada)". Ele também grava uma linha "adulteração detectada" no fim, iniciando uma nova corrente a partir dali. As linhas antigas não são corrigidas nem apagadas.
- **Segunda testemunha:** o log vai para o backup. Na sincronização, os logs dos dois lados são comparados e unidos por linha.
  - Linhas que existem só de um lado são acrescentadas.
  - Uma linha com o mesmo número e conteúdo diferente, ou uma corrente quebrada de um lado e íntegra do outro, gera alerta de adulteração mostrando o que difere.
  - **Nunca se "conserta" um lado copiando o outro por cima.** A versão íntegra é preservada e a adulterada fica guardada em `_Divergências`.
- **Várias máquinas:** cada máquina acrescenta linhas no seu próprio lado, e a junção do log acontece na sincronização. Para evitar números repetidos, a sequência de cada linha é `<computador>-<n>`, e a corrente é **por computador** [decisão do Claude]. Na tela, as linhas aparecem todas juntas, ordenadas por data/hora.
- **Várias pessoas ao vivo na mesma pasta:** quem trabalha direto na pasta do servidor grava no mesmo `acoes.log`. Cada linha é acrescentada sob uma trava curta do log (`.orbit\travas\_log.lock`, com as mesmas regras das outras travas). Assim duas pessoas nunca escrevem ao mesmo tempo nem intercalam linhas.
- **Âncora local** [decisão do Claude]: cada computador guarda em `%APPDATA%\Orbit\` o número e o código da **última linha que ele mesmo gravou** em cada log.
  - Alguém que edite o log e recalcule a corrente inteira ainda é pego: a âncora de quem gravou as linhas não confere mais.
  - Isso cobre também um colega com conhecimento técnico, sem exigir servidor ou chave secreta.
  - A âncora fica fora da pasta base, então quem edita o log na pasta não alcança a âncora das outras máquinas.

### Tela "Log de ações"
- Novo item na navegação. É **só leitura**: o Orbit não oferece nenhuma forma de editar ou apagar linhas.
- Tem filtros por período, usuário, cliente/projeto e tipo de ação, além de uma busca por texto.
- Um selo no topo mostra "Íntegro" ou "Alterado fora do Orbit", com o detalhe.

## 8. Recuperação

Fica em Configurações, em "Recuperar backup", e na tela de boas-vindas, quando ainda não há pasta base, com "Recuperar de um backup".

- **Juntar com a pasta base atual:** o usuário aponta o caminho do backup. O Orbit faz a sincronização em duas vias sem retrato: o que só existe de um lado é copiado, e o que difere vira divergência nos popups. Isso **não** muda o backup configurado.
  - *[decisão do Claude]* A junção é nos dois sentidos, como na sincronização. Assim a pasta indicada também recebe o que só existe localmente.
- **Restaurar num PC novo:** o usuário aponta o caminho do backup e uma pasta base **vazia** (pasta com conteúdo é recusada). O Orbit copia tudo, verifica a corrente do log e confere os arquivos copiados pelo código de conteúdo.
  - Ao final, ele pergunta se o backup de origem deve passar a ser o backup configurado desta máquina, já com o retrato da sincronização criado.
- As duas operações mostram progresso, podem ser canceladas entre itens e registram linhas no log.

## 9. Cabeçalho: espaço LOGO

- O espaço da logo da empresa (`#logo-empresa`) fica **oculto** enquanto nenhuma logo estiver configurada. Configurada a logo, ele aparece como hoje.
- A configuração da logo da empresa em Configurações continua existindo.

## 10. Animação de abertura (opção A aprovada)

Referência visual: `.superpowers/brainstorm/844-1792756537/content/abertura.html`, cartão **A**.

- Tela cheia, no fundo do tema atual, com a logo do Orbit centralizada. A sequência dura ≈2,5 s:
  1. A folha entra **girando** (rotação 3D no eixo vertical, com uma leve aproximação) e para de frente.
  2. A **órbita se desenha** em volta e passa a **rodar**: o tracejado corre e o satélite percorre a elipse.
  3. "ORBIT" é **digitado letra por letra**, com cursor piscando.
  4. A tela de abertura some suavemente e o programa aparece.
- Enquanto a animação roda, o Orbit já carrega os dados e testa a conexão e o backup por trás. Se terminar antes, espera a animação acabar. Se a carga demorar mais, a órbita continua rodando até ficar pronto [decisão do Claude].
- **Um clique ou qualquer tecla pula a animação** [decisão do Claude].
- Usa as cores do tema escolhido (escuro ou claro) e respeita a configuração "reduzir movimento" do Windows: nesse caso mostra a logo parada por 0,5 s [decisão do Claude].
- O resto do programa continua sem animações, como no design original.

## 11. Testes

- **pytest** cobre todo o núcleo novo:
  - retrato de sincronização e classificação de cada caso da tabela da seção 5;
  - junção por item dos JSONs;
  - divergências e resoluções, com a versão descartada indo para `_Divergências`;
  - espelhamento com backup inacessível, gerando pendências;
  - trava de sincronização;
  - log: corrente, detecção de edição/remoção/inserção e junção entre dois lados;
  - recuperação nos dois modos, incluindo pasta não vazia recusada.
- Testes de interrupção: uma falha no meio da sincronização não deixa arquivo pela metade nem sobrescreve nada.
- A interface é testada à mão: indicador, popups de divergência, tela do log, animação e LOGO oculto.

## 12. O que fica com quem vai construir

- O formato exato do retrato de sincronização e do identificador do par pasta base + backup.
- A organização dos módulos novos (por exemplo `orbit/core/backup.py`, `sync.py` e `actionlog.py`) e a API com a interface.
- A forma de calcular os hashes sem ficar lento em pastas grandes, por exemplo reaproveitando o hash quando tamanho e data de modificação não mudaram.
- O layout dos popups de divergência e da tela do log, dentro do estilo visual existente.
- A forma de cancelar a sincronização e de mostrar o progresso.
