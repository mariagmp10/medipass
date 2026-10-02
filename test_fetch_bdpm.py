"""
Pruebas del importador de Francia (fetch_bdpm.py): traducción de formas y enlace
de principios activos.

Ejecutar con:   python -m unittest test_fetch_bdpm -v
"""

import os
import sqlite3
import unittest

import fetch_bdpm as bd
import ingredients as ing


class MapForm(unittest.TestCase):
    form_map = bd.load_form_map()

    def test_traduce_cuando_la_forma_y_la_via_coinciden(self):
        cases = [
            ("comprimé pelliculé", "orale", "COMPRIMIDO"),
            ("comprimé gastro-résistant(e)", "orale", "COMPRIMIDO"),
            ("comprimé effervescent(e)", "orale", "COMPRIMIDO EFERVESCENTE"),
            ("gélule", "orale", "CAPSULA"),
            ("sirop", "orale", "SOLUCION/SUSPENSION ORAL"),
            ("solution buvable en gouttes", "orale", "SOLUCION/SUSPENSION GOTAS ORALES"),
            ("crème", "cutanée", "CREMA"),
            ("gel", "cutanée", "GEL"),
            ("solution pour application", "cutanée", "LIQUIDO USO TOPICO"),
            ("solution pour pulvérisation", "cutanée", "LIQUIDO USO TOPICO"),
            ("solution pour pulvérisation", "voie buccale autre", "PULVERIZACION BUCAL"),
            ("solution pour pulvérisation", "nasale", "PRODUCTO USO NASAL"),
            ("dispositif", "transdermique", "PARCHE TRANSDERMICO"),
            ("emplâtre médicamenteux(se)", "cutanée", "APOSITO"),
            ("collyre en solution", "ophtalmique", "COLIRIO"),
        ]
        for form, route, expected in cases:
            self.assertEqual(bd.map_form(form, route, self.form_map), expected, f"{form} / {route}")

    def test_no_traduce_si_la_via_no_es_la_esperada(self):
        for form, route in [
            ("gel", "orale"),                        # un gel oral no es un gel cutáneo
            ("gel", "rectale"),
            ("comprimé", "sublinguale"),             # otra vía = otra forma
            ("comprimé", "vaginale"),
            ("solution pour application", "voie buccale autre"),
        ]:
            self.assertIsNone(bd.map_form(form, route, self.form_map), f"{form} / {route}")

    def test_no_traduce_lo_ambiguo_o_sin_equivalente(self):
        for form, route in [
            ("solution pour bain de bouche", "voie buccale autre"),   # colutorio: CIMA no lo tiene
            ("comprimé à sucer ou à croquer", "orale"),               # ¿para chupar o masticable?
            ("comprimé dispersible et orodispersible", "orale"),
            ("solution injectable", "intraveineuse"),
        ]:
            self.assertIsNone(bd.map_form(form, route, self.form_map), f"{form} / {route}")


class FormMapFile(unittest.TestCase):
    form_map = bd.load_form_map()

    def test_las_palabras_van_sin_tildes_ni_mayusculas(self):
        # Se comparan con ing.plain(): si llevaran tildes, la fila no coincidiría nunca.
        for forma_fr, via, _cima in self.form_map:
            self.assertEqual(ing.plain(forma_fr), forma_fr)
            self.assertEqual(ing.plain(via), via)

    def test_no_hay_filas_repetidas(self):
        keys = [(f, v) for f, v, _ in self.form_map]
        self.assertEqual(len(keys), len(set(keys)))

    def test_todas_las_formas_de_destino_existen_en_espana(self):
        if not os.path.exists(bd.DB_PATH):
            self.skipTest("no hay base de datos")
        conn = sqlite3.connect(bd.DB_PATH)
        _names, es_forms = bd.load_spanish_vocabulary(conn)
        conn.close()
        if not es_forms:
            self.skipTest("la base no tiene productos de España")
        missing = {t for _f, _v, t in self.form_map if ing.plain(t) not in es_forms}
        self.assertEqual(missing, set(), "formas de destino que no existen en España (¿errata?)")


class ToProduct(unittest.TestCase):
    links = {ing.plain("ibuprofène"): "ibuprofeno", ing.plain("caféine"): "cafeína", ing.plain("paracétamol"): "paracetamol"}
    es_index = ing.build_es_index(["ibuprofeno", "paracetamol + cafeína"])
    es_forms = {"comprimido": "COMPRIMIDO", "solucion/suspension oral": "SOLUCIÓN/SUSPENSIÓN ORAL"}
    form_map = bd.load_form_map()

    def product(self, substances, form, route="orale"):
        item = {"cis": "1", "brand_name": "X", "form": form, "route": route, "substances": substances}
        return bd.to_product(item, self.links, self.es_index, self.form_map, self.es_forms)

    def test_enlaza_el_principio_activo_y_traduce_la_forma(self):
        p = self.product(["IBUPROFÈNE (LYSINATE D')"], "comprimé pelliculé")
        self.assertEqual((p["ingredient"], p["form"], p["link_reason"]), ("ibuprofeno", "COMPRIMIDO", "enlazado"))

    def test_la_forma_de_destino_usa_la_ortografia_exacta_de_espana(self):
        p = self.product(["IBUPROFÈNE"], "suspension buvable")
        self.assertEqual(p["form"], "SOLUCIÓN/SUSPENSIÓN ORAL")

    def test_las_combinaciones_se_enlazan_aunque_cambie_el_orden(self):
        p = self.product(["CAFÉINE", "PARACÉTAMOL"], "comprimé")
        self.assertEqual(p["ingredient"], "paracetamol + cafeína")

    def test_sin_enlace_ni_forma_conserva_todo_en_frances(self):
        p = self.product(["OXOMÉMAZINE"], "solution pour bain de bouche", "voie buccale autre")
        self.assertEqual(p["ingredient"], "oxomémazine")
        self.assertEqual(p["form"], "solution pour bain de bouche")
        self.assertFalse(p["form_mapped"])
        self.assertEqual(p["link_reason"], "sin_enlace")


if __name__ == "__main__":
    unittest.main()
