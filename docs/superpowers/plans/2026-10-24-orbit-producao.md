# Orbit: Módulo Produção — Plano de Implementação

> Executado inline (o Thiago pediu "desenvolva e nós testamos"). TDD em todo o núcleo.

**Objetivo:** OPs com pacote congelado, apontamentos e paradas, materiais, testes (IEC 61439 §11, ponto a ponto, isolação, energização, I/O, amostragem), NCs, relatório e gestão.

**Spec:** [docs/superpowers/specs/2026-10-24-orbit-producao-design.md](../specs/2026-10-24-orbit-producao-design.md)

## Restrições globais
- Tudo de uma OP fica em `<projeto>\Produção\OP-NNNN - <painel>\op.json`. O número `OP-NNNN` é sequencial e único na base, controlado em `<base>\.orbit\producao.json`, que também guarda a configuração da produção. As duas gravações são feitas sob trava.
- **Etapas, em ordem:** `planejada`, `liberada`, `em_montagem`, `em_teste`, `verificacao_final`, `aprovada`, `expedida`. O estado `bloqueada` com motivo é independente da etapa.
- **Nada é apagado:** cancelar ou desfazer fica registrado no histórico da OP.
- **Ponto a ponto e amostragem:** amostragem padrão de 10%, mínimo 10 ligações. Quem verifica precisa ser diferente de quem marcou as ligações.
- **Critérios padrão:** isolação ≥ 1 MΩ; tolerância de tensão ±10%.
- **Importação:** CSV (separador `;` ou `,` detectado sozinho, UTF-8 ou Latin-1) e XLSX (openpyxl), sempre com mapeamento de colunas.
- **Textos:** pt-BR; `esc()` em todo texto dinâmico; commits com `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Tarefas
1. **`orbit/core/producao/config.py` e `modelo.py`:**
   - configuração da produção com os padrões: operadores, motivos de parada, tipos de NC, checklist IEC e critérios;
   - numeração das OPs;
   - criação e listagem de OPs;
   - leitura e gravação do `op.json` sob trava;
   - histórico.
2. **`etapas.py`:**
   - avançar e voltar, com as condições da spec;
   - bloquear e desbloquear;
   - pacote: liberar (congelar as revisões atuais), alerta de revisão nova e atualizar o pacote.
3. **`apontamentos.py`:**
   - iniciar, pausar, retomar e encerrar, com um apontamento aberto por operador;
   - edição pela gestão;
   - totais de trabalho e de parada por OP, etapa, operador e motivo.
4. **`importar.py`:** ler CSV/XLSX (cabeçalho e linhas) e aplicar o mapeamento de colunas.
5. **`materiais.py`:** importar a lista, mudar a situação do item, consultar as faltas.
6. **`testes.py`:**
   - blocos A a E, a situação de cada um e a conclusão dos obrigatórios;
   - NCs: abrir, corrigir, verificar;
   - amostragem: sortear, validar quem verifica, falhar (zera o ponto a ponto) ou aprovar.
7. **`relatorio.py`:** gerar o relatório de ensaio em HTML.
8. **`gestao.py`:** indicadores (OPs por etapa, atrasadas, horas, paradas por motivo, faltas, Pareto de NCs, apontamentos abertos há mais de 10 h).
9. **Interface:**
   - `orbit/ui/api_producao.py` (mixin da Api);
   - telas `js/views/producao.js` (Fila, Meu trabalho, Gestão), `js/views/op.js` (abas da OP), a seção Produção no painel do projeto e Configurações → Produção.
10. **Entrega:** `requirements.txt` (openpyxl==3.1.5), README e o `.exe`.

A cada tarefa: teste que falha → implementação → `pytest -q` verde → commit.
