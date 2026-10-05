"""
importers.py
Piezas comunes a los importadores de países (fetch_bdpm.py para Francia,
fetch_dmd.py para el Reino Unido): tabla de formas, vocabulario español y
sincronización de la tabla products.

Cada importador convierte su fuente en una lista de productos (dicts) con estas
claves y llama a sync_products():
    ref          código del producto en la fuente (CIS en Francia, APID en el Reino Unido)
    brand_name   nombre comercial
    ingredient   nombre del principio activo (español si está enlazado)
    form         forma ya traducida a la de CIMA (o la original si no se pudo traducir)
    composition  composición tal como la publica la fuente
"""

import csv
import sqlite3
from datetime import date

import ingredients as ing

# Fuentes que NO son vocabulario español: sus nombres de principios activos se
# conservan en el idioma original cuando no hay enlace revisado.
IMPORTED_SOURCES = ("BDPM", "DMD")


def load_form_map(path):
    """[(forma en el idioma de origen, vía, forma CIMA)] desde un CSV con las columnas
    forma_xx, via_xx, forma_cima. Las dos primeras ya van sin tildes y en minúsculas;
    se comparan con ing.plain()."""
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        form_col, route_col = reader.fieldnames[0], reader.fieldnames[1]
        return [(r[form_col], r[route_col], r["forma_cima"]) for r in reader]


def map_form(form, route, form_map, exact_route=False):
    """Forma de CIMA para una forma de origen, o None si no está en la tabla.
    Hace falta que coincida la forma exacta Y que la vía contenga el texto de la
    fila (un gel "cutanée" no es un gel "ophtalmique").
    Con exact_route=True la vía debe ser IDENTICA a la de la fila: el Reino Unido
    puede dar varias vías juntas ("Oromucosal; Gingival; Nasal; ...") y un producto
    de varias vías no debe quedar clasificado por una sola de ellas."""
    f, r = ing.plain(form or ""), ing.plain(route or "")
    for source_form, via, cima_form in form_map:
        if f == source_form and (via == r if exact_route else via in r):
            return cima_form
    return None


def load_spanish_vocabulary(conn):
    """(nombres de principios activos canónicos, {forma sin tildes: forma exacta}).
    Los nombres son los de ingredientes que tienen algún producto que NO viene de
    un importador extranjero (CIMA y los ejemplos manuales de otros países)."""
    marks = ",".join("?" * len(IMPORTED_SOURCES))
    names = [
        r[0]
        for r in conn.execute(
            f"""
            SELECT DISTINCT ai.inn_name FROM active_ingredients ai
            JOIN products p ON p.active_ingredient_id = ai.id
            WHERE p.source NOT IN ({marks})
            """,
            IMPORTED_SOURCES,
        )
    ]
    forms = {
        ing.plain(r[0]): r[0]
        for r in conn.execute("SELECT DISTINCT form FROM products WHERE country_code = 'ES' AND form IS NOT NULL")
    }
    return names, forms


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


def sync_products(conn, products, country, source):
    stats = {"inserted": 0, "updated": 0, "deleted": 0, "duplicates": 0}
    today = date.today().isoformat()  # las licencias de las fuentes piden citar la fecha de los datos
    # (ingrediente, forma) para los que SÍ hay un producto real. Un ejemplo
    # manual solo se borra si hay un dato real de esa MISMA forma: si España
    # tiene "dimenhidrinato · comprimido" y el país solo trae "· jarabe", el
    # ejemplo manual del comprimido debe quedarse, porque nada real lo
    # sustituye todavía.
    superseded_forms = set()

    conn.execute("CREATE TEMP TABLE IF NOT EXISTS keep_refs (ref TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM keep_refs")
    conn.executemany("INSERT OR IGNORE INTO keep_refs VALUES (?)", [(p["ref"],) for p in products])

    stats["deleted"] = conn.execute(
        """
        DELETE FROM products
        WHERE country_code = ? AND source = ?
          AND (source_ref IS NULL OR source_ref NOT IN (SELECT ref FROM keep_refs))
        """,
        (country, source),
    ).rowcount

    for p in products:
        ingredient_id = get_or_create_ingredient(conn, p["ingredient"])
        superseded_forms.add((ingredient_id, p["form"]))

        existing = conn.execute(
            "SELECT id FROM products WHERE country_code = ? AND source = ? AND source_ref = ?",
            (country, source, p["ref"]),
        ).fetchone()
        try:
            if existing:
                conn.execute(
                    """
                    UPDATE products
                    SET active_ingredient_id = ?, brand_name = ?, form = ?, composition = ?,
                        verified_at = ?
                    WHERE id = ?
                    """,
                    (ingredient_id, p["brand_name"], p["form"], p["composition"], today, existing[0]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    """
                    INSERT INTO products
                        (active_ingredient_id, country_code, brand_name, requires_prescription,
                         source, source_ref, form, composition, verified_at)
                    VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)
                    """,
                    (ingredient_id, country, p["brand_name"], source, p["ref"], p["form"], p["composition"], today),
                )
                stats["inserted"] += 1
        except sqlite3.IntegrityError:
            # Mismo principio activo y mismo nombre con otro código: para el
            # usuario sería una fila idéntica, nos quedamos con la primera.
            stats["duplicates"] += 1
            if existing:  # y no dejamos una fila antigua a medias
                conn.execute("DELETE FROM products WHERE id = ?", (existing[0],))

    # Los ejemplos manuales (seed_manual_non_es.sql) se quitan cuando ya hay
    # datos reales de la misma forma; si el país no tiene esa forma, el ejemplo
    # se queda (mejor un dato marcado como sin verificar que ninguno).
    placeholders_removed = 0
    manual = conn.execute(
        "SELECT id, active_ingredient_id, form FROM products "
        "WHERE country_code = ? AND source = 'manual_seed'",
        (country,),
    ).fetchall()
    for row_id, ingredient_id, form in manual:
        if (ingredient_id, form) in superseded_forms:
            conn.execute("DELETE FROM products WHERE id = ?", (row_id,))
            placeholders_removed += 1

    # Al borrar productos pueden quedar principios activos sin ningún producto.
    # Solo se limpian los creados automáticamente por los importadores (sin
    # descripción ni ATC); los de seed_base.sql llevan descripción y no se tocan.
    stats["orphans_removed"] = conn.execute(
        """
        DELETE FROM active_ingredients
        WHERE common_use IS NULL AND atc_code IS NULL
          AND id NOT IN (SELECT DISTINCT active_ingredient_id FROM products)
        """
    ).rowcount

    conn.commit()
    stats["placeholders_removed"] = placeholders_removed
    return stats
