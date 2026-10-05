"""
Pruebas del importador del Reino Unido (fetch_dmd.py): qué cuenta como "sin receta",
traducción de formas y enlace de principios activos.

Ejecutar con:   python -m unittest test_fetch_dmd -v
"""

import os
import sqlite3
import tempfile
import unittest
import zipfile

import fetch_dmd as dmd
import importers
import ingredients as ing


def _lookup(group, entries):
    infos = "".join(f"<INFO><CD>{cd}</CD><DESC>{desc}</DESC></INFO>" for cd, desc in entries.items())
    return f"<{group}>{infos}</{group}>"


def _record(tag, **fields):
    return f"<{tag}>" + "".join(f"<{k}>{v}</{k}>" for k, v in fields.items()) + f"</{tag}>"


def build_zip(path):
    """dm+d en miniatura. Productos (APID): 1 Nurofen (GSL+P, ibuprofeno), 2 solo POM, 3 P descatalogado,
    4 homeopático GSL, 5 P sin licencia, 6 P con envases P y POM, 7 P importado, 8 P inválido."""
    lookup = (
        "<LOOKUP>"
        + _lookup("LEGAL_CATEGORY", {"0001": "GSL", "0002": "P", "0003": "POM", "0004": "Not Applicable"})
        + _lookup("LICENSING_AUTHORITY", {"0001": "Medicines - MHRA/EMA", "0002": "None"})
        + _lookup("AVAILABILITY_RESTRICTION", {"0000": "None", "0001": "Imported"})
        + _lookup("FORM", {"1": "Oral tablet", "2": "Homeopathic tablet"})
        + _lookup("ROUTE", {"1": "Oral"})
        + "</LOOKUP>"
    )
    ampp = [  # APPID, APID, LEGAL_CATCD, DISCCD
        (1, 1, "0001", None), (2, 1, "0002", None), (3, 2, "0003", None), (4, 3, "0002", "0001"),
        (5, 4, "0001", None), (6, 5, "0002", None), (7, 6, "0002", None), (8, 6, "0003", None),
        (9, 7, "0002", None), (10, 8, "0002", None),
    ]
    ampp_xml = "<ACTUAL_MEDICINAL_PROD_PACKS><AMPPS>" + "".join(
        _record("AMPP", APPID=a, VPPID=a, APID=apid, NM="pack", LEGAL_CATCD=cat, **({"DISCCD": d} if d else {}))
        for a, apid, cat, d in ampp
    ) + "</AMPPS></ACTUAL_MEDICINAL_PROD_PACKS>"
    amp_rows = [  # APID, VPID, licencia, disponibilidad, invalid
        (1, 1, "0001", "0000", 0), (2, 1, "0001", "0000", 0), (3, 1, "0001", "0000", 0),
        (4, 2, "0001", "0000", 0), (5, 1, "0002", "0000", 0), (6, 1, "0001", "0000", 0),
        (7, 1, "0001", "0001", 0), (8, 1, "0001", "0000", 1),
    ]
    names = {1: "Nurofen 200mg tablets", 2: "Pharmacy only POM", 3: "Discontinued", 4: "Homeopathic remedy",
             5: "Unlicensed", 6: "Mixed pack", 7: "Imported", 8: "Invalid"}
    amp_xml = "<ACTUAL_MEDICINAL_PRODUCTS><AMPS>" + "".join(
        _record("AMP", APID=a, VPID=v, NM=names[a], DESC=names[a], LIC_AUTHCD=lic, AVAIL_RESTRICTCD=av, **({"INVALID": 1} if inv else {}))
        for a, v, lic, av, inv in amp_rows
    ) + "</AMPS></ACTUAL_MEDICINAL_PRODUCTS>"
    vmp_xml = (
        "<VIRTUAL_MED_PRODUCTS><VMPS>" + _record("VMP", VPID=1, NM="Ibuprofen 200mg tablets") + _record("VMP", VPID=2, NM="Hom") + "</VMPS>"
        "<VIRTUAL_PRODUCT_INGREDIENT>" + _record("VPI", VPID=1, ISID=10) + _record("VPI", VPID=2, ISID=11) + "</VIRTUAL_PRODUCT_INGREDIENT>"
        "<DRUG_FORM>" + _record("DFORM", VPID=1, FORMCD=1) + _record("DFORM", VPID=2, FORMCD=2) + "</DRUG_FORM>"
        "<DRUG_ROUTE>" + _record("DROUTE", VPID=1, ROUTECD=1) + _record("DROUTE", VPID=2, ROUTECD=1) + "</DRUG_ROUTE>"
        "</VIRTUAL_MED_PRODUCTS>"
    )
    ing_xml = "<INGREDIENT_SUBSTANCES>" + _record("ING", ISID=10, NM="Ibuprofen") + _record("ING", ISID=11, NM="Arnica") + "</INGREDIENT_SUBSTANCES>"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("f_lookup2_3240926.xml", lookup)
        zf.writestr("f_ampp2_3240926.xml", ampp_xml)
        zf.writestr("f_amp2_3240926.xml", amp_xml)
        zf.writestr("f_vmp2_3240926.xml", vmp_xml)
        zf.writestr("f_ingredient2_3240926.xml", ing_xml)


class SinReceta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "nhsbsa_dmd_9.9.9_20260101000001.zip")
        build_zip(cls.path)
        cls.catalog, cls.excluded = dmd.load_catalog(cls.path)
        cls.by_ref = {p["ref"]: p for p in cls.catalog}

    def test_entran_los_productos_con_algun_envase_p_o_gsl(self):
        self.assertIn("1", self.by_ref)   # Nurofen: GSL y P
        self.assertIn("6", self.by_ref)   # envases P y POM: se incluye (hay un envase P)
        self.assertTrue(self.by_ref["6"]["mixed_legal"])
        self.assertFalse(self.by_ref["1"]["mixed_legal"])

    def test_no_entran_los_que_solo_tienen_receta(self):
        self.assertNotIn("2", self.by_ref)

    def test_no_entran_descatalogados_sin_licencia_importados_ni_invalidos(self):
        for ref in ("3", "5", "7", "8"):
            self.assertNotIn(ref, self.by_ref, ref)

    def test_no_entran_los_homeopaticos(self):
        self.assertNotIn("4", self.by_ref)
        self.assertEqual(self.excluded["homeopático"], 1)

    def test_forma_via_e_ingredientes(self):
        p = self.by_ref["1"]
        self.assertEqual((p["form"], p["route"], p["substances"]), ("Oral tablet", "Oral", ["Ibuprofen"]))

    def test_version_y_fecha_salen_del_nombre_del_archivo(self):
        self.assertEqual(dmd.release_info(self.path), ("9.9.9", "2026-01-01"))


class MapFormUK(unittest.TestCase):
    form_map = importers.load_form_map(dmd.FORM_MAP_PATH)

    def m(self, form, route):
        return importers.map_form(form, route, self.form_map, exact_route=True)

    def test_traduce_cuando_forma_y_via_coinciden(self):
        cases = [
            ("Oral tablet", "Oral", "COMPRIMIDO"),
            ("Cutaneous cream", "Cutaneous", "CREMA"),
            ("Spray", "Nasal", "PRODUCTO USO NASAL"),
            ("Spray", "Oromucosal", "PULVERIZACION BUCAL"),
            ("Spray", "Cutaneous", "LIQUIDO USO TOPICO"),
            ("Lozenge", "Oromucosal", "COMPRIMIDO BUCAL/PARA CHUPAR"),
            ("Transdermal patch", "Transdermal", "PARCHE TRANSDERMICO"),
            ("Rectal ointment", "Cutaneous; Rectal", "SEMISOLIDO RECTAL"),
            ("Pessary", "Vaginal", "OVULO/CAPSULA/COMPRIMIDO VAGINAL"),
        ]
        for form, route, expected in cases:
            self.assertEqual(self.m(form, route), expected, f"{form} / {route}")

    def test_no_traduce_si_la_via_no_coincide(self):
        for form, route in [
            ("Cutaneous gel", "Ocular"),
            ("Oral tablet", "Sublingual"),
            ("Spray", "Auricular"),
        ]:
            self.assertIsNone(self.m(form, route), f"{form} / {route}")

    def test_un_producto_de_varias_vias_no_se_clasifica_por_una_sola(self):
        # Con la regla "la vía está contenida" este spray acabaría como pulverización bucal.
        multi = "Oromucosal; Gingival; Nasal; Cutaneous; Endosinusial; Endotracheopulmonary"
        self.assertIsNone(self.m("Spray", multi))
        self.assertIsNone(self.m("Gel", "Oromucosal; Rectal; Cutaneous; Urethral"))

    def test_no_traduce_lo_ambiguo_o_sin_equivalente(self):
        for form, route in [
            ("Mouthwash", "Oromucosal"),
            ("Eye ointment", "Ocular"),
            ("Inhalation gas", "Inhalation"),
            ("Sublingual tablet", "Sublingual"),
            ("Buccal tablet", "Buccal"),
        ]:
            self.assertIsNone(self.m(form, route), f"{form} / {route}")


class FormMapFile(unittest.TestCase):
    form_map = importers.load_form_map(dmd.FORM_MAP_PATH)

    def test_las_palabras_van_sin_tildes_ni_mayusculas(self):
        for forma, via, _cima in self.form_map:
            self.assertEqual(ing.plain(forma), forma)
            self.assertEqual(ing.plain(via), via)

    def test_no_hay_filas_repetidas(self):
        keys = [(f, v) for f, v, _ in self.form_map]
        self.assertEqual(len(keys), len(set(keys)))

    def test_todas_las_formas_de_destino_existen_en_espana(self):
        if not os.path.exists(dmd.DB_PATH):
            self.skipTest("no hay base de datos")
        conn = sqlite3.connect(dmd.DB_PATH)
        _names, es_forms = importers.load_spanish_vocabulary(conn)
        conn.close()
        if not es_forms:
            self.skipTest("la base no tiene productos de España")
        missing = {t for _f, _v, t in self.form_map if ing.plain(t) not in es_forms}
        self.assertEqual(missing, set(), "formas de destino que no existen en España (¿errata?)")


class ToProduct(unittest.TestCase):
    links = {"ibuprofen": "ibuprofeno", "caffeine": "cafeína", "paracetamol": "paracetamol", "hyoscine": "escopolamina"}
    es_index = ing.build_es_index(["ibuprofeno", "paracetamol + cafeína", "escopolamina"])
    es_forms = {"comprimido": "COMPRIMIDO", "solucion/suspension oral": "SOLUCIÓN/SUSPENSIÓN ORAL"}
    form_map = importers.load_form_map(dmd.FORM_MAP_PATH)

    def product(self, substances, form="Oral tablet", route="Oral"):
        item = {"ref": "1", "brand_name": "X", "form": form, "route": route, "substances": substances}
        return dmd.to_product(item, self.links, self.es_index, self.form_map, self.es_forms)

    def test_enlaza_el_principio_activo_y_traduce_la_forma(self):
        p = self.product(["Ibuprofen sodium dihydrate"])
        self.assertEqual((p["ingredient"], p["form"], p["link_reason"]), ("ibuprofeno", "COMPRIMIDO", "enlazado"))

    def test_la_forma_de_destino_usa_la_ortografia_exacta_de_espana(self):
        self.assertEqual(self.product(["Ibuprofen"], "Oral suspension")["form"], "SOLUCIÓN/SUSPENSIÓN ORAL")

    def test_las_combinaciones_se_enlazan_aunque_cambie_el_orden(self):
        self.assertEqual(self.product(["Caffeine", "Paracetamol"])["ingredient"], "paracetamol + cafeína")

    def test_hyoscine_butylbromide_no_se_enlaza_con_escopolamina(self):
        p = self.product(["Hyoscine butylbromide"])
        self.assertEqual((p["ingredient"], p["link_reason"]), ("hyoscine butylbromide", "sin_enlace"))

    def test_sin_enlace_ni_forma_conserva_todo_en_ingles(self):
        p = self.product(["Cetrimide"], "Mouthwash", "Oromucosal")
        self.assertEqual((p["ingredient"], p["form"], p["form_mapped"]), ("cetrimide", "Mouthwash", False))


if __name__ == "__main__":
    unittest.main()
