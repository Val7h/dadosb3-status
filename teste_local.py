"""Teste local (biblioteca padrão):  python teste_local.py"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import gerar_pagina as G
import verificar as V

AQUI = Path(__file__).parent
AGORA = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class TestePagina(unittest.TestCase):
    def test_exemplo(self):
        linhas = G.ler(AQUI / "exemplo" / "historico_exemplo.csv")
        inc = G.incidentes(linhas, AGORA)
        self.assertEqual(len(inc), 5)
        self.assertTrue(inc[0]["em_andamento"] and inc[0]["verificacao"] == "/")
        sitemap = [i for i in inc if i["verificacao"] == "/sitemap.xml"][0]
        self.assertEqual((sitemap["fim"] - sitemap["inicio"]).total_seconds(), 897)   # 07:30:12 a 07:45:09
        pagina = G.montar(linhas, AGORA)
        for proibido in ("<script", "http://", "https://", "@import", "<link"):
            self.assertNotIn(proibido, pagina)
        self.assertIn("Medido de fora do servidor do Dados B3. Dados da B3 e da CVM têm a própria fonte; veja /saude do site para a atualização dos dados", pagina)
        self.assertIn('lang="en"', pagina)

    def test_sem_historico(self):
        pagina = G.montar([], AGORA)
        self.assertIn("Tudo funcionando", pagina)
        self.assertIn("100,00 %", pagina)
        self.assertIn("Nenhum incidente registrado", pagina)

    def test_nao_reescreve_so_por_causa_do_carimbo(self):
        with tempfile.TemporaryDirectory() as d:
            saida = Path(d) / "index.html"
            self.assertTrue(G.gravar(saida, G.montar([], AGORA), AGORA))
            from datetime import timedelta
            depois = AGORA + timedelta(minutes=5)
            self.assertFalse(G.gravar(saida, G.montar([], depois), depois))        # mesma página, carimbo novo: não escreve
            muito_depois = AGORA + timedelta(minutes=90)
            self.assertTrue(G.gravar(saida, G.montar([], muito_depois), muito_depois))   # passou 1 h: renova o carimbo


class TesteVerificacao(unittest.TestCase):
    BOM = json.dumps({"build": {"estado": "ok"}, "cobertura_de_preco": {"dias_desde_o_ultimo_pregao": 1}}).encode()

    def test_saude(self):
        self.assertIsNone(V.conferir_saude(self.BOM, 6))
        self.assertIn("JSON", V.conferir_saude(b"<html>", 6))
        ruim = json.dumps({"build": {"estado": "falhou"}, "cobertura_de_preco": {"dias_desde_o_ultimo_pregao": 1}}).encode()
        self.assertIn("build.estado", V.conferir_saude(ruim, 6))
        velho = json.dumps({"build": {"estado": "ok"}, "cobertura_de_preco": {"dias_desde_o_ultimo_pregao": 9}}).encode()
        self.assertIn("9 dias", V.conferir_saude(velho, 6))

    def test_duas_tentativas_e_historico(self):
        chamadas = []

        def falso(url, tempo=20):
            chamadas.append(url)
            return (502, b"", 10) if url.endswith("/sitemap.xml") else (200, self.BOM, 10)
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "status" / "historico.csv"
            rc = V.main(["--historico", str(h)], buscar_fn=falso, dorme=lambda s: None)
            self.assertEqual(rc, 1)
            self.assertEqual(sum(u.endswith("/sitemap.xml") for u in chamadas), 2)      # 2 tentativas
            linhas = h.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(linhas), 2)                                           # cabeçalho + 1 falha
            self.assertIn("https://dadosb3.com/sitemap.xml,502,10,HTTP 502", linhas[1])
            rc = V.main(["--historico", str(h)], buscar_fn=lambda u, t=20: (200, self.BOM, 5), dorme=lambda s: None)
            self.assertEqual(rc, 0)
            self.assertEqual(len(h.read_text(encoding="utf-8").splitlines()), 2)       # sucesso não escreve


if __name__ == "__main__":
    unittest.main(verbosity=2)
