"""
ingredients.py
Enlace de principios activos entre idiomas (francés, inglés e italiano -> español).

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

DOS NIVELES de equivalencia (ver README, "Dos niveles"):
  exacto   misma molécula activa aunque cambie la sal (lo que enlaza todo lo de abajo)
  base     misma molécula BASE pero distinto ÉSTER o profármaco: "fluticasone propionate" y
           "fluticasona". CIMA los nombra igual; MediPass los enseña aparte, en amarillo, con el
           nombre exacto de cada país. Los enlaces de nivel base salen de ingredient_links*.csv
           (columna `nivel` = base) y pasan por la misma comprobación ATC que los exactos.

Qué cuenta como "el mismo principio activo" (nivel exacto): la misma molécula activa aunque
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
LINKS_PATH_IT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingredient_links_it.csv")
LINK_FIELDS = ["nombre_fr", "nombre_es", "estado", "nivel", "evidencia", "productos_fr", "ejemplos"]
LINK_FIELDS_UK = ["nombre_en", "nombre_es", "estado", "nivel", "evidencia", "productos_uk", "ejemplos"]
LINK_FIELDS_IT = ["nome_it", "nombre_es", "estado", "nivel", "evidencia", "productos_it", "ejemplos"]
LEVEL_EXACT, LEVEL_BASE = "exacto", "base"
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
    "gluconate", "digluconate", "diisethionate", "epolamine", "oxalate", "xinafoate", "hemifumarate",
    "hydrogenotartrate",
)
# Contraiones que a veces son una SAL y a veces un ÉSTER ("benzoate de rizatriptan" es una sal;
# "benzoate de benzyle" es otra sustancia; "acétate de désmopressine" es una sal de péptido;
# "acétate d'hydrocortisone" es un éster). Solo se quitan para estas bases concretas.
AMBIGUOUS_COUNTERIONS = {
    "benzoate": {"rizatriptan"},
    "malate": {"sunitinib", "almotriptan"},
    "acetate": {"desmopressine", "octreotide", "lanreotide", "glatiramere", "leuproreline", "triptoreline",
                "goserelin", "terlipressine", "ganirelix", "cetrorelix", "icatibant", "degarelix",
                "flecainide", "chlorhexidine", "lysine", "indacaterol"},
}
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
    "trometamol", "olamine", "trihydratee", "dihydratee", "monohydratee", "hemihydratee", "sesquihydratee",
    "hydratee", "arginine", "tert-butylamine", "erbumine",
)
CATIONS = (
    "sodium", "potassium", "calcium", "magnesium", "zinc", "aluminium", "diethylamine",
    "diethylammonium", "lysine", "arginine", "olamine", "trometamol",
)

_COUNTERIONS_RE = _alt(COUNTERIONS)
_AMBIGUOUS_RE = _alt(AMBIGUOUS_COUNTERIONS)
_ANY_ION_RE = _alt(tuple(COUNTERIONS) + tuple(AMBIGUOUS_COUNTERIONS))


def _ion_allowed(ion, base_text):
    """Un contraión ambiguo solo se quita para las bases de la lista (ver AMBIGUOUS_COUNTERIONS)."""
    allowed = AMBIGUOUS_COUNTERIONS.get(ion)
    return allowed is None or (base_text.split() or [""])[0] in allowed
_TRAILING_RE = _alt(TRAILING)
_CATIONS_RE = _alt(CATIONS)


# Descriptores de plantas entre paréntesis (sin tildes): qué parte y qué extracto.
_BOTANICAL_WORDS = (
    "partie aerienne", "parties aeriennes", "feuille", "feuilles", "racine", "racines", "fruit", "fruits",
    "fleur", "fleurs", "ecorce", "sommite fleurie", "sommites fleuries", "plante entiere", "herbe",
    "extrait sec", "extrait mou", "extrait fluide", "extrait aqueux", "extrait hydroalcoolique",
    "extrait titre", "extrait standardise", "teinture", "poudre", "huile essentielle",
)
_BOTANICAL_RE = "|".join(re.escape(w) for w in sorted(_BOTANICAL_WORDS, key=len, reverse=True))


def _bare_anions():
    """Palabras que son solo un anión o una palabra de éster: si un nombre se queda en una de ellas, es que
    se ha perdido la molécula."""
    return (set(COUNTERIONS) | set(AMBIGUOUS_COUNTERIONS) | set(ESTER_WORDS)
            | {"chlorure", "carbonate", "oxyde", "hydroxyde", "lactate", "bicarbonate"})


def parse_substance(raw):
    """Devuelve el principio activo 'limpio' (minúsculas, con tildes) o None."""
    s = raw.lower().replace("’", "'").strip()
    p = strip_accents(s)
    if len(p) != len(s):  # algún carácter raro: mejor no interpretarlo
        return None
    # Plantas: "hydrocotyle (partie aérienne d') (extrait sec de)" -> "hydrocotyle". Se quitan la parte de
    # la planta y el tipo de extracto: se compara la PLANTA (el tipo de extracto y la dosis no se
    # comparan, igual que la dosis de cualquier otro medicamento). `s` y `p` tienen la misma longitud,
    # así que se quita el mismo tramo de los dos.
    while True:
        m = re.search(rf"\s*\((?:{_BOTANICAL_RE})(?:\s+(?:de|d'))?\s*\)", p)
        if not m:
            break
        p, s = p[: m.start()] + p[m.end():], s[: m.start()] + s[m.end():]
    s, p = s.strip(), p.strip()
    start, end = 0, len(p)

    # "lopéramide (chlorhydrate de)" -> "lopéramide"
    paren = re.fullmatch(r"(?P<base>[^()]+?)\s*\((?P<inner>[^()]*)\)", p)
    if paren:
        inner = re.fullmatch(rf"(?P<ion>{_ANY_ION_RE})\s+(?:de|d')\s*", paren.group("inner"))
        if not inner or not _ion_allowed(inner.group("ion"), paren.group("base")):
            return None  # entre paréntesis hay algo que no sabemos interpretar
        start, end = paren.span("base")
    else:
        # "chlorhydrate de lopéramide" -> "lopéramide"
        pre = re.fullmatch(rf"(?:solution de )?(?P<ion>{_ANY_ION_RE})\s+(?:de |d')\s*(?P<base>.+)", p)
        if pre and not _ion_allowed(pre.group("ion"), pre.group("base")):
            pre = None  # "benzoate de benzyle", "acétate d'hydrocortisone": no es una sal
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
    if moiety_plain in _bare_anions():
        # "acétate de lysine" se quedaría en "acétate": un anión suelto no identifica nada y
        # "acétate de sodium" acabaría con la misma clave.
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
    "besilate", "isetionate", "teoclate", "mucate", "gluconate", "oxalate", "xinafoate", "hemifumarate",
)
# Contraiones que a veces son una sal y a veces un éster: solo para estas bases (ver el francés).
AMBIGUOUS_COUNTERIONS_EN = {
    "benzoate": {"rizatriptan"},
    "malate": {"sunitinib", "almotriptan"},
    "acetate": {"desmopressin", "octreotide", "lanreotide", "glatiramer", "leuprorelin", "triptorelin",
                "goserelin", "terlipressin", "ganirelix", "cetrorelix", "icatibant", "degarelix",
                "flecainide", "chlorhexidine", "lysine", "indacaterol"},
}
CATIONS_EN = ("sodium", "potassium", "calcium", "diethylammonium", "diethylamine", "lysine", "trometamol", "olamine",
              "arginine", "erbumine", "tert-butylamine", "tromethamine")
HYDRATES_EN = ("hemihydrate", "monohydrate", "dihydrate", "trihydrate", "hexahydrate", "dodecahydrate", "anhydrous",
               "sesquihydrate", "hydrate", "micronised", "micronized")
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
    s = re.sub(r"\bhydrogen (tartrate|maleate|fumarate|malate)$", r"\1", s)  # sal ácida: sigue siendo la sal
    words = s.split()
    while len(words) > 1 and words[-1] in HYDRATES_EN:
        words.pop()
    ambiguous_ok = len(words) == 2 and words[0] in AMBIGUOUS_COUNTERIONS_EN.get(words[-1], ())
    if len(words) > 1 and words[-1] in CATIONS_EN and words[-2] not in INORGANIC_EN:
        words.pop()  # "diclofenac sodium", "ibuprofen lysine"
    elif len(words) > 1 and (words[-1] in COUNTERIONS_EN or ambiguous_ok):
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


def propose_acid_en(moiety):
    """Para la sal de un ácido orgánico ("sodium valproate"), el nombre español del ÁCIDO
    ("ácido valproico"): CIMA nombra así al valproato sódico. Solo es un candidato: hay que
    confirmarlo con el ATC (así se descartaría "sodium citrate" -> "ácido cítrico")."""
    m = re.fullmatch(r"(?:sodium|potassium|calcium|magnesium) ([a-z]+)ate", plain(moiety))
    return f"acido {m.group(1)}ico" if m else None


def propose_spanish_en(moiety, k_to_c=True):
    """Cómo se escribiría un nombre inglés en español. k_to_c=False conserva la k
    (ketoconazol), que en español se usa en unos nombres y se cambia por c en otros
    (benzalconio): el curador prueba las dos formas."""
    s = plain(moiety)
    nitrate = re.fullmatch(r"([a-z]+) ((?:mono|di)nitrate)", s)
    if nitrate:  # "isosorbide mononitrate" -> "mononitrato de isosorbida" (así lo escribe CIMA)
        return f"{nitrate.group(2)[:-1]}o de {propose_spanish_en(nitrate.group(1), k_to_c)}"
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


# --- Italia (nombres en italiano de la AIFA) ------------------------------------------
# Como en inglés, la sal va DESPUÉS del principio activo ("nafazolina nitrato"). Mismas reglas
# conservadoras: solo se quita la sal de una BASE ORGÁNICA; nunca los ésteres, ni las sales
# inorgánicas enteras ("magnesio idrossido"). Listas cerradas a propósito.
COUNTERIONS_IT = (
    "cloridrato", "dicloridrato", "bromidrato", "solfato", "nitrato", "maleato", "fumarato", "emifumarato",
    "tartrato", "bitartrato", "citrato", "succinato", "fosfato", "mesilato", "besilato", "tosilato", "isetionato",
    "gluconato", "ossalato", "xinafoato", "teoclato", "mucato",
)
AMBIGUOUS_COUNTERIONS_IT = {
    "benzoato": {"rizatriptan"},
    "malato": {"sunitinib", "almotriptan"},
    "acetato": {"desmopressina", "octreotide", "lanreotide", "glatiramer", "leuprorelina", "triptorelina",
                "goserelin", "terlipressina", "ganirelix", "cetrorelix", "icatibant", "degarelix",
                "flecainide", "clorexidina", "lisina", "indacaterolo"},
}
CATIONS_IT = ("sodico", "disodico", "potassico", "calcico", "magnesico", "dietilammonio", "dietilammina", "lisina",
              "arginina", "trometamolo", "trometamina", "olamina", "erbumina", "tert-butilammina")
HYDRATES_IT = ("monoidrato", "diidrato", "triidrato", "esaidrato", "emiidrato", "sesquiidrato", "idrato", "anidro",
               "micronizzato")
INORGANIC_IT = (
    "sodio", "disodio", "potassio", "calcio", "magnesio", "zinco", "alluminio", "litio", "argento", "ferro", "rame",
    "ammonio", "idrogeno", "acqua", "bario", "bismuto", "manganese", "cromo", "selenio", "molibdeno", "iodio", "zolfo",
    "carbonio", "azoto", "ossigeno", "elio", "fosforo", "cloruro", "bicarbonato", "aria",
)
# Descriptores de plantas al final del nombre ("senna foglia", "senna estratto secco").
BOTANICAL_IT = {
    "foglia", "foglie", "radice", "radici", "frutto", "frutti", "fiore", "fiori", "corteccia", "cortecce", "rizoma",
    "semi", "seme", "bulbo", "gemma", "gemme", "erba", "resina", "polvere", "essenza", "tintura", "tintura madre",
    "olio essenziale", "estratto", "estratto secco", "estratto molle", "estratto fluido", "estratto idroalcolico",
    "estratto acquoso", "parti aeree", "sommita fiorite", "pianta intera",
}


def parse_substance_it(raw):
    """Principio activo 'limpio' en italiano (minúsculas, sin tildes) o None si no se puede interpretar con
    seguridad. Si es una sal inorgánica o un éster se devuelve ENTERO (no se le quita nada)."""
    s = re.sub(r"\s+", " ", strip_accents(raw.lower()).strip())
    if not re.fullmatch(r"[a-z\- ]+", s):  # cifras, comas, paréntesis, barras: demasiado raro
        return None
    s = re.sub(r"\s+sale (?:di )?[a-z]+$", "", s)  # "ibuprofene sale di lisina" -> "ibuprofene"
    words = s.split()
    changed = True
    while changed and len(words) > 1:  # "senna foglia", "senna estratto secco" -> "senna"
        changed = False
        for n in (3, 2, 1):
            if len(words) > n and " ".join(words[-n:]) in BOTANICAL_IT:
                words = words[:-n]
                changed = True
                break
    while len(words) > 1 and words[-1] in HYDRATES_IT:
        words.pop()
    ambiguous_ok = len(words) == 2 and words[0] in AMBIGUOUS_COUNTERIONS_IT.get(words[-1], ())
    if len(words) > 1 and words[-1] in CATIONS_IT and words[-2] not in INORGANIC_IT:
        words.pop()  # "diclofenac sodico", "ibuprofene lisina"
    elif len(words) > 1 and (words[-1] in COUNTERIONS_IT or ambiguous_ok):
        base = words[:-1]
        if any(w in INORGANIC_IT for w in base):
            pass  # "zinco solfato": la sal importa
        elif len(base) == 1:
            words = base  # "loperamide cloridrato", "codeina fosfato"
        else:
            return None
    name = " ".join(words)
    if len(name) < 3 or name in INORGANIC_IT:
        return None
    return name


_IT_SUBSTITUTIONS = (
    ("idrossi", "hidroxi"), ("ossi", "oxi"), ("destro", "dextro"), ("ph", "f"), ("th", "t"),
    ("y", "i"), ("ff", "f"), ("chi", "qui"), ("che", "que"), ("ll", "l"), ("zz", "z"),
)
_IT_ENDINGS = (
    (r"ene\b", "eno"), (r"olo\b", "ol"), (r"one\b", "ona"), (r"ile\b", "ilo"), (r"ale\b", "al"), (r"ide\b", "ida"),
    (r"ina\b", "ina"), (r"ico\b", "ico"), (r"ato\b", "ato"), (r"io\b", "io"),
)


def propose_spanish_it(moiety, k_to_c=True):
    """Cómo se escribiría un nombre italiano en español (solo candidatos: hay que confirmarlos)."""
    s = plain(moiety)
    if k_to_c:
        s = s.replace("k", "c")
    for a, b in _IT_SUBSTITUTIONS:
        s = s.replace(a, b)
    s = re.sub(r"(?<!h)idro", "hidro", s)  # idrocortisone -> hidrocortisona (sin duplicar la h)
    for pattern, replacement in _IT_ENDINGS:
        s = re.sub(pattern, replacement, s)
    return s


def _parser(country):
    return {"FR": parse_substance, "UK": parse_substance_en, "IT": parse_substance_it}[country]


def load_links(path=LINKS_PATH, level=LEVEL_EXACT):
    """{nombre de origen sin tildes: nombre español} solo con los enlaces usables del `level`
    ("exacto" por defecto, o "base"). La primera columna del CSV es el nombre de origen
    (nombre_fr o nombre_en); si el archivo no tiene columna `nivel`, todo es exacto."""
    links = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            source_col = reader.fieldnames[0]
            for row in reader:
                if row["estado"] in USABLE_STATUSES and (row.get("nivel") or LEVEL_EXACT) == level:
                    links[plain(row[source_col])] = row["nombre_es"]
    return links


# Palabras que hacen de una molécula un ÉSTER o PROFÁRMACO ("propionate de fluticasone",
# "candésartan cilexétil"). Sin tildes. Solo sirven para PROPONER un enlace de nivel base.
ESTER_WORDS = (
    "dipropionate", "propionate", "furoate", "valerate", "butyrate", "acetate", "cilexetil", "medoxomil",
    "mofetil", "etexilate", "disoproxil", "axetil", "pivoxil", "proxetil", "probutate", "aceponate",
    # italiano (AIFA)
    "dipropionato", "propionato", "furoato", "valerato", "butirrato", "acetato", "mofetile", "etexilato",
    "probutato", "aceponato",
)
_ESTER_RE = _alt(ESTER_WORDS)


def source_key(raw, country):
    """Clave con la que se busca un nombre de origen en las tablas de enlaces de nivel base:
    la molécula ya limpia de sales si se pudo, y si no el nombre tal cual, sin tildes."""
    moiety = _parser(country)(raw)
    return plain(moiety if moiety is not None else raw)


def ester_base(raw, country):
    """Si `raw` es un éster o profármaco ("fluticasone propionate", "propionate de fluticasone",
    "béclométasone (dipropionate de)", "candésartan cilexétil"), devuelve el nombre de su BASE ya
    limpio de sales ("fluticasone"); si no, None. Solo propone: nunca se usa sin confirmación."""
    s = raw.lower().replace("’", "'").strip()
    p = strip_accents(s)
    if len(p) != len(s):
        return None
    # Primero se quita la SAL o el hidrato si los hay ("dabigatran etexilate mesilate"): la sal
    # va detrás del éster y no cambia qué éster es.
    if country == "FR":
        salt = re.search(rf"\s*\((?:{_COUNTERIONS_RE})\s+(?:de|d')\s*\)$|\s+(?:{_TRAILING_RE})$", p)
    elif country == "IT":
        salt = re.search(rf"\s+(?:{_alt(COUNTERIONS_IT + HYDRATES_IT + CATIONS_IT)})$", p)
    else:
        salt = re.search(rf"\s+(?:{_alt(COUNTERIONS_EN + HYDRATES_EN + CATIONS_EN)})$", p)
    if salt:
        p, s = p[: salt.start()], s[: salt.start()]
    rest = None
    if country == "FR":
        m = re.fullmatch(rf"(?P<base>[^()]+?)\s*\((?:{_ESTER_RE})\s+(?:de|d')\s*\)", p)
        if m:
            rest = s[m.start("base"):m.end("base")]
        if rest is None:
            m = re.fullmatch(rf"(?:{_ESTER_RE})\s+(?:de |d')\s*(?P<base>.+)", p)
            if m:
                rest = s[m.start("base"):m.end("base")]
    if rest is None:
        m = re.fullmatch(rf"(?P<base>.+?)\s+(?:{_ESTER_RE})", p)  # "fluticasone propionate", "ténofovir disoproxil"
        if m:
            rest = s[m.start("base"):m.end("base")]
    if rest is None:
        return None
    return _parser(country)(rest.strip())


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


def component_names(substances, links, base_links, parse=parse_substance, country="FR"):
    """Nombre comparable de cada sustancia, en el mismo orden: el español (sin tildes) si tiene enlace
    exacto o de base, y si no el nombre de origen limpio. Sirve para alinear las dosis con las de otro país."""
    out = []
    for raw in substances:
        moiety = parse(raw)
        es = links.get(plain(moiety)) if moiety is not None else None
        if es is None:
            es = base_links.get(source_key(raw, country))
        out.append(plain(es) if es else plain(moiety if moiety is not None else raw))
    return out


def resolve_levels(substances, links, base_links, es_index, parse=parse_substance, country="FR"):
    """(nombre español, motivo, nivel). nivel = "exacto" si todos los componentes tienen un enlace
    exacto, "base" si alguno solo lo tiene de nivel base (distinto éster/sal), None si no hay enlace.
    Con nivel "base" el nombre español es el de la BASE: el producto conserva su nombre propio y
    solo se usa para el nivel amarillo."""
    components, level = [], LEVEL_EXACT
    for raw in substances:
        moiety = parse(raw)
        exact = links.get(plain(moiety)) if moiety is not None else None
        if exact is not None:
            components.append(plain(exact))
            continue
        base = base_links.get(source_key(raw, country))
        if base is None:
            return None, ("no_interpretable" if moiety is None else "sin_enlace"), None
        components.append(plain(base))
        level = LEVEL_BASE
    name = es_index.get(frozenset(components))
    return (name, "enlazado", level) if name else (None, "combinacion_sin_equivalente", None)
