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
    requires_prescription  0 (libre o solo farmacia) o 1 (con receta)
    legal_category         'libre' | 'solo_farmacia' | 'receta'
    legal_note             etiqueta original del país (GSL, P, POM, "Liste I"...)
    base_inn               (opcional) nombre español de la BASE si `ingredient` es un éster/profármaco
    strengths, audience    (opcionales) dosis normalizada en JSON y público 'child'/'adult' (ver doses.py)
"""

import csv
import os
import sqlite3
from datetime import date

import ingredients as ing

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "schema.sql")

# Columnas añadidas a products después de la primera versión del esquema.
NEW_PRODUCT_COLUMNS = {
    "form": "TEXT", "dose": "TEXT", "composition": "TEXT", "atc_code": "TEXT", "atc_group": "TEXT",
    "photo_url": "TEXT", "legal_category": "TEXT", "legal_note": "TEXT", "strengths": "TEXT", "audience": "TEXT",
}

LEGAL_FREE, LEGAL_PHARMACY, LEGAL_RX = "libre", "solo_farmacia", "receta"

# Fuentes que NO son vocabulario español: sus nombres de principios activos se
# conservan en el idioma original cuando no hay enlace revisado.
IMPORTED_SOURCES = ("BDPM", "DMD")


def ensure_schema(conn):
    """Añade las columnas nuevas a una base antigua, rellena el estatus legal de las filas
    que aún no lo tienen y recrea la vista (schema.sql)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    for column, column_type in NEW_PRODUCT_COLUMNS.items():
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE products ADD COLUMN {column} {column_type}")
    ingredient_cols = {row[1] for row in conn.execute("PRAGMA table_info(active_ingredients)")}
    if ingredient_cols and "base_inn" not in ingredient_cols:
        conn.execute("ALTER TABLE active_ingredients ADD COLUMN base_inn TEXT")
    conn.commit()
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        conn.executescript(fh.read())
    # Filas anteriores a esta versión (todas eran sin receta o ejemplos manuales).
    conn.execute(
        "UPDATE products SET legal_category = CASE requires_prescription WHEN 0 THEN ? WHEN 1 THEN ? END "
        "WHERE legal_category IS NULL AND requires_prescription IS NOT NULL",
        (LEGAL_FREE, LEGAL_RX),
    )
    conn.commit()


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


def get_or_create_ingredient(conn, name, base=None):
    """Id del principio activo `name`, creándolo si no existe. `base` es su principio activo BASE si
    es un éster/profármaco ('fluticasona' para 'fluticasone propionate'), o None."""
    row = conn.execute(
        "SELECT id, base_inn FROM active_ingredients WHERE inn_name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        if row[1] != base:
            conn.execute("UPDATE active_ingredients SET base_inn = ? WHERE id = ?", (base, row[0]))
        return row[0]
    cur = conn.execute(
        "INSERT INTO active_ingredients (inn_name, category, base_inn) VALUES (?, 'Salud', ?)", (name, base)
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
    superseded_forms = set()  # (ingrediente, forma) con un producto real SIN receta

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
        ingredient_id = get_or_create_ingredient(conn, p["ingredient"], p.get("base_inn"))
        rx = int(p.get("requires_prescription", 0))
        category = p.get("legal_category") or (LEGAL_RX if rx else LEGAL_FREE)
        note = p.get("legal_note")
        if not rx:
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
                        requires_prescription = ?, legal_category = ?, legal_note = ?, strengths = ?, audience = ?,
                        verified_at = ?
                    WHERE id = ?
                    """,
                    (ingredient_id, p["brand_name"], p["form"], p["composition"], rx, category, note,
                     p.get("strengths"), p.get("audience"), today, existing[0]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    """
                    INSERT INTO products
                        (active_ingredient_id, country_code, brand_name, requires_prescription,
                         legal_category, legal_note, source, source_ref, form, composition, strengths, audience,
                         verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ingredient_id, country, p["brand_name"], rx, category, note, source, p["ref"], p["form"],
                     p["composition"], p.get("strengths"), p.get("audience"), today),
                )
                stats["inserted"] += 1
        except sqlite3.IntegrityError:
            # Mismo principio activo y mismo nombre con otro código: para el
            # usuario sería una fila idéntica, nos quedamos con la primera.
            stats["duplicates"] += 1
            if existing:  # y no dejamos una fila antigua a medias
                conn.execute("DELETE FROM products WHERE id = ?", (existing[0],))

    # Los ejemplos manuales (seed_manual_non_es.sql, todos de venta libre) se quitan
    # cuando ya hay datos reales SIN receta de la misma forma (un producto con receta
    # no sustituye a un ejemplo de venta libre); si el país no tiene esa forma, el ejemplo
    # se queda (mejor un dato marcado como sin verificar que ninguno).
    placeholders_removed = 0
    manual = conn.execute(
        "SELECT id, active_ingredient_id, form FROM products "
        "WHERE country_code = ? AND source = 'manual_seed' AND COALESCE(requires_prescription, 0) = 0",
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
