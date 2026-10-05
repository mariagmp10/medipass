"""
fetch_bdpm.py
Carga en products (country_code = 'FR') el catálogo de la Base de Données
Publique des Médicaments (BDPM), la fuente oficial de Francia (ANSM/DINUM):
https://base-donnees-publique.medicaments.gouv.fr/

No requiere API key ni login: son 3 archivos de texto para descargar. A
diferencia de CIMA, no es una API en vivo, así que este script descarga los
archivos completos en cada ejecución.

Licencia: los datos son de libre reutilización, pero hay que citar la fuente
y la fecha de actualización, y no se pueden alterar (ver
https://base-donnees-publique.medicaments.gouv.fr/docs/telechargement/licence_bdpm.pdf).
Ese aviso está en el README, y la fecha de la descarga queda en la columna
verified_at de cada producto.

Diferencias importantes con CIMA (léelas antes de tocar este archivo):

1. Codificación: los archivos vienen en Windows-1252 (cp1252), no UTF-8.
2. No hay un campo booleano "sin receta". Un medicamento se considera SIN
   RECETA si está comercializado y su código CIS NO aparece en
   CIS_CPD_bdpm.txt (el archivo de condiciones de prescripción). Lo
   verificamos con un caso real: "DOLIPRANE" (paracetamol solo) no aparece
   ahí; "CODOLIPRANE" (paracetamol + codeína) sí aparece.
3. No hay un "principio activo" ya armado (el 'vtm' de CIMA): se arma con las
   sustancias activas (nature = 'SA') de CIS_COMPO_bdpm.txt y se enlaza con el
   nombre español usando ingredient_links.csv (ver ingredients.py). Solo se
   usan enlaces revisados; si no hay enlace, el producto conserva su nombre
   francés y no se compara con nada.
4. La forma farmacéutica es texto libre en francés: se traduce a la de CIMA
   con form_map_fr.csv, que exige además una vía de administración compatible
   y cita cómo clasifica CIMA esa forma. Lo que no está en la tabla se guarda
   con su forma en francés y no se compara. La forma de destino se escribe
   siempre con el valor EXACTO que ya hay en España (CIMA a veces la escribe
   con tildes, SOLUCIÓN/SUSPENSIÓN ORAL, y a veces sin ellas).
5. No hay foto ni código ATC en estos archivos (si algún día se necesitan,
   habría que buscarlos en otro archivo de la BDPM o en otra fuente).
6. Se excluyen los medicamentos homeopáticos: sus datos vienen sucios (el
   campo de forma mezcla varias formas en un solo texto) y no son
   clínicamente comparables con el resto del catálogo. Hacen falta DOS
   señales para detectarlos (con una sola se colaban 132 productos):
   la etiqueta de procedimiento "Enreg homéo" (1.318 productos) y que el
   nombre de la sustancia diga "pour préparations homéopathiques" (132 más
   que están registrados como procedimiento nacional normal).

Ejecuta antes fetch_cima.py: el vocabulario español al que se enlaza sale de
los productos de España que ya estén en la base.

Uso:
    pip install requests
    python fetch_bdpm.py           # sincroniza Francia
    python fetch_bdpm.py --debug   # descarga y analiza, sin tocar medipass.db
"""

import collections
import os
import sqlite3
import sys
import unicodedata

import requests

import importers
import ingredients as ing
from importers import load_spanish_vocabulary, map_form  # noqa: F401  (se reexportan: las usan las pruebas)

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
BDPM_BASE = "https://base-donnees-publique.medicaments.gouv.fr/download/file"
FILES = ("CIS_bdpm.txt", "CIS_COMPO_bdpm.txt", "CIS_CPD_bdpm.txt")
FORM_MAP_PATH = os.path.join(HERE, "form_map_fr.csv")

# Ambas constantes van ya sin tildes: se comparan con norm(), que las quita.
HOMEOPATHIC_PROCEDURE = "enreg homeo (proc. nat.)"
HOMEOPATHIC_MARKER = "homeopathique"  # dentro del nombre de la sustancia activa

LINK_REASONS = {
    "enlazado": "enlazados con un principio activo español",
    "sin_enlace": "sin enlace en la tabla (se quedan con su nombre francés)",
    "no_interpretable": "nombre que no se interpreta con seguridad",
    "combinacion_sin_equivalente": "combinación sin equivalente español",
}


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text):
    return strip_accents(text.lower()).strip()


def download(fname):
    resp = requests.get(f"{BDPM_BASE}/{fname}", timeout=60)
    resp.raise_for_status()
    return resp.content.decode("cp1252")


def parse_rows(text):
    return [line.split("\t") for line in text.splitlines() if line.strip()]



def load_form_map(path=FORM_MAP_PATH):
    return importers.load_form_map(path)




def load_catalog():
    print("Descargando BDPM (CIS, composición, condiciones de prescripción)...")
    cis_rows = parse_rows(download("CIS_bdpm.txt"))
    compo_rows = parse_rows(download("CIS_COMPO_bdpm.txt"))
    cpd_rows = parse_rows(download("CIS_CPD_bdpm.txt"))
    print(f"Descargado: {len(cis_rows)} especialidades, {len(compo_rows)} filas de composición, "
          f"{len(cpd_rows)} condiciones de prescripción")

    restricted_cis = {r[0] for r in cpd_rows}

    substances_by_cis = collections.defaultdict(list)
    for r in compo_rows:
        if len(r) >= 7 and r[6] == "SA":  # SA = sustancia activa; ST = fracción terapéutica, se ignora
            substances_by_cis[r[0]].append(r[3])

    catalog = []
    skipped_homeo = 0
    for r in cis_rows:
        if len(r) < 12:
            continue
        cis, name, form, routes, _amm_status, procedure, market_status = r[0:7]
        if market_status != "Commercialisée" or cis in restricted_cis:
            continue
        substances = substances_by_cis.get(cis)
        if norm(procedure) == HOMEOPATHIC_PROCEDURE or (
            substances and any(HOMEOPATHIC_MARKER in norm(s) for s in substances)
        ):
            skipped_homeo += 1
            continue
        if not substances:
            continue
        catalog.append(
            {
                "cis": cis,
                "brand_name": name.strip(),
                "form": form.strip(),
                "route": routes.split(";")[0].strip() if routes else "",
                "substances": substances,
            }
        )
    print(f"Comercializados sin receta: {len(catalog)} (excluidos {skipped_homeo} homeopáticos)")
    return catalog


def to_product(item, links, es_index, form_map, es_forms):
    name, reason = ing.resolve(item["substances"], links, es_index)
    target = map_form(item["form"], item["route"], form_map)
    return {
        "ref": item["cis"],
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




def report(conn, products):
    """Resumen de qué se enlazó y qué no, y cuántas comparaciones con España salen."""
    total = max(len(products), 1)
    reasons = collections.Counter(p["link_reason"] for p in products)
    print("\nEnlace de principios activos:")
    for key, text in LINK_REASONS.items():
        print(f"  {reasons[key]:5} productos {text}")
    mapped = sum(p["form_mapped"] for p in products)
    print(f"Forma traducida a la de CIMA: {mapped} de {len(products)} productos ({100 * mapped // total} %)")
    unmapped = collections.Counter((norm(p["native_form"]), norm(p["route"])) for p in products if not p["form_mapped"])
    print("Formas sin traducir más frecuentes:", [(f, r, n) for (f, r), n in unmapped.most_common(8)])

    es_groups = collections.Counter(
        conn.execute(
            "SELECT ai.inn_name, p.form FROM products p "
            "JOIN active_ingredients ai ON ai.id = p.active_ingredient_id WHERE p.country_code = 'ES'"
        ).fetchall()
    )
    fr_groups = collections.Counter((p["ingredient"], p["form"]) for p in products)
    both = set(es_groups) & set(fr_groups)
    print(
        f"Comparaciones España-Francia (mismo principio activo y misma forma): {len(both)} grupos, "
        f"{sum(es_groups[g] for g in both)} productos de España y {sum(fr_groups[g] for g in both)} de Francia"
    )


def main():
    debug = "--debug" in sys.argv
    catalog = load_catalog()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    if not conn.execute("SELECT 1 FROM countries WHERE code = 'FR'").fetchone():
        sys.exit("Falta el país 'FR' en countries: ejecuta primero seed_base.sql")

    names, es_forms = load_spanish_vocabulary(conn)
    if not es_forms:
        print("[aviso] No hay productos de España en la base: ejecuta fetch_cima.py antes, "
              "o casi nada se podrá enlazar.")
    es_index = ing.build_es_index(names)
    links, form_map = ing.load_links(), load_form_map()
    print(f"Tabla de enlaces: {len(links)} principios activos | tabla de formas: {len(form_map)} filas")

    products = [to_product(item, links, es_index, form_map, es_forms) for item in catalog]
    report(conn, products)

    if debug:
        conn.close()
        return

    stats = importers.sync_products(conn, products, "FR", "BDPM")
    print(
        f"\nSincronizado: {stats['inserted']} nuevos, {stats['updated']} actualizados, "
        f"{stats['deleted']} borrados, {stats['duplicates']} omitidos por nombre repetido, "
        f"{stats['placeholders_removed']} ejemplos manuales sustituidos por datos reales, "
        f"{stats['orphans_removed']} principios activos sin productos eliminados"
    )
    total = conn.execute("SELECT COUNT(*) FROM products WHERE country_code = 'FR'").fetchone()[0]
    print(f"Listo. Productos de Francia en la base: {total}")
    conn.close()


if __name__ == "__main__":
    main()
