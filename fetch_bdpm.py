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
Ese aviso está en el README.

Diferencias importantes con CIMA (léelas antes de tocar este archivo):

1. Codificación: los archivos vienen en Windows-1252 (cp1252), no UTF-8.
2. No hay un campo booleano "sin receta". Un medicamento se considera SIN
   RECETA si está comercializado y su código CIS NO aparece en
   CIS_CPD_bdpm.txt (el archivo de condiciones de prescripción). Lo
   verificamos con un caso real: "DOLIPRANE" (paracetamol solo) no aparece
   ahí; "CODOLIPRANE" (paracetamol + codeína) sí aparece.
3. No hay un "principio activo" ya armado (el 'vtm' de CIMA): lo construimos
   juntando las sustancias activas (nature = 'SA') de CIS_COMPO_bdpm.txt.
4. La forma farmacéutica es texto libre en francés, no una categoría fija
   como en CIMA. Solo la traducimos al vocabulario de CIMA para los 4
   principios activos que ya existen en España (ver FORM_RULES) — el resto
   de principios activos de Francia se guardan con su forma en francés tal
   cual, sin intentar adivinar una traducción.
5. No hay foto ni código ATC en estos archivos (si algún día se necesitan,
   habría que buscarlos en otro archivo de la BDPM o en otra fuente).
6. Se excluyen los medicamentos homeopáticos: sus datos vienen sucios (el
   campo de forma mezcla varias formas en un solo texto) y no son
   clínicamente comparables con el resto del catálogo.

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

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
BDPM_BASE = "https://base-donnees-publique.medicaments.gouv.fr/download/file"
FILES = ("CIS_bdpm.txt", "CIS_COMPO_bdpm.txt", "CIS_CPD_bdpm.txt")

HOMEOPATHIC_PROCEDURE = "enreg homeo (proc. nat.)"  # ya sin tildes: se compara con norm(), que las quita

# Principios activos que ya existen en España (seed_base.sql). "needle" es el
# texto que buscamos (sin tildes, en minúsculas) dentro del nombre de
# sustancia francés, que suele venir con la sal química pegada (ej.
# "CHLORHEXIDINE (GLUCONATE DE)"), por eso es "contiene", no "es igual a".
INGREDIENT_MAP = {
    "diclofenac": "diclofenaco",
    "dimenhydrinate": "dimenhidrinato",
    "chlorhexidine": "clorhexidina",
    "docusate": "docusato sódico",
}

# Traducción de forma francesa -> vocabulario de CIMA, SOLO para los 4
# principios activos de arriba (para que sus grupos crucen con España). Se
# aplica en orden; la primera regla que coincide gana. "route" se compara
# contra la primera vía de administración que da BDPM.
# OJO: estas palabras clave van SIN TILDES a propósito — se comparan contra
# texto ya normalizado (norm() les quita las tildes), así que si el texto de
# aquí las tuviera, nunca coincidiría (ya me pasó una vez: ver commit).
FORM_RULES = [
    ("diclofenac", None, "gel", "GEL"),
    ("diclofenac", None, "pulveris", "LIQUIDO USO TOPICO"),
    ("diclofenac", None, "emplatre", "APOSITO"),
    ("dimenhydrinate", None, "comprime", "COMPRIMIDO"),
    ("dimenhydrinate", None, "sirop", "SOLUCION/SUSPENSION ORAL"),
    ("dimenhydrinate", None, "gelule", "CAPSULA"),
    # La clorhexidina de garganta/boca francesa (colutorios, pastillas) NO es
    # comparable con los antisépticos de piel de España: solo traducimos la
    # forma cuando la vía es cutánea. El resto queda en francés a propósito.
    ("chlorhexidine", "cutanee", None, "LIQUIDO USO TOPICO"),
]


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


def canonical_ingredient(substance_names):
    """Si el producto es de un solo principio activo y coincide con uno de los
    que ya tenemos en España, devuelve su nombre canónico (en español). Si
    no, arma un nombre a partir de las sustancias francesas (en minúsculas,
    igual que hacemos con las combinaciones de CIMA)."""
    if len(substance_names) == 1:
        normalized = norm(substance_names[0])
        for needle, canonical in INGREDIENT_MAP.items():
            if needle in normalized:
                return canonical, needle
    return " + ".join(s.lower() for s in substance_names), None


def canonical_form(matched_needle, route, raw_form):
    if not matched_needle:
        return raw_form
    route_norm = norm(route or "")
    form_norm = norm(raw_form or "")
    for needle, route_needle, form_needle, cima_form in FORM_RULES:
        if needle != matched_needle:
            continue
        if route_needle and route_needle not in route_norm:
            continue
        if form_needle and form_needle not in form_norm:
            continue
        return cima_form
    return raw_form  # no hay regla para esta combinación: se queda en francés


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
        if norm(procedure) == HOMEOPATHIC_PROCEDURE:
            skipped_homeo += 1
            continue
        substances = substances_by_cis.get(cis)
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


def to_product(item):
    ingredient, matched_needle = canonical_ingredient(item["substances"])
    return {
        "cis": item["cis"],
        "brand_name": item["brand_name"],
        "ingredient": ingredient,
        "canonical_match": matched_needle is not None,
        "form": canonical_form(matched_needle, item["route"], item["form"]),
        "composition": " + ".join(s.lower() for s in item["substances"]),
    }


def get_or_create_ingredient(conn, name):
    row = conn.execute(
        "SELECT id FROM active_ingredients WHERE inn_name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO active_ingredients (inn_name, category) VALUES (?, 'Salud')", (name,)
    )
    return cur.lastrowid


def sync_products(conn, products):
    stats = {"inserted": 0, "updated": 0, "deleted": 0, "duplicates": 0}
    # (ingrediente, forma) para los que SÍ hay un producto real de esa forma
    # exacta. No basta con que el principio activo coincida: si España tiene
    # "dimenhidrinato · comprimido" y Francia solo trae "· jarabe", el
    # ejemplo manual del comprimido francés debe quedarse, porque nada real
    # lo sustituye todavía.
    superseded_forms = set()

    conn.execute("CREATE TEMP TABLE IF NOT EXISTS keep_fr (ref TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM keep_fr")
    conn.executemany("INSERT OR IGNORE INTO keep_fr VALUES (?)", [(p["cis"],) for p in products])

    stats["deleted"] = conn.execute(
        """
        DELETE FROM products
        WHERE country_code = 'FR' AND source = 'BDPM'
          AND (source_ref IS NULL OR source_ref NOT IN (SELECT ref FROM keep_fr))
        """
    ).rowcount

    for p in products:
        ingredient_id = get_or_create_ingredient(conn, p["ingredient"])
        if p["canonical_match"]:
            superseded_forms.add((ingredient_id, p["form"]))

        existing = conn.execute(
            "SELECT id FROM products WHERE country_code = 'FR' AND source = 'BDPM' AND source_ref = ?",
            (p["cis"],),
        ).fetchone()
        try:
            if existing:
                conn.execute(
                    """
                    UPDATE products
                    SET active_ingredient_id = ?, brand_name = ?, form = ?, composition = ?
                    WHERE id = ?
                    """,
                    (ingredient_id, p["brand_name"], p["form"], p["composition"], existing[0]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    """
                    INSERT INTO products
                        (active_ingredient_id, country_code, brand_name, requires_prescription,
                         source, source_ref, form, composition)
                    VALUES (?, 'FR', ?, 0, 'BDPM', ?, ?, ?)
                    """,
                    (ingredient_id, p["brand_name"], p["cis"], p["form"], p["composition"]),
                )
                stats["inserted"] += 1
        except sqlite3.IntegrityError:
            # Mismo principio activo y mismo nombre con otro código CIS: para
            # el usuario sería una fila idéntica, nos quedamos con la primera.
            stats["duplicates"] += 1

    # Los 4 principios activos ya tenían ejemplos manuales sin verificar para
    # Francia (seed_manual_non_es.sql). Ahora que hay datos reales de la
    # MISMA forma, quitamos esos placeholders para que no convivan un dato
    # real y uno inventado. Si Francia no tiene esa forma todavía, el
    # ejemplo manual se queda (mejor un dato marcado como sin verificar que
    # ningún dato).
    placeholders_removed = 0
    manual_fr = conn.execute(
        "SELECT id, active_ingredient_id, form FROM products "
        "WHERE country_code = 'FR' AND source = 'manual_seed'"
    ).fetchall()
    for row_id, ingredient_id, form in manual_fr:
        if (ingredient_id, form) in superseded_forms:
            conn.execute("DELETE FROM products WHERE id = ?", (row_id,))
            placeholders_removed += 1

    conn.commit()
    stats["placeholders_removed"] = placeholders_removed
    return stats


def main():
    debug = "--debug" in sys.argv
    catalog = load_catalog()
    products = [to_product(item) for item in catalog]

    if debug:
        print("\n--- 5 productos de ejemplo (sin tocar medipass.db) ---")
        for p in products[:5]:
            print(" ", p)
        matched = sum(1 for p in products if p["canonical_match"])
        print(f"\n{matched} productos coinciden con un principio activo ya existente en España")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    if not conn.execute("SELECT 1 FROM countries WHERE code = 'FR'").fetchone():
        sys.exit("Falta el país 'FR' en countries: ejecuta primero seed_base.sql")

    stats = sync_products(conn, products)
    print(
        f"Sincronizado: {stats['inserted']} nuevos, {stats['updated']} actualizados, "
        f"{stats['deleted']} borrados, {stats['duplicates']} omitidos por nombre repetido, "
        f"{stats['placeholders_removed']} ejemplos manuales sustituidos por datos reales"
    )
    total = conn.execute("SELECT COUNT(*) FROM products WHERE country_code = 'FR'").fetchone()[0]
    print(f"Listo. Productos de Francia en la base: {total}")
    conn.close()


if __name__ == "__main__":
    main()
