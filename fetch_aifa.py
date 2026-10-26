"""
fetch_aifa.py
Carga en products (country_code = 'IT') el catálogo de medicamentos de Italia, sin receta y con
receta, a partir de los datos abiertos de la AIFA (Agenzia Italiana del Farmaco):
https://www.aifa.gov.it/dati-aifa  ->  https://drive.aifa.gov.it/farmaci/

Fuente:   tres archivos CSV (separados por «;», UTF-8) que la AIFA actualiza con frecuencia:
            confezioni_fornitura.csv   un registro por ENVASE (160.000): nombre, forma, ATC,
                                       principios activos y régimen de dispensación (FORNITURA)
            PA_confezioni.csv          cantidad de cada principio activo por envase
            atc.csv                    descripción de los códigos ATC
Licencia: Creative Commons Attribution 4.0 (CC-BY 4.0). Hay que citar la fuente: «Fonte: AIFA
          (Agenzia Italiana del Farmaco), dati aperti, licenza CC-BY 4.0» y la fecha de los datos
          (los archivos no traen número de versión: se usa la fecha de descarga).
Descarga: sin cuenta ni clave. Se descargan solos (--dir RUTA para usar copias ya bajadas).

Diferencias importantes con CIMA, BDPM y dm+d (léelas antes de tocar este archivo):

1. Estructura. Cada fila es un envase (CODICE_AIC); un producto es el COD_FARMACO. Algunos
   productos (267 sin receta) tienen varias formas: se tratan como productos distintos
   (COD_FARMACO + FORMA). Los datos del producto (nombre, forma, ATC, principios activos) se
   repiten en todos sus envases.
2. Régimen de dispensación (columna FORNITURA, texto oficial):
     «non soggetti a prescrizione medica, da banco»        -> libre (OTC; publicidad permitida)
     «non soggetti a prescrizione medica ma non da banco»  -> solo farmacia, sin receta (SOP)
     «soggetti a prescrizione medica …»                    -> con receta
   Sin receta = el producto tiene al menos un envase sin receta (igual que el Reino Unido).
3. Se EXCLUYEN: los no autorizados (STATO_AMMINISTRATIVO distinto de «Autorizzata»), los
   homeopáticos (TIPO_PROCEDURA «Omeopatico», igual que en Francia y el Reino Unido) y la
   IMPORTACIÓN PARALELA (medicamentos de otro país reetiquetados: son duplicados del mismo
   producto; el Reino Unido también excluye los importados). Con receta, igual que en los otros
   países: los de uso exclusivamente hospitalario o del especialista y los inyectables (por la
   forma). «Vendibili al pubblico su prescrizione di centri ospedalieri o di specialisti» SÍ se
   queda: se compra en la farmacia.
4. Los principios activos (PA_ASSOCIATI, separados por «/») vienen con sal («PIRIDOSSINA
   CLORIDRATO»), a veces repetidos o en otro idioma («IBUPROFEN»). El código ATC del producto
   (CODICE_ATC) es lo que permite comprobar el enlace con el nombre español sin depender de los
   nombres: ver curate_ingredient_links.py --country it.
5. La forma es texto italiano («Compressa rivestita con film») sin vía de administración: se traduce
   a la de CIMA con form_map_it.csv (la vía va vacía; la forma ya la lleva: «Crema vaginale»).
6. Dosis: PA_confezioni.csv trae cantidad y unidad por envase y principio activo, pero muchas
   están vacías (solo ~60 % de los envases sin receta) y «milligrammi»/«grammi» no dicen «por qué»
   (por comprimido o por envase). Solo se usan las concentraciones («mg/ml», «mg/g», «%») y los
   «mg»/«g» de formas de unidad (comprimido, cápsula, supositorio…). Lo demás queda sin dosis y
   la app dice «no se puede comparar».

Uso:
    python fetch_aifa.py                 # descarga y sincroniza Italia (sin receta y con receta)
    python fetch_aifa.py --dir CARPETA   # usa los CSV ya descargados en CARPETA
    python fetch_aifa.py --only-otc      # solo sin receta
    python fetch_aifa.py --debug         # analiza y muestra el informe, sin tocar medipass.db
    python fetch_aifa.py --inspect       # solo cuenta formas del catálogo

Ejecuta antes fetch_cima.py: el vocabulario español al que se enlaza sale de los productos de
España que ya estén en la base.
"""

import argparse
import collections
import csv
import datetime
import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.request

import doses
import importers
import ingredients as ing

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(10_000_000)

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
FORM_MAP_PATH = os.path.join(HERE, "form_map_it.csv")
AIFA_BASE = "https://drive.aifa.gov.it/farmaci"
FILES = ("confezioni_fornitura.csv", "PA_confezioni.csv")
SOURCE_NAME = "AIFA"

AUTHORIZED = "Autorizzata"
HOMEOPATHIC = "Omeopatico"
PARALLEL_IMPORT = "Importazione Parallela"
OTC_PREFIX = "Medicinali non soggetti a prescrizione medica"
# Régimen con receta que NO se compra en una farmacia (uso exclusivo de hospital o del especialista).
HOSPITAL_SUPPLY = ("esclusivamente in ambiente ospedaliero", "esclusivamente dallo specialista")
# Formas inyectables / parenterales (minúsculas, en italiano): se excluyen SOLO los productos con receta.
PARENTERAL_FORMS = ("iniettabil", "infusione", "iniezione", "siringa", "solvente per uso parenterale", "impianto")
# Diálisis y lavados: no los compra un paciente en la farmacia (igual que en Francia).
DIALYSIS_FORMS = ("emodialisi", "emofiltrazione", "dialisi", "lavanda gastrica", "irrigazione")
SOLID_UNIT_FORMS = ("compress", "capsula", "supposta", "ovulo", "pastiglia", "gomma", "bustina", "cerotto", "confetto")
LINK_REASONS = {
    "enlazado": "enlazados con un principio activo español (comparables)",
    "sin_enlace": "sin enlace revisado: conservan su nombre en italiano",
    "no_interpretable": "con un nombre que no se interpreta (cifras, extractos, elementos...)",
    "combinacion_sin_equivalente": "combinación sin equivalente en España",
}


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh, delimiter=";")


def download(directory):
    """Descarga los CSV a `directory` (se sobrescriben). Devuelve la carpeta."""
    os.makedirs(directory, exist_ok=True)
    for name in FILES:
        target = os.path.join(directory, name)
        print(f"Descargando {name}...")
        urllib.request.urlretrieve(f"{AIFA_BASE}/{name}", target)
    return directory


def data_date(directory):
    """Fecha de los datos = fecha del archivo principal (la AIFA no publica un número de versión)."""
    path = os.path.join(directory, FILES[0])
    return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def supply_label(supply):
    """(requiere receta, categoría legal, nota) a partir del texto oficial de FORNITURA."""
    s = supply.lower()
    if supply.startswith(OTC_PREFIX):
        if "non da banco" in s:
            return 0, importers.LEGAL_PHARMACY, "SOP (senza obbligo di prescrizione)"
        return 0, importers.LEGAL_FREE, "OTC (da banco)"
    if "ricalco" in s:
        note = "Ricetta a ricalco (stupefacenti)"
    elif "limitativa" in s:
        note = "Prescrizione medica limitativa (centri ospedalieri o specialisti)"
    elif "da rinnovare" in s:
        note = "Prescrizione medica da rinnovare volta per volta"
    else:
        note = "Prescrizione medica"
    return 1, importers.LEGAL_RX, note


def is_hospital_supply(supply):
    return any(w in supply.lower() for w in HOSPITAL_SUPPLY)


def is_parenteral(form):
    f = form.lower()
    return any(w in f for w in PARENTERAL_FORMS)


def clean_description(text):
    """Primera parte de DESCRIZIONE ("200 MG COMPRESSE RIVESTITE- 12 COMPRESSE" -> "200 MG COMPRESSE
    RIVESTITE"): la dosis y la forma, sin el tamaño del envase."""
    head = re.split(r"\s*-\s|-\s*(?=[A-Z0-9])|>|,\s*\d+\s", text, maxsplit=1)[0]
    head = re.sub(r"[<>]", "", head)
    head = re.sub(r"\s+", " ", head).strip(" .,-")
    return head[:80].rstrip()


def split_substances(raw):
    """Principios activos de PA_ASSOCIATI sin repeticiones. «IBUPROFENE/IBUPROFEN» es uno solo."""
    out = []
    for part in raw.split("/"):
        part = re.sub(r"\s+", " ", part).strip()
        if not part:
            continue
        key = ing.plain(re.sub(r"\s+sale di \w+$", "", part, flags=re.I)).rstrip("eo")
        if any(key == ing.plain(re.sub(r"\s+sale di \w+$", "", o, flags=re.I)).rstrip("eo") for o in out):
            continue
        out.append(part)
    return out


def load_catalog(directory, include_prescription=True):
    """Productos (lista de dicts) y un resumen de lo excluido."""
    excluded = collections.Counter()
    groups = {}
    for r in read_csv(os.path.join(directory, "confezioni_fornitura.csv")):
        if r["STATO_AMMINISTRATIVO"] != AUTHORIZED:
            excluded["no autorizado"] += 1
            continue
        if r["TIPO_PROCEDURA"] == HOMEOPATHIC:
            excluded["homeopático"] += 1
            continue
        if r["TIPO_PROCEDURA"] == PARALLEL_IMPORT:
            excluded["importación paralela"] += 1
            continue
        key = (r["COD_FARMACO"], r["FORMA"])
        g = groups.setdefault(key, {"row": r, "supplies": set(), "aics": []})
        g["supplies"].add(r["FORNITURA"])
        g["aics"].append(r["CODICE_AIC"])

    forms_of = collections.defaultdict(list)
    for cod, form in groups:
        forms_of[cod].append(form)

    catalog, wanted_aics = [], set()
    for (cod, form), g in groups.items():
        r = g["row"]
        supplies = g["supplies"]
        if not r["PA_ASSOCIATI"].strip():
            excluded["sin principio activo"] += 1
            continue
        if any(w in form.lower() for w in DIALYSIS_FORMS):
            excluded["diálisis o lavado"] += 1
            continue
        otc_supplies = {s for s in supplies if s.startswith(OTC_PREFIX)}
        if otc_supplies:
            # al menos un envase sin receta: se usa el régimen más libre (da banco antes que SOP)
            supply = min(otc_supplies, key=lambda s: "non da banco" in s.lower())
        else:
            supply = sorted(supplies)[0]
            if not include_prescription:
                continue
            if all(is_hospital_supply(s) for s in supplies):
                excluded["hospital"] += 1
                continue
            if is_parenteral(form):
                excluded["inyectable"] += 1
                continue
        needs_rx, category, note = supply_label(supply)
        ordinal = sorted(forms_of[cod]).index(form)
        name = f"{r['DENOMINAZIONE'].strip()} {clean_description(r['DESCRIZIONE'])}".strip()
        catalog.append({
            "ref": cod if len(forms_of[cod]) == 1 else f"{cod}-{ordinal + 1}",
            "brand_name": re.sub(r"\s+", " ", name),
            "form": form,
            "route": "",
            "description": r["DESCRIZIONE"],
            "substances": split_substances(r["PA_ASSOCIATI"]),
            "atc": r["CODICE_ATC"].strip(),
            "aics": g["aics"],
            "requires_prescription": needs_rx,
            "legal_category": category,
            "legal_note": note,
        })
        wanted_aics.update(g["aics"])

    # Nombres repetidos dentro del país: se distingue con el código AIFA del producto.
    seen = collections.Counter(p["brand_name"] for p in catalog)
    for p in catalog:
        if seen[p["brand_name"]] > 1:
            p["brand_name"] = f"{p['brand_name']} ({p['ref']})"

    # Cantidades por envase (PA_confezioni.csv)
    pa_path = os.path.join(directory, "PA_confezioni.csv")
    by_aic = collections.defaultdict(dict)
    if os.path.exists(pa_path):
        for r in read_csv(pa_path):
            if r["CODICE_AIC"] in wanted_aics:
                by_aic[r["CODICE_AIC"]][ing.plain(r["PRINCIPIO_ATTIVO"])] = (r["QUANTITA"], r["UNITA_MISURA"])
    for p in catalog:
        p["amounts"] = [by_aic[a] for a in p["aics"] if a in by_aic]
    return catalog, excluded


def product_strengths(item, names):
    """Dosis normalizada (JSON). Hay dos fuentes y se usan juntas:
      - las cantidades de PA_confezioni (muchas vacías), el resultado más frecuente entre los envases que
        traen todos los principios activos;
      - el texto del envase («200 MG COMPRESSE»), solo con UN principio activo (en una combinación no se
        sabe a qué principio corresponde cada cifra).
    Si las dos existen y no coinciden, no se da ninguna dosis: es mejor «no disponible» que un número dudoso."""
    form = ing.plain(item["form"])
    description = ing.plain(item.get("description", ""))
    solid = any(w in form for w in SOLID_UNIT_FORMS) or "bustin" in description
    options = collections.Counter()
    for amounts in item["amounts"]:
        rows = [amounts.get(ing.plain(s)) for s in item["substances"]]
        if any(row is None for row in rows):
            continue
        strengths = doses.it_strengths(rows, names, solid)
        if strengths:
            options[doses.dumps(strengths)] += 1
    from_amounts = json.loads(options.most_common(1)[0][0]) if options else []
    from_text = doses.it_description_strength(item.get("description", ""), names[0], solid) if len(names) == 1 else []
    if from_text and from_amounts:
        a, b = from_text[0], from_amounts[0]
        if len(from_amounts) == 1 and a["b"] == b["b"] and abs(a["v"] - b["v"]) <= 0.02 * max(a["v"], b["v"]):
            return doses.dumps(from_amounts)
        return doses.dumps([])
    return doses.dumps(from_text or from_amounts)


def debug_report(directory):
    catalog, excluded = load_catalog(directory)
    n_rx = sum(i["requires_prescription"] for i in catalog)
    print(f"datos del {data_date(directory)}: {len(catalog) - n_rx} sin receta y {n_rx} con receta. Excluidos: {dict(excluded)}")
    forms = collections.Counter(i["form"] for i in catalog)
    print(f"\nFormas distintas: {len(forms)}")
    for form, n in forms.most_common(150):
        print(f"  {n:5} {form}")


def to_product(item, links, es_index, form_map, es_forms, base_links=None):
    """Producto listo para sync_products. Sin enlace revisado ni forma conocida, el producto conserva
    su nombre y su forma en italiano y no se compara con nada."""
    name, reason, level = ing.resolve_levels(item["substances"], links, base_links or {}, es_index,
                                             parse=ing.parse_substance_it, country="IT")
    own_name = " + ".join(ing.plain(s) for s in item["substances"])
    target = importers.map_form(item["form"], item["route"], form_map)
    names = ing.component_names(item["substances"], links, base_links or {}, parse=ing.parse_substance_it, country="IT")
    return {
        "strengths": product_strengths(item, names),
        "audience": doses.audience_of(item["brand_name"]),
        "ref": item["ref"],
        "brand_name": item["brand_name"],
        "ingredient": name if level == ing.LEVEL_EXACT else own_name,
        "base_inn": name if level == ing.LEVEL_BASE else None,
        "link_level": level,
        "link_reason": reason,
        "form": es_forms.get(ing.plain(target), target) if target else item["form"],
        "form_mapped": target is not None,
        "native_form": item["form"],
        "route": item["route"],
        "composition": " + ".join(s.lower() for s in item["substances"]),
        "requires_prescription": item["requires_prescription"],
        "legal_category": item["legal_category"],
        "legal_note": item["legal_note"],
    }


def report(conn, products):
    """Resumen de qué se enlazó y qué no, y cuántas comparaciones salen con España, Francia y el Reino Unido."""
    total = max(len(products), 1)
    reasons = collections.Counter(p["link_reason"] for p in products)
    print("\nEnlace de principios activos:")
    for key, text in LINK_REASONS.items():
        print(f"  {reasons[key]:5} productos {text}")
    levels = collections.Counter(p["link_level"] for p in products)
    print(f"  de los enlazados: {levels[ing.LEVEL_EXACT]} de nivel exacto y {levels[ing.LEVEL_BASE]} de nivel base (otro éster)")
    mapped = sum(p["form_mapped"] for p in products)
    print(f"Forma traducida a la de CIMA: {mapped} de {len(products)} productos ({100 * mapped // total} %)")
    unmapped = collections.Counter(ing.plain(p["native_form"]) for p in products if not p["form_mapped"])
    print("Formas sin traducir más frecuentes:", unmapped.most_common(10))
    withdose = sum(1 for p in products if p["strengths"])
    print(f"Con dosis interpretada: {withdose} de {len(products)} ({100 * withdose // total} %)")

    it_groups = collections.Counter((p["ingredient"], p["form"]) for p in products)
    for code, label in (("ES", "España"), ("FR", "Francia"), ("UK", "Reino Unido")):
        groups = collections.Counter(
            conn.execute(
                "SELECT ai.inn_name, p.form FROM products p "
                "JOIN active_ingredients ai ON ai.id = p.active_ingredient_id WHERE p.country_code = ?",
                (code,),
            ).fetchall()
        )
        both = set(groups) & set(it_groups)
        print(
            f"Comparaciones {label}-Italia (mismo principio activo y misma forma): {len(both)} grupos, "
            f"{sum(groups[g] for g in both)} productos de {label} y {sum(it_groups[g] for g in both)} de Italia"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="carpeta con los CSV de la AIFA ya descargados; si falta, se descargan")
    ap.add_argument("--debug", action="store_true", help="analiza y muestra el informe, sin tocar medipass.db")
    ap.add_argument("--inspect", action="store_true", help="solo cuenta formas del catálogo")
    ap.add_argument("--only-otc", action="store_true", help="solo medicamentos sin receta")
    args = ap.parse_args()

    directory = args.dir or download(os.path.join(tempfile.gettempdir(), "aifa"))
    if args.inspect:
        return debug_report(directory)
    released = data_date(directory)
    catalog, excluded = load_catalog(directory, include_prescription=not args.only_otc)
    n_rx = sum(i["requires_prescription"] for i in catalog)
    print(f"AIFA, datos del {released}: {len(catalog) - n_rx} sin receta y {n_rx} con receta. Excluidos: {dict(excluded)}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    if not args.debug:
        importers.ensure_schema(conn)
    if not conn.execute("SELECT 1 FROM countries WHERE code = 'IT'").fetchone():
        sys.exit("Falta el país 'IT' en countries: ejecuta primero seed_base.sql")

    names, es_forms = importers.load_spanish_vocabulary(conn)
    if not es_forms:
        print("[aviso] No hay productos de España en la base: ejecuta fetch_cima.py antes, "
              "o casi nada se podrá enlazar.")
    es_index = ing.build_es_index(names)
    links, form_map = ing.load_links(ing.LINKS_PATH_IT), importers.load_form_map(FORM_MAP_PATH)
    base_links = ing.load_links(ing.LINKS_PATH_IT, level=ing.LEVEL_BASE)
    print(f"Tabla de enlaces: {len(links)} principios activos | tabla de formas: {len(form_map)} filas")

    products = [to_product(item, links, es_index, form_map, es_forms, base_links) for item in catalog]
    report(conn, products)

    if args.debug:
        conn.close()
        return

    stats = importers.sync_products(conn, products, "IT", SOURCE_NAME)
    print(
        f"\nSincronizado: {stats['inserted']} nuevos, {stats['updated']} actualizados, "
        f"{stats['deleted']} borrados, {stats['duplicates']} omitidos por nombre repetido, "
        f"{stats['placeholders_removed']} ejemplos manuales sustituidos por datos reales, "
        f"{stats['orphans_removed']} principios activos sin productos eliminados"
    )
    total = conn.execute("SELECT COUNT(*) FROM products WHERE country_code = 'IT'").fetchone()[0]
    print(f"Listo. Productos de Italia en la base: {total} (AIFA, {released})")
    conn.close()


if __name__ == "__main__":
    main()
