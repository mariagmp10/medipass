"""
doses.py
Normaliza la DOSIS de los tres países a una misma forma y detecta el PÚBLICO (adulto o niño).

Cada fuente expresa la dosis de forma distinta:
  España   texto libre de CIMA ("400 mg", "100 mg/5 ml", "40 mg/ml", "175/12.5 mg/mg", "2%"...)
  Francia  composición: cantidad + referencia ("400 mg" por "un comprimé", "5 mg" por "1 mL de solución")
  Reino U. concentración estructurada del dm+d (numerador y denominador con unidad)

La forma común es una lista, una entrada por principio activo:
    {"i": "ibuprofeno", "v": 400.0, "b": "unit"}   400 mg por unidad (comprimido, sobre, cápsula, dosis...)
    {"i": "ibuprofeno", "v": 20.0,  "b": "conc"}   20 mg por ml (o por g en semisólidos)
v siempre va en MILIGRAMOS. Lo que no se sabe interpretar con seguridad se deja fuera (lista vacía):
es mejor decir "dosis no comparable" que inventarse un número.

Limitación importante: la cantidad puede referirse a la SAL y no a la base (ibuprofeno arginina 684 mg
equivale a ibuprofeno 400 mg). Eso no se corrige aquí: la app solo compara dosis del MISMO tipo y avisa
de que la dosis puede variar.

El público (`audience`) es una HEURÍSTICA por palabras del nombre comercial: "child" o "adult", o None
si el nombre no dice nada (que es lo habitual en un producto general).
"""

import json
import re

import ingredients as ing

NUM = r"\d+(?:[.,]\d+)?"
MASS_TO_MG = {
    "mg": 1.0, "g": 1000.0, "gram": 1000.0, "kg": 1e6, "ug": 0.001, "mcg": 0.001, "µg": 0.001, "microgram": 0.001,
    "micrograms": 0.001, "microgramo": 0.001, "microgramos": 0.001, "microgramme": 0.001, "microgrammes": 0.001,
    "nanogram": 1e-6, "ng": 1e-6,
}
UNIT_WORDS = {"tablet", "capsule", "dose", "patch", "sachet", "suppository", "pessary", "ampoule", "lozenge",
              "pastille", "actuation", "comprime", "gelule", "sachet", "suppositoire", "ovule", "dose"}


def _num(token):
    """'1,5' -> 1.5, '1.000' -> 1000 (separador de miles), '12.5' -> 12.5."""
    token = token.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        return float(token.replace(".", ""))
    return float(token.replace(",", "."))


def _json(strengths):
    return json.dumps(strengths, ensure_ascii=False, separators=(",", ":")) if strengths else None


# ------------------------------------------------------------------------------------ España
def _norm(text):
    """Minúsculas sin tildes y con todas las variantes de microgramo como 'ug' (µ latina, μ griega, mcg)."""
    s = (text or "").replace("µ", "u").replace("μ", "u")
    s = ing.plain(s)
    return re.sub(r"\b(?:microgramos?|mcg)\b", "ug", s)


def _es_single(text, name):
    s = _norm(text)
    m = re.match(rf"^({NUM})\s*%", s)
    if m:  # 2 % -> 20 mg por ml o g
        return {"i": name, "v": _num(m.group(1)) * 10, "b": "conc"}
    m = re.match(rf"^({NUM})\s*(mg|g|ug)\s*(?:[a-z ]+)?/\s*({NUM})?\s*(ml|g|l)\b", s)
    if m:
        per = _num(m.group(3)) if m.group(3) else 1.0
        per = per * 1000 if m.group(4) == "l" else per
        return {"i": name, "v": _num(m.group(1)) * MASS_TO_MG[m.group(2)] / per, "b": "conc"}
    if re.match(rf"^({NUM})\s*(mg|g|ug)\s*(?:[a-z ]+)?/\s*({NUM})?\s*(h|hora|horas|24)", s):
        return None  # parches: mg por hora, no se compara
    m = re.match(rf"^({NUM})\s*(mg|g|ug)(?![a-z])(.*)$", s)
    if m and not re.search(r"\d", m.group(3)):  # "400 mg/10 mg" para un solo ingrediente: no se sabe qué es
        return {"i": name, "v": _num(m.group(1)) * MASS_TO_MG[m.group(2)], "b": "unit"}
    return None


def es_strengths(dose, inn_name):
    """Dosis de un producto de España (texto de CIMA) para su principio activo `inn_name` (con ' + ' si es
    una combinación). Lista vacía si no se puede interpretar con seguridad."""
    if not dose or not inn_name:
        return []
    names = [ing.plain(n) for n in inn_name.split(" + ")]
    if len(names) == 1:
        one = _es_single(dose, names[0])
        return [one] if one else []
    s = _norm(dose)
    if "+" in s:
        parts = [x.strip() for x in s.split("+")]
        if len(parts) != len(names):
            return []
        out = [_es_single(part, name) for part, name in zip(parts, names)]
        return out if all(out) else []
    # "175/12.5 mg/mg", "400 mg/10 mg": una cantidad por componente, en el orden del nombre
    if re.search(r"\bml\b|\bg/|/g\b|%", s):
        return []
    nums = re.findall(NUM, s)
    unit = re.search(r"(?<![a-z])(mg|g|ug)\b", s)
    if len(nums) != len(names) or not unit:
        return []
    mult = MASS_TO_MG[unit.group(1)]
    return [{"i": n, "v": _num(x) * mult, "b": "unit"} for n, x in zip(names, nums)]


# ------------------------------------------------------------------------------------ Francia
def fr_strengths(compo, names):
    """`compo`: lista de (sustancia, dosificación, referencia) de CIS_COMPO; `names`: nombre comparable de cada
    sustancia (el español si está enlazado), en el mismo orden. Lista vacía si algo no se interpreta."""
    out = []
    for (substance, dosage, reference), name in zip(compo, names):
        m = re.match(rf"^\s*({NUM}(?:\s\d{{3}})*)\s*([a-zµ]+)\s*$", dosage.lower().strip())
        mass = MASS_TO_MG.get(m.group(2)) if m else None
        if not m or mass is None:
            return []
        mg = _num(m.group(1)) * mass
        ref = ing.plain(reference)
        r = re.match(rf"^({NUM})?\s*(ml|g|l)\b", ref)
        if r:
            per = _num(r.group(1)) if r.group(1) else 1.0
            per = per * 1000 if r.group(2) == "l" else per
            out.append({"i": ing.plain(name), "v": mg / per, "b": "conc"})
        elif re.match(r"^(un|une)\s", ref) and not re.search(r"flacon|tube|pot|boite|stylo|cartouche", ref):
            out.append({"i": ing.plain(name), "v": mg, "b": "unit"})
        else:
            return []
    return out


# ------------------------------------------------------------------------------------ Reino Unido
def uk_strengths(vpi, names):
    """`vpi`: lista de (numerador, unidad numerador, denominador, unidad denominador) del dm+d."""
    out = []
    for (num, num_unit, den, den_unit), name in zip(vpi, names):
        mass = MASS_TO_MG.get((num_unit or "").lower())
        if not num or mass is None:
            return []
        mg = float(num) * mass
        den_unit = (den_unit or "").lower()
        if not den_unit:
            out.append({"i": ing.plain(name), "v": mg, "b": "unit"})
        elif den_unit in ("ml", "gram", "g", "litre", "l"):
            per = float(den) if den else 1.0
            per = per * 1000 if den_unit in ("litre", "l") else per
            out.append({"i": ing.plain(name), "v": mg / per, "b": "conc"})
        elif den_unit in UNIT_WORDS:
            out.append({"i": ing.plain(name), "v": mg / (float(den) if den else 1.0), "b": "unit"})
        else:
            return []
    return out


# ------------------------------------------------------------------------------------ Italia
def it_strengths(rows, names, solid):
    """`rows`: (cantidad, unidad) de PA_confezioni de la AIFA para cada principio activo; `names`: nombre
    comparable de cada uno (el español si está enlazado), en el mismo orden; `solid`: la forma es de unidad
    (comprimido, cápsula, supositorio...). Solo se interpretan las CONCENTRACIONES («mg/ml», «mg/g», «%») y
    los mg o g de una forma de unidad: «milligrammi» a secas no dice si es por comprimido o por envase."""
    out = []
    for (quantity, unit), name in zip(rows, names):
        try:
            q = float((quantity or "").strip().replace(",", "."))
        except ValueError:
            return []
        u = (unit or "").strip().lower()
        if q <= 0:
            return []
        if u in ("milligram(s)/millilitre", "milligram(s)/gram"):
            out.append({"i": ing.plain(name), "v": q, "b": "conc"})
        elif u == "percent":
            out.append({"i": ing.plain(name), "v": q * 10, "b": "conc"})  # 1 % = 10 mg por ml o por g
        elif u in ("milligrammi", "grammi") and solid:
            out.append({"i": ing.plain(name), "v": q * (1000.0 if u == "grammi" else 1.0), "b": "unit"})
        else:
            return []
    return out


_IT_DOSE = re.compile(rf"{NUM}\s*(?:mg|g|ug)\s*/\s*(?:{NUM})?\s*(?:ml|g)\b|{NUM}\s*%|{NUM}\s*(?:mg|g|ug)(?![a-z])")


def it_description_strength(description, name, solid):
    """Dosis de un producto italiano de UN solo principio activo a partir del texto del envase
    («200 MG COMPRESSE RIVESTITE», «120 mg/5 ml sciroppo», «5% COLLIRIO»). `solid`: la presentación es de
    unidad (comprimido, sobre...): solo entonces un «mg» a secas es por unidad."""
    s = re.sub(r"\bmicrogrammi\b", "ug", _norm(description))
    m = _IT_DOSE.search(s)
    one = _es_single(m.group(0), name) if m else None
    if one is None or (one["b"] == "unit" and not solid):
        return []
    return [one]


# ------------------------------------------------------------------------------------ público
_CHILD = re.compile(
    r"\b(infantil|infantiles|pediatric\w*|paediatric\w*|nino|ninos|junior|bebe|bebes|lactante|lactantes|"
    r"kids?|baby|babies|child|children|childrens|infant|infants|enfant|enfants|nourrisson|nourrissons|"
    r"pediatrique|pediatriques|bambino|bambini|pediatrico|pediatrica|neonato|neonati|lattante|lattanti)\b"
)
_ADULT = re.compile(r"\b(adulto|adultos|adult|adults|adulte|adultes|adulti)\b")
_MONTHS = re.compile(r"\b(\d+)\s*(?:months?|mois|meses)\b")
_YEARS = re.compile(r"\b(\d+)\s*(?:years?|ans|anos)\s*(?:plus|\+)?")


def audience_of(brand_name):
    """'child', 'adult' o None según palabras del nombre ('Children's', 'Junior', '3 Months Plus',
    'ENFANTS', '12 Years Plus'). Heurística: un nombre sin palabras así devuelve None."""
    s = ing.plain(brand_name or "").replace("'", " ")
    if _CHILD.search(s) or _MONTHS.search(s):
        return "child"
    y = _YEARS.search(s)
    if y and ("plus" in s or "+" in s):
        return "child" if int(y.group(1)) < 12 else "adult"
    if _ADULT.search(s):
        return "adult"
    return None


def dumps(strengths):
    return _json(strengths)


def backfill_es(conn):
    """Rellena `strengths` y `audience` de los productos de España a partir de su texto de dosis y su
    nombre. Es idempotente y no necesita red: se llama tras cada sincronización de CIMA."""
    rows = conn.execute(
        "SELECT p.id, p.dose, ai.inn_name, p.brand_name FROM products p "
        "JOIN active_ingredients ai ON ai.id = p.active_ingredient_id WHERE p.country_code = 'ES'"
    ).fetchall()
    for product_id, dose, inn_name, brand in rows:
        conn.execute(
            "UPDATE products SET strengths = ?, audience = ? WHERE id = ?",
            (_json(es_strengths(dose, inn_name)), audience_of(brand), product_id),
        )
    conn.commit()
    return len(rows)
