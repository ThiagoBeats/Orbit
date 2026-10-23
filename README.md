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
- **Importação.** Traz documentos de projetos antigos, inclusive várias revisões de uma vez, sem alterar os originais.
- **Arquivos colocados à mão.** O Orbit detecta arquivos copiados direto na pasta e permite registrá-los.
- **Pronto para rede.**
  - Aviso quando outra pessoa está com o mesmo projeto aberto.
  - Trava de upload por documento e trava de gravação por projeto.
  - Teste de conexão com a pasta base.
- **Configurações.** Tipos de documento e status editáveis, tema escuro e claro e logo da empresa no cabeçalho.

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
orbit/ui/               janela pywebview, Api exposta ao JavaScript e servidor local de arquivos
orbit/ui/web/           interface em HTML/CSS/JS (sem framework)
tests/                  testes automáticos (pytest)
docs/superpowers/       documento de design e plano de implementação
```

## Limitações conhecidas

- **Novo Outlook:** não permite automação. Nesse caso o Orbit abre um rascunho `.eml` com os anexos.
- **Acesso pelo Explorer:** o aviso de "outra pessoa no projeto" só enxerga quem está usando o Orbit, não quem abre a pasta pelo Explorer.
- **Uso em rede:** para várias pessoas na mesma pasta de rede, mantenha os relógios dos computadores sincronizados. As travas usam o horário de cada máquina.
- **Renomeações:** renomear um cliente, projeto ou tipo muda apenas os nomes exibidos e os arquivos novos. Pastas e arquivos existentes não são renomeados.
