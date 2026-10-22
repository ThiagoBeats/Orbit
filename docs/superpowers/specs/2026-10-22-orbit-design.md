# Orbit: Gerenciador de Documentação de Projetos

Documento de design. Data: 22/10/2026. Autor do pedido: Thiago Carlos (Automação e Elétrica).

Convenção usada neste documento: decisões tomadas pelo Thiago aparecem sem marcação. Decisões tomadas por mim (Claude), que ele pode revisar, aparecem marcadas com **[decisão do Claude]**.

---

## 1. Intenção e o porquê

O Thiago cuida da Automação e Elétrica dos projetos da empresa. Hoje os documentos de cada projeto (diagramas, memoriais, layouts, planilhas) ficam em pastas sem padrão. Isso dificulta duas coisas:

1. **Saber qual é a revisão vigente** de cada documento e qual revisão foi enviada ao cliente.
2. **Achar rápido o arquivo certo**, sem procurar em várias pastas.

O Orbit é um programa para Windows que:

- cria e mantém uma estrutura de pastas padrão para cada cliente, projeto e máquina padrão;
- recebe documentos novos, renomeia no padrão, controla a revisão e arquiva a anterior;
- mostra num painel o andamento da documentação de cada projeto;
- permite ler os PDFs dentro do programa e enviá-los por e-mail pelo Outlook.

Por enquanto só o Thiago usa, num único computador. **No futuro** a pasta base vai para uma pasta compartilhada na rede ou no OneDrive, com vários usuários, e o programa vai crescer para gerenciar outras etapas do projeto, **incluindo a montagem de painéis**. A estrutura precisa nascer pronta para isso.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos
- Estrutura de pastas criada automaticamente ao cadastrar cliente, projeto ou máquina padrão.
- Upload com renomeação automática e controle de revisão (a anterior vai para `Antigos`).
- Painel por projeto com status, revisão, datas, pendentes, visualizador de PDF e histórico.
- Envio de documentos por e-mail via Outlook, com registro do envio.
- Importação de documentos de projetos antigos.
- Área separada para máquinas padrão, com documentação geral única.
- Arquitetura preparada para multiusuário e para novos módulos (por exemplo, montagem de painéis).

### Não-objetivos (fora do escopo)
- **Projetos de CLP e IHM não entram no Orbit.**
- Não é um editor de documentos: o Orbit não abre o EPLAN nem o AutoCAD nem edita PDF.
- Não substitui o Outlook: o e-mail é montado no Outlook e enviado por ele.
- Gestão de montagem de painéis, horas e financeiro **não** entram nesta versão. Só a arquitetura precisa permitir isso depois.
- Ligação entre máquinas padrão e clientes não existe: a máquina padrão tem só a documentação geral.

### Anti-objetivos (o que tornaria isto um fracasso mesmo funcionando)
- **Perder ou sobrescrever um arquivo.** Nenhuma revisão é apagada nem sobrescrita, nunca.
- **Prender os dados no programa.** As pastas precisam continuar navegáveis e compreensíveis pelo Explorer do Windows, mesmo sem o Orbit.
- **Ter que refazer tudo para multiusuário.** O formato dos dados precisa funcionar numa pasta de rede desde o início.
- Ficar visualmente poluído ou cheio de animações.

## 3. Restrições

- **Plataforma:** Windows 11. Outlook **clássico** instalado (o "Novo Outlook" não aceita automação COM; ver seção 9).
- **Desenvolvimento:** durante o desenvolvimento o programa roda direto no interpretador (`python main.py`), sem gerar `.exe` a cada teste. O `.exe` só é gerado na entrega final.
- **Idioma:** interface toda em português do Brasil.
- **Dados em arquivos abertos:** pastas, PDFs e arquivos JSON legíveis, nada de banco de dados local escondido.

## 4. Tecnologia **[decisão do Claude]**

O Thiago deixou a escolha comigo.

- **Python 3.12+** para toda a lógica (arquivos, revisões, Outlook, importação).
- **pywebview** (motor Edge WebView2, já presente no Windows 11) para a janela. A interface é **HTML/CSS/JS**. Motivos: o visual pedido é de estilo "site", e o WebView2 já traz um visualizador de PDF embutido.
- **JavaScript puro** na interface, sem framework e sem etapa de build. Mantém o "rodar no interpretador" simples.
- **pywin32** para automação do Outlook (COM).
- **pytest** para os testes da lógica central.
- **PyInstaller** para gerar o `.exe` no fim.
- **Fonte Roboto embutida** nos arquivos do programa, sem depender da internet.

## 5. Conceitos (modelo de dados)

```
Pasta Base
├── Clientes
│   └── Cliente
│       └── Projeto  ──┐
└── Máquinas Padrão     │  ambos são "Containers de documentos"
    └── Máquina  ───────┘
            └── Documento (um por tipo)
                    └── Revisões (Rev00, Rev01, ...)
                            └── arquivos: 1 arquivo principal (qualquer formato) + 0..n editáveis
```

- **Cliente:** nome, CNPJ (opcional) e contatos (nome + e-mail).
- **Projeto:** pertence a um cliente. Tem código, nome, nº do pedido, responsável, contatos de e-mail, situação (ativo/concluído) e a lista de documentos marcados como "não se aplica". Cada projeto tem as próprias revisões, mesmo que seja do mesmo cliente.
- **Máquina Padrão:** máquina de catálogo com documentação geral única. Tem nome, código e descrição. Não tem cliente.
- **Container de documentos [decisão do Claude]:** abstração comum a Projeto e Máquina Padrão. Toda a lógica de documentos, revisões, upload, importação, histórico e e-mail trabalha sobre "container", e não sobre "projeto". Assim, novos tipos de container entram sem reescrever o núcleo.
- **Tipo de documento:** a lista padrão tem 9 tipos:
  1. Diagrama Elétrico
  2. Topologia de Rede
  3. Memorial Descritivo
  4. Layout de Painel
  5. Planilha de Cargas
  6. Consumo Pneumático
  7. Manual de Operação
  8. Descritivo Funcional
  9. Lista de Tags

  A lista é **editável nas configurações** [decisão do Claude]. Cada tipo tem um nome de exibição e um nome de pasta. Tipos removidos nunca apagam pastas existentes, só deixam de aparecer para novos containers.
  - **Diagrama Elétrico = "projeto elétrico"** [decisão do Claude]. No primeiro pedido o Thiago chamou de "Projeto Elétrico"; na lista de tipos chamou de "Diagrama Elétrico". Usei "Diagrama Elétrico", e o nome é editável.
- **Revisão:** número inteiro de dois dígitos (Rev00, Rev01...). Guarda data, status, motivo, usuário e arquivos.
- **Arquivo principal e editáveis:** toda revisão tem exatamente **um arquivo principal**, que é o documento emitido. Ele pode ser de qualquer formato: PDF, XLSX, XML etc. Opcionalmente, a revisão tem **arquivos editáveis** que geraram o principal, por exemplo o `.drawio` junto com o PDF da Topologia de Rede, ou o `.dwg` junto com o PDF do Diagrama Elétrico. Quando o principal já é editável (ex.: um `.xlsx` da Planilha de Cargas), normalmente não há editável. Não há restrição de formato por tipo de documento [decisão do Claude].
- **Status de documento** (lista padrão, editável nas configurações): Em elaboração → Para aprovação → Aprovado → Liberado para fabricação → As Built. Além disso, cada documento do container pode estar **Pendente** (nunca emitido) ou **Não se aplica**.

## 6. Estrutura de pastas

```
<Pasta Base>\
  .orbit\                                  ← configuração compartilhada
    config.json                            ← tipos de documento, status, versão do formato
  Clientes\
    Cliente X\
      cliente.json
      001 - Envasadora Linha 2\
        projeto.json                       ← metadados + histórico (ver seção 7)
        .orbit\                            ← presença e travas (fase de desenvolvimento)
        Diagrama Elétrico\
          Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 201026 - Rev02.pdf
          Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 201026 - Rev02.dwg
          Antigos\
            Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 051026 - Rev01.pdf
            ...
        Topologia de Rede\
          Antigos\
        ... (uma pasta por tipo de documento, cada uma com Antigos\)
  Máquinas Padrão\
    Esteira Compacta EC-200\
      maquina.json
      Diagrama Elétrico\
        Diagrama Elétrico - Esteira Compacta EC-200 - 140926 - Rev04.pdf
        Antigos\
      ...
```

- As pastas de tipo são criadas todas no cadastro do container, inclusive para tipos marcados como "não se aplica".
- A pasta do projeto é `<código> - <nome>` [decisão do Claude].
- Configurações pessoais (caminho da pasta base, tema, janela) ficam em `%APPDATA%\Orbit\settings.json`, e não na pasta base [decisão do Claude]. Assim cada usuário tem as suas.

## 7. Metadados e histórico

- Cada container tem um JSON (`projeto.json` ou `maquina.json`) com os dados cadastrais, o estado de cada documento (revisão atual, status, "não se aplica") e um **histórico em lista de eventos**: upload de revisão, mudança de status, importação, e-mail preparado e documento marcado ou desmarcado como "não se aplica". Cada evento tem data/hora, usuário do Windows e computador.
- O JSON tem um campo `versao_formato` para permitir migrações futuras [decisão do Claude].
- **Escrita segura [decisão do Claude]:** grava num arquivo temporário na mesma pasta e depois renomeia por cima. Isso evita JSON corrompido se o programa ou a rede cair no meio.
- **Fonte da verdade:** os arquivos na pasta são a verdade sobre *quais revisões existem*. O JSON é a verdade sobre *status, motivo e histórico*. Se o Orbit encontrar um arquivo de revisão no padrão de nome que não está no JSON (por exemplo, colocado à mão), ele mostra o arquivo com status "desconhecido" e oferece registrar [decisão do Claude]. Não apaga nem move nada sozinho.
- Para a tela inicial não precisar abrir todos os JSONs em pastas de rede lentas, pode existir um índice/cache local reconstruível. Se existir, ele é **só cache**: pode ser apagado sem perda.

## 8. Regras de nome e revisão

**Padrão de nome**

- Projeto: `<Tipo> - <Cliente> - <Projeto> - <DDMMAA> - Rev<NN>.<ext>`
- Máquina padrão: `<Tipo> - <Máquina> - <DDMMAA> - Rev<NN>.<ext>`

**Regras**

- `DDMMAA` é a data do upload (ex.: 22/10/2026 → `221026`). Na importação, ver a seção 10.
- `<Projeto>` usa o nome do projeto, sem o código [decisão do Claude], para o nome não ficar longo demais.
- Caracteres inválidos para nomes de arquivo no Windows (`\ / : * ? " < > |`) são removidos ou trocados por `-`. Nomes muito longos são encurtados para o caminho completo ficar abaixo de 240 caracteres [decisão do Claude].
- Os editáveis enviados junto recebem o **mesmo nome base e a mesma revisão** do arquivo principal, com a extensão original.
- Se um editável tiver a mesma extensão do principal, ou se houver dois editáveis com a mesma extensão, recebem o sufixo ` - Editavel`, ` - Editavel 2` antes da extensão [decisão do Claude].
- O JSON registra qual arquivo é o principal. A extensão sozinha não basta para saber [decisão do Claude].

**Fluxo de upload (nova revisão)**

1. O usuário arrasta o arquivo principal para o cartão do documento ou clica em "Nova revisão". O popup abre com o arquivo principal, os editáveis (opcionais), o nome final (pré-visualização), o status e o motivo.
2. O Orbit sugere `revisão atual + 1` (ou `00` se for a primeira), e o usuário pode alterar só para um número **maior** que o atual (ex.: pular para Rev03 porque o cliente já recebeu uma Rev02 por fora) [decisão do Claude]. Revisões antigas esquecidas (números menores) entram pela **Importação** (seção 10), que já sabe mandá-las para `Antigos\`.
3. Ao confirmar, os arquivos da revisão atual (PDF + editáveis) são movidos para `Antigos\`. Os novos arquivos são **copiados** (não movidos) para a pasta do tipo com o nome novo. O evento é gravado no histórico.
4. Se qualquer passo falhar, o Orbit desfaz o que já fez e mostra o erro. Em nenhum caso um arquivo é apagado.

**Renomear cliente, projeto, máquina ou tipo [decisão do Claude]:**
- Muda os nomes de exibição e o nome usado nos **arquivos novos**.
- Pastas e arquivos que já existem **não são renomeados**, para não arriscar arquivos de rede em uso nem o histórico.
- Por isso o reconhecimento das revisões na pasta não depende do nome completo, e sim do sufixo `- Rev<NN>.<ext>` dentro da pasta do tipo. O JSON guarda o nome real de cada arquivo.
- Cada container e cada tipo têm um **identificador interno fixo** no JSON, e o nome da pasta é guardado no JSON em vez de ser recalculado a partir do nome.
- Renomear pastas em lote fica como melhoria futura.

**Mudança de status:** pode ser feita a qualquer momento, sem arquivo novo e sem mudar a revisão. Fica registrada no histórico.

## 9. Telas

O rascunho aprovado está em `.superpowers/brainstorm/379-1792683614/content/visual-v2.html` (tema escuro suave), e a logo em `logo-orbit.html` na mesma pasta (opção **C**).

### Estilo visual
- Inspiração: o site da Starlink, com tipografia limpa em caixa alta e espaçamento largo nos títulos, muito espaço livre e sem efeitos ou animações (só transições de borda no hover).
- **Fonte Roboto.** **Cantos arredondados** (8 px em campos e botões, 12 px em cartões, 16 px em popups).
- **Cores suaves**, sem preto e branco puros. Dois temas selecionáveis nas configurações; o **padrão é o escuro suave**. Paleta do rascunho:

| Elemento | Escuro suave | Claro suave |
| :--- | :--- | :--- |
| Fundo | `#1b2129` | `#eef1f5` |
| Superfície | `#232b35` | `#ffffff` |
| Superfície 2 | `#2a333f` | `#f5f7fa` |
| Linhas | `#38434f` | `#d6dce4` |
| Texto | `#e4e8ee` | `#26313d` |
| Texto secundário | `#93a0b0` | `#6c7988` |
| Destaque | `#7fa7d9` | `#4f7cb3` |

- Status com cor discreta em "pílulas": Aprovado em verde, Para aprovação em âmbar, Liberado em azul, Pendente em rosado e Em elaboração neutro.
- **Logo:** opção C (folha de documento com uma órbita em volta). É usada no cabeçalho, ao lado do nome ORBIT, e como ícone do programa. Existe também um **espaço reservado para a logo da empresa** no cabeçalho, configurável depois.
- **Popups** são o padrão para ver detalhes e fazer ações. O PDF fica no painel lateral, e não em popup, para dar para ler com calma.

### Cabeçalho (todas as telas)
Logo e nome Orbit, espaço para a logo da empresa, navegação (Clientes, Máquinas Padrão, Envios, Configurações) e **indicador de conexão** (seção 12).

### Tela inicial: Clientes
Cartões de cliente com nome, nº de projetos ativos e data da última emissão. Campo de busca (cliente ou projeto) e botões "Novo cliente" e "Novo projeto" (popups).

### Página do cliente
Dados e contatos do cliente, com a lista de projetos em cartões (código, nome, situação, emitidos x/y e última emissão).

### Painel do projeto (layout "B", aprovado)
- **Topo:** caminho (Cliente / Projeto), nome do projeto e resumo em blocos: *Emitidos X/Y* (sem contar os "não se aplica"), *Última atualização* e *Último emitido*.
- **Esquerda:** um cartão por tipo de documento, com revisão atual, pílula de status e data. Pendentes têm borda tracejada e aceitam arrastar o PDF. "Não se aplica" aparecem apagados.
- **Direita:** visualizador do arquivo principal selecionado. **PDF e imagens** abrem dentro do Orbit. **Outros formatos** (XLSX, XML, etc.) mostram um cartão com nome, tamanho e data, e um botão *Abrir no programa padrão* [decisão do Claude]. Em qualquer formato há o botão *Abrir pasta* e, se existirem, a lista de editáveis com *Abrir*. Também ficam aqui os botões *Enviar por e-mail*, *Nova revisão* e *Histórico*. Abaixo, o histórico curto de revisões com o motivo. Clicar numa revisão antiga abre o PDF dela no visualizador.
- **Seleção múltipla** de documentos para enviar vários num só e-mail.
- **Popups:** nova revisão, mudar status, histórico completo, enviar e-mail, dados do projeto/contatos, marcar "não se aplica" e importação.

### Máquinas Padrão
Tela de cartões das máquinas, e o painel de cada máquina é igual ao do projeto, sem cliente e sem contatos fixos.

### Envios
Lista de todos os e-mails preparados pelo Orbit, com filtro por cliente/projeto: data, destinatários, documentos e revisões.

### Configurações
Pasta base, tema, tipos de documento, status, logo da empresa e botão de teste de conexão. "Pastas configuradas" no Orbit significa só a pasta base. Não existe pasta monitorada nem importação automática.

## 10. Importação de projetos antigos

- Popup aberto a partir de um container já cadastrado.
- O usuário arrasta um ou mais arquivos existentes. Para cada um informa o tipo, o número da revisão, o status e, opcionalmente, o motivo. Em cada revisão, um arquivo é marcado como principal, e os outros podem ser associados a ele como editáveis.
- A data no nome vem da **data de modificação do arquivo original**, editável antes de confirmar [decisão do Claude].
- Se vierem várias revisões do mesmo documento, a mais alta vira a atual e as outras vão para `Antigos\`.
- O Orbit **copia** os arquivos e **nunca altera nem apaga os originais**.
- Conflito com uma revisão que já existe no Orbit: bloqueia aquela linha e pede outro número.

## 11. E-mail (Outlook)

- O usuário seleciona um ou mais documentos (revisão atual por padrão, ou uma revisão antiga pelo histórico) e clica em *Enviar por e-mail*.
- Abre um popup com destinatários (pré-preenchidos com os contatos do projeto e editáveis), o assunto sugerido (ex.: `Cliente X - Envasadora Linha 2 - Documentos para aprovação`), a lista de anexos com o tamanho total. Por padrão vão os arquivos principais. Os editáveis aparecem desmarcados e podem ser incluídos.
- O Orbit cria o e-mail no Outlook clássico via COM, já com os anexos, e **abre a janela do e-mail para o usuário revisar e enviar**. Ele nunca envia sozinho.
- **Registro:** grava um evento "e-mail preparado" no histórico do container (destinatários, documentos, revisões). O Orbit não confirma se o e-mail foi de fato enviado [decisão do Claude]. Confirmar exigiria monitorar o Outlook, o que fica como melhoria futura.
- Se o Outlook clássico não estiver disponível, o Orbit mostra uma mensagem clara e oferece abrir a pasta com os arquivos para anexar à mão.

## 12. Funcionalidades da fase de desenvolvimento (ideias do Thiago)

Fazem parte desta construção, mas entram **depois** que o núcleo estiver funcionando (cadastro, upload/revisão, painel, visualizador, e-mail e importação). No plano, ficam como as últimas etapas. Até lá, o indicador de conexão no cabeçalho pode existir só como espaço reservado.

**Aviso de outro usuário no mesmo projeto**
- Enquanto um container está aberto, o Orbit grava um arquivo de presença em `<container>\.orbit\presenca\<usuario>@<computador>.json` e o renova a cada ~30 s.
- Ao abrir um container que tem presença de outro usuário com menos de ~2 min, aparece um popup "Fulano (PC-XYZ) está com este projeto aberto desde 14:32".
- **Limitação aceita:** só detecta quem está usando o Orbit. Acesso direto pelo Explorer não é detectável de forma confiável.

**Trava de upload**
- Durante o upload de uma revisão, o Orbit cria `<container>\.orbit\travas\<tipo>.lock`. Outro usuário que tentar subir revisão do mesmo documento recebe um popup e é bloqueado.
- Travas com mais de ~10 min são tratadas como abandonadas, e o Orbit pergunta se quer liberar.

**Teste de conexão com as pastas**
- Na abertura, o Orbit verifica se alcança a pasta base (leitura e escrita) e mostra um popup se falhar.
- Um indicador no cabeçalho (verde/vermelho) mostra o estado. Clicar nele refaz o teste e mostra o detalhe por pasta.

## 13. Preparado para escalar

- **Núcleo separado da interface:** a lógica (containers, revisões, nomes, importação, e-mail, presença) fica num pacote Python sem nenhuma dependência de pywebview. A interface chama esse núcleo por uma API pequena. Isso permite, no futuro, trocar a interface ou colocar um servidor no meio para multiusuário.
- **Containers genéricos:** Projeto e Máquina Padrão são tipos de container. Um módulo futuro (por exemplo, montagem de painéis) entra como um novo **módulo** que adiciona seções ao painel do projeto e dados próprios num arquivo separado dentro da pasta do projeto (ex.: `montagem.json`), sem mexer no formato de `projeto.json`.
- **Tipos e status configuráveis** em `<Pasta Base>\.orbit\config.json`, compartilhados entre usuários.
- **Usuário em todo evento** desde o primeiro dia (usuário do Windows + computador), para o histórico já estar certo quando houver várias pessoas.
- **`versao_formato`** em todos os JSONs, para migrar sem perder dados.

## 14. Testes

- **pytest** cobre o núcleo: geração de nomes, sanitização, cálculo de revisão, fluxo de upload (inclusive falha no meio e desfazer), importação, leitura e escrita de JSON, reconciliação com arquivos colocados à mão e travas e presença. Usa pastas temporárias.
- A interface e o Outlook são testados à mão, rodando `python main.py`.

## 15. O que fica com quem vai construir

- Organização interna dos módulos Python e a API exata entre interface e núcleo.
- Detalhes visuais finos dentro do estilo aprovado: espaçamentos, ícones e a versão final da logo C.
- Como servir os PDFs para o WebView2 (servidor local ou caminho de arquivo).
- Estratégia do índice/cache da tela inicial.
- Configuração do PyInstaller.
