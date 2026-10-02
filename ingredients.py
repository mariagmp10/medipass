"""
ingredients.py
Enlace de principios activos entre idiomas (francés -> español).

REGLA DE ORO: ningún enlace se crea solo. Un nombre francés se enlaza con uno
español únicamente si el par está en ingredient_links.csv con estado
"confirmado" o "aprobado". Ese archivo lo prepara curate_ingredient_links.py
(reglas fijas + comprobación independiente en Wikidata) y se revisa a mano;
al importar datos no se adivina nada.

Este módulo solo hace tres cosas:
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
LINK_FIELDS = ["nombre_fr", "nombre_es", "estado", "evidencia", "productos_fr", "ejemplos"]
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
    """{nombre francés sin tildes: nombre español} solo con los enlaces usables."""
    links = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["estado"] in USABLE_STATUSES:
                    links[plain(row["nombre_fr"])] = row["nombre_es"]
    return links


def build_es_index(names):
    """{conjunto de componentes sin tildes: nombre español completo}."""
    return {frozenset(plain(c) for c in name.split(" + ")): name for name in names}


def resolve(substances, links, es_index):
    """(nombre español, motivo). El nombre es None si no se puede enlazar."""
    components = []
    for raw in substances:
        moiety = parse_substance(raw)
        if moiety is None:
            return None, "no_interpretable"
        spanish = links.get(plain(moiety))
        if spanish is None:
            return None, "sin_enlace"
        components.append(plain(spanish))
    name = es_index.get(frozenset(components))
    return (name, "enlazado") if name else (None, "combinacion_sin_equivalente")
