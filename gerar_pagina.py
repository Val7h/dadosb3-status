#!/usr/bin/env python3
"""Gera docs/index.html (página de status estática, português e inglês, sem JavaScript, sem fonte externa)
a partir de status/historico.csv. Só biblioteca padrão.

O histórico guarda apenas as FALHAS (uma linha por verificação que falhou: data_utc,url,codigo,tempo_ms,motivo).
Como o monitor roda a cada 5 minutos, o resto do tempo conta como disponível:
  - falhas consecutivas da mesma verificação, com intervalo de até 12 min entre elas, formam UM incidente;
  - o incidente começa na primeira falha e termina 5 min depois da última (a próxima rodada já passou);
  - incidente com a última falha há 12 min ou menos ainda está em andamento.
Se existir status/desde.txt (AAAA-MM-DD), a disponibilidade só conta a partir dessa data.

Uso:  python gerar_pagina.py [--historico status/historico.csv] [--saida docs/index.html] [--agora 2026-10-23T12:00:00Z]
"""
from __future__ import annotations

import argparse
import csv
import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

INTERVALO = timedelta(minutes=5)
FOLGA = timedelta(minutes=12)
JANELAS = ((timedelta(hours=24), "24 h", "24 h"), (timedelta(days=7), "7 dias", "7 days"), (timedelta(days=30), "30 dias", "30 days"))
VERIFICACOES = (
    ("/saude", "Saúde dos dados (/saude)", "Data health (/saude)"),
    ("/", "Página inicial", "Home page"),
    ("/acoes/PETR4", "Página de ação (PETR4)", "Stock page (PETR4)"),
    ("/fiis/mxrf11", "Página de FII (MXRF11)", "FII page (MXRF11)"),
    ("/sitemap.xml", "Mapa do site (sitemap.xml)", "Sitemap (sitemap.xml)"),
    ("/mcp", "Conector de IA (/mcp)", "AI connector (/mcp)"),
)
MAX_INCIDENTES = 20
AVISO_PT = ("Medido de fora do servidor do Dados B3. Dados da B3 e da CVM têm a própria fonte; "
            "veja /saude do site para a atualização dos dados.")
AVISO_EN = ("Measured from outside the Dados B3 server. B3 and CVM data have their own source; "
            "see the site's /saude for data freshness.")
_RE_CARIMBO = re.compile(r"<!--GERADO-->.*?<!--/GERADO-->", re.S)


def _tempo(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def ler(historico: Path) -> list[dict]:
    """Falhas registradas, em ordem de tempo. Linha torta é ignorada (o histórico é só acrescentado por robô)."""
    linhas: list[dict] = []
    if not historico.exists():
        return linhas
    with historico.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                linhas.append({"quando": _tempo(r["data_utc"]), "url": (r["url"] or "").strip(),
                               "codigo": (r.get("codigo") or "").strip(), "ms": (r.get("tempo_ms") or "").strip(),
                               "motivo": (r.get("motivo") or "").strip()})
            except Exception:  # noqa: BLE001
                continue
    return sorted(linhas, key=lambda x: x["quando"])


def _caminho(url: str) -> str:
    return urlsplit(url).path or "/"


def incidentes(linhas: list[dict], agora: datetime) -> list[dict]:
    """Agrupa as falhas por verificação em incidentes: {verificacao, inicio, fim, em_andamento, codigo, motivo}."""
    por: dict[str, list[dict]] = {}
    for l in linhas:
        por.setdefault(_caminho(l["url"]), []).append(l)
    out = []
    for caminho, ls in por.items():
        atual = None
        for l in ls:
            if atual and l["quando"] - atual["ultima"] <= FOLGA:
                atual["ultima"] = l["quando"]
                atual["codigo"], atual["motivo"] = l["codigo"], l["motivo"]
            else:
                if atual:
                    out.append(atual)
                atual = {"verificacao": caminho, "inicio": l["quando"], "ultima": l["quando"],
                         "codigo": l["codigo"], "motivo": l["motivo"]}
        if atual:
            out.append(atual)
    for i in out:
        i["em_andamento"] = agora - i["ultima"] <= FOLGA
        i["fim"] = agora if i["em_andamento"] else i["ultima"] + INTERVALO
    return sorted(out, key=lambda i: i["inicio"], reverse=True)


def _uniao(intervalos: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    res: list[tuple[datetime, datetime]] = []
    for a, b in sorted(intervalos):
        if res and a <= res[-1][1]:
            res[-1] = (res[-1][0], max(res[-1][1], b))
        else:
            res.append((a, b))
    return res


def disponibilidade(intervalos: list[tuple[datetime, datetime]], janela: timedelta, agora: datetime,
                    desde: datetime | None) -> float:
    ini = agora - janela
    if desde and desde > ini:
        ini = min(desde, agora)
    total = (agora - ini).total_seconds()
    if total <= 0:
        return 100.0
    fora = 0.0
    for a, b in _uniao(intervalos):
        a, b = max(a, ini), min(b, agora)
        if b > a:
            fora += (b - a).total_seconds()
    return max(0.0, 100.0 * (1 - fora / total))


def _pct(v: float) -> str:
    # nunca arredonda para cima até 100,00 quando houve falha
    s = f"{v:.2f}".replace(".", ",")
    return "99,99 %" if s == "100,00" and v < 100 else f"{s} %"


def _duracao(d: timedelta) -> tuple[str, str]:
    m = max(1, int(d.total_seconds() // 60))
    if m < 60:
        return f"{m} min", f"{m} min"
    h, r = divmod(m, 60)
    if h < 24:
        return (f"{h} h {r:02d} min", f"{h} h {r:02d} min")
    dd, h = divmod(h, 24)
    return f"{dd} d {h} h", f"{dd} d {h} h"


def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


def _bi(pt: str, en: str) -> str:
    return f'<span lang="pt-BR">{html.escape(pt)}</span><br><span lang="en">{html.escape(en)}</span>'


def montar(linhas: list[dict], agora: datetime, desde: datetime | None = None) -> str:
    inc = incidentes(linhas, agora)
    por_ver: dict[str, list[tuple[datetime, datetime]]] = {}
    for i in inc:
        por_ver.setdefault(i["verificacao"], []).append((i["inicio"], i["fim"]))
    todos = [iv for v in por_ver.values() for iv in v]
    abertos = {i["verificacao"] for i in inc if i["em_andamento"]}
    n_fora = sum(1 for c, _, _ in VERIFICACOES if c in abertos)

    if n_fora == 0:
        geral = '<p class="geral ok">' + _bi("Tudo funcionando", "All systems operational") + "</p>"
    else:
        geral = ('<p class="geral falha">'
                 + _bi(f"{n_fora} verificação(ões) com falha agora", f"{n_fora} check(s) failing now") + "</p>")

    linhas_tab = []
    for caminho, pt, en in VERIFICACOES:
        fora = caminho in abertos
        estado = (f'<td class="falha">{_bi("Com falha", "Failing")}</td>' if fora
                  else f'<td class="ok">{_bi("No ar", "Up")}</td>')
        cel = "".join(f'<td class="n">{_pct(disponibilidade(por_ver.get(caminho, []), j, agora, desde))}</td>'
                      for j, _, _ in JANELAS)
        linhas_tab.append(f"<tr><th scope=\"row\">{_bi(pt, en)}</th>{estado}{cel}</tr>")
    cel = "".join(f'<td class="n">{_pct(disponibilidade(todos, j, agora, desde))}</td>' for j, _, _ in JANELAS)
    linhas_tab.append(f'<tr class="tot"><th scope="row">{_bi("Todas as verificações juntas (basta uma falhar)", "All checks together (any one failing counts)")}</th>'
                      f'<td></td>{cel}</tr>')
    cab_janelas = "".join(f"<th scope=\"col\" class=\"n\">{_bi(pt, en)}</th>" for _, pt, en in JANELAS)

    rotulo = {c: (pt, en) for c, pt, en in VERIFICACOES}
    if inc:
        itens = []
        for i in inc[:MAX_INCIDENTES]:
            pt, en = rotulo.get(i["verificacao"], (i["verificacao"], i["verificacao"]))
            dpt, den = _duracao(i["fim"] - i["inicio"])
            fim = (f'<span class="falha">{_bi("em andamento", "ongoing")}</span>' if i["em_andamento"]
                   else html.escape(_fmt(i["fim"])))
            motivo = html.escape(i["motivo"] or ("HTTP " + i["codigo"] if i["codigo"] else ""))
            itens.append(f"<tr><td>{_bi(pt, en)}</td><td class=\"n\">{html.escape(_fmt(i['inicio']))}</td>"
                         f"<td class=\"n\">{fim}</td><td class=\"n\">{html.escape(dpt)}</td><td>{motivo}</td></tr>")
        incid = ("<table><thead><tr>"
                 f"<th scope=\"col\">{_bi('Verificação', 'Check')}</th><th scope=\"col\">{_bi('Início', 'Start')}</th>"
                 f"<th scope=\"col\">{_bi('Fim', 'End')}</th><th scope=\"col\">{_bi('Duração', 'Duration')}</th>"
                 f"<th scope=\"col\">{_bi('O que falhou', 'What failed')}</th></tr></thead><tbody>" + "".join(itens) + "</tbody></table>")
    else:
        incid = "<p>" + _bi("Nenhum incidente registrado.", "No incidents recorded.") + "</p>"

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Status do Dados B3 · Dados B3 status</title>
<style>
:root{{--bg:#fff;--fg:#1a1d21;--mut:#5b6470;--lin:#d9dde3;--ok:#127a3a;--falha:#b3261e;--cartao:#f5f7fa}}
@media (prefers-color-scheme:dark){{:root{{--bg:#101316;--fg:#e8eaed;--mut:#9aa3ad;--lin:#2a3036;--ok:#4cc27a;--falha:#ff8a80;--cartao:#181c20}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:60rem;margin:0 auto;padding:1rem}}
h1{{font-size:1.6rem;margin:.5rem 0}} h2{{font-size:1.2rem;margin:2rem 0 .5rem}}
.geral{{font-size:1.3rem;font-weight:700;padding:.8rem 1rem;border-radius:.6rem;background:var(--cartao);border-left:.4rem solid var(--ok)}}
.geral.falha{{border-left-color:var(--falha)}} .ok{{color:var(--ok);font-weight:600}} .falha{{color:var(--falha);font-weight:600}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:.45rem .6rem;border-bottom:1px solid var(--lin);text-align:left;vertical-align:top}}
.n{{text-align:right;white-space:nowrap}} tr.tot th,tr.tot td{{font-weight:700}}
.aviso{{background:var(--cartao);padding:.8rem 1rem;border-radius:.6rem;color:var(--mut)}} .mini{{color:var(--mut);font-size:.9rem}}
@media (max-width:40rem){{.rolar{{overflow-x:auto}}}}
</style>
</head>
<body>
<main>
<h1>{_bi("Status do Dados B3", "Dados B3 status")}</h1>
{geral}
<p class="aviso"><span lang="pt-BR">{html.escape(AVISO_PT)}</span><br><span lang="en">{html.escape(AVISO_EN)}</span></p>
<h2>{_bi("Estado atual e disponibilidade", "Current state and availability")}</h2>
<div class="rolar"><table>
<thead><tr><th scope="col">{_bi("Verificação", "Check")}</th><th scope="col">{_bi("Agora", "Now")}</th>{cab_janelas}</tr></thead>
<tbody>
{chr(10).join(linhas_tab)}
</tbody></table></div>
<h2>{_bi(f"Últimos {MAX_INCIDENTES} incidentes", f"Last {MAX_INCIDENTES} incidents")}</h2>
<div class="rolar">{incid}</div>
<p class="mini"><span lang="pt-BR">Uma verificação a cada 5 minutos, de fora do Render; 2 tentativas e 20 s de espera por endereço. Um incidente junta as falhas seguidas da mesma verificação.</span><br>
<span lang="en">One check every 5 minutes, from outside Render; 2 tries and a 20 s wait per address. An incident groups consecutive failures of the same check.</span></p>
<p class="mini"><!--GERADO-->{html.escape(_fmt(agora))}<!--/GERADO--></p>
</main>
</body>
</html>
"""


def gravar(saida: Path, texto: str, agora: datetime, minutos_max: int = 60) -> bool:
    """Grava a página. Não reescreve se só o carimbo de hora mudaria e o carimbo atual tem menos de
    `minutos_max` minutos (evita um commit a cada 5 minutos com o site de pé). True se escreveu."""
    if saida.exists():
        antigo = saida.read_text(encoding="utf-8")
        if _RE_CARIMBO.sub("", antigo) == _RE_CARIMBO.sub("", texto):
            m = re.search(r"<!--GERADO-->(.*?)<!--/GERADO-->", antigo, re.S)
            try:
                feito = datetime.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                if timedelta(0) <= agora - feito < timedelta(minutes=minutos_max):
                    return False
            except Exception:  # noqa: BLE001
                pass
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(texto, encoding="utf-8", newline="\n")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--historico", default="status/historico.csv")
    ap.add_argument("--saida", default="docs/index.html")
    ap.add_argument("--agora", default=None, help="AAAA-MM-DDTHH:MM:SSZ (para teste); padrão: agora, em UTC")
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD; padrão: conteúdo de status/desde.txt, se existir")
    a = ap.parse_args(argv)
    agora = _tempo(a.agora) if a.agora else datetime.now(timezone.utc).replace(microsecond=0)
    desde_txt = a.desde
    arq = Path(a.historico).parent / "desde.txt"
    if not desde_txt and arq.exists():
        desde_txt = arq.read_text(encoding="utf-8").strip()
    desde = datetime.strptime(desde_txt, "%Y-%m-%d").replace(tzinfo=timezone.utc) if desde_txt else None
    linhas = ler(Path(a.historico))
    escreveu = gravar(Path(a.saida), montar(linhas, agora, desde), agora)
    print(f"{'escrita' if escreveu else 'sem mudança'}: {a.saida} ({len(linhas)} falhas no histórico)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
