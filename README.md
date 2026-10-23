<p align="center">
  <img src="orbit/ui/web/img/orbit-logo.svg" alt="Logo do Orbit" width="96">
</p>

<h1 align="center">Orbit</h1>

<p align="center">Gerenciador de documentação de projetos de Automação e Elétrica para Windows.</p>

---

O Orbit organiza os documentos técnicos de cada cliente, projeto e máquina padrão numa estrutura de pastas única. Ele também controla as revisões automaticamente.

Ao subir um arquivo, o Orbit faz o seguinte:
- renomeia no padrão da empresa, por exemplo `ABCDE.pdf` → `Diagrama Elétrico - Cliente X - Envasadora - 221026 - Rev01.pdf`;
- move a revisão anterior para a subpasta `Antigos`;
- registra quem fez a alteração, quando e por quê.

Tudo continua em pastas e arquivos comuns. Qualquer pessoa entende a organização pelo Explorer do Windows, mesmo sem o programa.

> Projetos de CLP e IHM ficam fora do Orbit.

## Funcionalidades

- **Estrutura automática.** Ao cadastrar um cliente, projeto ou máquina padrão, o Orbit cria uma pasta por tipo de documento, cada uma com sua subpasta `Antigos`.
- **Controle de revisão.** O Orbit sugere a próxima revisão e arquiva a anterior. Ele nunca apaga nem sobrescreve arquivos: se algo falha no meio do processo, tudo volta como estava.
- **Arquivo principal + editáveis.** O arquivo principal pode ser de qualquer formato (PDF, XLSX, XML…). Os editáveis são opcionais, por exemplo `.drawio` ou `.dwg`, e acompanham a mesma revisão.
- **Painel do projeto.**
  - Cartões por documento, com status (Em elaboração, Para aprovação, Aprovado, Liberado para fabricação, As Built).
  - Visualizador de PDF e imagens.
  - Histórico de revisões.
  - Contador de documentos emitidos.
- **Máquinas padrão.** Documentação geral única para máquinas de catálogo, sem vínculo com cliente.
- **E-mail.** O Orbit monta o e-mail com os anexos pelo Outlook clássico. Sem ele, abre um rascunho `.eml` no programa de e-mail padrão. Todo envio fica registrado na tela **Envios**.
- **Anexos sem revisão.** Manuais de componentes, notas fiscais e informativos ficam na pasta `Anexos` do projeto ou da máquina, com o nome original, sem renomear e sem controle de revisão.
- **Importação.** Traz documentos de projetos antigos, inclusive várias revisões de uma vez, sem alterar os originais.
- **Arquivos colocados à mão.** O Orbit detecta arquivos copiados direto na pasta e permite registrá-los.
- **Pronto para rede.**
  - Aviso quando outra pessoa está com o mesmo projeto aberto.
  - Trava de upload por documento e trava de gravação por projeto.
  - Teste de conexão com a pasta base.
- **Configurações.** Tipos de documento e status editáveis, tema escuro e claro e logo da empresa no cabeçalho.
- **Início (Meu dia).** A tela inicial mostra:
  - a lista do dia, com OK;
  - as anotações de projeto (insight, onde parei, pesquisar depois, definição futura);
  - onde você parou em cada projeto e as ideias para replicar;
  - os lembretes.
- **Lembretes** com data e hora, recorrentes ou não. Aparecem como notificação do Windows (com Adiar e Concluir), mesmo com o Orbit minimizado.
- **Backup e sincronização.** Cópia automática de cada alteração para uma pasta de backup (servidor, HD externo ou nuvem). Um indicador mostra se o backup está em dia, e o botão **Sincronizar** junta as alterações dos dois lados.
- **Log de ações.** Registro de tudo o que é feito pelo Orbit, com alerta se o arquivo do log for alterado por fora.
- **Recuperação.** Junta um backup com a pasta base atual ou monta tudo do zero num computador novo.

### Tipos de documento padrão

Diagrama Elétrico · Topologia de Rede · Memorial Descritivo · Layout de Painel · Planilha de Cargas · Consumo Pneumático · Manual de Operação · Descritivo Funcional · Lista de Tags

A lista pode ser alterada em **Configurações**.

## Estrutura de pastas gerada

```
<Pasta Base>\
  .orbit\config.json              ← tipos de documento e status (compartilhados)
  Clientes\
    Cliente X\
      cliente.json
      001 - Envasadora Linha 2\
        projeto.json              ← revisões, status e histórico
        Diagrama Elétrico\
          Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 201026 - Rev02.pdf
          Antigos\
            Diagrama Elétrico - Cliente X - Envasadora Linha 2 - 051026 - Rev01.pdf
        ...
  Máquinas Padrão\
    Esteira Compacta EC-200\
      maquina.json
      Diagrama Elétrico\
        Antigos\
      ...
```

**Padrão de nome dos arquivos**

| Tipo de item | Padrão |
| :--- | :--- |
| Projeto | `<Tipo> - <Cliente> - <Projeto> - <DDMMAA> - Rev<NN>.<ext>` |
| Máquina padrão | `<Tipo> - <Máquina> - <DDMMAA> - Rev<NN>.<ext>` |

As preferências pessoais (pasta base e tema) ficam em `%APPDATA%\Orbit\settings.json`. Erros inesperados são registrados em `%APPDATA%\Orbit\orbit.log`.

## Meu dia, anotações e lembretes

A tela **Início** é o painel do dia:

- **Meu dia:** digite e aperte Enter. Escolha o tipo e, se quiser, o projeto.
  - As atividades ganham uma caixinha de OK.
  - O que não foi terminado passa sozinho para o dia seguinte.
  - "Pesquisar depois" e "definição futura" ficam na lista até receberem OK.
- **Anotações de projeto:** insight, onde parei, pesquisar depois e definição futura.
  - Também podem ser feitas dentro do painel do projeto.
  - Ficam visíveis para quem abrir o projeto, com o nome do autor.
  - As atividades são sempre só suas.
- **Onde parei:** a sua última anotação desse tipo em cada projeto. O painel do projeto mostra a mais recente no topo.
- **Ideias para replicar:** os insights de todos os projetos.
- **Lembretes:** data, hora e repetição (todo dia, dias úteis, dias da semana ou todo mês).
  - O aviso aparece como notificação do Windows, com os botões *Adiar 10 min*, *Adiar 1 h* e *Concluir*, e também dentro do Orbit.
  - Um lembrete que venceu com o Orbit fechado aparece em "Lembretes perdidos" na próxima abertura.

**Onde ficam guardados:**

| O quê | Arquivo |
| :--- | :--- |
| Seus itens e lembretes | `<pasta base>\.orbit\usuarios\<usuário>\meu_dia.json` |
| Anotações de projeto | `anotacoes.json`, na pasta do projeto |

Os dois são juntados item a item na sincronização entre casa e empresa.

## Backup e sincronização

Em **Configurações → Backup**, escolha a pasta de backup. Ela pode estar no servidor da empresa, num HD externo ou numa pasta de nuvem.

- **Pasta vazia:** o Orbit faz a primeira cópia completa.
- **Pasta que já tem um backup do Orbit:** ele **junta** os dois lados e não sobrescreve nada.
- **Pasta com outros arquivos:** é recusada.

Depois disso:

- **Cópia automática.** Cada alteração feita no Orbit também é copiada para o backup. Se o backup estiver fora do ar (em casa, por exemplo), a alteração fica pendente e é enviada quando ele voltar.
- **Indicador.** Fica no cabeçalho e mostra *Backup em dia*, *Backup diferente*, *Backup inacessível* ou *Sincronizando…*. A comparação roda na abertura e a cada 10 minutos (configurável).
- **Sincronizar.** O botão na tela Clientes, ou o clique no indicador, junta os dois lados.
  - O que mudou só de um lado vai para o outro sozinho.
  - Quando os **dois** lados mudaram a mesma coisa, aparece um popup com as duas versões, e você escolhe: manter a desta máquina, a do backup ou as duas.
- **Nada se perde.** Nada é apagado. A versão descartada fica guardada em `_Divergências\<data-hora>\`. Um arquivo apagado pelo Explorer é restaurado a partir do outro lado.
- **Servidor como ponto de encontro.** A mesma pasta do servidor pode servir de backup para várias pessoas e, ao mesmo tempo, de pasta base "ao vivo" para outras. As travas evitam que duas gravações se atropelem.

O retrato da última sincronização fica em `%APPDATA%\Orbit\sync\`, fora da pasta base.

## Log de ações

Toda ação feita pelo Orbit (upload, status, importação, e-mail, sincronização, configurações…) vira uma linha em `<pasta base>\.orbit\log\acoes.log`. A tela **Log** mostra as linhas, com filtros, e só permite leitura.

Cada linha é "carimbada" junto com a anterior, e cada computador guarda em `%APPDATA%\Orbit\ancoras.json` o carimbo da última linha que gravou. Se alguém editar, apagar ou inserir linhas fora do Orbit, o programa mostra um alerta na abertura indicando a partir de onde o log foi mexido. O Orbit não impede a edição do arquivo, mas a torna impossível de esconder.

## Recuperação

Em **Configurações → Backup → Recuperar backup**:

- **Juntar com a pasta base:** traz o que falta de um backup e envia para ele o que só existe aqui. As divergências aparecem nos mesmos popups da sincronização.
- **Restaurar num PC novo:** escolha o backup e uma pasta **vazia**. O Orbit copia tudo, confere cada arquivo e o log, e pergunta se esse backup passa a ser o desta máquina. Essa opção também está na tela de boas-vindas, em *Recuperar de um backup*.

## Requisitos

- Windows 10 ou 11, com o runtime **Microsoft Edge WebView2**, que já vem no Windows 11.
- Para rodar a partir do código: **Python 3.14**.
- Opcional: Outlook clássico, para abrir o e-mail direto nele.

## Como rodar (desenvolvimento)

```powershell
git clone https://github.com/ThiagoBeats/Orbit.git
cd Orbit
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Na primeira execução o Orbit pede a **pasta base**, onde ficarão os clientes e as máquinas padrão. Para testar, use uma pasta separada dos projetos reais.

### Testes

```powershell
.venv\Scripts\python -m pytest
```

### Gerar o executável

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python tools\gerar_icone.py      # só se a logo mudar
.venv\Scripts\pyinstaller orbit.spec --noconfirm
```

O executável é gerado em `dist\Orbit\Orbit.exe`. Para distribuir, copie a pasta `dist\Orbit` inteira.

## Organização do código

```
main.py                 ponto de entrada
orbit/core/             regras de negócio (sem dependência da interface)
  repository.py         clientes, projetos, máquinas e pastas
  revisions.py          upload de revisão com transação e desfazer
  importer.py           importação de documentos antigos
  reconcile.py          arquivos colocados à mão na pasta
  email.py, outlook.py, eml.py   montagem e abertura do e-mail
  presence.py           presença de usuários e travas
  connection.py         teste de conexão com a pasta base
  actionlog.py          log de ações com detecção de adulteração
  backup.py             backup: configurar, espelhar, status e recuperação
  sync/                 sincronização em duas vias (varredura, junção, motor, divergências)
orbit/ui/               janela pywebview, Api exposta ao JavaScript e servidor local de arquivos
orbit/ui/web/           interface em HTML/CSS/JS (sem framework)
tests/                  testes automáticos (pytest)
docs/superpowers/       documento de design e plano de implementação
```

## Limitações conhecidas

- **Novo Outlook:** não permite automação. Nesse caso o Orbit abre um rascunho `.eml` com os anexos.
- **Acesso pelo Explorer:** o aviso de "outra pessoa no projeto" só enxerga quem está usando o Orbit, não quem abre a pasta pelo Explorer.
- **Uso em rede:** para várias pessoas na mesma pasta de rede, mantenha os relógios dos computadores sincronizados. As travas usam o horário de cada máquina.
- **Backup em pasta de nuvem** (OneDrive, Dropbox…): funciona bem para uma máquina. Com várias máquinas sincronizando pela mesma pasta de nuvem, prefira o servidor da empresa.
- **Lembretes:** só avisam com o Orbit aberto (minimizado também vale).
- **Verificação do backup:** a comparação automática só roda com o Orbit aberto.
- **Renomeações:** renomear um cliente, projeto ou tipo muda apenas os nomes exibidos e os arquivos novos. Pastas e arquivos existentes não são renomeados.
