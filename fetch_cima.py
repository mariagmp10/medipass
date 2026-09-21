"""
fetch_cima.py
Carga en products (country_code = 'ES') el catálogo de la API REST pública y
gratuita de CIMA (AEMPS): https://cima.aemps.es/

No requiere API key ni login. Documentación oficial (PDF):
https://www.aemps.gob.es/apps/cima/docs/CIMA_REST_API.pdf

Alcance: solo medicamentos COMERCIALIZADOS y SIN RECETA (comerc=1, receta=0).
Cada medicamento se guarda con su principio activo (el 'vtm' de CIMA, que ya
distingue combinaciones: "dimenhidrinato" vs "dimenhidrinato + cafeína"), su
forma farmacéutica simplificada y su dosis. Después se pide el detalle de cada
uno para completar composición, código ATC y foto.

Es una sincronización: puedes volver a ejecutarlo cuando quieras. Actualiza lo
que ya existe, añade lo nuevo y borra los productos de España de CIMA que ya
no cumplan el filtro (retirados, o que pasaron a requerir receta).

Uso:
    pip install requests
    python fetch_cima.py                    # sincroniza y completa el detalle que falte
    python fetch_cima.py --no-details       # solo el listado (rápido, sin ATC/composición)
    python fetch_cima.py --refresh-details  # vuelve a pedir el detalle de todos (~5 min)
    python fetch_cima.py --debug            # imprime el JSON crudo de 1 medicamento y sale
"""

import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
SCHEMA_PATH = os.path.join(HERE, "schema.sql")
CIMA_BASE = "https://cima.aemps.es/cima/rest"
PAGE_SIZE = 200
DETAIL_WORKERS = 4  # peticiones de detalle en paralelo; pocas, por cortesía con la API pública

# Columnas añadidas a products después de la primera versión del esquema.
NEW_PRODUCT_COLUMNS = {
    "form": "TEXT",
    "dose": "TEXT",
    "composition": "TEXT",
    "atc_code": "TEXT",
    "atc_group": "TEXT",
    "photo_url": "TEXT",
}


def cima_get(path, params):
    last_exc = None
    for attempt in range(4):
        try:
            resp = requests.get(f"{CIMA_BASE}/{path}", params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"CIMA no respondió a /{path} {params}: {last_exc}")


def pick_photo(fotos):
    """Prefiere la foto de la forma farmacéutica; si no, la primera que haya."""
    fotos = fotos or []
    for foto in fotos:
        if foto.get("tipo") == "formafarmac":
            return foto.get("url")
    return fotos[0].get("url") if fotos else None


def fetch_catalog():
    """GET /medicamentos?comerc=1&receta=0, paginando hasta traer todo."""
    items, page = [], 1
    while True:
        data = cima_get(
            "medicamentos",
            {"comerc": 1, "receta": 0, "pagina": page, "tamanioPagina": PAGE_SIZE},
        )
        total = data["totalFilas"]
        if not data["resultados"]:
            break
        items.extend(data["resultados"])
        if len(items) >= total:
            break
        page += 1
        time.sleep(0.5)  # cortesía con la API pública
    if len(items) != total:
        raise RuntimeError(f"CIMA anunció {total} medicamentos pero llegaron {len(items)}")
    return items


def to_product(med):
    """Convierte un medicamento del listado de CIMA en los campos que guardamos."""
    vtm = ((med.get("vtm") or {}).get("nombre") or "").strip().lower()
    if not med.get("nregistro") or not med.get("nombre") or not vtm:
        return None
    return {
        "nregistro": med["nregistro"],
        "brand_name": med["nombre"],
        "vtm": vtm,
        "form": (med.get("formaFarmaceuticaSimplificada") or {}).get("nombre"),
        "dose": med.get("dosis"),
        "photo_url": pick_photo(med.get("fotos")),
    }


def parse_detail(detail):
    """Extrae ATC, composición y foto del detalle GET /medicamento?nregistro=..."""
    atcs = sorted(detail.get("atcs") or [], key=lambda a: a.get("nivel") or 0)
    atc_code = atcs[-1].get("codigo") if atcs else None
    group = next((a for a in atcs if a.get("nivel") == 3), None) or (atcs[0] if atcs else None)
    atc_group = group["nombre"].capitalize() if group and group.get("nombre") else None

    # Solo los nombres: la cantidad que da CIMA no dice a qué se refiere (¿por
    # comprimido, por gramo de gel?), y para eso ya está la dosis del producto.
    parts = []
    for pa in sorted(detail.get("principiosActivos") or [], key=lambda p: p.get("orden") or 0):
        name = (pa.get("nombre") or "").strip().lower()
        if name:
            parts.append(name)

    return {
        "atc_code": atc_code,
        "atc_group": atc_group,
        "composition": " + ".join(parts) or None,
        "photo_url": pick_photo(detail.get("fotos")),
    }


def ensure_schema(conn):
    """Añade las columnas nuevas a una base antigua y recrea la vista (schema.sql)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if existing:
        for column, column_type in NEW_PRODUCT_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE products ADD COLUMN {column} {column_type}")
        conn.commit()
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        conn.executescript(fh.read())


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
    """Deja en products (ES, CIMA_API) exactamente el catálogo recibido."""
    today = date.today().isoformat()
    stats = {"inserted": 0, "updated": 0, "deleted": 0, "duplicates": 0}

    conn.execute("CREATE TEMP TABLE IF NOT EXISTS keep (ref TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM keep")
    conn.executemany("INSERT OR IGNORE INTO keep VALUES (?)", [(p["nregistro"],) for p in products])

    # Primero se borra lo que sobra: así un producto nuevo no choca con el nombre
    # de uno antiguo que ya no aplica.
    stats["deleted"] = conn.execute(
        """
        DELETE FROM products
        WHERE country_code = 'ES' AND source = 'CIMA_API'
          AND (source_ref IS NULL OR source_ref NOT IN (SELECT ref FROM keep))
        """
    ).rowcount

    for p in products:
        ingredient_id = get_or_create_ingredient(conn, p["vtm"])
        existing = conn.execute(
            "SELECT id FROM products WHERE country_code = 'ES' AND source = 'CIMA_API' AND source_ref = ?",
            (p["nregistro"],),
        ).fetchone()
        try:
            if existing:
                conn.execute(
                    """
                    UPDATE products
                    SET active_ingredient_id = ?, brand_name = ?, requires_prescription = 0,
                        form = ?, dose = ?, photo_url = COALESCE(?, photo_url), verified_at = ?
                    WHERE id = ?
                    """,
                    (ingredient_id, p["brand_name"], p["form"], p["dose"], p["photo_url"], today, existing[0]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    """
                    INSERT INTO products
                        (active_ingredient_id, country_code, brand_name, requires_prescription,
                         source, source_ref, verified_at, form, dose, photo_url)
                    VALUES (?, 'ES', ?, 0, 'CIMA_API', ?, ?, ?, ?, ?)
                    """,
                    (ingredient_id, p["brand_name"], p["nregistro"], today, p["form"], p["dose"], p["photo_url"]),
                )
                stats["inserted"] += 1
        except sqlite3.IntegrityError:
            # Mismo principio activo y mismo nombre con otro nº de registro: para el
            # usuario sería una fila idéntica, así que nos quedamos con la primera.
            stats["duplicates"] += 1

    conn.commit()
    return stats


def enrich_details(conn, refresh=False):
    """Completa ATC, composición y foto pidiendo el detalle de cada producto.

    Por defecto solo los que aún no tienen ATC; con refresh=True, todos."""
    only_missing = "" if refresh else "AND atc_code IS NULL"
    todo = conn.execute(
        f"""
        SELECT id, source_ref FROM products
        WHERE country_code = 'ES' AND source = 'CIMA_API' {only_missing}
        """
    ).fetchall()
    print(f"Detalle pendiente: {len(todo)} productos ({DETAIL_WORKERS} peticiones en paralelo)")

    def work(item):
        product_id, nregistro = item
        time.sleep(0.1)
        return product_id, parse_detail(cima_get("medicamento", {"nregistro": nregistro}))

    done = failed = 0
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        futures = [pool.submit(work, item) for item in todo]
        for future in as_completed(futures):
            try:
                product_id, detail = future.result()
            except RuntimeError as exc:
                failed += 1
                print(f"[aviso] {exc}")
                continue
            conn.execute(
                """
                UPDATE products
                SET atc_code = ?, atc_group = ?, composition = ?, photo_url = COALESCE(photo_url, ?)
                WHERE id = ?
                """,
                (detail["atc_code"], detail["atc_group"], detail["composition"], detail["photo_url"], product_id),
            )
            done += 1
            if done % 100 == 0:
                conn.commit()
                print(f"  detalle {done}/{len(todo)}")
    conn.commit()
    print(f"Detalle completado: {done} ok, {failed} fallidos (se reintentan en la próxima ejecución)")


def main():
    if "--debug" in sys.argv:
        data = cima_get("medicamentos", {"comerc": 1, "receta": 0, "pagina": 1, "tamanioPagina": 1})
        print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
        nregistro = data["resultados"][0]["nregistro"]
        detail = cima_get("medicamento", {"nregistro": nregistro})
        print(json.dumps(detail, indent=2, ensure_ascii=False)[:4000])
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)

    if not conn.execute("SELECT 1 FROM countries WHERE code = 'ES'").fetchone():
        sys.exit("Falta el país 'ES' en countries: ejecuta primero seed_base.sql")

    print("Consultando CIMA (comercializados y sin receta)...")
    items = fetch_catalog()
    products = [p for p in (to_product(m) for m in items) if p]
    print(f"CIMA devolvió {len(items)} medicamentos ({len(items) - len(products)} descartados por datos incompletos)")

    stats = sync_products(conn, products)
    print(
        f"Sincronizado: {stats['inserted']} nuevos, {stats['updated']} actualizados, "
        f"{stats['deleted']} borrados, {stats['duplicates']} omitidos por nombre repetido"
    )

    if "--no-details" not in sys.argv:
        enrich_details(conn, refresh="--refresh-details" in sys.argv)

    total = conn.execute("SELECT COUNT(*) FROM products WHERE country_code = 'ES'").fetchone()[0]
    print(f"Listo. Productos de España en la base: {total}")
    conn.close()


if __name__ == "__main__":
    main()
