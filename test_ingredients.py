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


class ParseSubstanceEn(unittest.TestCase):
    """Reino Unido (nombres ingleses del dm+d)."""

    def test_quita_sales_de_bases_organicas(self):
        cases = {
            "Loperamide hydrochloride": "loperamide",
            "Codeine phosphate": "codeine",
            "Chlorhexidine gluconate": "chlorhexidine",
            "Ibuprofen sodium dihydrate": "ibuprofen",
            "Ibuprofen lysine": "ibuprofen",
            "Diclofenac diethylammonium": "diclofenac",
            "Docusate sodium": "docusate",
            "Fosfomycin trometamol": "fosfomycin",
            "Hyoscine hydrobromide": "hyoscine",
            "Citric acid monohydrate": "citric acid",
        }
        for raw, expected in cases.items():
            self.assertEqual(ing.parse_substance_en(raw), expected, raw)

    def test_esteres_derivados_y_sales_inorganicas_se_dejan_enteros(self):
        # No se les quita nada: "hyoscine butylbromide" NO es hioscina, un éster NO es su base
        # y en una sal inorgánica importa cuál es la sal. Solo podrán enlazarse con su nombre completo.
        for raw in (
            "Hyoscine butylbromide",
            "Beclometasone dipropionate",
            "Hydrocortisone acetate",
            "Calcium carbonate",
            "Zinc sulfate monohydrate",
            "Riboflavin sodium phosphate",   # éster fosfato: no es riboflavina
            "Menadiol sodium phosphate",
            "Ferric ammonium citrate",
        ):
            self.assertEqual(ing.parse_substance_en(raw), ing.plain(raw).replace(" monohydrate", ""), raw)

    def test_se_niega_a_interpretar_lo_raro(self):
        for raw in ("Macrogol '3350'", "Carbomer 980", "Ethanol 30%", "Oxygen", "Sodium", "Zinc"):
            self.assertIsNone(ing.parse_substance_en(raw), raw)


class ProponerEspanolEn(unittest.TestCase):
    def test_terminaciones(self):
        cases = {
            "ibuprofen": "ibuprofeno",
            "caffeine": "cafeina",
            "hydrocortisone": "hidrocortisona",
            "dextromethorphan": "dextrometorfano",
            "cinnarizine": "cinarizina",
            "folic acid": "acido folico",
            "salicylic acid": "acido salicilico",
            "sodium chloride": "sodio cloruro",
            "zinc oxide": "zinc oxido",
            "ferrous fumarate": "hierro fumarato",
            "benzalkonium chloride": "benzalconio cloruro",
        }
        for en, es in cases.items():
            self.assertEqual(ing.propose_spanish_en(en), es, en)

    def test_la_k_se_puede_conservar(self):
        self.assertEqual(ing.propose_spanish_en("ketoconazole", k_to_c=False), "ketoconazol")


class ResolverEn(unittest.TestCase):
    links = {"paracetamol": "paracetamol", "caffeine": "cafeína", "hyoscine": "escopolamina"}
    index = ing.build_es_index(["paracetamol + cafeína", "paracetamol", "escopolamina"])

    def resolve(self, substances):
        return ing.resolve(substances, self.links, self.index, parse=ing.parse_substance_en)

    def test_combinaciones_como_conjunto(self):
        self.assertEqual(self.resolve(["Caffeine", "Paracetamol"]), ("paracetamol + cafeína", "enlazado"))

    def test_la_sal_no_impide_el_enlace(self):
        self.assertEqual(self.resolve(["Hyoscine hydrobromide"]), ("escopolamina", "enlazado"))

    def test_hyoscine_butylbromide_no_se_enlaza_con_hioscina(self):
        self.assertEqual(self.resolve(["Hyoscine butylbromide"]), (None, "sin_enlace"))


class TablaDeEnlacesUK(unittest.TestCase):
    # Pares que NUNCA deben estar en uso: parecen iguales y son sustancias distintas.
    PROHIBIDOS = {
        "hyoscine butylbromide": "escopolamina",
        "beclometasone dipropionate": "beclometasona",
        "hydrocortisone acetate": "hidrocortisona",
        "cyclizine": "cetirizina",
        "cinnarizine": "cetirizina",
        "levomenthol": "mentol",
    }

    def test_ningun_par_prohibido_esta_en_uso(self):
        links = ing.load_links(ing.LINKS_PATH_UK)
        for en, es in self.PROHIBIDOS.items():
            self.assertNotEqual(links.get(ing.plain(en)), es, f"{en} -> {es} no debe estar en uso")

    def test_solo_se_usan_estados_revisados(self):
        import csv
        usable = ing.load_links(ing.LINKS_PATH_UK)
        with open(ing.LINKS_PATH_UK, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if ing.plain(row["nombre_en"]) in usable:
                    self.assertIn(row["estado"], ing.USABLE_STATUSES, row["nombre_en"])

    def test_cada_par_en_uso_esta_confirmado_con_evidencia(self):
        import csv
        with open(ing.LINKS_PATH_UK, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["estado"] in ing.USABLE_STATUSES:
                    self.assertTrue(row["evidencia"].strip(), f"{row['nombre_en']} sin evidencia")


if __name__ == "__main__":
    unittest.main()
