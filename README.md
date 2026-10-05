# MediPass · base de datos + app

## Idea del esquema

La tabla puente es `active_ingredients` (el principio activo / DCI), no el
producto. Es lo único que es objetivamente igual entre países — la marca
comercial cambia, el principio activo no. `products` cuelga de ahí, con una
fila por (principio activo, país, marca).

```
countries ──┐
            ├──< products >──── active_ingredients
```

**La unidad de equivalencia es principio activo + forma farmacéutica**, no solo
el principio activo. "Diclofenaco · gel" y "diclofenaco · comprimido" son
grupos distintos: un gel y unas pastillas no son intercambiables. Las
combinaciones también son grupos aparte ("dimenhidrinato" no es lo mismo que
"dimenhidrinato + cafeína"); CIMA ya las distingue.

## Estado real de los datos ahora mismo

| País | Filas | Fuente | Fiabilidad |
|---|---|---|---|
| 🇪🇸 España | 1.014 | **CIMA API (AEMPS)** — pública, JSON, sin login | Real, oficial |
| 🇫🇷 Francia | 1.493 | **BDPM (ANSM/data.gouv.fr)** — descarga pública oficial | Real, oficial |
| 🇬🇧 Reino Unido | 1.239 | **NHS dm+d (NHSBSA)** — descarga con cuenta gratuita en NHS TRUD, licencia OGL v3.0 | Real, oficial |
| 🇩🇪🇮🇹🇵🇹 DE/IT/PT | 6 por país | `manual_seed` (escritos a mano, de memoria) | **Sin verificar** — ejemplos para poder probar la app, no para producción |

El Reino Unido conserva además 5 ejemplos manuales (los que todavía no tienen
un producto real de la misma forma con el que sustituirlos).

**España** es el catálogo de CIMA de medicamentos **comercializados y sin
receta** (`comerc=1&receta=0`): 1.066 registros, de los que se guardan 1.014
(52 se omiten porque repiten principio activo y nombre con otro nº de
registro y, para el usuario, serían filas idénticas). Cada producto lleva
forma, dosis, composición, código ATC y grupo terapéutico; 395 tienen foto.

**Francia** es la BDPM filtrada a comercializados, sin ninguna condición de
receta y sin homeopáticos (`fetch_bdpm.py`): 1.512 candidatos, de los que se
guardan 1.493 (19 se omiten por el mismo motivo que en España). Los
homeopáticos se detectan con dos señales (la etiqueta de procedimiento
"Enreg homéo" y que la sustancia diga "préparations homéopathiques"); con
solo la primera se colaron 132 hasta que se comprobó. A diferencia de CIMA:
- La BDPM **no tiene un campo booleano de receta**. Se infiere: un
  medicamento es sin receta si está comercializado y su código CIS **no**
  aparece en el archivo de condiciones de prescripción (`CIS_CPD_bdpm.txt`).
  Verificado con un caso real: Doliprane (paracetamol solo) no aparece ahí;
  Codoliprane (paracetamol + codeína) sí.
- **No tiene foto ni código ATC** en los archivos públicos — esas columnas
  quedan vacías para Francia.
- La forma es texto libre en francés (no una categoría fija como en CIMA).
  Se traduce a la de CIMA con `form_map_fr.csv` (ver "Enlace entre idiomas");
  lo que no está en la tabla queda con su forma en francés.
- Los archivos vienen en **Windows-1252**, no UTF-8.
- Licencia: reutilización libre citando fuente y fecha, sin alterar los
  datos ([texto de la licencia](https://base-donnees-publique.medicaments.gouv.fr/docs/telechargement/licence_bdpm.pdf)).
  La fecha de la descarga queda en la columna `verified_at` de cada producto
  francés.

**Reino Unido** es el NHS dm+d (versión 9.3.0, publicada el 28/09/2026)
filtrado a medicamentos **sin receta** (`fetch_dmd.py`): 1.936 candidatos, de
los que se guardan 1.239 (697 se omiten porque repiten principio activo y
nombre comercial exacto, muy habitual en genéricos de varios laboratorios).
Cómo se decide qué es "sin receta":
- Cada **envase** lleva una categoría legal: `GSL` (venta libre), `P` (solo en
  farmacia, sin receta; lo dispensa un farmacéutico) o `POM` (con receta).
  Un producto entra si tiene **algún envase activo P o GSL**. P cuenta como
  "sin receta", igual que en España; la app lo aclara en el pie. Hay 90
  productos con envases P y POM a la vez (según el tamaño del envase): se
  incluyen porque tienen un envase P.
- Se excluyen envases descatalogados o inválidos, productos sin licencia
  (MHRA/EMA o hierbas tradicionales), importados, "Special" (preparados a
  medida), no disponibles y homeopáticos (63).
- Los ingredientes vienen con la sal ("Benzydamine hydrochloride"). El campo
  `BS_SUBID` (sustancia base) del dm+d **no se usa**: a veces reduce un éster a
  su base (betamethasone valerate → betamethasone, que no son equivalentes) o
  se equivoca (ioversol → iodine). Se usa nuestro parser conservador.
- Forma y vía vienen normalizadas (una forma por producto). Se traducen con
  `form_map_uk.csv` (54 filas, 89 % de los productos). Si un producto tiene
  **varias vías** ("Oromucosal; Gingival; Nasal; …") se exige que la vía de la
  tabla sea idéntica: si no, un spray de varias vías acabaría clasificado
  como "pulverización bucal".
- **Atribución obligatoria (OGL v3.0)**: *Contains public sector information
  licensed under the Open Government Licence v3.0.* Fuente: NHS Business
  Services Authority, dm+d. El pie de la app lo cita, y la fecha de la
  descarga queda en `verified_at`. El ZIP se baja de
  [NHS TRUD](https://isd.digital.nhs.uk) (elemento 24, "NHSBSA dm+d").
- La clave de API de TRUD va en `.env` (`TRUD_API_KEY=...`), que **nunca se
  sube a GitHub** (está en `.gitignore`).

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, con su propio formato. La ruta lógica es: dejar el esquema
listo para todos, conectar cada país de verdad, y sustituir cada ejemplo
manual por una fuente real cuando la investiguemos.

**Comparaciones que hoy funcionan con datos reales de dos países**: **80
grupos** (principio activo + forma) tienen productos en España y en Francia,
con 409 productos españoles y 520 franceses dentro de ellos. Los mayores:
paracetamol · comprimido, ibuprofeno (comprimido, solución oral, gel,
cápsula), diclofenaco · gel, nicotina (parche, chicle, comprimido para
chupar), clorhexidina · líquido de uso tópico (antisépticos de piel; los
enjuagues bucales franceses quedan aparte, ver abajo), loperamida, omeprazol
y combinaciones como paracetamol + cafeína. Además, dimenhidrinato ·
comprimido compara España (real) con el ejemplo manual de Francia, porque
Francia no tiene ningún comprimido suelto de dimenhidrinato sin receta (solo
jarabe y cápsula, que son grupos distintos).

Con el Reino Unido: **74 grupos** comparan España con el Reino Unido
(386 productos españoles y 383 británicos), **51 grupos** Francia con el Reino
Unido (393 y 302) y **43 grupos** existen en los tres países. Los mayores:
ibuprofeno (comprimido, gel, solución oral, cápsula), paracetamol (comprimido,
supositorio, solución oral, efervescente), ácido acetilsalicílico, nicotina
(parche, chicle, comprimido para chupar), cetirizina, loratadina, clotrimazol
y bencidamina. Cuando un nombre no tiene enlace con España pero es **idéntico
en francés y en inglés** (p. ej. *lactulose*, *sennosides*), la comparación
Francia-Reino Unido se hace por nombre idéntico: son nombres internacionales
(DCI), pero no están comprobados con Wikidata.

Lo que ninguna de las dos fuentes cubre:
- **Docusato sódico**: no comercializado sin receta en España. Francia tiene
  1 producto (un gel), pero España no tiene nada con qué compararlo todavía.
- **Enjuagues/pastillas de garganta con clorhexidina**: en España no existen
  sin receta (son parafarmacia); en Francia sí existen, pero se guardan como
  su propio grupo en francés (p.ej. "clorhexidina · solution pour bain de
  bouche"), sin forzarlos a compararse con los antisépticos de piel.
- **Productos sanitarios y parafarmacia** (apósitos, etc.): ni CIMA ni la
  BDPM son bases de datos de eso.

## Enlace entre idiomas

Los principios activos y las formas se escriben distinto en cada país
(*ibuprofène* / ibuprofeno, *comprimé pelliculé* / comprimido recubierto con
película), así que para comparar hay que enlazarlos. La regla del proyecto:
**un enlace solo existe si se ha comprobado**, nunca por parecido de nombres
(hay medicamentos de nombre casi idéntico y efectos muy distintos, como
clonidina y clonazepam).

**Principios activos** (`ingredients.py`, `curate_ingredient_links.py`,
`ingredient_links.csv`):
- *Qué cuenta como "el mismo"*: la misma molécula aunque cambie la sal
  (diclofenaco sódico o dietilamina, lopéramide o su clorhidrato), que es lo
  que hace el `vtm` de CIMA. No cuentan los ésteres (el dipropionato de
  betametasona no es betametasona) ni las sales inorgánicas enteras
  (*carbonate de calcium* no es "calcium").
- *Cómo se propone un par*: se limpia el nombre francés (se quita la sal) y,
  con reglas fijas de terminaciones (-ène → -eno, -ine → -ina, -ide → -ida...),
  debe quedar **idéntico** a un nombre español que ya tengamos.
- *Cómo se comprueba*, con fuentes independientes de esas reglas: Wikidata
  (¿un mismo elemento tiene los dos nombres?), el artículo de Wikipedia en
  francés, y sobre todo el **código ATC**: el que da Wikidata debe coincidir
  con el que da el maestro oficial de la AEMPS para el nombre español. Esto
  cubre incluso diferencias de ortografía (méclozine / meclozina, que
  Wikipedia escribe *meclizina*).
- *Combinaciones*: se comparan como conjunto, así que "caféine + paracétamol"
  es lo mismo que "paracetamol + cafeína".
- *Estados* de `ingredient_links.csv`: `confirmado` y `aprobado` se usan;
  `sin_confirmar`, `sugerido`, `contradice` y `rechazado` no. Hoy hay **73
  confirmados**. Seis pares siguen sin comprobación independiente (parafina
  líquida, amilmetacresol, l-cistina, carbocysteine, mirtecaína y carmelosa;
  45 productos): esperan que alguien con conocimiento farmacéutico los
  apruebe, cambiando `sin_confirmar` por `aprobado` en el archivo.
- `python curate_ingredient_links.py` vuelve a proponer y comprobar los
  pares (conserva las decisiones manuales). El importador **nunca** crea
  enlaces por su cuenta: solo lee el archivo.

**Formas** (`form_map_fr.csv`): cada fila lleva la forma francesa exacta, la
vía de administración que debe cumplir (un gel *cutanée* no es un gel
*ophtalmique*), la forma de CIMA y la evidencia de cómo clasifica CIMA esa
forma. La forma de destino se escribe siempre con el valor exacto que ya hay
en España (CIMA a veces la escribe con tildes, `SOLUCIÓN/SUSPENSIÓN ORAL`, y a
veces sin ellas). Son 59 filas y cubren el 81 % de los productos franceses;
lo ambiguo o sin equivalente (colutorios, inyectables, "comprimido para chupar
o masticar"...) se queda en francés y no se compara.

**Reino Unido** (`parse_substance_en()` en `ingredients.py`,
`ingredient_links_uk.csv`, `form_map_uk.csv`): mismas reglas que en Francia.
- Solo se quita la sal de una **base orgánica** (*loperamide hydrochloride* →
  loperamide, *ibuprofen lysine* → ibuprofen). Se dejan enteros los ésteres
  (*beclometasone dipropionate*), los derivados distintos (*hyoscine
  butylbromide* **no** es hioscina) y las sales inorgánicas (*calcium
  carbonate*); lo que lleva cifras o es un elemento suelto (*oxygen*) no se
  interpreta.
- Los candidatos salen de reglas ortográficas (*-ine → -ina*, *chloride →
  cloruro*, *ferrous → hierro*), del nombre español que Wikidata da al nombre
  inglés, o de un nombre de una palabra casi igual (*benzydamine* ≈
  bencidamina). **Ninguno se usa sin comprobar**: el código ATC de Wikidata
  debe coincidir con el que da la AEMPS al nombre español (o, para las
  reglas, que un mismo elemento de Wikidata tenga los dos nombres, aunque
  cambie el orden: "cloruro de benzalconio" = "benzalconio cloruro"). Si los
  ATC son distintos queda como `contradice` (así se descartó, por ejemplo,
  cyclizine ≈ cetirizina).
- `python curate_ingredient_links.py --country uk --zip RUTA_AL_ZIP` regenera
  la tabla (conserva las decisiones manuales). Hoy: **63 confirmados**, 2
  aprobados a mano, 8 sin confirmar (98 productos) y 8 sugeridos (50
  productos).
- **Dos pares aprobados a mano, pendientes del visto bueno de una persona con
  conocimiento farmacéutico**: *sodium bicarbonate* → sodio bicarbonato y
  *sodium chloride* → sodio cloruro. Wikidata y la AEMPS los marcaban como
  contradictorios solo porque listan ATC de usos distintos (intravenoso frente
  a antiácido o nasal); es la misma sustancia química. Si no estás de acuerdo,
  cambia `aprobado` por `rechazado` en `ingredient_links_uk.csv`.
- Sin confirmar (no se usan): alginato sódico, prometazina, citrato sódico,
  cloruro de benzalconio, fumarato de hierro, amilmetacresol, dimeticona y
  carmelosa. El nombre coincide al traducirlo, pero Wikidata no tiene datos
  para comprobarlo. Esperan revisión farmacéutica (cambiar `sin_confirmar` por
  `aprobado`).
- Tampoco se enlazan, por falta de confirmación: **levomenthol con mentol**
  (Wikidata no da ATC para comprobarlo; el levomentol es solo uno de los
  isómeros del mentol), las enzimas (amilasa, lipasa, proteasa), y la
  equinácea y el tomillo (extractos de planta, con varias especies posibles).

**Pruebas**: `python -m unittest test_ingredients test_fetch_bdpm test_fetch_dmd -v`.
Incluyen pares que **nunca** deben enlazarse (alanina / alantoína, ketoprofeno /
piketoprofeno, *hyoscine butylbromide* / hioscina, ésteres y sus bases...),
combinaciones de forma y vía que no deben traducirse, y un ZIP de dm+d en
miniatura para comprobar la regla de "sin receta" (solo POM fuera; P y GSL
dentro; descatalogados, sin licencia, importados y homeopáticos fuera).

**Avisos en la app** cuando un país no tiene el grupo que se mira: "hay
productos con este principio activo, pero en otra forma (…); no son
equivalentes"; "no hemos encontrado en [país] ningún producto de venta libre
con este principio activo"; y, para países sin datos reales, "todavía no
tenemos datos verificados". Las tarjetas de ejemplos manuales llevan la
etiqueta "Ejemplo sin verificar".

## Alcance legal

Antes de mostrar esto a usuarios reales, investigamos la Directiva 2001/83/CE
de la UE, que en su artículo 88 prohíbe la publicidad de medicamentos sujetos
a receta médica dirigida al público general. La conclusión: el catálogo de
MediPass, para uso con usuarios reales, debería limitarse a tres categorías:

- **Medicamento sin receta** (OTC)
- **Producto sanitario**
- **Parafarmacia**

y excluir cualquier medicamento con receta del catálogo público.

**Estado actual de la implementación, tal como es hoy:**
- Para **España, Francia y el Reino Unido** ya se cumple por construcción:
  `fetch_cima.py`, `fetch_bdpm.py` y `fetch_dmd.py` solo importan
  medicamentos sin receta, así que la base no contiene ningún medicamento real
  de esos países con receta. En el Reino Unido, el estatus P (solo en
  farmacia) cuenta como "sin receta" pero la app hoy lo muestra como "Venta
  libre" igual que el GSL: distinguirlos requiere el `legal_category` de abajo.
- **Todavía no hay campo `legal_category`** en el esquema ni filtro en la app.
- **Productos sanitarios y parafarmacia** no tienen ninguna fuente real
  todavía (ver "Próximos pasos"); solo hay ejemplos manuales.
- Los ejemplos manuales de los países restantes (DE/IT/PT) no están
  verificados y uno de ellos (Voltaren Schmerzgel Forte, Alemania) está
  marcado como "con receta", lo que es un dato de ejemplo, no una fuente.

**Esto no es asesoría legal.** Es una interpretación de no-abogados de un
texto normativo. Antes de lanzar esto a usuarios reales hay que consultarlo
con un abogado especializado en derecho farmacéutico/sanitario.

## Arquitectura actual

```
medipass.db  ←── backend/app.py (Flask, puerto 5000)  ←── frontend/ (Vite + React, puerto 5173)
```

- **`backend/app.py`** — expone `GET /api/equivalences`, que devuelve la vista
  `equivalences` de `medipass.db` (todo el catálogo, ~450 KB en JSON). La
  respuesta va comprimida con gzip (~47 KB): además de ahorrar ancho de banda,
  en algunas máquinas Windows las respuestas grandes por localhost se cortan
  a medias y la conexión se cuelga ~19 s.
- **`frontend/`** — proyecto Vite + React. Busca por principio activo, forma o
  marca; compara entre países; muestra foto, composición y dosis del producto
  de España; y ofrece un listado completo de los medicamentos de España.
  Agrupa por principio activo + forma y, como cada país puede tener muchos
  productos por grupo, enseña uno y cuenta cuántos más hay ("y 18 más de esta
  forma en España"). Buscando por una marca concreta se muestra esa marca.
  Cuando un país no tiene el grupo, explica por qué (otra forma, no
  encontrado o sin datos verificados) y marca los ejemplos manuales.
- **`medipass-prototype.jsx`** (en la raíz) — el prototipo original con datos
  de ejemplo en memoria. Ya no se usa; quedó como referencia de diseño.

## Archivos

- `schema.sql` — esquema (tablas + vista `equivalences`); se puede volver a
  ejecutar, recrea la vista
- `seed_base.sql` — países + principios activos base
- `seed_manual_non_es.sql` — productos de ejemplo para DE/IT/PT/UK (y los que
  Francia y el Reino Unido todavía no tienen con qué reemplazar, como los
  apósitos)
- `fetch_cima.py` — sincroniza España desde CIMA (ver abajo)
- `fetch_bdpm.py` — sincroniza Francia desde la BDPM (ver abajo)
- `fetch_dmd.py` — sincroniza el Reino Unido desde NHS dm+d (ver abajo)
- `importers.py` — piezas comunes de los importadores extranjeros (tabla de
  formas, vocabulario español, sincronización de `products`)
- `ingredients.py` — enlace de principios activos entre idiomas (ver "Enlace
  entre idiomas")
- `ingredient_links.csv`, `ingredient_links_uk.csv` — tablas de enlaces
  revisadas (las usan los importadores)
- `curate_ingredient_links.py` — propone y comprueba enlaces nuevos
- `form_map_fr.csv`, `form_map_uk.csv` — traducción de formas francesas e
  inglesas a las de CIMA
- `.env` — clave de API de NHS TRUD (no se sube a GitHub)
- `test_ingredients.py`, `test_fetch_bdpm.py`, `test_fetch_dmd.py` — pruebas
- `medipass.db` — la base ya construida
- `backend/app.py` — servidor Flask
- `frontend/` — app Vite + React

## Cómo correr el proyecto

Hacen falta dos terminales, una para el backend y otra para el frontend.

**Terminal 1 — backend:**
```bash
cd backend
pip install flask flask-cors
python app.py
```
Queda escuchando en `http://127.0.0.1:5000`.

**Terminal 2 — frontend:**
```bash
cd frontend
npm install
npm run dev
```
Queda escuchando en `http://localhost:5173`.

Con ambos corriendo, abre **`http://localhost:5173`** en el navegador.

## Actualizar los datos de España, Francia y el Reino Unido

Los tres scripts son sincronizaciones: se pueden ejecutar cuando quieras sin
duplicar nada. Actualizan lo que existe, añaden lo nuevo, borran lo que ya
no cumpla el filtro, y quitan los ejemplos manuales de un país en cuanto
llega un dato real de la misma forma que los sustituye.

```bash
pip install requests

python fetch_cima.py                    # sincroniza y completa el detalle que falte
python fetch_cima.py --no-details       # solo el listado (rápido, sin ATC/composición)
python fetch_cima.py --refresh-details  # vuelve a pedir el detalle de todos (~5 min)
python fetch_cima.py --debug            # imprime el JSON crudo de 1 medicamento

python fetch_bdpm.py                    # sincroniza Francia (descarga ~10 MB cada vez)
python fetch_bdpm.py --debug            # descarga y analiza, sin tocar medipass.db

python fetch_dmd.py --zip RUTA_AL_ZIP   # Reino Unido, con el ZIP ya descargado de NHS TRUD
python fetch_dmd.py                     # igual, descargando la última versión (necesita TRUD_API_KEY en .env)
python fetch_dmd.py --zip RUTA --debug  # analiza y muestra el informe, sin tocar medipass.db
python fetch_dmd.py --zip RUTA --inspect  # solo cuenta formas y vías del ZIP
```

Ejecuta **primero `fetch_cima.py`**: los importadores de Francia y del Reino
Unido enlazan con los principios activos españoles que ya estén en la base.
`--debug` enseña cuántos productos se enlazan, cuántas formas se traducen,
las formas que se quedan sin traducir y cuántas comparaciones con España salen.

Para el Reino Unido hace falta una cuenta gratuita en
[NHS TRUD](https://isd.digital.nhs.uk), suscribirse al elemento 24 «NHSBSA
dm+d» (hay que explicar para qué se quieren los datos) y descargar el ZIP o
copiar la clave de API en `.env`. Con la clave, `fetch_dmd.py` comprueba la
suma SHA-256 del ZIP descargado contra la que publica TRUD.

El detalle de CIMA se pide con 4 peticiones en paralelo, por cortesía con la
API pública (unos 5 minutos para ~1.000 productos).

### Construir la base desde cero

```bash
python -c "
import sqlite3
c = sqlite3.connect('medipass.db')
for f in ('schema.sql', 'seed_base.sql', 'seed_manual_non_es.sql'):
    c.executescript(open(f, encoding='utf-8').read())
"
python fetch_cima.py
python fetch_bdpm.py
python fetch_dmd.py --zip RUTA_AL_ZIP
```

## Consultar la base directamente

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('medipass.db')
for row in conn.execute(\"SELECT country_code, brand_name, dose, form FROM equivalences WHERE inn_name='dimenhidrinato'\"):
    print(row)
"
```

## Límites conocidos

- Los datos de Alemania, Italia y Portugal son ejemplos sin verificar.
- Cada grupo enseña **un** producto por país (el primero por nombre) y cuenta
  los demás; puedes elegir uno concreto buscando su marca. **La dosis no se
  compara**: "equivalente" significa mismo principio activo y misma forma, y
  los dos productos que se enseñan pueden tener concentraciones distintas
  (por ejemplo, Dalsydol 400 mg en España frente a Advil 200 mg en Francia o
  Anadin Joint Pain 200 mg en el Reino Unido).
- La forma de España es la "simplificada" de CIMA (36 valores en venta
  libre, bastante gruesa: "solución/suspensión oral" agrupa jarabes, polvos y
  granulados). La de Francia se traduce con `form_map_fr.csv` (81 % de los
  productos); el resto conserva su forma en francés y no se compara.
- Solo se enlazan 585 de los 1.512 productos franceses con un principio
  activo español; otros 632 tienen un principio activo que no está en la tabla
  (muchos no tienen equivalente de venta libre en España), 251 tienen un
  nombre que no se interpreta con seguridad y 44 son combinaciones sin
  equivalente español. Las combinaciones francesas con todos los componentes
  enlazados pero sin equivalente en España conservan su nombre francés.
- Que un medicamento francés sea "sin receta" es una regla **inferida**
  (no aparece en el archivo de condiciones de prescripción), no un campo
  explícito como en CIMA. Se verificó con un caso real, pero no se auditó
  exhaustivamente.
- La dosis de España se muestra tal como la da CIMA, que a veces no indica a
  qué unidad se refiere. Francia no tiene columna de dosis única: se guarda
  solo la composición (nombres de sustancias, sin cantidades).
- Los grupos terapéuticos (ATC) de CIMA vienen sin tildes. Francia no tiene
  ATC ni foto en los archivos que usamos.
- Solo ~39 % de los productos de España tienen foto en CIMA; Francia no
  tiene ninguna.
- La tabla `active_ingredients` mezcla nombres en español (los de España y
  los ejemplos), en francés (467 que trajo la BDPM sin equivalente enlazado)
  y en inglés (331 que trajo el dm+d, de un total de 1.076): un principio
  activo sin enlace conserva su nombre en el idioma de su fuente.
- Reino Unido: de los 1.239 productos guardados, **493 quedan enlazados con
  un principio activo español** (los demás no tienen equivalente de venta
  libre en España o su nombre no se pudo comprobar). Los 697 omitidos por
  nombre repetido son, en su mayoría, el mismo genérico de varios
  laboratorios: no se pierde ninguna combinación principio activo + forma.
  El dm+d cubre lo que circula por el NHS; si falta algún medicamento de
  venta libre habitual, será por eso (no se ha auditado exhaustivamente).
- Reino Unido: `GSL` y `P` se guardan igual (sin receta) y la app no los
  distingue; el estatus legal exacto no se almacena todavía.
- El estado "solo se vende con receta en ese país" **no se guarda** (haría
  falta conservar un estado sin marcas, y antes hay que consultarlo con un
  abogado): hoy un principio activo que en Francia solo existe con receta
  sale como "no hemos encontrado en Francia ningún producto de venta libre".

## Próximos pasos

- Que alguien con conocimiento farmacéutico revise los 6 pares sin comprobar
  de `ingredient_links.csv` (45 productos), los 8 de `ingredient_links_uk.csv`
  (98 productos) y los 2 aprobados a mano (bicarbonato y cloruro sódicos), y
  apruebe o rechace lo que proceda
- Comparar la **dosis** (hoy no se compara): requiere normalizar unidades y
  sales, y elegir en cada país el producto de la misma concentración

- Conseguir acceso a **BotPlus/BADIS** o **Medipim** para datos reales de
  parafarmacia y productos sanitarios (hoy no hay ninguna fuente real);
  antes, preguntarles si su licencia permite una app para el público
- **Alemania, Italia y Portugal siguen sin fuente abierta utilizable** (lo que
  se encontró en octubre de 2026):
  - *Alemania*: el BfArM solo publica un ZIP con nombres de sustancias
    (`pnbez-*.zip`), no el catálogo de productos con forma y estatus.
  - *Italia*: AIFA publica CSV de medicamentos reembolsables (clases A/H),
    genéricos y faltas de suministro; no el catálogo completo de venta libre.
  - *Portugal*: los datos abiertos de INFARMED son solo ensayos clínicos; el
    catálogo de medicamentos es de pago.
  Hay que volver a mirarlo (o pedir acceso a las agencias) antes de conectarlos.
- Cada país nuevo repite el proceso: su propia tabla de formas y volver a
  ejecutar `curate_ingredient_links.py` para enlazar sus principios activos
- Implementar de verdad el `legal_category` y el filtrado descrito en
  "Alcance legal" — hoy solo se cumple para España, Francia y el Reino Unido
  por cómo se importan, no por un filtro explícito en el esquema (ahí
  entraría también distinguir `GSL` de `P` en el Reino Unido)
- Desplegar a **Vercel** cuando esté lista para compartir con otras personas

### Para después de cerrar la integración de las bases de datos

Caso de uso real que hoy la app **no cubre**: estás en París con catarro, sabes
que en España te va bien el Frenadol, no hablas francés y necesitas encontrar
algo parecido en la farmacia.

Qué dicen los datos hoy (octubre de 2026):
- Frenadol Forte y Junior llevan paracetamol + clorfenamina + dextrometorfano;
  Frenadol Descongestivo añade pseudoefedrina.
- En los datos oficiales de Francia **ningún producto con dextrometorfano se
  vende sin receta**, así que un equivalente exacto no puede existir. La app
  dice "no hemos encontrado", que es correcto pero no ayuda.
- Lo más cercano en venta libre son los sobres de granulado Fervex y
  Rhinofebral (paracetamol + feniramina, un antihistamínico de la misma
  familia que la clorfenamina, + vitamina C). **No son equivalentes**: no
  llevan antitusivo y las dosis no se han comparado.

Pasos propuestos, por orden:
1. **Tarjeta "Cómo pedirlo en la farmacia"**: pantalla en francés, lista para
   enseñar, con el producto de origen, sus principios activos con el nombre
   francés (salen de `ingredient_links.csv`; para los que no tienen
   equivalente allí, como el dextrometorfano, habría que sacar el nombre
   francés de Wikidata a partir del ATC de la AEMPS), una frase hecha
   ("Bonjour, je suis enrhumée et je ne parle pas français. En Espagne je
   prends du Frenadol (…). Auriez-vous quelque chose de similaire, sans
   ordonnance ?") y el aviso de qué ingrediente no se vende sin receta allí.
   No recomienda nada: ayuda a que el farmacéutico entienda lo que buscas.
   Para el aviso de "sin receta allí" hace falta guardar el estado "solo con
   receta" sin marcas (decisión pendiente, consultar antes con el abogado).
2. **"Alternativas parecidas"**: productos del otro país que comparten la
   *familia* de principios activos (código ATC de nivel 4: clorfenamina y
   feniramina son R06AB), siempre mostrando "comparte / no tiene / no son
   equivalentes". Hace falta el ATC de los ingredientes franceses (Wikidata,
   como en `curate_ingredient_links.py`). Como sugiere medicamentos al
   público, revisarlo con el abogado antes de publicarlo.
3. **Arreglo de datos**: Frenadol Complex está guardado con el principio
   activo "multicomponente" (así lo da el `vtm` de CIMA) y no se agrupa bien;
   habría que agruparlo por su composición real.

Requisitos previos: comparar la dosis, resolver los 6 pares sin comprobar y
tener otros países reales; si no, las sugerencias serían poco fiables.
