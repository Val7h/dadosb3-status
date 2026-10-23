#!/usr/bin/env python3
"""Verificação externa do Dados B3 (biblioteca padrão; roda no GitHub Actions, fora do servidor do site).

Faz GET em cada endereço (tempo limite de 20 s, 2 tentativas) e confere o que precisa estar certo.
Quando algo falha, ACRESCENTA uma linha por verificação em status/historico.csv e sai com código 1
(o job falha e o GitHub avisa o dono por e-mail). Quando tudo passa, não escreve nada e sai com 0.

Uso:  python verificar.py [--base https://dadosb3.com] [--historico status/historico.csv] [--limite-dias 6]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_PADRAO = "https://dadosb3.com"
CAMINHOS = ("/saude", "/", "/acoes/PETR4", "/fiis/mxrf11", "/sitemap.xml", "/mcp")
CABECALHO = ("data_utc", "url", "codigo", "tempo_ms", "motivo")
TEMPO_LIMITE_S = 20
TENTATIVAS = 2
PAUSA_ENTRE_TENTATIVAS_S = 5
USER_AGENT = "DadosB3-monitor-externo/1.0 (+status)"


def buscar(url: str, tempo_limite: float = TEMPO_LIMITE_S) -> tuple[int, bytes, int]:
    """(código HTTP, corpo, tempo em ms). Código 0 = sem resposta (rede, tempo esgotado, DNS)."""
    inicio = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=tempo_limite) as r:
            corpo = r.read(2_000_000)
            return r.status, corpo, int((time.monotonic() - inicio) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, b"", int((time.monotonic() - inicio) * 1000)
    except Exception:  # noqa: BLE001 - rede, DNS, TLS, tempo esgotado
        return 0, b"", int((time.monotonic() - inicio) * 1000)


def conferir_saude(corpo: bytes, limite_dias: int) -> str | None:
    """None se está tudo certo; senão o motivo, em uma frase."""
    try:
        d = json.loads(corpo.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return "resposta não é JSON válido"
    if not isinstance(d, dict):
        return "JSON inesperado (não é um objeto)"
    estado = (d.get("build") or {}).get("estado")
    if estado != "ok":
        return f"build.estado = {estado!r} (esperado 'ok')"
    dias = (d.get("cobertura_de_preco") or {}).get("dias_desde_o_ultimo_pregao")
    if not isinstance(dias, int):
        return "cobertura_de_preco.dias_desde_o_ultimo_pregao ausente"
    if dias > limite_dias:
        return f"último pregão há {dias} dias (limite {limite_dias})"
    return None


def verificar_um(url: str, saude: bool, limite_dias: int, buscar_fn=buscar, dorme=time.sleep) -> tuple[int, int, str | None]:
    """(código, tempo_ms, motivo ou None). Até TENTATIVAS vezes; a última resposta é a que vale."""
    codigo, ms, motivo = 0, 0, "sem tentativa"
    for i in range(TENTATIVAS):
        codigo, corpo, ms = buscar_fn(url)
        if codigo == 200:
            motivo = conferir_saude(corpo, limite_dias) if saude else None
        elif codigo == 0:
            motivo = "sem resposta (rede ou tempo esgotado)"
        else:
            motivo = f"HTTP {codigo}"
        if motivo is None:
            return codigo, ms, None
        if i + 1 < TENTATIVAS:
            dorme(PAUSA_ENTRE_TENTATIVAS_S)
    return codigo, ms, motivo


def anexar(historico: Path, linhas: list[list]) -> None:
    historico.parent.mkdir(parents=True, exist_ok=True)
    novo = not historico.exists() or historico.stat().st_size == 0
    with historico.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if novo:
            w.writerow(CABECALHO)
        w.writerows(linhas)


def main(argv=None, buscar_fn=buscar, dorme=time.sleep) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_PADRAO)
    ap.add_argument("--historico", default="status/historico.csv")
    ap.add_argument("--limite-dias", type=int, default=6)
    a = ap.parse_args(argv)
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    falhas = []
    for caminho in CAMINHOS:
        url = a.base.rstrip("/") + caminho
        codigo, ms, motivo = verificar_um(url, caminho == "/saude", a.limite_dias, buscar_fn, dorme)
        print(f"{'ok   ' if motivo is None else 'FALHA'} {url} -> {codigo} em {ms} ms" + (f" ({motivo})" if motivo else ""))
        if motivo is not None:
            falhas.append([agora, url, codigo, ms, motivo])
    if falhas:
        anexar(Path(a.historico), falhas)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
