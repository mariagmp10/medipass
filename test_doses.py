"""
Pruebas de la normalización de dosis y del público (doses.py).

Ejecutar con:   python -m unittest test_doses -v

Regla que protegen: lo que no se sabe interpretar se deja FUERA (lista vacía), no se inventa un número.
"""

import unittest

import doses


def v(strengths):
    return [(s["i"], round(s["v"], 4), s["b"]) for s in strengths]


class España(unittest.TestCase):
    def test_cantidad_por_unidad(self):
        self.assertEqual(v(doses.es_strengths("400 mg", "ibuprofeno")), [("ibuprofeno", 400.0, "unit")])
        self.assertEqual(v(doses.es_strengths("1,5 g", "almagato")), [("almagato", 1500.0, "unit")])
        self.assertEqual(v(doses.es_strengths("50 microgramos", "fentanilo")), [("fentanilo", 0.05, "unit")])
        self.assertEqual(v(doses.es_strengths("400 MG", "ibuprofeno")), [("ibuprofeno", 400.0, "unit")])

    def test_concentracion(self):
        self.assertEqual(v(doses.es_strengths("40 mg/ml", "ibuprofeno")), [("ibuprofeno", 40.0, "conc")])
        self.assertEqual(v(doses.es_strengths("100 mg ibuprofeno/5 ml", "ibuprofeno")), [("ibuprofeno", 20.0, "conc")])
        self.assertEqual(v(doses.es_strengths("10 mg/g", "hidrocortisona")), [("hidrocortisona", 10.0, "conc")])
        self.assertEqual(v(doses.es_strengths("2%", "ketoconazol")), [("ketoconazol", 20.0, "conc")])

    def test_combinaciones(self):
        self.assertEqual(
            v(doses.es_strengths("175/12.5 mg/mg", "a + b")), [("a", 175.0, "unit"), ("b", 12.5, "unit")]
        )
        self.assertEqual(
            v(doses.es_strengths("400 mg/10 mg", "a + b")), [("a", 400.0, "unit"), ("b", 10.0, "unit")]
        )
        self.assertEqual(
            v(doses.es_strengths("20 mg/ml + 5 mg/ml", "a + b")), [("a", 20.0, "conc"), ("b", 5.0, "conc")]
        )

    def test_lo_que_no_se_sabe_interpretar_queda_fuera(self):
        for dose, name in [
            ("25 mg/24 h", "fentanilo"),          # parche: mg por hora
            ("-", "algo"),
            ("", "algo"),
            ("400 mg/10 mg", "solo"),              # dos cantidades para un solo principio activo
            ("175/12.5 mg/mg", "a + b + c"),       # no coincide el número de componentes
        ]:
            self.assertEqual(doses.es_strengths(dose, name), [], (dose, name))

    def test_la_sal_no_se_corrige(self):
        # 684 mg de ibuprofeno arginina son ~400 mg de ibuprofeno: aquí NO se convierte (limitación documentada).
        self.assertEqual(v(doses.es_strengths("684 mg", "ibuprofeno")), [("ibuprofeno", 684.0, "unit")])


class Francia(unittest.TestCase):
    def test_unidad_y_concentracion(self):
        self.assertEqual(v(doses.fr_strengths([("IBUPROFÈNE", "400 mg", "un comprimé")], ["ibuprofeno"])), [("ibuprofeno", 400.0, "unit")])
        self.assertEqual(v(doses.fr_strengths([("IBUPROFÈNE", "100 mg", "5 ml")], ["ibuprofeno"])), [("ibuprofeno", 20.0, "conc")])
        self.assertEqual(v(doses.fr_strengths([("X", "2,5 mg", "1 mL de solution")], ["x"])), [("x", 2.5, "conc")])
        self.assertEqual(v(doses.fr_strengths([("X", "200 microgrammes", "une gélule")], ["x"])), [("x", 0.2, "unit")])
        self.assertEqual(v(doses.fr_strengths([("X", "1 g", "100 g")], ["x"])), [("x", 10.0, "conc")])

    def test_combinacion_en_orden(self):
        out = doses.fr_strengths([("A", "500 mg", "un comprimé"), ("B", "65 mg", "un comprimé")], ["paracetamol", "cafeina"])
        self.assertEqual(v(out), [("paracetamol", 500.0, "unit"), ("cafeina", 65.0, "unit")])

    def test_lo_que_no_se_sabe_interpretar_queda_fuera(self):
        for compo in (
            [("X", "2 500 UI", "un comprimé")],        # unidades internacionales: no son masa
            [("X", "5 mg", "un flacon")],              # volumen del frasco desconocido
            [("X", "5 mg", "")],                       # sin referencia
            [("X", "2CH à 30CH", "un comprimé")],      # homeopatía
        ):
            self.assertEqual(doses.fr_strengths(compo, ["x"]), [], compo)


class ReinoUnido(unittest.TestCase):
    def test_unidad_y_concentracion(self):
        self.assertEqual(v(doses.uk_strengths([("400", "mg", None, None)], ["ibuprofen"])), [("ibuprofen", 400.0, "unit")])
        self.assertEqual(v(doses.uk_strengths([("100", "mg", "5", "ml")], ["ibuprofen"])), [("ibuprofen", 20.0, "conc")])
        self.assertEqual(v(doses.uk_strengths([("20", "gram", "1", "litre")], ["x"])), [("x", 20.0, "conc")])
        self.assertEqual(v(doses.uk_strengths([("200", "microgram", "1", "dose")], ["x"])), [("x", 0.2, "unit")])
        self.assertEqual(v(doses.uk_strengths([("5", "mg", "1", "gram")], ["x"])), [("x", 5.0, "conc")])

    def test_lo_que_no_es_masa_queda_fuera(self):
        self.assertEqual(doses.uk_strengths([("500", "unit", None, None)], ["x"]), [])
        self.assertEqual(doses.uk_strengths([("5", "mg", "1", "unknown")], ["x"]), [])


class Comparable(unittest.TestCase):
    def test_la_misma_dosis_sale_igual_en_los_tres_paises(self):
        es = doses.es_strengths("100 mg ibuprofeno/5 ml", "ibuprofeno")
        fr = doses.fr_strengths([("IBUPROFÈNE", "100 mg", "5 ml")], ["ibuprofeno"])
        uk = doses.uk_strengths([("100", "mg", "5", "ml")], ["ibuprofeno"])
        self.assertEqual(v(es), v(fr))
        self.assertEqual(v(es), v(uk))


class Público(unittest.TestCase):
    def test_niños(self):
        for name in (
            "Bell's Children's Pain & Fever Relief 100mg/5ml oral suspension",
            "Calpol Infant Suspension",
            "FRENADOL JUNIOR",
            "NUROFEN ENFANTS 20 mg/ml",
            "DOLIPRANE NOURRISSONS",
            "Boots Ibuprofen 3 Months Plus 100mg/5ml oral suspension",
            "Ibuprofen 6 Years Plus tablets",
            "IBUPROFENO PEDIÁTRICO",
        ):
            self.assertEqual(doses.audience_of(name), "child", name)

    def test_adultos(self):
        self.assertEqual(doses.audience_of("Senokot 7.5mg tablets 12 Years Plus"), "adult")
        self.assertEqual(doses.audience_of("Gelocatil Adultos"), "adult")

    def test_sin_pista_es_none(self):
        for name in ("ESPIDIDOL 400 mg GRANULADO PARA SOLUCION ORAL SABOR MENTA", "Nurofen 200mg tablets", "ADVIL 200 mg, comprimé enrobé", ""):
            self.assertIsNone(doses.audience_of(name), name)


if __name__ == "__main__":
    unittest.main()
