"""
curate_ingredient_links.py
Prepara (NO aplica) la tabla ingredient_links.csv: qué principio activo francés
corresponde a cuál español.

Para cada principio activo francés de la BDPM:
  1. parse_substance() lo deja en su molécula activa (sin sales).
  2. propose_spanish() propone cómo se escribiría en español. Si queda
     EXACTAMENTE igual que un nombre español que ya tenemos, es un candidato
     "por regla". Si no, se busca un nombre español muy parecido y se marca como
     "sugerencia" (una sugerencia nunca se usa sin comprobación).
  3. Se comprueba el par con fuentes independientes de las reglas: ¿Wikidata
     tiene un mismo elemento para los dos nombres? ¿el artículo de Wikipedia en
     francés lleva al nombre español? Y sobre todo: ¿coincide el código ATC (el
     "pasaporte" universal de la OMS) que da Wikidata con el que da la AEMPS
     (maestro oficial de CIMA) para el nombre español?

Estados:
  confirmado      regla o sugerencia + Wikidata coincide (mismo elemento o ATC)
  sin_confirmar   regla exacta, pero Wikidata no tiene datos para comprobarlo
  sugerido        solo parecido de nombres y sin comprobación: hay que revisarlo
  contradice      Wikidata indica que NO son lo mismo: no se usa
  aprobado / rechazado   decisiones manuales: se conservan al volver a ejecutar

El importador solo usa "confirmado" y "aprobado".

Uso:
    python curate_ingredient_links.py            # propone, comprueba en Wikidata y escribe ingredient_links.csv
    python curate_ingredient_links.py --offline  # sin Wikidata (nada queda "confirmado")
"""

import collections
import csv
import difflib
import json
import os
import pathlib
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import fetch_bdpm
import ingredients as ing

sys.stdout.reconfigure(encoding="utf-8")

WIKIDATA_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "MediPass-learning-project/0.1 (personal non-commercial research)"
BACKSLASH, QUOTE = chr(92), chr(34)
BATCH = 50  # pares por consulta a Wikidata
STATUS_ORDER = ["confirmado", "aprobado", "sin_confirmar", "sugerido", "contradice", "rechazado"]


def sparql(query):
    request = urllib.request.Request(
        WIKIDATA_URL,
        data=urllib.parse.urlencode({"query": query}).encode(),
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["results"]["bindings"]


def literal(text, lang):
    escaped = text.replace(BACKSLASH, BACKSLASH * 2).replace(QUOTE, BACKSLASH + QUOTE)
    return f"{QUOTE}{escaped}{QUOTE}@{lang}"


def variants(label):
    return {label, label[:1].upper() + label[1:]}


def load_spanish_vocabulary(conn):
    """Nombres españoles canónicos: los de ingredientes que tienen algún producto
    que NO viene de la BDPM (CIMA y ejemplos de otros países)."""
    names = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT ai.inn_name FROM active_ingredients ai
            JOIN products p ON p.active_ingredient_id = ai.id
            WHERE p.source != 'BDPM'
            """
        )
    ]
    components = {}
    for name in names:
        for component in name.split("+"):
            component = component.strip()  # CIMA a veces deja un espacio de más
            components[ing.plain(component)] = component
    cima_atc = collections.defaultdict(set)
    for name, code in conn.execute(
        """
        SELECT ai.inn_name, p.atc_code FROM products p
        JOIN active_ingredients ai ON ai.id = p.active_ingredient_id
        WHERE p.country_code = 'ES' AND p.atc_code IS NOT NULL
        """
    ):
        if " + " not in name:
            cima_atc[ing.plain(name)].add(code)
    return names, components, cima_atc


def french_moieties(catalog):
    display, products, examples = {}, collections.defaultdict(set), collections.defaultdict(list)
    unparsed = collections.Counter()
    for item in catalog:
        for raw in item["substances"]:
            moiety = ing.parse_substance(raw)
            if moiety is None:
                unparsed[raw.lower()] += 1
                continue
            key = ing.plain(moiety)
            display[key] = moiety
            products[key].add(item["cis"])
            if raw.lower() not in examples[key] and len(examples[key]) < 2:
                examples[key].append(raw.lower())
    return display, products, examples, unparsed


def propose(display, es_components):
    proposals = {}
    es_plain = list(es_components)
    for key, moiety in display.items():
        # Primero el nombre tal cual (minoxidil, aciclovir...) y luego con las
        # terminaciones pasadas al español; las dos formas son "por regla".
        guesses = list(dict.fromkeys((ing.plain(moiety), ing.propose_spanish(moiety))))
        exact = next((g for g in guesses if g in es_components), None)
        if exact:
            proposals[key] = (es_components[exact], "regla")
            continue
        close = difflib.get_close_matches(guesses[-1], es_plain, n=1, cutoff=0.86)
        if close:
            proposals[key] = (es_components[close[0]], "sugerencia")
    return proposals


def aemps_atc(name):
    """Códigos ATC que el maestro oficial de la AEMPS (CIMA) da a este nombre
    de principio activo en español. Solo cuenta el nombre exacto: no las
    combinaciones ("Clorfenamina, combinaciones con")."""
    data = get_json("https://cima.aemps.es/cima/rest/maestras", {"maestra": 7, "nombre": name})
    return {r["codigo"] for r in data.get("resultados", []) if ing.plain(r["nombre"]) == ing.plain(name)}


def enrich_with_aemps_atc(cima_atc, spanish_names):
    for name in sorted(spanish_names):
        try:
            cima_atc[ing.plain(name)] |= aemps_atc(name)
        except Exception as exc:
            print(f"[aviso] el maestro de ATC de la AEMPS no respondió para «{name}» ({exc})")
        time.sleep(0.3)


def english_label_check(pairs, cima_atc):
    """Último recurso. Muchos nombres franceses solo se diferencian del inglés
    por las tildes (carbocistéine / carbocisteine). Se busca en Wikidata ese
    nombre sin tildes y se compara SU código ATC con el del maestro de la AEMPS
    para el nombre español. Lo decisivo es que los dos ATC coincidan: el nombre
    solo sirve para localizar el elemento."""
    labels = {fr: ing.plain(fr) for fr, _ in pairs}
    values = " ".join(literal(v, "en") for label in set(labels.values()) for v in variants(label))
    atc_by_label = collections.defaultdict(set)
    for b in sparql(
        "SELECT ?lab ?atc WHERE { VALUES ?lab { " + values + " } "
        "?item (rdfs:label|skos:altLabel) ?lab . ?item wdt:P267 ?atc }"
    ):
        atc_by_label[b["lab"]["value"].lower()].add(b["atc"]["value"])
    decided = {}
    for fr, es in pairs:
        wikidata, reference = atc_by_label.get(labels[fr], set()), cima_atc.get(ing.plain(es), set())
        if not (wikidata and reference):
            continue
        where = f"Wikidata (nombre sin tildes «{labels[fr]}» en inglés)"
        if wikidata & reference:
            decided[(fr, es)] = ("confirmado", f"{where}: mismo ATC que la AEMPS/CIMA ({', '.join(sorted(wikidata & reference))})")
        else:
            decided[(fr, es)] = ("contradice", f"{where}: ATC {', '.join(sorted(wikidata))} frente a AEMPS/CIMA {', '.join(sorted(reference))}")
    return decided


def get_json(base_url, params):
    """GET que devuelve JSON, con reintentos: si el servicio responde 429
    (demasiadas peticiones) espera lo que pida y vuelve a intentarlo."""
    url = base_url + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(min(int(exc.headers.get("Retry-After") or 0) or 3 * (attempt + 1), 30))
    raise RuntimeError("el servicio sigue rechazando las peticiones")


def without_disambiguation(title):
    return re.sub(r"\s*\([^)]*\)\s*$", "", title)  # "Hesperidina (flavonoide)" -> "Hesperidina"


def wikipedia_check(pairs, cima_atc):
    """Para los pares que Wikidata no pudo comprobar por nombres. Parte del
    artículo de Wikipedia en FRANCÉS (siguiendo redirecciones), mira a qué
    elemento de Wikidata está enlazado y confirma si:
      - su nombre español (etiqueta, alias o título del artículo) incluye el
        nuestro, o
      - su código ATC coincide con el que CIMA da para el producto español
        (esto cubre diferencias de ortografía: meclozina / meclizina).
    Si los ATC son distintos, lo marca como "contradice"."""
    wanted = {fr: fr[:1].upper() + fr[1:] for fr, _ in pairs}
    qid_by_fr, title_by_fr = {}, {}
    titles = sorted(set(wanted.values()))
    for i in range(0, len(titles), 40):
        chunk = titles[i : i + 40]
        query = get_json(
            "https://fr.wikipedia.org/w/api.php",
            {"action": "query", "format": "json", "redirects": 1, "prop": "pageprops",
             "ppprop": "wikibase_item", "titles": "|".join(chunk)},
        ).get("query", {})
        normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
        redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
        qid_of = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in query.get("pages", {}).values()}
        for original in chunk:
            title = normalized.get(original, original)
            for _ in range(3):
                title = redirects.get(title, title)
            if qid_of.get(title):
                for fr, wanted_title in wanted.items():
                    if wanted_title == original:
                        qid_by_fr[fr], title_by_fr[fr] = qid_of[title], title
        time.sleep(1)

    qids = sorted(set(qid_by_fr.values()))
    spanish_names, atc_of = collections.defaultdict(set), collections.defaultdict(set)
    for i in range(0, len(qids), 40):
        items = " ".join("wd:" + q for q in qids[i : i + 40])
        for b in sparql(
            "SELECT ?item ?kind ?value WHERE { VALUES ?item { " + items + " } "
            "{ ?item rdfs:label ?value . FILTER(LANG(?value) = " + QUOTE + "es" + QUOTE + ") BIND(" + QUOTE + "nombre" + QUOTE + " AS ?kind) } "
            "UNION { ?item skos:altLabel ?value . FILTER(LANG(?value) = " + QUOTE + "es" + QUOTE + ") BIND(" + QUOTE + "nombre" + QUOTE + " AS ?kind) } "
            "UNION { ?page schema:about ?item ; schema:isPartOf <https://es.wikipedia.org/> ; schema:name ?value . BIND(" + QUOTE + "nombre" + QUOTE + " AS ?kind) } "
            "UNION { ?item wdt:P267 ?value . BIND(" + QUOTE + "atc" + QUOTE + " AS ?kind) } }"
        ):
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            (atc_of if b["kind"]["value"] == "atc" else spanish_names)[qid].add(b["value"]["value"])
        time.sleep(1)

    decided = {}
    for fr, es in pairs:
        qid = qid_by_fr.get(fr)
        if not qid:
            continue
        where = f"Wikipedia fr «{title_by_fr[fr]}» (Wikidata {qid})"
        names = {ing.plain(without_disambiguation(n)) for n in spanish_names[qid]}
        wd_atc, cima = atc_of[qid], cima_atc.get(ing.plain(es), set())
        if ing.plain(es) in names:
            decided[(fr, es)] = ("confirmado", f"{where}: su nombre en español incluye «{es}»")
        elif wd_atc & cima:
            decided[(fr, es)] = ("confirmado", f"{where}: mismo ATC que CIMA ({', '.join(sorted(wd_atc & cima))})")
        elif wd_atc and cima:
            decided[(fr, es)] = ("contradice", f"{where}: ATC {', '.join(sorted(wd_atc))} frente a CIMA {', '.join(sorted(cima))}")
    return decided


def wikidata_batch(pairs, cima_atc):
    """pairs: [(nombre fr, nombre es)] con tildes -> {(fr, es): (resultado, evidencia)}."""
    rows = " ".join(
        f"({literal(f, 'fr')} {literal(e, 'es')})" for fr, es in pairs for f in variants(fr) for e in variants(es)
    )
    same = collections.defaultdict(lambda: {"items": set(), "atc": set()})
    for b in sparql(
        "SELECT ?fr ?es ?item ?atc WHERE { VALUES (?fr ?es) { " + rows + " } "
        "?item (rdfs:label|skos:altLabel) ?fr . ?item (rdfs:label|skos:altLabel) ?es . "
        "OPTIONAL { ?item wdt:P267 ?atc } }"
    ):
        key = (b["fr"]["value"].lower(), b["es"]["value"].lower())
        same[key]["items"].add(b["item"]["value"].rsplit("/", 1)[-1])
        if "atc" in b:
            same[key]["atc"].add(b["atc"]["value"])

    pending = [(fr, es) for fr, es in pairs if (fr.lower(), es.lower()) not in same]
    atc_by_label = collections.defaultdict(set)
    if pending:
        values = " ".join(
            [literal(v, "fr") for fr, _ in pending for v in variants(fr)]
            + [literal(v, "es") for _, es in pending for v in variants(es)]
        )
        for b in sparql(
            "SELECT ?lab ?item ?atc WHERE { VALUES ?lab { " + values + " } "
            "?item (rdfs:label|skos:altLabel) ?lab . OPTIONAL { ?item wdt:P267 ?atc } }"
        ):
            if "atc" in b:
                atc_by_label[(b["lab"]["xml:lang"], b["lab"]["value"].lower())].add(b["atc"]["value"])

    result = {}
    for fr, es in pairs:
        key = (fr.lower(), es.lower())
        if key in same:
            data = same[key]
            extra = f" (ATC {', '.join(sorted(data['atc']))})" if data["atc"] else ""
            result[(fr, es)] = ("confirmado", f"Wikidata {sorted(data['items'])[0]}: un mismo elemento tiene los dos nombres{extra}")
            continue
        fr_atc = atc_by_label.get(("fr", fr.lower()), set())
        reference = atc_by_label.get(("es", es.lower()), set()) | cima_atc.get(ing.plain(es), set())
        if fr_atc and reference:
            common = fr_atc & reference
            if common:
                result[(fr, es)] = ("confirmado", f"mismo código ATC en Wikidata y CIMA/Wikidata: {', '.join(sorted(common))}")
            else:
                result[(fr, es)] = (
                    "contradice",
                    f"ATC distintos: fr {', '.join(sorted(fr_atc))} frente a es {', '.join(sorted(reference))}",
                )
        else:
            result[(fr, es)] = ("sin_datos", "Wikidata no tiene datos suficientes para este par")

    # Tercera comprobación para lo que sigue sin confirmar (ver wikipedia_check).
    for check in (wikipedia_check, english_label_check):
        undecided = [pair for pair, (outcome, _e) in result.items() if outcome == "sin_datos"]
        if not undecided:
            break
        try:
            result.update(check(undecided, cima_atc))
        except Exception as exc:
            print(f"[aviso] la comprobación {check.__name__} falló ({exc}); esos pares quedan sin comprobar")
    return result


def verify(pairs, cima_atc, offline):
    if offline:
        return {pair: ("sin_datos", "no comprobado (modo sin conexión)") for pair in pairs}
    result = {}
    for i in range(0, len(pairs), BATCH):
        chunk = pairs[i : i + BATCH]
        try:
            result.update(wikidata_batch(chunk, cima_atc))
        except Exception as exc:  # red caída, límite de peticiones...
            print(f"[aviso] Wikidata no respondió para un lote ({exc}); esos pares quedan sin comprobar")
            result.update({pair: ("sin_datos", "Wikidata no respondió") for pair in chunk})
        time.sleep(1)
    return result


def load_manual_decisions(path):
    decisions = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row["estado"] in ("aprobado", "rechazado"):
                    decisions[ing.plain(row["nombre_fr"])] = row
    return decisions


def main():
    offline = "--offline" in sys.argv
    conn = sqlite3.connect(pathlib.Path(fetch_bdpm.DB_PATH).as_uri() + "?mode=ro", uri=True)
    _names, es_components, cima_atc = load_spanish_vocabulary(conn)
    conn.close()

    catalog = fetch_bdpm.load_catalog()
    display, products, examples, unparsed = french_moieties(catalog)
    proposals = propose(display, es_components)
    print(
        f"\nPrincipios activos franceses distintos: {len(display)} interpretables, "
        f"{len(unparsed)} que no se interpretan (se quedan en francés)"
    )
    print(f"Candidatos: {sum(1 for v in proposals.values() if v[1] == 'regla')} por regla exacta, "
          f"{sum(1 for v in proposals.values() if v[1] == 'sugerencia')} por parecido de nombres")

    pairs = sorted({(display[key], es) for key, (es, _m) in proposals.items()})
    if not offline:
        enrich_with_aemps_atc(cima_atc, {es for _fr, es in pairs})
    checks = verify(pairs, cima_atc, offline)

    manual = load_manual_decisions(ing.LINKS_PATH)
    rows = []
    for key, (es, method) in proposals.items():
        outcome, evidence = checks[(display[key], es)]
        if outcome == "confirmado":
            status = "confirmado"
            evidence = ("sugerencia + " if method == "sugerencia" else "regla + ") + evidence
        elif outcome == "contradice":
            status = "contradice"
        else:
            status = "sin_confirmar" if method == "regla" else "sugerido"
        row = {
            "nombre_fr": display[key], "nombre_es": es, "estado": status, "evidencia": evidence,
            "productos_fr": len(products[key]), "ejemplos": " | ".join(examples[key]),
        }
        rows.append(manual.get(key, row))
    for key, row in manual.items():  # decisiones manuales de pares que ya no se proponen
        if key not in proposals:
            rows.append(row)

    rows.sort(key=lambda r: (STATUS_ORDER.index(r["estado"]), -int(r["productos_fr"]), r["nombre_fr"]))
    with open(ing.LINKS_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ing.LINK_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    by_status = collections.Counter(r["estado"] for r in rows)
    weight = collections.Counter()
    for r in rows:
        weight[r["estado"]] += int(r["productos_fr"])
    print(f"\nEscrito {ing.LINKS_PATH} ({len(rows)} pares):")
    for status in STATUS_ORDER:
        if by_status[status]:
            print(f"  {status:14} {by_status[status]:3} pares, {weight[status]:4} productos franceses afectados")


if __name__ == "__main__":
    main()
