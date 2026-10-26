"""Relatório de ensaio da OP em HTML imprimível (spec Produção §4 "Relatório").

Gravado em `<pasta da OP>/Relatório de ensaio OP-NNNN.html`. É o único
arquivo regravado pelo módulo, porque é sempre derivado do op.json.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from orbit.core.errors import OrbitError
from orbit.core.producao.materiais import resumo as resumo_materiais
from orbit.core.producao.modelo import NOMES_ETAPAS, ProducaoService
from orbit.core.producao.testes import NOMES_BLOCOS, situacao

_RES = {"ok": "OK", "nc": "NC", "na": "N/A", None: "—"}
_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;font-size:11px;color:#111;margin:24px}
h1{font-size:18px;margin:0 0 4px}h2{font-size:13px;margin:18px 0 6px;border-bottom:1px solid #999}
table{border-collapse:collapse;width:100%;margin-bottom:6px}
th,td{border:1px solid #bbb;padding:3px 5px;text-align:left;vertical-align:top}
th{background:#eee}.nc{color:#b00;font-weight:600}.ok{color:#060}
.id td{border:none;padding:1px 8px 1px 0}.ass{display:flex;gap:40px;margin-top:40px}
.ass div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}
.resumo{font-weight:600}@media print{body{margin:10mm}h2{break-after:avoid}}
"""


def _e(v) -> str:
    return escape("" if v is None else str(v))


def _quando(s) -> str:
    if not s:
        return ""
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]} {s[11:16]}"


def _res(r) -> str:
    cls = "nc" if r == "nc" else "ok" if r == "ok" else ""
    return f'<td class="{cls}">{_RES.get(r, _e(r))}</td>'


def _tabela(cab: list[str], linhas: list[str]) -> str:
    if not linhas:
        return "<p>Sem registros.</p>"
    th = "".join(f"<th>{_e(c)}</th>" for c in cab)
    return f"<table><tr>{th}</tr>{''.join(linhas)}</table>"


def gerar_html(svc: ProducaoService, op: dict) -> str:
    c = svc.repo.load_container(op["container_id"])
    cli = svc.repo.cliente_de(c)
    cfg = svc.config()
    t = op["testes"]
    st = situacao(op, cfg)
    p = []
    p.append(f"<h1>Relatório de ensaio — {_e(op['numero'])} — {_e(op['painel'])}</h1>")
    p.append('<table class="id">'
             f"<tr><td>Cliente:</td><td><b>{_e(cli.nome if cli else '—')}</b></td>"
             f"<td>Projeto/máquina:</td><td><b>{_e(c.codigo)} {_e(c.nome)}</b></td></tr>"
             f"<tr><td>Painel:</td><td><b>{_e(op['painel'])}</b></td>"
             f"<td>Quantidade:</td><td>{_e(op.get('quantidade', 1))}</td></tr>"
             f"<tr><td>Etapa:</td><td>{_e(NOMES_ETAPAS.get(op['etapa'], op['etapa']))}</td>"
             f"<td>Responsável:</td><td>{_e(op.get('responsavel'))}</td></tr>"
             f"<tr><td>Gerado em:</td><td>{_e(_quando(svc.agora_iso()))}</td>"
             "<td>Norma de referência:</td><td>IEC 61439-1 §11 (verificação de rotina)</td>"
             "</tr></table>")

    p.append("<h2>Documentos utilizados na montagem</h2>")
    p.append(_tabela(["Documento", "Revisão", "Arquivo", "Status"], [
        f"<tr><td>{_e(d['nome'])}</td><td>Rev{d['numero']:02d}</td><td>{_e(d['principal'])}</td>"
        f"<td>{_e(d.get('status'))}</td></tr>" for d in op.get("pacote") or []]))

    p.append("<h2>Resumo dos ensaios</h2>")
    p.append(_tabela(["Bloco", "Situação", "Feitos", "NC"], [
        f"<tr><td>{_e(NOMES_BLOCOS[b])}{'' if s['obrigatorio'] else ' (opcional)'}</td>"
        f"<td>{_e({'concluido': 'Concluído', 'em_andamento': 'Em andamento', 'nao_iniciado': 'Não iniciado'}[s['estado']])}</td>"
        f"<td>{s['feitos']}/{s['total']}</td><td>{s['nc']}</td></tr>" for b, s in st.items()]))

    p.append("<h2>A. Inspeção de rotina (IEC 61439-1 §11)</h2>")
    p.append(_tabela(["Ref.", "Item", "Resultado", "Obs.", "Por", "Em"], [
        f"<tr><td>{_e(i['ref'])}</td><td>{_e(i['texto'])}</td>{_res(i['resultado'])}"
        f"<td>{_e(i.get('obs'))}</td><td>{_e(i.get('por'))}</td><td>{_e(_quando(i.get('em')))}</td></tr>"
        for i in t["inspecao"]["itens"]]))

    linhas = t["ponto_a_ponto"]["linhas"]
    p.append("<h2>B. Ponto a ponto (ligação e aperto)</h2>")
    p.append(_tabela(["Origem", "Destino", "Fio", "Seção", "Cor", "Ligação", "Aperto", "Por",
                      "Em"], [
        f"<tr><td>{_e(l['origem'])}</td><td>{_e(l['destino'])}</td><td>{_e(l['fio'])}</td>"
        f"<td>{_e(l['secao'])}</td><td>{_e(l['cor'])}</td>{_res(l['ligacao'])}{_res(l['aperto'])}"
        f"<td>{_e(l.get('por'))}</td><td>{_e(_quando(l.get('em')))}</td></tr>" for l in linhas]))

    p.append(f"<h2>C. Resistência de isolação (critério ≥ {_e(cfg['isolacao_min_mohm'])} MΩ)</h2>")
    p.append(_tabela(["Circuito", "Tensão de ensaio (V)", "Medido (MΩ)", "Resultado", "Por",
                      "Em"], [
        f"<tr><td>{_e(x['nome'])}</td><td>{_e(x['tensao_v'])}</td><td>{_e(x.get('medido_mohm'))}</td>"
        f"{_res(x['resultado'])}<td>{_e(x.get('por'))}</td><td>{_e(_quando(x.get('em')))}</td></tr>"
        for x in t["isolacao"]["circuitos"]]))

    p.append(f"<h2>D. Energização (tolerância ±{_e(cfg['tolerancia_tensao_pct'])}%)</h2>")
    p.append(_tabela(["Passo", "Resultado", "Obs.", "Por"], [
        f"<tr><td>{_e(x['texto'])}</td>{_res(x['resultado'])}<td>{_e(x.get('obs'))}</td>"
        f"<td>{_e(x.get('por'))}</td></tr>" for x in t["energizacao"]["passos"]]))
    p.append(_tabela(["Ponto", "Esperado (V)", "Medido (V)", "Resultado", "Por"], [
        f"<tr><td>{_e(x['nome'])}</td><td>{_e(x['esperado_v'])}</td><td>{_e(x.get('medido_v'))}</td>"
        f"{_res(x['resultado'])}<td>{_e(x.get('por'))}</td></tr>"
        for x in t["energizacao"]["pontos"]]))

    p.append("<h2>E. Entradas e saídas</h2>")
    p.append(_tabela(["Tag", "Descrição", "Endereço", "Tipo", "Resultado", "Por"], [
        f"<tr><td>{_e(x['tag'])}</td><td>{_e(x['descricao'])}</td><td>{_e(x['endereco'])}</td>"
        f"<td>{_e(x['tipo'])}</td>{_res(x['resultado'])}<td>{_e(x.get('por'))}</td></tr>"
        for x in t["io"]["sinais"]]))

    p.append("<h2>Não conformidades</h2>")
    situ = {"aberta": "Aberta", "corrigida": "Corrigida", "verificada": "Verificada (reteste OK)"}
    p.append(_tabela(["Nº", "Tipo", "Descrição", "Aberta por", "Correção", "Reteste", "Situação"], [
        f"<tr><td>{n['numero']}</td><td>{_e(n['tipo'])}</td><td>{_e(n['descricao'])}</td>"
        f"<td>{_e(n['aberta_por'])} {_e(_quando(n['aberta_em']))}</td>"
        f"<td>{_e(n.get('correcao'))} {_e(n.get('corrigida_por'))}</td>"
        f"<td>{_e(n.get('verificada_por'))} {_e(_quando(n.get('verificada_em')))}</td>"
        f"<td>{_e(situ.get(n['situacao'], n['situacao']))}</td></tr>" for n in op["ncs"]]))

    v = t["verificacao"]
    p.append("<h2>Verificação final por amostragem</h2>")
    if v.get("sorteadas"):
        pp = {l["id"]: l for l in linhas}
        aprov = {True: "APROVADA", False: "REPROVADA", None: "em andamento"}[v.get("aprovada")]
        p.append(f'<p class="resumo">Verificador: {_e(v.get("verificador"))} — '
                 f'{len(v["sorteadas"])} de {len(linhas)} ligações conferidas — {aprov}</p>')
        p.append(_tabela(["Origem", "Destino", "Resultado", "Obs."], [
            f"<tr><td>{_e(pp.get(i, {}).get('origem'))}</td><td>{_e(pp.get(i, {}).get('destino'))}</td>"
            f"{_res((v['resultados'].get(i) or {}).get('resultado'))}"
            f"<td>{_e((v['resultados'].get(i) or {}).get('obs'))}</td></tr>" for i in v["sorteadas"]]))
        p.append(_tabela(["Checklist final", "Resultado"], [
            f"<tr><td>{_e(x['texto'])}</td>{_res(x['resultado'])}</tr>" for x in v["checklist"]]))
    else:
        p.append("<p>Ainda não realizada.</p>")

    rm = resumo_materiais(op)
    if rm["total"]:
        p.append(f"<p>Materiais: {rm['total']} itens; em falta: {rm['falta']}.</p>")

    p.append('<div class="ass"><div>Montagem / ensaio</div><div>Verificação final</div>'
             '<div>Responsável técnico</div></div>')
    titulo = _e(f"Relatório de ensaio {op['numero']} - {op['painel']}")
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{titulo}'
            f"</title><style>{_CSS}</style></head><body>{''.join(p)}</body></html>")


def gerar(svc: ProducaoService, op_id: str) -> Path:
    op = svc.carregar(op_id)
    html = gerar_html(svc, op)
    destino = svc.pasta_op(op_id) / f"Relatório de ensaio {op['numero']}.html"
    try:
        tmp = destino.with_suffix(".html.tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(destino)
    except OSError as e:
        raise OrbitError(f"Não foi possível gravar o relatório: {e}") from e
    return destino
