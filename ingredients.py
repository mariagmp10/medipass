"""
ingredients.py
Enlace de principios activos entre idiomas (francés e inglés -> español).

REGLA DE ORO: ningún enlace se crea solo. Un nombre francés se enlaza con uno
español únicamente si el par está en ingredient_links.csv con estado
"confirmado" o "aprobado". Ese archivo lo prepara curate_ingredient_links.py
(reglas fijas + comprobación independiente en Wikidata) y se revisa a mano;
al importar datos no se adivina nada.

Este módulo solo hace tres cosas (para Francia; el Reino Unido usa
parse_substance_en() y ingredient_links_uk.csv con las mismas reglas):
  1. plain(): comparar nombres sin tildes ni mayúsculas.
  2. parse_substance(): dejar un nombre francés en su principio activo
     ("chlorhydrate de lopéramide" -> "lopéramide"), o None si el nombre es
     demasiado raro para interpretarlo con seguridad.
  3. resolve(): con la tabla de enlaces ya revisada, decidir a qué principio
     activo español corresponde un producto. Se compara como CONJUNTO, así que
     "caféine + paracétamol" y "paracetamol + cafeína" son lo mismo.

Qué cuenta como "el mismo principio activo": la misma molécula activa aunque
cambie la SAL (diclofenaco sódico o dietilamina, lopéramide o su clorhidrato),
que es también lo que hace el 'vtm' de CIMA. NO se consideran iguales los
ésteres ("dipropionate de bétaméthasone" no es bétaméthasone) ni las sales
inorgánicas enteras ("carbonate de calcium" no es "calcium").
"""

import csv
import os
import re
import unicodedata

LINKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingredient_links.csv")
LINKS_PATH_UK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingredient_links_uk.csv")
LINK_FIELDS = ["nombre_fr", "nombre_es", "estado", "evidencia", "productos_fr", "ejemplos"]
LINK_FIELDS_UK = ["nombre_en", "nombre_es", "estado", "evidencia", "productos_uk", "ejemplos"]
USABLE_STATUSES = {"confirmado", "aprobado"}


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def plain(text):
    return re.sub(r"\s+", " ", strip_accents(text.lower())).strip()


def _alt(words):
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


# Contraiones de BASES ORGÁNICAS: "chlorhydrate de lopéramide" es lopéramide +
# ácido clorhídrico y el principio activo es el lopéramide. Lista CERRADA a
# propósito. No incluye "carbonate", "chlorure", "oxyde" (en "carbonate de
# calcium" lo que sigue NO es el principio activo) ni ésteres como "acétate",
# "propionate", "valérate", "salicylate" o "benzoate" (el éster es otro
# medicamento, no el mismo con otra sal).
COUNTERIONS = (
    "dichlorhydrate", "chlorhydrate", "bromhydrate", "nitrate", "sulfate", "maleate",
    "fumarate", "tartrate", "bitartrate", "citrate", "succinate", "hydrogenosuccinate",
    "phosphate", "mesilate", "besilate", "tosilate", "lysinate", "resinate", "embonate",
    "gluconate", "digluconate", "diisethionate", "epolamine",
)
# Si tras quitar el contraión queda una de estas palabras, era una sal
# inorgánica entera ("nitrate d'argent") y no se interpreta.
INORGANIC = (
    "sodium", "potassium", "calcium", "magnesium", "zinc", "aluminium", "lithium",
    "argent", "fer", "cuivre", "ammonium", "hydrogene", "eau",
)
# Palabras sueltas que acompañan al principio activo sin cambiarlo.
TRAILING = (
    "hemihydrate", "monohydrate", "dihydrate", "trihydrate", "sesquihydrate", "hydrate",
    "anhydre", "sodique", "disodique", "potassique", "calcique", "magnesique",
    "trometamol", "olamine",
)
CATIONS = (
    "sodium", "potassium", "calcium", "magnesium", "zinc", "aluminium", "diethylamine",
    "diethylammonium", "lysine", "arginine", "olamine", "trometamol",
)

_COUNTERIONS_RE = _alt(COUNTERIONS)
_TRAILING_RE = _alt(TRAILING)
_CATIONS_RE = _alt(CATIONS)


def parse_substance(raw):
    """Devuelve el principio activo 'limpio' (minúsculas, con tildes) o None."""
    s = raw.lower().replace("’", "'").strip()
    p = strip_accents(s)
    if len(p) != len(s):  # algún carácter raro: mejor no interpretarlo
        return None
    start, end = 0, len(p)

    # "lopéramide (chlorhydrate de)" -> "lopéramide"
    paren = re.fullmatch(r"(?P<base>[^()]+?)\s*\((?P<inner>[^()]*)\)", p)
    if paren:
        if not re.fullmatch(rf"(?:{_COUNTERIONS_RE})\s+(?:de|d')\s*", paren.group("inner")):
            return None  # entre paréntesis hay algo que no sabemos interpretar
        start, end = paren.span("base")
    else:
        # "chlorhydrate de lopéramide" -> "lopéramide"
        pre = re.fullmatch(rf"(?:solution de )?(?:{_COUNTERIONS_RE})\s+(?:de |d')\s*(?P<base>.+)", p)
        if pre:
            start, end = pre.span("base")
            if re.fullmatch(rf"(?:{_alt(INORGANIC)})", p[start:end].strip()):
                return None

    # "pantoprazole sodique sesquihydraté", "diclofénac de diéthylamine"
    while True:
        tail = re.search(rf"\s+(?:{_TRAILING_RE}|(?:de |d')\s*(?:{_CATIONS_RE}))$", p[start:end])
        if tail is None:
            break
        end = start + tail.start()

    moiety_plain = p[start:end].strip()
    if len(moiety_plain) < 3 or not re.fullmatch(r"[a-z\- ]+", moiety_plain):
        return None  # cifras, comas, paréntesis...: demasiado raro
    if moiety_plain in INORGANIC:
        # "magnésium (gluconate de)" es gluconato de magnesio, no "magnesio": con
        # los minerales importa qué sal es, así que no se interpreta.
        return None
    return s[start:end].strip()


# --- Reino Unido (nombres en inglés del dm+d) -------------------------------------
# Mismas reglas que en francés: solo se quita la sal de una BASE ORGÁNICA; nunca los
# ésteres ("beclometasone dipropionate", "hydrocortisone acetate") ni derivados
# distintos ("hyoscine butylbromide" no es hioscina), ni las sales inorgánicas enteras
# ("calcium carbonate"). Lista CERRADA a propósito.
COUNTERIONS_EN = (
    "hydrochloride", "dihydrochloride", "hydrobromide", "maleate", "fumarate", "tartrate",
    "bitartrate", "citrate", "succinate", "sulfate", "phosphate", "nitrate", "mesilate",
    "besilate", "isetionate", "teoclate", "mucate", "gluconate",
)
CATIONS_EN = ("sodium", "potassium", "calcium", "diethylammonium", "diethylamine", "lysine", "trometamol", "olamine")
HYDRATES_EN = ("hemihydrate", "monohydrate", "dihydrate", "trihydrate", "hexahydrate", "dodecahydrate", "anhydrous")
INORGANIC_EN = (
    "sodium", "disodium", "potassium", "calcium", "magnesium", "zinc", "aluminium", "lithium",
    "silver", "iron", "ferrous", "ferric", "copper", "ammonium", "hydrogen", "dihydrogen", "water",
    "barium", "bismuth", "manganese", "chromium", "selenium", "molybdenum", "iodine", "sulfur",
    "carbon", "nitrogen", "oxygen", "helium", "phosphorus", "chloride", "bicarbonate", "air",
)


def parse_substance_en(raw):
    """Principio activo 'limpio' en inglés (minúsculas) o None si no se puede interpretar
    con seguridad. Si el nombre es una sal inorgánica o un éster, se devuelve ENTERO (no
    se le quita nada): solo podrá enlazarse si ese nombre completo está confirmado."""
    s = raw.lower().strip()
    if not re.fullmatch(r"[a-z\- ]+", s):  # cifras, comillas, paréntesis, tildes: demasiado raro
        return None
    words = s.split()
    while len(words) > 1 and words[-1] in HYDRATES_EN:
        words.pop()
    if len(words) > 1 and words[-1] in CATIONS_EN and words[-2] not in INORGANIC_EN:
        words.pop()  # "diclofenac sodium", "ibuprofen lysine"
    elif len(words) > 1 and words[-1] in COUNTERIONS_EN:
        base = words[:-1]
        if any(w in INORGANIC_EN for w in base):
            pass  # "zinc sulfate", "riboflavin sodium phosphate": la sal (o el éster) importa
        elif len(base) == 1:
            words = base  # "loperamide hydrochloride", "codeine phosphate"
        else:
            return None
    name = " ".join(words)
    if len(name) < 3 or name in INORGANIC_EN:
        return None  # "sodium", "zinc", "oxygen" solos: elementos, no medicamentos comparables
    return name


# Reglas para PROPONER cómo se escribiría un nombre inglés en español (solo candidatos).
_EN_SUBSTITUTIONS = (("ph", "f"), ("th", "t"), ("y", "i"), ("ff", "f"), ("nn", "n"), ("ll", "l"), ("chl", "cl"))
_EN_ENDINGS = (
    (r"ine\b", "ina"), (r"ide\b", "ida"), (r"one\b", "ona"), (r"ole\b", "ol"), (r"ane\b", "ano"),
    (r"ene\b", "eno"), (r"ate\b", "ato"), (r"ium\b", "io"), (r"ose\b", "osa"),
    (r"(?<=[a-z]{4})en\b", "eno"), (r"(?<=[a-z]{4})an\b", "ano"), (r"il\b", "ilo"), (r"ac\b", "aco"),
)


# Palabras que CIMA escribe distinto (sodio cloruro, zinc óxido, hierro fumarato).
_EN_WORDS = {
    "chloride": "cloruro", "oxide": "oxido", "dioxide": "dioxido", "peroxide": "peroxido",
    "hydroxide": "hidroxido", "ferrous": "hierro", "ferric": "hierro",
}


def propose_spanish_en(moiety, k_to_c=True):
    """Cómo se escribiría un nombre inglés en español. k_to_c=False conserva la k
    (ketoconazol), que en español se usa en unos nombres y se cambia por c en otros
    (benzalconio): el curador prueba las dos formas."""
    s = plain(moiety)
    s = " ".join(_EN_WORDS.get(w, w) for w in s.split())
    s = re.sub(r"^(.+?)ic acid$", r"acido \1ico", s)  # "folic acid" -> "acido folico"
    if k_to_c:
        s = s.replace("k", "c")
    for a, b in _EN_SUBSTITUTIONS:
        s = s.replace(a, b)
    for pattern, replacement in _EN_ENDINGS:
        s = re.sub(pattern, replacement, s)
    return s


# Reglas para PROPONER cómo se escribiría un nombre francés en español. Solo
# sirven para generar candidatos: el candidato se usa únicamente si, además,
# queda confirmado (ver curate_ingredient_links.py).
_SUBSTITUTIONS = (("ph", "f"), ("th", "t"), ("y", "i"), ("ll", "l"), ("ff", "f"), ("chl", "cl"))
_ENDINGS = (
    (r"ique\b", "ico"), (r"iodee\b", "iodada"), (r"ine\b", "ina"), (r"ide\b", "ida"),
    (r"ane\b", "ano"), (r"ene\b", "eno"), (r"one\b", "ona"), (r"ole\b", "ol"),
    (r"ate\b", "ato"), (r"ium\b", "io"), (r"(?<=[a-z]{3})ac\b", "aco"), (r"(?<=[a-z]{3})il\b", "ilo"),
)


def propose_spanish(moiety):
    s = plain(moiety)
    s = re.sub(r"\bacide\b", "acido", s)
    for a, b in _SUBSTITUTIONS:
        s = s.replace(a, b)
    for pattern, replacement in _ENDINGS:
        s = re.sub(pattern, replacement, s)
    return s


def load_links(path=LINKS_PATH):
    """{nombre de origen sin tildes: nombre español} solo con los enlaces usables.
    La primera columna del CSV es el nombre de origen (nombre_fr o nombre_en)."""
    links = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            source_col = reader.fieldnames[0]
            for row in reader:
                if row["estado"] in USABLE_STATUSES:
                    links[plain(row[source_col])] = row["nombre_es"]
    return links


def build_es_index(names):
    """{conjunto de componentes sin tildes: nombre español completo}."""
    return {frozenset(plain(c) for c in name.split(" + ")): name for name in names}


def resolve(substances, links, es_index, parse=parse_substance):
    """(nombre español, motivo). El nombre es None si no se puede enlazar.
    parse: parse_substance (francés) o parse_substance_en (inglés)."""
    components = []
    for raw in substances:
        moiety = parse(raw)
        if moiety is None:
            return None, "no_interpretable"
        spanish = links.get(plain(moiety))
        if spanish is None:
            return None, "sin_enlace"
        components.append(plain(spanish))
    name = es_index.get(frozenset(components))
    return (name, "enlazado") if name else (None, "combinacion_sin_equivalente")
