"""
Pruebas de los medicamentos CON receta: reglas de exclusión (inyectables y hospital) en España,
Francia y el Reino Unido, y la sincronización con estatus legal.

Ejecutar con:   python -m unittest test_prescription -v

Protegen dos cosas: que un medicamento con receta NUNCA se guarde como libre, y que las
exclusiones (decisión de María: sin inyectables ni productos de hospital) sean iguales en
los tres países, para que las comparaciones sean justas.
"""

import os
import sqlite3
import unittest

import fetch_bdpm as bd
import fetch_cima as cima
import fetch_dmd as dmd
import importers


class CimaExclusiones(unittest.TestCase):
    def med(self, cpresc="Medicamento Sujeto A Prescripción Médica", form="COMPRIMIDO", simple="COMPRIMIDO", vias=("VÍA ORAL",)):
        return {
            "cpresc": cpresc,
            "formaFarmaceutica": {"nombre": form},
            "formaFarmaceuticaSimplificada": {"nombre": simple},
            "viasAdministracion": [{"nombre": v} for v in vias],
        }

    def test_un_comprimido_con_receta_entra(self):
        self.assertIsNone(cima.exclusion_reason(self.med()))

    def test_uso_hospitalario_se_excluye(self):
        for c in ("Uso Hospitalario", "Uso Hospitalario. Estupefacientes", "Uso Hospitalario Y Centros De Diagnóstico Autorizados"):
            self.assertEqual(cima.exclusion_reason(self.med(cpresc=c)), "hospital", c)

    def test_diagnostico_hospitalario_NO_se_excluye(self):
        # Lo receta un especialista, pero el paciente lo compra en la farmacia.
        for c in ("Diagnóstico Hospitalario", "Diagnóstico Hospitalario. Psicótropos"):
            self.assertIsNone(cima.exclusion_reason(self.med(cpresc=c)), c)

    def test_inyectables_se_excluyen_por_forma_o_por_via(self):
        self.assertEqual(cima.exclusion_reason(self.med(form="SOLUCIÓN INYECTABLE", simple="INYECTABLE", vias=("VÍA ORAL",))), "inyectable")
        self.assertEqual(cima.exclusion_reason(self.med(form="CONCENTRADO PARA SOLUCIÓN PARA PERFUSIÓN")), "inyectable")
        self.assertEqual(cima.exclusion_reason(self.med(vias=("VÍA SUBCUTÁNEA",))), "inyectable")
        self.assertEqual(cima.exclusion_reason(self.med(vias=("VÍA INTRAVENOSA",))), "inyectable")

    def test_producto_cima_con_receta_se_guarda_como_receta(self):
        p = cima.to_product({"nregistro": "1", "nombre": "X", "vtm": {"nombre": "ibuprofeno"}, "receta": True,
                             "cpresc": "Medicamento Sujeto A Prescripción Médica", "dosis": "600 mg"})
        self.assertEqual((p["requires_prescription"], p["legal_category"]), (1, "receta"))
        libre = cima.to_product({"nregistro": "2", "nombre": "Y", "vtm": {"nombre": "ibuprofeno"}, "receta": False})
        self.assertEqual((libre["requires_prescription"], libre["legal_category"]), (0, "libre"))


class BdpmExclusiones(unittest.TestCase):
    def test_un_comprimido_con_liste_I_entra(self):
        self.assertIsNone(bd.exclusion_reason("comprimé pelliculé", "orale", ["liste I"]))

    def test_prescription_hospitaliere_NO_se_excluye(self):
        # Se dispensa en farmacia (como "diagnóstico hospitalario" en España).
        for c in ("prescription hospitalière", "prescription initiale hospitalière annuelle",
                  "prescription réservée aux spécialistes et services ONCOLOGIE MEDICALE"):
            self.assertIsNone(bd.exclusion_reason("comprimé", "orale", [c]), c)

    def test_uso_hospitalario_y_similares_se_excluyen(self):
        for c in ("réservé à l'usage HOSPITALIER", "délivrance réservée aux pharmacies à usage intérieur",
                  "réservé à l'usage professionnel", "réservé à l'usage en situation d'urgence selon l'article R5121-96"):
            self.assertEqual(bd.exclusion_reason("comprimé", "orale", ["liste I", c]), "hospital", c)

    def test_inyectables_y_dialisis_se_excluyen(self):
        self.assertEqual(bd.exclusion_reason("solution injectable", "orale", ["liste I"]), "inyectable")
        self.assertEqual(bd.exclusion_reason("comprimé", "intraveineuse", ["liste I"]), "inyectable")
        self.assertEqual(bd.exclusion_reason("poudre", "orale;sous-cutanée", ["liste I"]), "inyectable")
        self.assertEqual(bd.exclusion_reason("solution", "hémodialyse", ["liste I"]), "inyectable")

    def test_producto_frances_con_receta_se_guarda_como_receta(self):
        item = {"cis": "1", "brand_name": "X", "form": "comprimé", "route": "orale", "substances": ["IBUPROFÈNE"],
                "requires_prescription": 1, "legal_note": "liste I"}
        p = bd.to_product(item, {}, {}, bd.load_form_map(), {})
        self.assertEqual((p["requires_prescription"], p["legal_category"], p["legal_note"]), (1, "receta", "liste I"))


class DmdEstatus(unittest.TestCase):
    def test_estatus_legal(self):
        self.assertEqual(dmd.legal_status({"GSL"}), (0, "libre", "GSL"))
        self.assertEqual(dmd.legal_status({"P"}), (0, "solo_farmacia", "P"))
        self.assertEqual(dmd.legal_status({"GSL", "P"}), (0, "solo_farmacia", "GSL + P"))
        self.assertEqual(dmd.legal_status({"POM"}), (1, "receta", "POM"))
        # Envases P y POM: sigue siendo sin receta (hay un envase P) pero se dice.
        self.assertEqual(dmd.legal_status({"P", "POM"}), (0, "solo_farmacia", "P + POM"))

    def test_parenterales(self):
        self.assertTrue(dmd.is_parenteral("Solution for injection", ["Intravenous"]))
        self.assertTrue(dmd.is_parenteral("Powder for solution for infusion", ["Intravenous"]))
        self.assertTrue(dmd.is_parenteral("Prolonged-release subcutaneous implant", ["Subcutaneous"]))
        self.assertFalse(dmd.is_parenteral("Oral tablet", ["Oral"]))
        # "Concentrate for oral solution" es oral: la palabra "concentrate" no basta.
        self.assertFalse(dmd.is_parenteral("Concentrate for oral solution", ["Oral"]))


class SyncConEstatus(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        with open(importers.SCHEMA_PATH, encoding="utf-8") as fh:
            self.conn.executescript(fh.read())
        self.conn.execute("INSERT INTO countries VALUES ('FR', 'Francia')")
        self.conn.execute("INSERT INTO active_ingredients (inn_name, category) VALUES ('dimenhidrinato', 'Salud')")
        # Ejemplo manual de venta libre
        self.conn.execute(
            "INSERT INTO products (active_ingredient_id, country_code, brand_name, requires_prescription, source, form) "
            "VALUES (1, 'FR', 'Ejemplo manual', 0, 'manual_seed', 'COMPRIMIDO')"
        )
        self.conn.commit()

    def product(self, ref, name, rx, form="COMPRIMIDO"):
        return {"ref": ref, "brand_name": name, "ingredient": "dimenhidrinato", "form": form, "composition": "x",
                "requires_prescription": rx, "legal_category": "receta" if rx else "libre", "legal_note": "liste I" if rx else None}

    def rows(self):
        return self.conn.execute("SELECT brand_name, requires_prescription, legal_category, legal_note FROM products ORDER BY brand_name").fetchall()

    def test_guarda_el_estatus_legal(self):
        importers.sync_products(self.conn, [self.product("1", "Con receta", 1)], "FR", "BDPM")
        row = next(r for r in self.rows() if r[0] == "Con receta")
        self.assertEqual(row[1:], (1, "receta", "liste I"))

    def test_un_producto_con_receta_NO_sustituye_a_un_ejemplo_manual_libre(self):
        importers.sync_products(self.conn, [self.product("1", "Con receta", 1)], "FR", "BDPM")
        self.assertIn("Ejemplo manual", [r[0] for r in self.rows()])

    def test_un_producto_libre_de_la_misma_forma_si_lo_sustituye(self):
        importers.sync_products(self.conn, [self.product("1", "Libre real", 0)], "FR", "BDPM")
        self.assertNotIn("Ejemplo manual", [r[0] for r in self.rows()])

    def test_ensure_schema_rellena_el_estatus_de_filas_antiguas(self):
        self.conn.execute("UPDATE products SET legal_category = NULL")
        importers.ensure_schema(self.conn)
        self.assertEqual(self.rows()[0][2], "libre")


class Interruptor(unittest.TestCase):
    """El interruptor INCLUDE_PRESCRIPTION del backend no debe dejar pasar ninguna receta."""

    def test_con_el_interruptor_apagado_no_sale_ninguna_receta(self):
        import importlib
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
        old = os.environ.get("INCLUDE_PRESCRIPTION")
        os.environ["INCLUDE_PRESCRIPTION"] = "0"
        try:
            app_module = importlib.import_module("app")
            importlib.reload(app_module)
            client = app_module.app.test_client()
            self.assertFalse(client.get("/api/config").get_json()["include_prescription"])
            rows = client.get("/api/equivalences").get_json()
            self.assertTrue(rows)
            self.assertEqual([r for r in rows if r["requires_prescription"]], [])
        finally:
            if old is None:
                os.environ.pop("INCLUDE_PRESCRIPTION", None)
            else:
                os.environ["INCLUDE_PRESCRIPTION"] = old
            importlib.reload(importlib.import_module("app"))


if __name__ == "__main__":
    unittest.main()
