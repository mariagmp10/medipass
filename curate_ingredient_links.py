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

Cada fila lleva un `nivel`: "exacto" (misma molécula, aunque cambie la sal) o "base" (misma molécula
BASE pero otro ÉSTER o profármaco: "fluticasone propionate" ~ "fluticasona"). Los de nivel base se
proponen con ester_candidates() y pasan por la MISMA comprobación ATC; la app los enseña aparte, en
amarillo, y nunca como "el mismo".

Reino Unido (--country uk): igual, pero con los nombres en inglés del dm+d y escribiendo
ingredient_links_uk.csv. Los candidatos salen de reglas ortográficas o del nombre español
que Wikidata da al nombre inglés, y NUNCA se confirman solo por eso: hace falta que el código
ATC de Wikidata coincida con el que la AEMPS da al nombre español (ver uk_verify).

Uso:
    python curate_ingredient_links.py            # Francia: propone, comprueba en Wikidata y escribe ingredient_links.csv
    python curate_ingredient_links.py --offline  # sin Wikidata (nada queda "confirmado")
    python curate_ingredient_links.py --country uk --zip RUTA_AL_ZIP   # Reino Unido
    python curate_ingredient_links.py --country it [--dir CARPETA_AIFA] # Italia (sin Wikidata: usa el ATC de la AIFA)
"""

import argparse
import collections
import csv
import difflib
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import fetch_aifa
import fetch_bdpm
import fetch_dmd
import importers
import ingredients as ing

sys.stdout.reconfigure(encoding="utf-8")

WIKIDATA_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "MediPass-learning-project/0.1 (personal non-commercial research)"
BACKSLASH, QUOTE = chr(92), chr(34)
BATCH = 50  # pares por consulta a Wikidata
STATUS_ORDER = ["confirmado", "aprobado", "sin_confirmar", "sugerido", "contradice", "rechazado"]


def sparql(query, attempts=4):
    """Consulta a Wikidata con reintentos: si está saturado responde 429/50x o agota el tiempo,
    y un lote perdido dejaba decenas de pares válidos "sin comprobar"."""
    for attempt in range(attempts):
        request = urllib.request.Request(
            WIKIDATA_URL,
            data=urllib.parse.urlencode({"query": query}).encode(),
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)["results"]["bindings"]
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(min(int(exc.headers.get("Retry-After") or 0) or 10 * (attempt + 1), 60))
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))


def literal(text, lang):
    escaped = text.replace(BACKSLASH, BACKSLASH * 2).replace(QUOTE, BACKSLASH + QUOTE)
    return f"{QUOTE}{escaped}{QUOTE}@{lang}"


def variants(label):
    return {label, label[:1].upper() + label[1:]}


def load_spanish_vocabulary(conn):
    """Nombres españoles canónicos: los de ingredientes que tienen algún producto
    que NO viene de un importador extranjero (CIMA y ejemplos manuales)."""
    names, _forms = importers.load_spanish_vocabulary(conn)
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


def english_ester_name(raw):
    """El nombre INGLÉS de un éster francés, sin tildes: "propionate de fluticasone" ->
    "fluticasone propionate". Wikidata suele tener el ATC del nombre inglés aunque no del francés."""
    p = ing.strip_accents(raw.lower().replace("’", "'")).strip()
    ester = ing._ESTER_RE
    m = re.fullmatch(rf"(?P<base>[^()]+?)\s*\((?P<e>{ester})\s+(?:de|d')\s*\)", p) or re.fullmatch(
        rf"(?P<e>{ester})\s+(?:de |d')\s*(?P<base>.+)", p)
    if m:
        return f"{m.group('base').strip()} {m.group('e')}"
    return p if re.fullmatch(rf".+\s+(?:{ester})", p) else None


def ester_candidates(catalog, country, es_components, exact_keys, id_field):
    """Nombres de `country` ("FR" o "UK") que son un ÉSTER o profármaco y cuya BASE es un nombre
    español que ya tenemos: {clave: (nombre mostrado, nombre español)}, más productos y ejemplos
    por clave. Se omiten los que ya tienen un candidato exacto (`exact_keys`)."""
    propose = {"FR": ing.propose_spanish, "UK": ing.propose_spanish_en, "IT": ing.propose_spanish_it}[country]
    parse = ing._parser(country)
    found, products, examples = {}, collections.defaultdict(set), collections.defaultdict(list)
    for item in catalog:
        for raw in item["substances"]:
            key = ing.source_key(raw, country)
            if key in exact_keys:
                continue
            base = ing.ester_base(raw, country)
            if not base:
                continue
            guesses = [ing.plain(base), propose(base)]
            if country == "UK":
                guesses.append(ing.propose_spanish_en(base, k_to_c=False))
            elif country == "IT":
                guesses.append(ing.propose_spanish_it(base, k_to_c=False))
            es = next((es_components[g] for g in guesses if g in es_components), None)
            if es is None:
                continue
            moiety = parse(raw)
            found[key] = (moiety if moiety is not None else raw.lower(), es)
            products[key].add(item[id_field])
            if raw.lower() not in examples[key] and len(examples[key]) < 2:
                examples[key].append(raw.lower())
    return found, products, examples


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
            reader = csv.DictReader(fh)
            source_col = reader.fieldnames[0]  # nombre_fr o nombre_en
            for row in reader:
                if row["estado"] in ("aprobado", "rechazado"):
                    decisions[ing.plain(row[source_col])] = row
    return decisions


def uk_moieties(catalog):
    display, products, examples = {}, collections.defaultdict(set), collections.defaultdict(list)
    unparsed = collections.Counter()
    for item in catalog:
        for raw in item["substances"]:
            moiety = ing.parse_substance_en(raw)
            if moiety is None:
                unparsed[raw.lower()] += 1
                continue
            key = ing.plain(moiety)
            display[key] = moiety
            products[key].add(item["ref"])
            if raw.lower() not in examples[key] and len(examples[key]) < 2:
                examples[key].append(raw.lower())
    return display, products, examples, unparsed


UK_BATCH = 20  # nombres por consulta: con más, Wikidata da "504 Gateway Timeout"


def sparql_retry(query, attempts=4):
    """sparql() con reintentos: Wikidata a veces responde 429/50x si está saturado."""
    for attempt in range(attempts):
        try:
            return sparql(query)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            time.sleep(min(int(exc.headers.get("Retry-After") or 0) or 10 * (attempt + 1), 60))
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(10 * (attempt + 1))


def wikidata_by_english_label(moieties, lang="en"):
    """Para cada nombre en el idioma `lang` (inglés por defecto): los elementos de Wikidata que lo tienen como etiqueta o
    alias, con su nombre en español y sus códigos ATC. Son dos consultas sencillas por
    lote (una compleja con UNION agota el tiempo de Wikidata).
    Devuelve {nombre inglés en minúsculas: {"items": set, "es": set, "atc": set}}."""
    found = collections.defaultdict(lambda: {"items": set(), "es": set(), "atc": set()})
    moieties = sorted(moieties)
    failed = 0
    for i in range(0, len(moieties), UK_BATCH):
        chunk = moieties[i : i + UK_BATCH]
        values = " ".join(literal(v, lang) for m in chunk for v in variants(m))
        head = "SELECT ?lab ?item ?value WHERE { VALUES ?lab { " + values + " } ?item (rdfs:label|skos:altLabel) ?lab . "
        queries = {
            "atc": head + "?item wdt:P267 ?value }",
            "es": head + "?item rdfs:label ?value . FILTER(LANG(?value) = " + QUOTE + "es" + QUOTE + ") }",
        }
        for kind, query in queries.items():
            try:
                rows = sparql_retry(query)
            except Exception as exc:  # red caída, límite de peticiones...
                failed += 1
                print(f"[aviso] Wikidata no respondió ({kind}, lote {i // UK_BATCH + 1}): {exc}")
                continue
            for b in rows:
                entry = found[b["lab"]["value"].lower()]
                entry["items"].add(b["item"]["value"].rsplit("/", 1)[-1])
                entry[kind].add(b["value"]["value"])
            time.sleep(1)
    if failed:
        print(f"[aviso] {failed} consultas fallaron: los nombres afectados quedan sin comprobar")
    return found


def uk_candidates(display, es_components, wikidata):
    """{nombre inglés: {nombre español: método}}. Dos métodos:
    "regla"    el nombre inglés pasado al español queda IGUAL que uno que ya tenemos.
    "wikidata" Wikidata da ese nombre español para el elemento del nombre inglés. Solo
               para nombres de una palabra o "X acid": con ésteres o sales ("zinc sulfate")
               un elemento de Wikidata podría ser el compuesto y no la molécula."""
    candidates = collections.defaultdict(dict)
    for key, moiety in display.items():
        guesses = list(dict.fromkeys(g for g in (
            ing.plain(moiety), ing.propose_spanish_en(moiety), ing.propose_spanish_en(moiety, k_to_c=False),
            ing.propose_acid_en(moiety),
        ) if g))
        exact = next((g for g in guesses if g in es_components), None)
        if exact:
            candidates[key][es_components[exact]] = "regla"
        if " " not in moiety or moiety.endswith(" acid"):
            for name in wikidata.get(moiety, {}).get("es", ()):
                plain_name = ing.plain(without_disambiguation(name))
                if plain_name in es_components:
                    candidates[key].setdefault(es_components[plain_name], "wikidata")
        if not candidates[key] and " " not in moiety:
            # Nombres de una palabra casi iguales ("benzydamine" ~ "bencidamina"). Solo
            # sugerencia: se usa únicamente si el ATC lo confirma (ver uk_verify).
            close = difflib.get_close_matches(ing.propose_spanish_en(moiety), list(es_components), n=1, cutoff=0.86)
            if close:
                candidates[key][es_components[close[0]]] = "sugerencia"
    return candidates


def uk_verify(moiety, es, method, wikidata, cima_atc):
    """(resultado, evidencia). Lo decisivo es el ATC: el nombre en español sale de una
    fuente (regla o Wikidata) y el código ATC de otra (la AEMPS), así que si coinciden
    no es casualidad de nombres. Para "regla" también vale que un mismo elemento de
    Wikidata tenga el nombre inglés y el español; para "wikidata" eso no cuenta, porque
    el nombre español salió justamente de ahí."""
    data = wikidata.get(moiety)
    if not data:
        return "sin_datos", "Wikidata no tiene ningún elemento con ese nombre en inglés"
    wd_atc, reference = data["atc"], cima_atc.get(ing.plain(es), set())
    where = f"Wikidata ({', '.join(sorted(data['items'])[:2])}, nombre inglés «{moiety}»)"
    if wd_atc and reference:
        common = wd_atc & reference
        if common:
            return "confirmado", f"{where}: mismo ATC que la AEMPS/CIMA ({', '.join(sorted(common))})"
        return "contradice", f"{where}: ATC {', '.join(sorted(wd_atc))} frente a AEMPS/CIMA {', '.join(sorted(reference))}"
    # Mismo nombre aunque cambie el orden: "cloruro de benzalconio" = "benzalconio cloruro".
    def words(name):
        return frozenset(ing.plain(without_disambiguation(name)).split()) - {"de", "del", "la", "el"}

    names = {words(n) for n in data["es"]}
    if method == "regla" and words(es) in names:
        return "confirmado", f"{where}: el mismo elemento tiene el nombre español «{es}»"
    return "sin_datos", f"{where}: falta el código ATC para comprobar"


def main_uk(zip_path, offline):
    conn = sqlite3.connect(pathlib.Path(fetch_bdpm.DB_PATH).as_uri() + "?mode=ro", uri=True)
    _names, es_components, cima_atc = load_spanish_vocabulary(conn)
    conn.close()

    catalog, _excluded = fetch_dmd.load_catalog(zip_path)
    display, products, examples, unparsed = uk_moieties(catalog)
    print(f"\nPrincipios activos británicos distintos: {len(display)} interpretables, "
          f"{len(unparsed)} que no se interpretan (se quedan en inglés)")

    # Los de nivel base se buscan entre TODOS los nombres; después se descartan los que ya tienen un
    # candidato exacto (en `display` están todos los interpretados, no solo los que tienen candidato).
    esters, ester_products, ester_examples = ester_candidates(catalog, "UK", es_components, set(), "ref")
    wikidata = {} if offline else wikidata_by_english_label(list(display.values()) + [name for name, _es in esters.values()])
    candidates = uk_candidates(display, es_components, wikidata)
    esters = {key: value for key, value in esters.items() if not candidates.get(key)}
    print(f"Candidatos de nivel base (éster/profármaco): {len(esters)}")
    for key, (name, es) in esters.items():
        display[key] = name
        products[key], examples[key] = ester_products[key], ester_examples[key]
        candidates[key][es] = "ester"
    spanish = {es for options in candidates.values() for es in options}
    print(f"Candidatos: {sum(1 for c in candidates.values() if 'regla' in c.values())} por regla, "
          f"{sum(1 for c in candidates.values() if 'wikidata' in c.values())} por Wikidata")
    if not offline:
        enrich_with_aemps_atc(cima_atc, spanish)

    manual = load_manual_decisions(ing.LINKS_PATH_UK)
    rows = []
    for key, options in candidates.items():
        checked = {es: (method, *uk_verify(display[key], es, method, wikidata, cima_atc)) for es, method in options.items()}
        confirmed = [es for es, (_m, outcome, _e) in checked.items() if outcome == "confirmado"]
        for es, (method, outcome, evidence) in checked.items():
            if outcome == "confirmado" and len(confirmed) > 1:
                status, evidence = "sugerido", f"hay {len(confirmed)} candidatos confirmados distintos; hay que decidir a mano. " + evidence
            elif outcome == "confirmado":
                status = "confirmado"
                evidence = {"regla": "regla + ", "wikidata": "Wikidata + ", "sugerencia": "sugerencia + ", "ester": "éster + "}[method] + evidence
            elif outcome == "contradice":
                status = "contradice"
            else:
                status = "sin_confirmar" if method in ("regla", "ester") else "sugerido"
            rows.append({
                "nombre_en": display[key], "nombre_es": es, "estado": status,
                "nivel": ing.LEVEL_BASE if method == "ester" else ing.LEVEL_EXACT, "evidencia": evidence,
                "productos_uk": len(products[key]), "ejemplos": " | ".join(examples[key]),
            })
    done = {ing.plain(r["nombre_en"]) for r in rows}
    rows = [manual.get(ing.plain(r["nombre_en"]), r) for r in rows]
    rows += [row for key, row in manual.items() if key not in done]  # decisiones manuales de pares que ya no se proponen

    rows.sort(key=lambda r: (STATUS_ORDER.index(r["estado"]), -int(r["productos_uk"]), r["nombre_en"]))
    with open(ing.LINKS_PATH_UK, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ing.LINK_FIELDS_UK, restval=ing.LEVEL_EXACT)
        writer.writeheader()
        writer.writerows(rows)

    weight = collections.Counter()
    for r in rows:
        weight[r["estado"]] += int(r["productos_uk"])
    by_status = collections.Counter(r["estado"] for r in rows)
    print(f"\nEscrito {ing.LINKS_PATH_UK} ({len(rows)} pares):")
    for status in STATUS_ORDER:
        if by_status[status]:
            print(f"  {status:14} {by_status[status]:3} pares, {weight[status]:4} productos británicos afectados")
    linked = {ing.plain(r["nombre_en"]) for r in rows}
    left = sorted(((len(products[k]), display[k]) for k in display if k not in linked), reverse=True)
    print(f"\nSin ningún candidato ({len(left)}), los más frecuentes:")
    print(", ".join(f"{name} ({n})" for n, name in left[:60]))


# --- Italia (AIFA) ---------------------------------------------------------------------------------
# A diferencia de Francia y el Reino Unido, aquí NO hace falta Wikidata: la AIFA da el código ATC de
# cada producto. Para un producto con UN solo principio activo, ese ATC es el del principio activo, y se
# compara con el que la AEMPS da al nombre español (maestro oficial de CIMA): dos fuentes oficiales
# distintas que no comparten nombres. Los nombres que solo aparecen en combinaciones no tienen ATC
# propio y se quedan «sin confirmar» (no se usan).
ATC_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aemps_atc_cache.json")


def enrich_all_with_aemps_atc(cima_atc, spanish_names, cache_path=ATC_CACHE):
    """Como enrich_with_aemps_atc, pero para TODOS los nombres españoles y con caché en disco (son ~1.100
    consultas). La caché (aemps_atc_cache.json) no se sube a git: se regenera sola."""
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    new = 0
    for name in sorted(spanish_names):
        key = ing.plain(name)
        if key not in cache:
            try:
                cache[key] = sorted(aemps_atc(name))
            except Exception as exc:
                print(f"[aviso] el maestro de ATC de la AEMPS no respondió para «{name}» ({exc})")
                continue
            new += 1
            time.sleep(0.25)
            if new % 100 == 0:
                print(f"  ...{new} nombres consultados")
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump(cache, fh, ensure_ascii=False)
        cima_atc[key] |= set(cache[key])
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)


def it_moieties(catalog):
    display, products, examples = {}, collections.defaultdict(set), collections.defaultdict(list)
    atc_of = collections.defaultdict(set)  # nombre limpio -> ATC de 7 caracteres de sus productos de UN solo principio activo
    unparsed = collections.Counter()
    for item in catalog:
        for raw in item["substances"]:
            moiety = ing.parse_substance_it(raw)
            if moiety is None:
                unparsed[raw.lower()] += 1
                continue
            key = ing.plain(moiety)
            display[key] = moiety
            products[key].add(item["ref"])
            if raw.lower() not in examples[key] and len(examples[key]) < 2:
                examples[key].append(raw.lower())
            if len(item["substances"]) == 1 and len(item["atc"]) == 7:
                atc_of[key].add(item["atc"])
    return display, products, examples, unparsed, atc_of


def it_candidates(display, examples, es_components, atc_of, es_by_atc):
    """{nombre italiano: {nombre español: método}}. Métodos:
    "regla"      el nombre italiano pasado al español queda IGUAL que uno que ya tenemos.
    "atc"        el ATC de la AIFA lo da la AEMPS a ese nombre español (sirve para grafías raras, "ibuprofen").
                 Si el nombre italiano es un éster, se propone solo de nivel base ("ester").
    "sugerencia" nombres de una palabra casi iguales; solo se usa si el ATC lo confirma."""
    candidates = collections.defaultdict(dict)
    for key, moiety in display.items():
        guesses = list(dict.fromkeys(g for g in (
            ing.plain(moiety), ing.propose_spanish_it(moiety), ing.propose_spanish_it(moiety, k_to_c=False)) if g))
        exact = next((g for g in guesses if g in es_components), None)
        if exact:
            candidates[key][es_components[exact]] = "regla"
        # Éster solo si la palabra del éster sigue en el nombre limpio: "flecainide acetato" ya se limpió a
        # "flecainide" (sal), pero "betametasone dipropionato" conserva "dipropionato" (éster).
        is_ester = bool(re.search(rf"\s(?:{ing._ESTER_RE})$", moiety))
        for code in atc_of.get(key, ()):
            for es in es_by_atc.get(code, ()):
                candidates[key].setdefault(es, "ester" if is_ester else "atc")
        if not candidates[key] and " " not in moiety:
            close = difflib.get_close_matches(ing.propose_spanish_it(moiety), list(es_components), n=1, cutoff=0.86)
            if close:
                candidates[key][es_components[close[0]]] = "sugerencia"
    return candidates


def it_wikidata_check(moiety, es, method, wikidata, cima_atc):
    """Segunda comprobación, para los nombres que la AIFA no puede confirmar con su ATC (solo salen en
    combinaciones): Wikidata por el nombre italiano. Vale que el ATC de Wikidata coincida con el de la AEMPS,
    o (solo con "regla") que el mismo elemento tenga el nombre español."""
    data = (wikidata or {}).get(moiety)
    if not data:
        return None
    where = f"Wikidata ({', '.join(sorted(data['items'])[:2])}, nombre italiano «{moiety}»)"
    reference = cima_atc.get(ing.plain(es), set())
    if data["atc"] and reference:
        common = data["atc"] & reference
        if common:
            return "confirmado", f"{where}: mismo ATC que la AEMPS/CIMA ({', '.join(sorted(common))})"
        return "contradice", f"{where}: ATC {', '.join(sorted(data['atc']))} frente a AEMPS/CIMA {', '.join(sorted(reference))}"

    def words(name):
        return frozenset(ing.plain(without_disambiguation(name)).split()) - {"de", "del", "la", "el"}

    if method == "regla" and words(es) in {words(n) for n in data["es"]}:
        return "confirmado", f"{where}: el mismo elemento tiene el nombre español «{es}»"
    return None


def it_verify(key, moiety, es, method, atc_of, cima_atc, wikidata=None):
    """(resultado, evidencia). El ATC de la AIFA (de los productos de ese solo principio activo) frente
    al que la AEMPS da al nombre español. Para "atc" se exige además que los nombres se parezcan: un
    mismo ATC con nombres muy distintos se deja como «sugerido» para revisarlo a mano."""
    italian, spanish = atc_of.get(key, set()), cima_atc.get(ing.plain(es), set())
    if not italian or not spanish:
        found = it_wikidata_check(moiety, es, method, wikidata, cima_atc)
        if found:
            return found
        if not italian:
            return "sin_datos", "la AIFA no da un ATC propio (el nombre solo aparece en combinaciones)"
        return "sin_datos", f"el maestro de la AEMPS no tiene ATC para «{es}»"
    common = italian & spanish
    if common:
        where = f"ATC de la AIFA ({', '.join(sorted(common))}) igual al de la AEMPS/CIMA para «{es}»"
        if method == "atc":
            similarity = difflib.SequenceMatcher(None, ing.propose_spanish_it(moiety), ing.plain(es)).ratio()
            if similarity < 0.75:
                return "sugerido", f"{where}, pero los nombres se parecen poco ({similarity:.2f}): hay que revisarlo"
        return "confirmado", where
    return "contradice", f"ATC de la AIFA {', '.join(sorted(italian))} frente a AEMPS/CIMA {', '.join(sorted(spanish))} para «{es}»"


def main_it(directory, offline):
    conn = sqlite3.connect(pathlib.Path(fetch_bdpm.DB_PATH).as_uri() + "?mode=ro", uri=True)
    _names, es_components, cima_atc = load_spanish_vocabulary(conn)
    conn.close()

    catalog, _excluded = fetch_aifa.load_catalog(directory)
    display, products, examples, unparsed, atc_of = it_moieties(catalog)
    print(f"\nPrincipios activos italianos distintos: {len(display)} interpretables, "
          f"{len(unparsed)} que no se interpretan (se quedan en italiano)")
    print(f"Con ATC propio (algún producto de un solo principio activo): {sum(1 for k in display if atc_of.get(k))}")

    if not offline:
        enrich_all_with_aemps_atc(cima_atc, es_components.values())
    es_by_atc = collections.defaultdict(set)
    for name, codes in cima_atc.items():
        if name in es_components:  # solo nombres de UN principio activo
            for code in codes:
                es_by_atc[code].add(es_components[name])

    candidates = it_candidates(display, examples, es_components, atc_of, es_by_atc)
    # Ésteres sin ATC propio ni coincidencia: se buscan por la regla de nombres (base conocida en España).
    esters, ester_products, ester_examples = ester_candidates(catalog, "IT", es_components, set(), "ref")
    for key, (name, es) in esters.items():
        if not candidates.get(key) or all(m in ("regla", "sugerencia") for m in candidates[key].values()):
            if key not in display:
                display[key], products[key], examples[key] = name, ester_products[key], ester_examples[key]
            candidates[key] = {es: "ester"}
    print(f"Candidatos: {sum(1 for c in candidates.values() if 'regla' in c.values())} por regla, "
          f"{sum(1 for c in candidates.values() if 'atc' in c.values())} por ATC, "
          f"{sum(1 for c in candidates.values() if 'ester' in c.values())} de nivel base (éster/profármaco)")

    # Wikidata solo para los nombres que la AIFA no puede confirmar con su propio ATC.
    wikidata = {}
    pending = sorted({display[key] for key, options in candidates.items() for es, method in options.items()
                      if it_verify(key, display[key], es, method, atc_of, cima_atc)[0] == "sin_datos"})
    if pending and not offline:
        print(f"Consultando Wikidata para {len(pending)} nombres sin ATC propio en la AIFA...")
        wikidata = wikidata_by_english_label(pending, "it")

    manual = load_manual_decisions(ing.LINKS_PATH_IT)
    rows = []
    for key, options in candidates.items():
        checked = {es: (method, *it_verify(key, display[key], es, method, atc_of, cima_atc, wikidata)) for es, method in options.items()}
        confirmed = [es for es, (_m, outcome, _e) in checked.items() if outcome == "confirmado"]
        for es, (method, outcome, evidence) in checked.items():
            if outcome == "confirmado" and len(confirmed) > 1:
                status, evidence = "sugerido", f"hay {len(confirmed)} candidatos confirmados distintos; hay que decidir a mano. " + evidence
            elif outcome == "confirmado":
                status = "confirmado"
                evidence = {"regla": "regla + ", "atc": "ATC + ", "sugerencia": "sugerencia + ", "ester": "éster + "}[method] + evidence
            elif outcome == "contradice":
                status = "contradice"
            elif outcome == "sugerido":
                status = "sugerido"
            else:
                status = "sin_confirmar" if method in ("regla", "ester") else "sugerido"
            rows.append({
                "nome_it": display[key], "nombre_es": es, "estado": status,
                "nivel": ing.LEVEL_BASE if method == "ester" else ing.LEVEL_EXACT, "evidencia": evidence,
                "productos_it": len(products[key]), "ejemplos": " | ".join(examples[key]),
            })
    done = {ing.plain(r["nome_it"]) for r in rows}
    decided, merged = set(), []
    for r in rows:  # una decisión manual sustituye a TODOS los candidatos de ese nombre, y solo cuenta una vez
        key = ing.plain(r["nome_it"])
        if key in manual:
            if key not in decided:
                decided.add(key)
                merged.append(manual[key])
        else:
            merged.append(r)
    rows = merged + [row for key, row in manual.items() if key not in done]

    rows.sort(key=lambda r: (STATUS_ORDER.index(r["estado"]), -int(r["productos_it"]), r["nome_it"]))
    with open(ing.LINKS_PATH_IT, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ing.LINK_FIELDS_IT, restval=ing.LEVEL_EXACT)
        writer.writeheader()
        writer.writerows(rows)

    weight = collections.Counter()
    for r in rows:
        weight[r["estado"]] += int(r["productos_it"])
    by_status = collections.Counter(r["estado"] for r in rows)
    print(f"\nEscrito {ing.LINKS_PATH_IT} ({len(rows)} pares):")
    for status in STATUS_ORDER:
        if by_status[status]:
            print(f"  {status:14} {by_status[status]:3} pares, {weight[status]:4} productos italianos afectados")
    linked = {ing.plain(r["nome_it"]) for r in rows}
    left = sorted(((len(products[k]), display[k]) for k in display if k not in linked), reverse=True)
    print(f"\nSin ningún candidato ({len(left)}), los más frecuentes:")
    print(", ".join(f"{name} ({n})" for n, name in left[:80]))


def main_fr(offline):
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

    # Nivel base: ésteres/profármacos cuya base sí existe en España.
    esters, ester_products, ester_examples = ester_candidates(catalog, "FR", es_components, set(proposals), "cis")
    print(f"Candidatos de nivel base (éster/profármaco): {len(esters)}")
    for key, (name, es) in esters.items():
        display[key] = name
        products[key], examples[key] = ester_products[key], ester_examples[key]
        proposals[key] = (es, "ester")

    pairs = sorted({(display[key], es) for key, (es, _m) in proposals.items()})
    if not offline:
        enrich_with_aemps_atc(cima_atc, {es for _fr, es in pairs})
    checks = verify(pairs, cima_atc, offline)

    # Para los ésteres sin datos en francés, se prueba el nombre inglés reordenado.
    retry = [(display[k], es) for k, (es, m) in proposals.items()
             if m == "ester" and checks[(display[k], es)][0] == "sin_datos"]
    english = {pair: english_ester_name(pair[0]) for pair in retry}
    if retry and not offline:
        try:
            found = english_label_check([(english[p], p[1]) for p in retry if english[p]], cima_atc)
        except Exception as exc:
            print(f"[aviso] la comprobación inglesa de ésteres falló ({exc})")
            found = {}
        for pair in retry:
            result = found.get((english[pair], pair[1]))
            if result:
                checks[pair] = result

    manual = load_manual_decisions(ing.LINKS_PATH)
    rows = []
    for key, (es, method) in proposals.items():
        outcome, evidence = checks[(display[key], es)]
        if outcome == "confirmado":
            status = "confirmado"
            evidence = {"sugerencia": "sugerencia + ", "ester": "éster + "}.get(method, "regla + ") + evidence
        elif outcome == "contradice":
            status = "contradice"
        else:
            status = "sugerido" if method == "sugerencia" else "sin_confirmar"
        row = {
            "nombre_fr": display[key], "nombre_es": es, "estado": status,
            "nivel": ing.LEVEL_BASE if method == "ester" else ing.LEVEL_EXACT, "evidencia": evidence,
            "productos_fr": len(products[key]), "ejemplos": " | ".join(examples[key]),
        }
        rows.append(manual.get(key, row))
    for key, row in manual.items():  # decisiones manuales de pares que ya no se proponen
        if key not in proposals:
            rows.append(row)

    rows.sort(key=lambda r: (STATUS_ORDER.index(r["estado"]), -int(r["productos_fr"]), r["nombre_fr"]))
    with open(ing.LINKS_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ing.LINK_FIELDS, restval=ing.LEVEL_EXACT)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", choices=("fr", "uk", "it"), default="fr")
    ap.add_argument("--zip", help="ZIP de NHS dm+d (solo con --country uk)")
    ap.add_argument("--dir", help="carpeta con los CSV de la AIFA (solo con --country it); si falta, se descargan")
    ap.add_argument("--offline", action="store_true", help="sin Wikidata ni AEMPS (nada queda confirmado)")
    args = ap.parse_args()
    if args.country == "it":
        main_it(args.dir or fetch_aifa.download(os.path.join(tempfile.gettempdir(), "aifa")), args.offline)
    elif args.country == "uk":
        if not args.zip:
            sys.exit("Con --country uk hace falta --zip RUTA_AL_ZIP_DE_DMD")
        main_uk(args.zip, args.offline)
    else:
        main_fr(args.offline)


if __name__ == "__main__":
    main()
