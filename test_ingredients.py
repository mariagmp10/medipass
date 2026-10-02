"""
Pruebas de seguridad del enlace de principios activos.

Ejecutar con:   python -m unittest test_ingredients -v

Protegen la regla más importante del proyecto: un enlace solo existe si es la
MISMA sustancia. Los casos "nunca deben enlazarse" son errores reales que
aparecieron al proponer enlaces por parecido de nombres.
"""

import unittest

import ingredients as ing


class ParseSubstance(unittest.TestCase):
    def test_quita_sales_de_bases_organicas(self):
        cases = {
            "CHLORHYDRATE DE LOPÉRAMIDE": "lopéramide",
            "LOPÉRAMIDE (CHLORHYDRATE DE)": "lopéramide",
            "NITRATE D'ÉCONAZOLE": "éconazole",
            "PANTOPRAZOLE SODIQUE SESQUIHYDRATÉ": "pantoprazole",
            "DICLOFÉNAC DE DIÉTHYLAMINE": "diclofénac",
            "IBUPROFÈNE (LYSINATE D')": "ibuprofène",
            "SOLUTION DE DIGLUCONATE DE CHLORHEXIDINE": "chlorhexidine",
        }
        for raw, expected in cases.items():
            self.assertEqual(ing.parse_substance(raw), expected, raw)

    def test_se_niega_a_interpretar_lo_ambiguo(self):
        for raw in (
            "DL-LYSINE (ACÉTYLSALICYLATE DE)",   # el activo es la aspirina, no la lisina
            "NITRATE D'ARGENT",                  # sal inorgánica entera
            "MAGNÉSIUM (GLUCONATE DE)",          # con minerales importa qué sal es
            "BÉTAMÉTHASONE (DIPROPIONATE DE)",   # éster: otro medicamento
            "ÉTHANOL À 70 POUR CENT",            # lleva cifras
        ):
            self.assertIsNone(ing.parse_substance(raw), raw)


class ProponerEspanol(unittest.TestCase):
    def test_terminaciones(self):
        cases = {
            "lopéramide": "loperamida",
            "ibuprofène": "ibuprofeno",
            "diclofénac": "diclofenaco",
            "dextrométhorphane": "dextrometorfano",
            "acide acétylsalicylique": "acido acetilsalicilico",
            "chlorhexidine": "clorhexidina",
        }
        for fr, es in cases.items():
            self.assertEqual(ing.propose_spanish(fr), es, fr)


class Resolver(unittest.TestCase):
    links = {ing.plain("paracétamol"): "paracetamol", ing.plain("caféine"): "cafeína"}
    index = ing.build_es_index(["paracetamol + cafeína", "paracetamol"])

    def test_las_combinaciones_se_comparan_como_conjunto(self):
        self.assertEqual(ing.resolve(["CAFÉINE", "PARACÉTAMOL"], self.links, self.index), ("paracetamol + cafeína", "enlazado"))

    def test_si_falta_un_componente_no_se_enlaza(self):
        self.assertEqual(ing.resolve(["PARACÉTAMOL", "OXOMÉMAZINE"], self.links, self.index), (None, "sin_enlace"))

    def test_no_se_inventa_una_combinacion_que_no_existe(self):
        index = ing.build_es_index(["paracetamol"])
        self.assertEqual(ing.resolve(["PARACÉTAMOL", "CAFÉINE"], self.links, index), (None, "combinacion_sin_equivalente"))


class TablaDeEnlaces(unittest.TestCase):
    # Pares que NUNCA deben estar en uso: parecen iguales y son sustancias distintas.
    PROHIBIDOS = {
        "alanine": "alantoína",
        "cystéine": "cistina",
        "alcool propylique": "alcohol isopropílico",
        "kétoprofène": "piketoprofeno",
        "salicylate de choline": "salicilato de trolamina",
    }

    def test_ningun_par_prohibido_esta_en_uso(self):
        links = ing.load_links()
        for fr, es in self.PROHIBIDOS.items():
            self.assertNotEqual(links.get(ing.plain(fr)), es, f"{fr} -> {es} no debe estar en uso")

    def test_solo_se_usan_estados_revisados(self):
        import csv
        with open(ing.LINKS_PATH, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if ing.plain(row["nombre_fr"]) in ing.load_links():
                    self.assertIn(row["estado"], ing.USABLE_STATUSES, row["nombre_fr"])


if __name__ == "__main__":
    unittest.main()
