"""
Pruebas de los DOS NIVELES de equivalencia: exacto (misma molécula, aunque cambie la sal) y base
(misma molécula base pero otro éster/profármaco: "fluticasone propionate" ~ "fluticasona").

Ejecutar con:   python -m unittest test_levels -v

La regla que protegen: un enlace de nivel base NUNCA se trata como exacto. Si pasara, la app diría
"es lo mismo" de dos moléculas que se dosifican distinto.
"""

import csv
import sqlite3
import unittest

import fetch_bdpm as bd
import fetch_dmd as dmd
import importers
import ingredients as ing


class EsterBase(unittest.TestCase):
    def test_ingles(self):
        cases = {
            "Fluticasone propionate": "fluticasone",
            "Beclometasone dipropionate": "beclometasone",
            "Candesartan cilexetil": "candesartan",
            "Olmesartan medoxomil": "olmesartan",
            "Mycophenolate mofetil": "mycophenolate",
            "Dabigatran etexilate mesilate": "dabigatran",       # éster + sal
            "Tenofovir disoproxil fumarate": "tenofovir",        # éster + sal
            "Mometasone furoate": "mometasone",
        }
        for raw, expected in cases.items():
            self.assertEqual(ing.ester_base(raw, "UK"), expected, raw)

    def test_frances(self):
        cases = {
            "PROPIONATE DE FLUTICASONE": "fluticasone",
            "BÉCLOMÉTASONE (DIPROPIONATE DE)": "béclométasone",
            "CANDÉSARTAN CILEXÉTIL": "candésartan",
            "FUMARATE DE TÉNOFOVIR DISOPROXIL": "ténofovir",
            "FUROATE DE MOMÉTASONE": "mométasone",
        }
        for raw, expected in cases.items():
            self.assertEqual(ing.ester_base(raw, "FR"), expected, raw)

    def test_lo_que_no_es_un_ester_no_se_toca(self):
        for raw in ("Paracetamol", "Escitalopram oxalate", "Benzyl benzoate", "Ibuprofen lysine", "Sodium valproate"):
            self.assertIsNone(ing.ester_base(raw, "UK"), raw)
        for raw in ("IBUPROFÈNE", "BENZOATE DE BENZYLE", "OXALATE D'ESCITALOPRAM"):
            self.assertIsNone(ing.ester_base(raw, "FR"), raw)


class UnAnionSueltoNoIdentificaNada(unittest.TestCase):
    """"acétate de sodium" y "chlorure de sodium" se quedaban en "acétate" / "chlorure": dos sustancias
    distintas con la misma clave. Un nombre reducido a un anión suelto no se interpreta."""

    def test_frances(self):
        for raw in ("ACÉTATE DE SODIUM", "CHLORURE DE SODIUM", "ACÉTATE D'HYDROCORTISONE"):
            self.assertIsNone(ing.parse_substance(raw), raw)

    def test_acetatos_que_son_sal_si_se_quitan(self):
        self.assertEqual(ing.parse_substance("ACÉTATE DE FLÉCAÏNIDE"), "flécaïnide")
        self.assertEqual(ing.parse_substance("ACÉTATE DE LYSINE"), "lysine")
        self.assertEqual(ing.parse_substance_en("Flecainide acetate"), "flecainide")
        self.assertEqual(ing.parse_substance_en("Chlorhexidine acetate"), "chlorhexidine")

    def test_un_acetato_de_ester_se_queda_entero(self):
        self.assertEqual(ing.parse_substance_en("Hydrocortisone acetate"), "hydrocortisone acetate")


class ResolverPorNiveles(unittest.TestCase):
    index = ing.build_es_index(["fluticasona", "salmeterol + fluticasona", "salmeterol", "paracetamol"])
    exact = {ing.plain("salmeterol"): "salmeterol", ing.plain("paracetamol"): "paracetamol"}
    base = {ing.plain("fluticasone propionate"): "fluticasona"}

    def resolve(self, substances):
        return ing.resolve_levels(substances, self.exact, self.base, self.index, parse=ing.parse_substance_en, country="UK")

    def test_exacto(self):
        self.assertEqual(self.resolve(["Paracetamol"]), ("paracetamol", "enlazado", "exacto"))

    def test_base(self):
        self.assertEqual(self.resolve(["Fluticasone propionate"]), ("fluticasona", "enlazado", "base"))

    def test_una_combinacion_con_un_componente_de_base_es_de_nivel_base(self):
        self.assertEqual(self.resolve(["Fluticasone propionate", "Salmeterol"]), ("salmeterol + fluticasona", "enlazado", "base"))

    def test_sin_enlace(self):
        self.assertEqual(self.resolve(["Unknown"])[0:2], (None, "sin_enlace"))

    def test_un_enlace_de_base_no_se_usa_como_exacto(self):
        # resolve() (solo exactos) NO debe enlazar fluticasone propionate aunque exista el de base.
        self.assertEqual(ing.resolve(["Fluticasone propionate"], self.exact, self.index, parse=ing.parse_substance_en)[0], None)


class TablasDeEnlaces(unittest.TestCase):
    def test_los_enlaces_de_base_no_estan_entre_los_exactos(self):
        for path in (ing.LINKS_PATH, ing.LINKS_PATH_UK):
            exact = ing.load_links(path)
            base = ing.load_links(path, level="base")
            self.assertEqual(set(exact) & set(base), set(), path)

    def test_los_de_base_en_uso_estan_confirmados_con_evidencia(self):
        for path, col in ((ing.LINKS_PATH, "nombre_fr"), (ing.LINKS_PATH_UK, "nombre_en")):
            with open(path, encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row.get("nivel") == "base" and row["estado"] in ing.USABLE_STATUSES:
                        self.assertTrue(row["evidencia"].strip(), f"{row[col]} sin evidencia")
                        self.assertIn(row["evidencia"].split(" ")[0], ("éster", "Wikidata", "aprobado", "Revisión"), row[col])

    def test_pares_que_nunca_deben_ser_de_base(self):
        # Parecidos peligrosos: nunca deben estar en uso, ni exactos ni de base.
        forbidden = {"fluticasone furoate": "fluticasona propionato", "procaine": "prilocaína", "estazolam": "ketazolam"}
        for path in (ing.LINKS_PATH, ing.LINKS_PATH_UK):
            for level in ("exacto", "base"):
                links = ing.load_links(path, level=level)
                for name, es in forbidden.items():
                    self.assertNotEqual(links.get(ing.plain(name)), es, f"{name} -> {es} ({level})")


class ProductoConNivel(unittest.TestCase):
    es_index = ing.build_es_index(["fluticasona"])
    es_forms = {"inhalacion pulmonar": "INHALACIÓN PULMONAR"}
    form_map = importers.load_form_map(dmd.FORM_MAP_PATH)

    def product(self, base_links, exact=None):
        item = {"ref": "1", "brand_name": "Flixotide", "form": "Pressurised inhalation", "route": "Inhalation",
                "substances": ["Fluticasone propionate"], "requires_prescription": 1, "legal_category": "receta", "legal_note": "POM"}
        return dmd.to_product(item, exact or {}, self.es_index, self.form_map, self.es_forms, base_links)

    def test_con_enlace_de_base_conserva_su_nombre_y_guarda_la_base(self):
        p = self.product({ing.plain("fluticasone propionate"): "fluticasona"})
        self.assertEqual((p["ingredient"], p["base_inn"], p["link_level"]), ("fluticasone propionate", "fluticasona", "base"))

    def test_con_enlace_exacto_se_llama_como_en_espana(self):
        p = self.product({}, exact={ing.plain("fluticasone propionate"): "fluticasona"})
        self.assertEqual((p["ingredient"], p["base_inn"], p["link_level"]), ("fluticasona", None, "exacto"))

    def test_sin_enlace(self):
        p = self.product({})
        self.assertEqual((p["ingredient"], p["base_inn"], p["link_level"]), ("fluticasone propionate", None, None))


class BaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        with open(importers.SCHEMA_PATH, encoding="utf-8") as fh:
            self.conn.executescript(fh.read())
        self.conn.execute("INSERT INTO countries VALUES ('UK', 'Reino Unido')")
        self.conn.commit()

    def product(self, ref, name, ingredient, base):
        return {"ref": ref, "brand_name": name, "ingredient": ingredient, "form": "INHALACIÓN PULMONAR", "composition": "x",
                "requires_prescription": 0, "legal_category": "libre", "legal_note": None, "base_inn": base}

    def test_la_vista_expone_la_base(self):
        importers.sync_products(self.conn, [self.product("1", "Flixotide", "fluticasone propionate", "fluticasona"),
                                            self.product("2", "Otro", "salbutamol", None)], "UK", "DMD")
        rows = dict(self.conn.execute("SELECT inn_name, base_inn FROM equivalences").fetchall())
        self.assertEqual(rows["fluticasone propionate"], "fluticasona")
        self.assertEqual(rows["salbutamol"], "salbutamol")  # sin base: es su propia base

    def test_si_el_enlace_cambia_la_base_se_actualiza(self):
        importers.sync_products(self.conn, [self.product("1", "Flixotide", "fluticasone propionate", "fluticasona")], "UK", "DMD")
        importers.sync_products(self.conn, [self.product("1", "Flixotide", "fluticasone propionate", None)], "UK", "DMD")
        self.assertEqual(self.conn.execute("SELECT base_inn FROM equivalences").fetchone()[0], "fluticasone propionate")

    def test_ensure_schema_anade_la_columna_a_una_base_antigua(self):
        old = sqlite3.connect(":memory:")
        old.executescript(
            "CREATE TABLE countries (code TEXT PRIMARY KEY, name TEXT);"
            "CREATE TABLE active_ingredients (id INTEGER PRIMARY KEY, inn_name TEXT UNIQUE, atc_code TEXT, category TEXT, common_use TEXT);"
            "CREATE TABLE products (id INTEGER PRIMARY KEY, active_ingredient_id INTEGER, country_code TEXT, brand_name TEXT,"
            " requires_prescription INTEGER, source TEXT, source_ref TEXT, verified_at TEXT);"
        )
        importers.ensure_schema(old)
        self.assertIn("base_inn", {r[1] for r in old.execute("PRAGMA table_info(active_ingredients)")})


if __name__ == "__main__":
    unittest.main()
