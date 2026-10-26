"""
Pruebas del importador de Italia (fetch_aifa.py): qué cuenta como "sin receta", qué se excluye,
traducción de formas y limpieza de nombres.

Ejecutar con:   python -m unittest test_fetch_aifa -v
"""

import csv
import os
import tempfile
import unittest

import doses
import fetch_aifa as aifa
import importers
import ingredients as ing

HEADER = ["CODICE_AIC", "COD_FARMACO", "COD_CONFEZIONE", "DENOMINAZIONE", "DESCRIZIONE", "CODICE_DITTA",
          "RAGIONE_SOCIALE", "STATO_AMMINISTRATIVO", "TIPO_PROCEDURA", "FORMA", "CODICE_ATC", "PA_ASSOCIATI",
          "FORNITURA", "LINK_FI", "LINK_RCP"]
OTC = "Medicinali non soggetti a prescrizione medica, da banco."
SOP = "Medicinali non soggetti a prescrizione medica ma non da banco"
RX = "Medicinali soggetti a prescrizione medica"
RX_REPEAT = "Medicinali soggetti a prescrizione medica da rinnovare volta per volta"
RX_SPECIALIST = ("Medicinali soggetti a prescrizione medica limitativa, vendibili al pubblico su prescrizione "
                 "di centri ospedalieri o di specialisti")
RX_HOSPITAL = ("Medicinali soggetti a prescrizione medica limitativa, utilizzabili esclusivamente in ambiente "
               "ospedaliero o in una struttura ad esso assimilabile")


def row(aic, cod, name, desc, form, atc, pa, supply, status="Autorizzata", procedure="Procedura Nazionale"):
    return [aic, cod, "01", name, desc, "1", "Ditta", status, procedure, form, atc, pa, supply, "", ""]


ROWS = [
    row("1", "100", "NUROFEN", "200 MG COMPRESSE RIVESTITE- 12 COMPRESSE", "Compressa rivestita", "M01AE01", "IBUPROFENE", OTC),
    row("2", "100", "NUROFEN", "200 MG COMPRESSE RIVESTITE- 24 COMPRESSE", "Compressa rivestita", "M01AE01", "IBUPROFENE", OTC),
    row("3", "101", "TACHIPIRINA", "120 mg/5 ml sciroppo> flacone da 120 ml", "Sciroppo", "N02BE01", "PARACETAMOLO", SOP),
    row("4", "102", "ANTIBIOTICO", "500 MG COMPRESSE- 12 COMPRESSE", "Compressa", "J01CA04", "AMOXICILLINA", RX),
    row("5", "103", "SPECIALISTA", "10 MG COMPRESSE- 30 COMPRESSE", "Compressa", "N05AH03", "OLANZAPINA", RX_SPECIALIST),
    row("6", "104", "OSPEDALE", "10 MG COMPRESSE- 30 COMPRESSE", "Compressa", "N05AH03", "OLANZAPINA", RX_HOSPITAL),
    row("7", "105", "FIALE", "1 G POLVERE- 1 FIALA", "Soluzione iniettabile", "J01DD04", "CEFTRIAXONE", RX),
    row("8", "106", "OMEO", "GLOBULI", "Compressa", "V60", "ARNICA", OTC, procedure="Omeopatico"),
    row("9", "107", "PARALLELO", "200 MG COMPRESSE- 12 COMPRESSE", "Compressa", "M01AE01", "IBUPROFENE", OTC,
        procedure="Importazione Parallela"),
    row("10", "108", "SOSPESO", "200 MG COMPRESSE- 12 COMPRESSE", "Compressa", "M01AE01", "IBUPROFENE", OTC, status="Sospesa"),
    row("11", "109", "SENZAPA", "200 MG COMPRESSE- 12 COMPRESSE", "Compressa", "M01AE01", "", OTC),
    row("12", "110", "DIALISI", "SACCA", "Concentrato per soluzione per emodialisi", "B05ZB", "SODIO CLORURO", RX),
    row("13", "111", "DUEFORME", "ASTUCCIO", "Crema", "D07AA02", "IDROCORTISONE", OTC),
    row("14", "111", "DUEFORME", "ASTUCCIO", "Unguento", "D07AA02", "IDROCORTISONE", OTC),
    row("15", "112", "MOMENT", "200 MG/30 MG COMPRESSE RIVESTITE- 10 COMPRESSE", "Compressa rivestita", "M01AE51",
        "IBUPROFENE/PSEUDOEFEDRINA CLORIDRATO/IBUPROFEN", OTC),
    row("16", "113", "MISTO", "100 MG COMPRESSE- 10 COMPRESSE", "Compressa", "N02BE01", "PARACETAMOLO", OTC),
    row("17", "113", "MISTO", "100 MG COMPRESSE- 20 COMPRESSE", "Compressa", "N02BE01", "PARACETAMOLO", RX),
    row("18", "114", "RIPETUTA", "5 MG COMPRESSE- 30 COMPRESSE", "Compressa", "N05BA01", "DIAZEPAM", RX_REPEAT),
]
PA = [
    ["1", "IBUPROFENE", "200", "milligrammi"],
    ["3", "PARACETAMOLO", "24", "milligram(s)/millilitre"],
    ["13", "IDROCORTISONE", "1", "percent"],
    ["14", "IDROCORTISONE", "0.5", "percent"],
    ["15", "IBUPROFENE", "200", "milligrammi"],
    ["15", "PSEUDOEFEDRINA CLORIDRATO", "30", "milligrammi"],
]


def write(directory, rows=ROWS, pa=PA):
    with open(os.path.join(directory, "confezioni_fornitura.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(HEADER)
        w.writerows(rows)
    with open(os.path.join(directory, "PA_confezioni.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["CODICE_AIC", "PRINCIPIO_ATTIVO", "QUANTITA", "UNITA_MISURA"])
        w.writerows(pa)


class Catalogo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write(cls.tmp.name)
        cls.catalog, cls.excluded = aifa.load_catalog(cls.tmp.name)
        cls.by_ref = {p["ref"]: p for p in cls.catalog}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_sin_receta_libre_y_solo_farmacia(self):
        nurofen = self.by_ref["100"]
        self.assertEqual((nurofen["requires_prescription"], nurofen["legal_category"]), (0, importers.LEGAL_FREE))
        sop = self.by_ref["101"]
        self.assertEqual((sop["requires_prescription"], sop["legal_category"]), (0, importers.LEGAL_PHARMACY))
        self.assertIn("SOP", sop["legal_note"])

    def test_con_receta_se_marca_y_el_de_especialista_se_queda(self):
        for ref in ("102", "103", "114"):
            p = self.by_ref[ref]
            self.assertEqual((p["requires_prescription"], p["legal_category"]), (1, importers.LEGAL_RX), ref)
        self.assertIn("limitativa", self.by_ref["103"]["legal_note"])
        self.assertIn("rinnovare", self.by_ref["114"]["legal_note"])

    def test_exclusiones(self):
        for ref, why in (("104", "hospital"), ("105", "inyectable"), ("106", "homeopático"), ("107", "importación paralela"),
                         ("108", "no autorizado"), ("109", "sin principio activo"), ("110", "diálisis")):
            self.assertNotIn(ref, self.by_ref, why)
        self.assertEqual(self.excluded["hospital"], 1)
        self.assertEqual(self.excluded["importación paralela"], 1)
        self.assertEqual(self.excluded["homeopático"], 1)

    def test_un_producto_con_envase_sin_receta_cuenta_como_sin_receta(self):
        self.assertEqual(self.by_ref["113"]["requires_prescription"], 0)

    def test_dos_formas_son_dos_productos_con_referencia_distinta(self):
        forms = {p["form"] for p in self.catalog if p["ref"].startswith("111-")}
        self.assertEqual(forms, {"Crema", "Unguento"})
        self.assertEqual(len([p for p in self.catalog if p["ref"].startswith("111-")]), 2)

    def test_nombre_con_dosis_y_sin_tamano_de_envase(self):
        self.assertEqual(self.by_ref["100"]["brand_name"], "NUROFEN 200 MG COMPRESSE RIVESTITE")
        self.assertEqual(self.by_ref["101"]["brand_name"], "TACHIPIRINA 120 mg/5 ml sciroppo")

    def test_nombres_repetidos_se_distinguen_con_el_codigo(self):
        names = [p["brand_name"] for p in self.catalog]
        self.assertEqual(len(names), len(set(names)))

    def test_solo_sin_receta(self):
        catalog, _ = aifa.load_catalog(self.tmp.name, include_prescription=False)
        self.assertTrue(catalog)
        self.assertTrue(all(p["requires_prescription"] == 0 for p in catalog))

    def test_principios_activos_sin_repeticiones(self):
        self.assertEqual(self.by_ref["112"]["substances"], ["IBUPROFENE", "PSEUDOEFEDRINA CLORIDRATO"])
        self.assertEqual(aifa.split_substances("IBUPROFENE SALE DI LISINA/IBUPROFENE"), ["IBUPROFENE SALE DI LISINA"])
        self.assertEqual(aifa.split_substances("ACIDO ASCORBICO/CLORFENAMINA MALEATO/PARACETAMOLO"),
                         ["ACIDO ASCORBICO", "CLORFENAMINA MALEATO", "PARACETAMOLO"])


class Dosis(unittest.TestCase):
    def test_las_dosis_se_leen_de_las_cantidades_del_envase(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp)
            catalog, _ = aifa.load_catalog(tmp)
            by_ref = {p["ref"]: p for p in catalog}
            def s(ref, names):
                import json
                return [(x["i"], x["v"], x["b"]) for x in json.loads(aifa.product_strengths(by_ref[ref], names) or "[]")]
            self.assertEqual(s("100", ["ibuprofeno"]), [("ibuprofeno", 200.0, "unit")])  # comprimido: mg por unidad
            self.assertEqual(s("101", ["paracetamol"]), [("paracetamol", 24.0, "conc")])
            self.assertEqual(s("112", ["ibuprofeno", "pseudoefedrina"]),
                             [("ibuprofeno", 200.0, "unit"), ("pseudoefedrina", 30.0, "unit")])

    def test_sin_cantidad_no_hay_dosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp)
            catalog, _ = aifa.load_catalog(tmp)
            item = dict(next(p for p in catalog if p["ref"] == "102"), description="COMPRESSE- 12 COMPRESSE")
            self.assertEqual(aifa.product_strengths(item, ["amoxicilina"]), doses.dumps([]))

    def test_la_dosis_tambien_sale_del_texto_del_envase(self):
        item = {"form": "Compressa", "description": "500 MG COMPRESSE- 20 COMPRESSE", "substances": ["PARACETAMOLO"], "amounts": []}
        self.assertEqual(aifa.product_strengths(item, ["paracetamol"]), doses.dumps([{"i": "paracetamol", "v": 500.0, "b": "unit"}]))
        syrup = {"form": "Sciroppo", "description": "120 mg/5 ml sciroppo> flacone da 120 ml", "substances": ["PARACETAMOLO"], "amounts": []}
        self.assertEqual(aifa.product_strengths(syrup, ["paracetamol"]), doses.dumps([{"i": "paracetamol", "v": 24.0, "b": "conc"}]))

    def test_si_el_texto_y_las_cantidades_no_coinciden_no_hay_dosis(self):
        item = {"form": "Compressa", "description": "500 MG COMPRESSE- 20 COMPRESSE", "substances": ["PARACETAMOLO"],
                "amounts": [{"paracetamolo": ("1", "grammi")}]}
        self.assertEqual(aifa.product_strengths(item, ["paracetamol"]), doses.dumps([]))
        item["amounts"] = [{"paracetamolo": ("500", "milligrammi")}]
        self.assertEqual(aifa.product_strengths(item, ["paracetamol"]), doses.dumps([{"i": "paracetamol", "v": 500.0, "b": "unit"}]))

    def test_en_una_combinacion_el_texto_no_se_usa(self):
        item = {"form": "Compressa", "description": "200 MG + 30 MG COMPRESSE", "substances": ["IBUPROFENE", "PSEUDOEFEDRINA CLORIDRATO"],
                "amounts": []}
        self.assertEqual(aifa.product_strengths(item, ["ibuprofeno", "pseudoefedrina"]), doses.dumps([]))

    def test_publico_infantil_en_italiano(self):
        self.assertEqual(doses.audience_of("NUROFEN FEBBRE E DOLORE BAMBINI 100 MG/5 ML SOSPENSIONE ORALE"), "child")
        self.assertEqual(doses.audience_of("PRODOTTO ADULTI 500 MG"), "adult")
        self.assertIsNone(doses.audience_of("TACHIPIRINA 500 MG COMPRESSE"))

    def test_unidades_ambiguas_en_formas_que_no_son_de_unidad(self):
        self.assertEqual(doses.it_strengths([("40", "grammi")], ["magnesio hidroxido"], solid=False), [])
        self.assertEqual(doses.it_strengths([("40", "milligrammi")], ["x"], solid=False), [])
        self.assertEqual(doses.it_strengths([("1.3", "grammi")], ["x"], solid=True), [{"i": "x", "v": 1300.0, "b": "unit"}])
        self.assertEqual(doses.it_strengths([("5", "percent")], ["x"], solid=False), [{"i": "x", "v": 50.0, "b": "conc"}])
        self.assertEqual(doses.it_strengths([("", "milligrammi")], ["x"], solid=True), [])


class Formas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.form_map = importers.load_form_map(aifa.FORM_MAP_PATH)

    def target(self, form):
        return importers.map_form(form, "", self.form_map)

    def test_formas_habituales(self):
        self.assertEqual(self.target("Compressa rivestita con film"), "COMPRIMIDO")
        self.assertEqual(self.target("Compressa a rilascio prolungato"), "COMPRIMIDO LIBERACION MODIFICADA")
        self.assertEqual(self.target("Collirio, soluzione"), "COLIRIO")
        self.assertEqual(self.target("Sciroppo"), "SOLUCION/SUSPENSION ORAL")
        self.assertEqual(self.target("Crema vaginale"), "SEMISOLIDO VAGINAL")
        self.assertEqual(self.target("Crema"), "CREMA")
        self.assertEqual(self.target("Unguento"), "POMADA")
        self.assertEqual(self.target("Supposta"), "SUPOSITORIO")
        self.assertEqual(self.target("CREMA"), "CREMA")  # AIFA mezcla mayúsculas y minúsculas

    def test_lo_ambiguo_no_se_traduce(self):
        for form in ("Soluzione", "Polvere", "Gel rettale", "Colluttorio", "Soluzione per infusione", "Garza impregnata"):
            self.assertIsNone(self.target(form), form)

    def test_cada_fila_cita_como_clasifica_cima(self):
        with open(aifa.FORM_MAP_PATH, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                self.assertTrue(r["evidencia"].startswith("CIMA:"), r["forma_it"])
                self.assertEqual(r["via_it"], "", r["forma_it"])


class Enlace(unittest.TestCase):
    def test_un_producto_sin_enlace_conserva_su_nombre_y_forma_en_italiano(self):
        item = {"ref": "1", "brand_name": "X", "form": "Soluzione", "route": "", "substances": ["PIRIDOSSINA CLORIDRATO"],
                "atc": "A11HA02", "aics": [], "amounts": [], "requires_prescription": 0,
                "legal_category": "libre", "legal_note": "OTC (da banco)"}
        p = aifa.to_product(item, {}, {}, [], {})
        self.assertEqual(p["ingredient"], "piridossina cloridrato")
        self.assertEqual(p["form"], "Soluzione")
        self.assertFalse(p["form_mapped"])

    def test_con_enlace_se_llama_como_en_espana(self):
        item = {"ref": "1", "brand_name": "X", "form": "Compressa", "route": "", "substances": ["LOPERAMIDE CLORIDRATO"],
                "atc": "A07DA03", "aics": [], "amounts": [], "requires_prescription": 0,
                "legal_category": "libre", "legal_note": "OTC (da banco)"}
        links = {"loperamide": "loperamida"}
        es_index = ing.build_es_index(["loperamida"])
        p = aifa.to_product(item, links, es_index, [("compressa", "", "COMPRIMIDO")], {"comprimido": "COMPRIMIDO"})
        self.assertEqual((p["ingredient"], p["form"]), ("loperamida", "COMPRIMIDO"))


if __name__ == "__main__":
    unittest.main()
