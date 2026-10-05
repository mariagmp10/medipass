"""
fetch_dmd.py
Carga en products (country_code = 'UK') el catálogo de medicamentos SIN RECETA del
Reino Unido a partir de NHS dm+d (NHSBSA dictionary of medicines and devices):
https://www.nhsbsa.nhs.uk/pharmacies-gp-practices-and-appliance-contractors/dictionary-medicines-and-devices-dmd

Fuente:   NHS TRUD, elemento 24 "NHSBSA dm+d" (ZIP con XML, se publica cada semana).
Licencia: Open Government Licence v3.0. Hay que citar la fuente:
          "Contains public sector information licensed under the Open Government Licence v3.0."
          La versión y la fecha de los datos quedan en README.md y en verified_at.
Descarga: hace falta una cuenta gratuita en TRUD y suscribirse al elemento 24. El ZIP
          se descarga a mano (--zip) o con la clave de API (TRUD_API_KEY en .env, nunca en git).

Diferencias importantes con CIMA y BDPM (léelas antes de tocar este archivo):

1. Estructura. Un producto "de marca" es un AMP; pertenece a un producto virtual (VMP) que
   tiene los ingredientes, la forma y la vía. Cada AMP tiene envases (AMPP) y es EL ENVASE
   quien lleva la categoría legal (LEGAL_CATCD): GSL (venta libre), P (solo en farmacia, sin
   receta) o POM (con receta).
2. SIN RECETA = el producto tiene al menos un envase activo con categoría P o GSL. Un producto
   puede tener envases P y POM según el tamaño (p. ej. 16 comprimidos P, 100 POM): se
   incluye si hay algún envase P/GSL. P (solo farmacia) cuenta como "sin receta", igual que en
   España. Los envases descatalogados (DISCCD = 0001) o inválidos (INVALID = 1) no cuentan.
3. Solo entran productos con licencia (MHRA/EMA o hierbas tradicionales) y disponibles sin
   restricción: se excluyen los importados sin licencia, los "Special" (preparados a medida)
   y los marcados como no disponibles.
4. Se excluyen los homeopáticos (la forma empieza por "Homeopathic"), igual que en Francia.
5. Los ingredientes vienen con la sal ("Benzydamine hydrochloride"). El campo BS_SUBID
   (sustancia base) NO se usa: a veces reduce un éster a su base (betamethasone valerate ->
   betamethasone, que no son equivalentes) o se equivoca del todo (ioversol -> iodine). El
   enlace con el nombre español usa nuestro parser conservador (ingredients.py) y
   ingredient_links_uk.csv, como en Francia.
6. Forma y vía son códigos del propio dm+d (una sola forma por producto, ya normalizada) y se
   traducen a la de CIMA con form_map_uk.csv.

Uso:
    python fetch_dmd.py --zip RUTA_AL_ZIP            # sincroniza el Reino Unido con un ZIP ya descargado
    python fetch_dmd.py                              # igual, descargando la última versión con TRUD_API_KEY
    python fetch_dmd.py --zip RUTA --debug           # analiza y muestra el informe, sin tocar medipass.db
    python fetch_dmd.py --zip RUTA --inspect         # solo cuenta formas y vías del ZIP

Ejecuta antes fetch_cima.py: el vocabulario español al que se enlaza sale de los productos de
España que ya estén en la base.
"""

import argparse
import collections
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

import importers
import ingredients as ing

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
FORM_MAP_PATH = os.path.join(HERE, "form_map_uk.csv")
TRUD_API = "https://isd.digital.nhs.uk/trud/api/v1"
DMD_ITEM = 24  # "NHSBSA dm+d" en TRUD
LINK_REASONS = {
    "enlazado": "enlazados con un principio activo español (comparables)",
    "sin_enlace": "sin enlace revisado: conservan su nombre en inglés",
    "no_interpretable": "con un nombre que no se interpreta (cifras, extractos, elementos...)",
    "combinacion_sin_equivalente": "combinación sin equivalente en España",
}

SOURCE_NAME = "NHS dm+d"
OTC_CATEGORIES = {"P", "GSL"}
LICENSED = {"Medicines - MHRA/EMA", "Traditional Herbal Medicines"}
DISCONTINUED = "0001"  # DISCONTINUED_IND: 0001 = Discontinued Flag, 0000 = Reinstated


def read_lookup(zf):
    """Devuelve {grupo: {codigo: descripcion}} a partir del archivo f_lookup*.xml."""
    name = next(n for n in zf.namelist() if re.match(r"f_lookup\d*_.*\.xml$", n))
    lookup = {}
    root = ET.fromstring(zf.read(name))
    for group in root:
        entries = {}
        for info in group.findall("INFO"):
            code, desc = info.findtext("CD"), info.findtext("DESC")
            if code is not None:
                entries[code.strip()] = (desc or "").strip()
        lookup[group.tag] = entries
    return lookup


def iter_records(zf, prefix, tag):
    """Recorre un archivo XML grande registro a registro (sin cargarlo entero en memoria)."""
    name = next(n for n in zf.namelist() if re.match(rf"f_{prefix}\d*_.*\.xml$", n))
    with zf.open(name) as fh:
        for _event, el in ET.iterparse(fh, events=("end",)):
            if el.tag == tag:
                yield {child.tag: (child.text or "").strip() for child in el}
                el.clear()


def release_info(zip_path):
    """Versión y fecha del ZIP, p. ej. ('9.3.0', '2026-09-28'), a partir del nombre del archivo."""
    m = re.search(r"dmd_(\d+\.\d+\.\d+)_(\d{4})(\d{2})(\d{2})", zip_path)
    return (m.group(1), f"{m.group(2)}-{m.group(3)}-{m.group(4)}") if m else (None, None)


def load_catalog(zip_path):
    """Productos de marca sin receta (lista de dicts) y un resumen de lo excluido."""
    zf = zipfile.ZipFile(zip_path)
    lookup = read_lookup(zf)
    legal = lookup["LEGAL_CATEGORY"]

    # 1) Categorías legales de los envases activos de cada producto.
    categories = collections.defaultdict(set)
    for r in iter_records(zf, "ampp", "AMPP"):
        if r.get("INVALID") == "1" or r.get("DISCCD") == DISCONTINUED:
            continue
        categories[r["APID"]].add(legal.get(r["LEGAL_CATCD"]))
    otc = {apid for apid, cats in categories.items() if cats & OTC_CATEGORIES}

    # 2) Productos de marca: con licencia, disponibles y válidos.
    excluded = collections.Counter()
    amps = {}
    for r in iter_records(zf, "amp", "AMP"):
        if r["APID"] not in otc:
            continue
        if r.get("INVALID") == "1":
            excluded["inválido"] += 1
        elif lookup["LICENSING_AUTHORITY"].get(r["LIC_AUTHCD"]) not in LICENSED:
            excluded["sin licencia"] += 1
        elif lookup["AVAILABILITY_RESTRICTION"].get(r["AVAIL_RESTRICTCD"]) != "None":
            excluded["importado, especial o no disponible"] += 1
        else:
            amps[r["APID"]] = r
    vpids = {r["VPID"] for r in amps.values()}

    # 3) Forma, vía e ingredientes del producto virtual.
    forms, routes, substances = {}, collections.defaultdict(list), collections.defaultdict(list)
    for r in iter_records(zf, "vmp", "DFORM"):
        if r["VPID"] in vpids:
            forms[r["VPID"]] = lookup["FORM"].get(r["FORMCD"], "")
    for r in iter_records(zf, "vmp", "DROUTE"):
        if r["VPID"] in vpids:
            routes[r["VPID"]].append(lookup["ROUTE"].get(r["ROUTECD"], ""))
    names = {r["ISID"]: r["NM"] for r in iter_records(zf, "ingredient", "ING")}
    for r in iter_records(zf, "vmp", "VPI"):
        if r["VPID"] in vpids:
            n = names.get(r["ISID"])
            if n and n not in substances[r["VPID"]]:
                substances[r["VPID"]].append(n)

    catalog = []
    for apid, r in amps.items():
        vpid = r["VPID"]
        form = forms.get(vpid, "")
        if form.lower().startswith("homeopathic"):
            excluded["homeopático"] += 1
        elif not substances.get(vpid):
            excluded["sin ingredientes"] += 1
        else:
            catalog.append(
                {
                    "ref": apid,
                    "brand_name": r["NM"],
                    "form": form,
                    # Si hay varias vías las guardamos todas: map_form pide que la vía de la
                    # tabla esté contenida en este texto.
                    "route": "; ".join(routes[vpid]),
                    "substances": substances[vpid],
                    "mixed_legal": "POM" in categories[apid],
                }
            )
    return catalog, excluded


def debug_report(zip_path):
    version, released = release_info(zip_path)
    print(f"dm+d versión {version}, publicada el {released}")
    catalog, excluded = load_catalog(zip_path)
    print(f"\nProductos sin receta (P/GSL) candidatos: {len(catalog)}")
    print("Excluidos:", dict(excluded))
    print(f"  de los cuales con algún envase POM además: {sum(p['mixed_legal'] for p in catalog)}")
    pairs = collections.Counter((p["form"], p["route"]) for p in catalog)
    print(f"\nFormas distintas: {len(pairs)} (forma + vía)")
    for (form, route), n in pairs.most_common(120):
        print(f"  {n:4} {form} | {route}")
    ingredients = collections.Counter(s for p in catalog for s in p["substances"])
    print(f"\nIngredientes distintos: {len(ingredients)}")


def to_product(item, links, es_index, form_map, es_forms):
    """Producto listo para sync_products. Sin enlace revisado ni forma conocida, el
    producto conserva su nombre y su forma en inglés y no se compara con nada."""
    name, reason = ing.resolve(item["substances"], links, es_index, parse=ing.parse_substance_en)
    target = importers.map_form(item["form"], item["route"], form_map, exact_route=True)
    return {
        "ref": item["ref"],
        "brand_name": item["brand_name"],
        "ingredient": name or " + ".join(s.lower() for s in item["substances"]),
        "link_reason": reason,
        # La forma de destino se escribe como ya está en España (con o sin tildes).
        "form": es_forms.get(ing.plain(target), target) if target else item["form"],
        "form_mapped": target is not None,
        "native_form": item["form"],
        "route": item["route"],
        "composition": " + ".join(s.lower() for s in item["substances"]),
    }


def download_latest(api_key):
    """Descarga la última versión del elemento 24 con la clave de API de TRUD y comprueba
    su suma SHA-256. Devuelve la ruta del ZIP. La clave se lee de TRUD_API_KEY o de .env."""
    meta_url = f"{TRUD_API}/keys/{api_key}/items/{DMD_ITEM}/releases?latest"
    with urllib.request.urlopen(meta_url, timeout=60) as response:
        releases = json.load(response).get("releases") or []
    if not releases:
        sys.exit("TRUD no devuelve ninguna versión: ¿estás suscrita al elemento 24 «NHSBSA dm+d»?")
    release = releases[0]
    target = os.path.join(tempfile.gettempdir(), release["archiveFileName"])
    print(f"Descargando {release['archiveFileName']} ({release['archiveFileSizeBytes'] / 1e6:.1f} MB)...")
    urllib.request.urlretrieve(release["archiveFileUrl"], target)
    digest = hashlib.sha256(open(target, "rb").read()).hexdigest().upper()
    if digest != release["archiveFileSha256"].upper():
        os.remove(target)
        sys.exit("La suma SHA-256 del ZIP no coincide con la que publica TRUD: descarga descartada.")
    return target


def api_key_from_env():
    key = os.environ.get("TRUD_API_KEY")
    env_file = os.path.join(HERE, ".env")
    if not key and os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("TRUD_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    return key


def report(conn, products):
    """Resumen de qué se enlazó y qué no, y cuántas comparaciones salen con España y Francia."""
    total = max(len(products), 1)
    reasons = collections.Counter(p["link_reason"] for p in products)
    print("\nEnlace de principios activos:")
    for key, text in LINK_REASONS.items():
        print(f"  {reasons[key]:5} productos {text}")
    mapped = sum(p["form_mapped"] for p in products)
    print(f"Forma traducida a la de CIMA: {mapped} de {len(products)} productos ({100 * mapped // total} %)")
    unmapped = collections.Counter((ing.plain(p["native_form"]), ing.plain(p["route"])) for p in products if not p["form_mapped"])
    print("Formas sin traducir más frecuentes:", [(f, r, n) for (f, r), n in unmapped.most_common(8)])

    uk_groups = collections.Counter((p["ingredient"], p["form"]) for p in products)
    for code, label in (("ES", "España"), ("FR", "Francia")):
        groups = collections.Counter(
            conn.execute(
                "SELECT ai.inn_name, p.form FROM products p "
                "JOIN active_ingredients ai ON ai.id = p.active_ingredient_id WHERE p.country_code = ?",
                (code,),
            ).fetchall()
        )
        both = set(groups) & set(uk_groups)
        print(
            f"Comparaciones {label}-Reino Unido (mismo principio activo y misma forma): {len(both)} grupos, "
            f"{sum(groups[g] for g in both)} productos de {label} y {sum(uk_groups[g] for g in both)} del Reino Unido"
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="ZIP ya descargado de NHS TRUD (nhsbsa_dmd_*.zip); si falta, se descarga con la clave de API")
    ap.add_argument("--debug", action="store_true", help="analiza y muestra el informe, sin tocar medipass.db")
    ap.add_argument("--inspect", action="store_true", help="solo cuenta formas y vías del ZIP")
    args = ap.parse_args()

    zip_path = args.zip
    if not zip_path:
        key = api_key_from_env()
        if not key:
            sys.exit("Falta --zip RUTA o la clave de API (variable TRUD_API_KEY o archivo .env)")
        zip_path = download_latest(key)
    if args.inspect:
        return debug_report(zip_path)

    version, released = release_info(zip_path)
    print(f"dm+d versión {version}, publicada el {released}")
    catalog, excluded = load_catalog(zip_path)
    print(f"Sin receta (P/GSL): {len(catalog)} productos. Excluidos: {dict(excluded)}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    if not conn.execute("SELECT 1 FROM countries WHERE code = 'UK'").fetchone():
        sys.exit("Falta el país 'UK' en countries: ejecuta primero seed_base.sql")

    names, es_forms = importers.load_spanish_vocabulary(conn)
    if not es_forms:
        print("[aviso] No hay productos de España en la base: ejecuta fetch_cima.py antes, "
              "o casi nada se podrá enlazar.")
    es_index = ing.build_es_index(names)
    links, form_map = ing.load_links(ing.LINKS_PATH_UK), importers.load_form_map(FORM_MAP_PATH)
    print(f"Tabla de enlaces: {len(links)} principios activos | tabla de formas: {len(form_map)} filas")

    products = [to_product(item, links, es_index, form_map, es_forms) for item in catalog]
    report(conn, products)

    if args.debug:
        conn.close()
        return

    stats = importers.sync_products(conn, products, "UK", "DMD")
    print(
        f"\nSincronizado: {stats['inserted']} nuevos, {stats['updated']} actualizados, "
        f"{stats['deleted']} borrados, {stats['duplicates']} omitidos por nombre repetido, "
        f"{stats['placeholders_removed']} ejemplos manuales sustituidos por datos reales, "
        f"{stats['orphans_removed']} principios activos sin productos eliminados"
    )
    total = conn.execute("SELECT COUNT(*) FROM products WHERE country_code = 'UK'").fetchone()[0]
    print(f"Listo. Productos del Reino Unido en la base: {total} (dm+d {version}, {released})")
    conn.close()


if __name__ == "__main__":
    main()
