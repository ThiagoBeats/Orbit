# Orbit: Módulo Produção (montagem e testes de painéis)

Documento de design. Data: 24/10/2026. Pedido de: Thiago Carlos.

O Thiago pediu para não haver mais perguntas: **todas as decisões deste documento são minhas (Claude)**, tomadas a partir do que ele disse na conversa e de práticas de mercado. O que veio dele está na seção 1.

## 1. O que o Thiago pediu

- **Erros que chegaram ao campo:** o último painel foi para o cliente com fio errado, borne solto e sem aperto, entre outros.
- **Uma ferramenta para gerenciar a produção, não só para testar.** Uma espécie de "mini ERP" da montagem:
  - garantir que os documentos atualizados cheguem à produção (hoje ela recebe só o projeto elétrico, na última versão disponível);
  - controlar a chegada das demandas;
  - medir tempos de trabalho e períodos de ociosidade;
  - registrar a falta de materiais.
- **Testes nos padrões de mercado**, e não focados só nos erros internos.
- **Fatos da produção:**
  - o pessoal usa um **computador** na bancada;
  - o diagrama sai do software de projeto com uma **lista de conexões** exportável (Excel/CSV);
  - os testes de bancada são feitos **com o painel energizado**;
  - hoje quem testa é quem montou, mas **dá para ter outra pessoa** fazendo uma verificação no final.

## 2. Referências de mercado usadas

- **IEC 61439-1/-2 (NBR IEC 61439), seção 11, "verificação de rotina".** É feita em todo painel montado e é a base do checklist de inspeção. Itens:
  - 11.2 grau de proteção;
  - 11.3 distâncias de isolação e de escoamento;
  - 11.4 proteção contra choque e continuidade do circuito de proteção;
  - 11.5 incorporação dos componentes;
  - 11.6 circuitos internos e conexões, incluindo aperto;
  - 11.7 terminais para condutores externos;
  - 11.8 operação mecânica;
  - 11.9 propriedades dielétricas (ensaio de tensão ou resistência de isolamento);
  - 11.10 fiação, desempenho operacional e função.
- **Teste ponto a ponto** (fio a fio) a partir da lista de conexões, com verificação de aperto.
  - Prática comum é **marcar o parafuso com caneta (torque mark)** depois de conferir o aperto.
- **Ensaio de isolação com megômetro.**
  - Padrão sugerido: 500 V CC em circuitos até 690 V.
  - Critério mínimo configurável, com padrão de **1 MΩ** por circuito [decisão do Claude; a IEC 61439-1 11.9 aceita a medição de isolamento como alternativa ao ensaio dielétrico, com critério próprio, que o Thiago pode ajustar].
- **FAT interno (IEC 62381 como referência de estrutura):**
  - energização em sequência;
  - medição de tensões;
  - teste de entradas e saídas (I/O check) a partir da lista de tags;
  - registro de não conformidades (NC), com correção e reteste.
- **Dupla checagem por amostragem** (segunda pessoa), prática comum para reduzir erro de quem verifica o próprio trabalho.
- **Apontamento de produção (padrão de MES/ERP):**
  - início, pausa e fim por etapa e por operador;
  - motivos de parada para medir ociosidade (falta de material, aguardando projeto, retrabalho…).

## 3. Objetivos e não-objetivos

### Objetivos
- **Ordem de Produção (OP)** por painel, com fila, prioridade, prazo e etapas.
- **Pacote de documentos liberado e congelado por OP**, com alerta quando sair revisão nova.
- **Apontamento de horas e de paradas** por operador, com relatórios de horas produtivas e de ociosidade por motivo.
- **Materiais por OP:**
  - lista importada do Excel/CSV;
  - situação de cada item (pendente, solicitado, recebido, separado);
  - lista de faltas;
  - parada por "falta de material".
- **Testes:**
  - inspeção de rotina IEC 61439;
  - ponto a ponto com aperto;
  - isolação;
  - energização e tensões;
  - I/O;
  - verificação final por amostragem feita por outra pessoa;
  - NCs com reteste.
- **Relatório de ensaio** da OP, para imprimir ou salvar em PDF e mandar com o painel.
- **Painel de gestão:**
  - OPs por etapa e OPs atrasadas;
  - horas por OP;
  - ociosidade por motivo;
  - faltas de material;
  - NCs por tipo (Pareto).

### Não-objetivos
- Compras, estoque, financeiro e nota fiscal. O material só tem a situação daquela OP; não há saldo de estoque.
- Integração direta com EPLAN ou com o CLP. A entrada é sempre por planilha exportada.
- Aplicativo de celular. O uso é no computador da bancada.

### Anti-objetivos
- Uma OP aprovada sem que todos os testes obrigatórios estejam completos.
- A produção trabalhando com um documento diferente do liberado sem saber.
- Perder apontamentos ou registros de teste.

## 4. Conceitos

### OP (Ordem de Produção)
Pertence a um projeto e tem:
- número sequencial `OP-0001`, único na pasta base;
- painel (tag/nome, ex.: "QGBT-01"), descrição e quantidade;
- prazo e prioridade (normal / alta / urgente);
- responsável;
- data de criação;
- a etapa atual.

### Etapas
1. **Planejada:** criada e ainda não liberada.
2. **Liberada:** o pacote foi liberado e a OP entra na fila da produção.
3. **Em montagem.**
4. **Em teste.**
5. **Verificação final:** feita por outra pessoa.
6. **Aprovada.**
7. **Expedida.**

Além das etapas, há o estado **"Bloqueada"**, com um motivo (ex.: falta de material, aguardando projeto). Ele pode ser aplicado em qualquer etapa e não troca a etapa.

As regras de avanço:
- **Avançar** pula para a etapa seguinte. Algumas passagens têm condição:
  - Liberada exige um pacote com pelo menos um documento;
  - "Verificação final" exige os testes obrigatórios completos e nenhuma NC aberta;
  - Aprovada exige a amostragem feita por outra pessoa e sem falhas.
- **Voltar** para uma etapa anterior é permitido, com motivo registrado. Exemplo: a verificação final achou erro.

### Pacote de documentos
- Na liberação, o Orbit registra a revisão **atual** de cada documento escolhido do projeto: tipo, número da revisão e nome do arquivo principal.
- A tela da OP abre **exatamente** esses arquivos, que ficam na pasta do tipo ou em `Antigos`.
- **Alerta de revisão nova:** se algum documento do pacote ganhar revisão mais nova no projeto, a OP mostra o alerta, e quem gerencia pode **atualizar o pacote**. A troca fica registrada no histórico da OP.

### Operadores
- Lista em Configurações → Produção, com nome e se pode fazer a verificação final.
- No computador da bancada, cada ação pede o operador, já sugerindo o último usado naquela máquina. Ninguém precisa de usuário do Windows próprio.

### Apontamentos
Cada apontamento tem: operador, OP, etapa, tipo (`trabalho` ou `parada`), motivo da parada, início, fim e observação.
- **Iniciar trabalho:** um operador só tem um apontamento aberto por vez; iniciar outro encerra o anterior.
- **Pausar com motivo:** abre uma parada.
- **Retomar:** encerra a parada.
- **Encerrar.**
- **Motivos de parada padrão:** Falta de material, Aguardando projeto/informação, Aguardando cliente, Retrabalho, Manutenção/ferramenta, Outro. A lista é editável.
- **Ociosidade** = tempo em paradas, por motivo e por OP.
- **Horas produtivas** = tempo em trabalho, por OP, etapa e operador.
- **Apontamento esquecido aberto:** passa a aparecer como "aberto há mais de 10 h" no painel de gestão, para correção manual. Quem gerencia pode editar o início e o fim, e fica registrado quem editou.

### Materiais
- A lista vem de uma planilha (CSV ou XLSX), com escolha de quais colunas são código, descrição, quantidade, unidade e fabricante.
- Cada item tem uma situação: **pendente → solicitado → recebido → separado**, ou **falta**.
- **Falta:**
  - tem observação e uma previsão opcional;
  - item em falta faz a OP mostrar **"Falta de material (N itens)"**;
  - o painel de gestão consolida as faltas de todas as OPs.

### Testes da OP
Cada bloco tem situação **não iniciado / em andamento / concluído**:

| Bloco | Obrigatório | Como funciona |
| :--- | :--- | :--- |
| **A. Inspeção de rotina (IEC 61439-1 §11)** | Sim | Checklist com os itens da seção 2. Cada item é OK, NC ou N/A, com observação. |
| **B. Ponto a ponto** | Sim, se houver lista de conexões | Lista importada (CSV/XLSX), escolhendo as colunas origem, destino e opcionalmente fio, seção e cor. Cada linha tem **Ligação OK**, **Aperto OK** ou NC. Filtros: pendentes, por régua ou componente, e busca. |
| **C. Isolação** | Sim | Tabela de circuitos, com tensão de ensaio (V) e resistência medida (MΩ). Valor abaixo do critério reprova o circuito e gera NC. |
| **D. Energização** | Não | Checklist sequencial (proteções abertas, alimentação, medições) e tabela de pontos com tensão esperada e medida, com tolerância padrão de ±10%. |
| **E. Entradas e saídas** | Sim, se houver lista de tags | Importada da Lista de Tags (CSV/XLSX, mapeando tag, descrição, endereço e tipo). Cada sinal é OK ou NC. |

- **Bloco A, itens padrão:**
  - grau de proteção e vedações;
  - distâncias de isolação;
  - continuidade do PE e aterramento das portas;
  - componentes conforme o projeto (modelo e corrente);
  - fiação conforme o diagrama;
  - aperto das conexões de potência e de comando, com marcação;
  - identificação de fios, bornes e componentes;
  - terminais para condutores externos;
  - operação mecânica (portas, fechaduras, intertravamentos);
  - documentação no painel (diagrama na porta, placa de identificação);
  - limpeza (sem cavacos ou sobras).
- Em qualquer bloco, uma NC pode ser criada direto da linha que falhou.
- O critério de isolação e as tolerâncias de tensão ficam em Configurações.

### Não conformidades (NC)
- Cada NC tem: número, tipo e descrição, origem (bloco/linha), quem registrou e quando, situação **aberta → corrigida → verificada**, quem corrigiu e o reteste.
- **Tipos padrão:** Fio/ligação trocada, Aperto/borne solto, Identificação, Componente divergente, Dano/montagem mecânica, Isolação, Função/lógica, Documentação, Outro. A lista é editável.
- **Encerramento:** a NC só fica verificada depois do reteste, feito por qualquer pessoa.

### Verificação final por amostragem
- Na etapa "Verificação final", o Orbit sorteia **10% das ligações do ponto a ponto**, com no mínimo 10 e no máximo todas. O percentual é configurável.
- Quem verifica precisa ser **diferente de quem fez o ponto a ponto**, e o Orbit bloqueia se for a mesma pessoa.
- A pessoa confere as ligações sorteadas mais um mini-checklist final: identificação, aperto marcado, tampas, documentação na porta.
- **Se alguma ligação falhar:** é aberta uma NC, a OP volta para "Em teste" e o ponto a ponto é **zerado para revisão completa**. O histórico do teste anterior fica guardado.

### Relatório de ensaio
- Arquivo HTML imprimível ("Salvar como PDF" na impressão), em `Produção\OP-xxxx\Relatório de ensaio OP-xxxx.html`.
- **Conteúdo:**
  - identificação (cliente, projeto, painel e OP);
  - pacote de documentos (revisões);
  - resultados de cada bloco, com quem fez e quando;
  - NCs e reteste;
  - verificação final;
  - campos de assinatura.
- O relatório é gerado sob demanda e regravado a cada geração. É o único arquivo regravado, porque é sempre derivado dos dados.

## 5. Telas

- **Menu "Produção"** com três abas:
  - **Fila:** cartões de OP por etapa, com prazo, prioridade e alertas (revisão nova, falta de material, bloqueada, atrasada).
  - **Meu trabalho:** para a bancada. O operador é escolhido no topo, e a tela mostra o apontamento aberto com os botões grandes Iniciar, Pausar com motivo, Retomar e Encerrar.
  - **Gestão:** números e listas:
    - OPs por etapa e OPs atrasadas;
    - horas produtivas e paradas na semana;
    - paradas por motivo;
    - faltas de material abertas;
    - NCs por tipo (Pareto);
    - apontamentos abertos há mais de 10 h.
- **Tela da OP**, com abas:
  - **Resumo:** dados, etapa, avançar/voltar, bloquear;
  - **Documentos:** o pacote, com abrir e o alerta de revisão nova;
  - **Materiais;**
  - **Testes:** os blocos A a E e a verificação final;
  - **NCs;**
  - **Apontamentos;**
  - **Relatório.**
- **No painel do projeto,** uma seção "Produção" com as OPs daquele projeto e o botão "Nova OP".
- **Configurações → Produção:** operadores, motivos de parada, tipos de NC, critério de isolação, tolerância de tensão, percentual da amostragem e itens do checklist IEC (editáveis).

## 6. Armazenamento

- `<pasta do projeto>\Produção\OP-0001 - QGBT-01\op.json`: tudo da OP (dados, pacote, etapas, materiais, testes, NCs, apontamentos e histórico).
- A numeração das OPs fica em `<pasta base>\.orbit\producao.json`, junto com as configurações de produção. O número é atribuído sob uma trava.
- **Gravação:** sob a trava da OP (`.orbit\travas\_op.lock` na pasta da OP), com releitura dentro da trava, igual ao resto do Orbit.
- **Rede e backup:** o módulo é pensado para rodar **ao vivo na pasta do servidor**, com o Thiago e a bancada no mesmo `op.json`. Pela sincronização com backup, o `op.json` segue as regras de arquivo comum. Uma mudança nos dois lados vira divergência, com as duas versões guardadas [decisão do Claude: uma junção item a item da OP fica para depois].
- **Log de ações:** criar OP, liberar, mudar de etapa, bloquear, atualizar pacote, aprovar e expedir.

## 7. Restrições técnicas

- Mesmo Orbit: Python 3.14, pywebview e núcleo em `orbit/core` sem interface.
- **Nova dependência `openpyxl`** (pura Python), para ler `.xlsx`. CSV é lido pela biblioteca padrão, com separador `;` ou `,` detectado sozinho e codificação UTF-8 ou Latin-1.
- Testes automáticos de todas as regras:
  - etapas e condições;
  - congelamento do pacote e alerta de revisão;
  - apontamentos e cálculo de horas e paradas;
  - importação com mapeamento de colunas;
  - situação dos testes, NCs e amostragem (incluindo a mesma pessoa bloqueada);
  - relatório;
  - indicadores de gestão.
