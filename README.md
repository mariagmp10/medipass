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
| 🇪🇸 España | 11.556 (1.016 sin receta + 10.540 con receta) | **CIMA API (AEMPS)** — pública, JSON, sin login | Real, oficial |
| 🇫🇷 Francia | 9.208 (1.493 sin receta + 7.715 con receta) | **BDPM (ANSM/data.gouv.fr)** — descarga pública oficial | Real, oficial |
| 🇬🇧 Reino Unido | 5.661 (1.231 sin receta, 641 de ellos «solo en farmacia», + 4.430 con receta) | **NHS dm+d (NHSBSA)** — descarga con cuenta gratuita en NHS TRUD, licencia OGL v3.0 | Real, oficial |
| 🇮🇹 Italia | 8.635 (1.482 sin receta, 650 de ellos «SOP» solo en farmacia, + 7.149 con receta) | **AIFA (Agenzia Italiana del Farmaco)** — descarga pública en CSV, licencia CC-BY 4.0 | Real, oficial |
| 🇩🇪🇵🇹 DE/PT | 6 por país | `manual_seed` (escritos a mano, de memoria) | **Sin verificar** — ejemplos para poder probar la app, no para producción |

El Reino Unido conserva además 5 ejemplos manuales e Italia 4 (los que todavía no tienen
un producto real de la misma forma con el que sustituirlos).

**Desde octubre de 2026 la base incluye también los medicamentos CON receta** (decisión de
María), marcados con un aviso rojo grande en la app y con un interruptor para ocultarlos
(`INCLUDE_PRESCRIPTION`; ver "Alcance legal"). No se incluyen inyectables ni productos de uso
hospitalario, en ninguno de los cuatro países. Todo lo que sigue sobre cada fuente describe cómo
se decide qué entra.

**España** es el catálogo de CIMA de medicamentos **comercializados**, sin receta
(`comerc=1&receta=0`, 1.067 registros) y con receta (`receta=1`, 15.043 registros, de los que
se importan 11.490: se excluyen 2.534 de "uso hospitalario" y 1.019 inyectables). Se guardan
11.556 en total (los demás se omiten porque repiten principio activo y nombre con otro nº de
registro y, para el usuario, serían filas idénticas). Cada producto lleva forma, dosis, estatus
legal (`legal_category` y la condición de prescripción original en `legal_note`) y foto si la
hay. **El detalle (código ATC, composición) solo se pide para los sin receta**: pedirlo para
los de receta son ~10.000 peticiones más (`python fetch_cima.py --details-rx`, más de una hora).
Los de receta no tienen ATC ni composición en la base.

**Francia** es la BDPM filtrada a comercializados y sin homeopáticos (`fetch_bdpm.py`):
9.334 candidatos (1.512 sin receta y 7.822 con receta; se excluyen 1.995 inyectables, 868 de uso
hospitalario y 1.451 homeopáticos), de los que se guardan 9.208 (los demás repiten principio
activo y nombre). Los homeopáticos se detectan con dos señales (la etiqueta de procedimiento
"Enreg homéo" y que la sustancia diga "préparations homéopathiques"); con solo la primera se
colaron 132 hasta que se comprobó. A diferencia de CIMA:
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

**Reino Unido** es el NHS dm+d (versión 9.3.0, publicada el 28/09/2026) (`fetch_dmd.py`):
17.731 candidatos (1.936 sin receta y 15.795 con receta), de los que se guardan 5.661 (12.070 se
omiten porque repiten principio activo y nombre comercial exacto, muy habitual en genéricos de
varios laboratorios; no se pierde ninguna combinación principio activo + forma). De los de receta
se excluyen los productos sin licencia (unos 7.900 "unlicensed specials"), los de hospital (3.630)
y los inyectables (1.736). Cómo se decide qué es "sin receta":
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
  `form_map_uk.csv` (83 filas, 98 % de los productos). Si un producto tiene
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

**Italia** es el catálogo de la AIFA (`fetch_aifa.py`, datos del 26/10/2026; los archivos no traen número de
versión, así que se usa la fecha de descarga): 160.225 envases, de los que se guardan 8.631 productos
(1.482 sin receta y 7.149 con receta; los 4 ejemplos manuales restantes siguen en la base). Se excluyen
74.313 envases homeopáticos, 2.578 de **importación paralela** (medicamentos de otro país reetiquetados:
duplican un producto que ya está, y el Reino Unido también excluye los importados), 33 no autorizados, los de
uso exclusivamente hospitalario o del especialista (1.305), los inyectables con receta (1.589) y los de
diálisis o lavado (40). «Vendibili al pubblico su prescrizione di centri ospedalieri o di specialisti» sí
se queda: se compra en la farmacia. Cómo se decide qué es «sin receta»:
- La columna `FORNITURA` trae el régimen oficial: «non soggetti a prescrizione medica, **da banco**» (OTC;
  se guarda como `libre`) o «…**ma non da banco**» (SOP, sin receta pero sin publicidad al público; se guarda
  como `solo_farmacia`, que la app enseña como «Sin receta, solo en farmacia»). Un producto con algún envase sin
  receta cuenta como sin receta, igual que en el Reino Unido. La etiqueta original queda en `legal_note`.
- Un producto es un `COD_FARMACO`; si tiene varias formas (267 sin receta), cada forma es un producto.
- La forma (texto italiano, sin vía de administración) se traduce con `form_map_it.csv` (103 filas, 96 % de los
  productos), con la misma evidencia de CIMA que las tablas francesa e inglesa.
- Los principios activos (`PA_ASSOCIATI`) vienen con la sal detrás («PIRIDOSSINA CLORIDRATO»), a veces repetidos o
  en otro idioma («IBUPROFEN»); `parse_substance_it` los limpia con las mismas reglas conservadoras (ver «Enlace
  entre idiomas»).
- Dosis: 76 % de los productos con dosis interpretada. Salen de dos sitios: las cantidades de `PA_confezioni.csv`
  (muchas vacías) y el texto del envase («200 MG COMPRESSE»), este último solo con un principio activo (en una
  combinación no se sabe qué cifra es de cuál). Si los dos existen y no coinciden, no se da dosis. Las cantidades
  en «milligrammi»/«grammi» no dicen si son por comprimido o por envase: solo se usan en formas de unidad.
- **Atribución obligatoria (CC-BY 4.0)**: «Fonte: AIFA (Agenzia Italiana del Farmaco), dati aperti, licenza
  CC-BY 4.0», más la fecha de los datos. El pie de la app lo cita.

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, con su propio formato. La ruta lógica es: dejar el esquema
listo para todos, conectar cada país de verdad, y sustituir cada ejemplo
manual por una fuente real cuando la investiguemos.

**Comparaciones con datos reales** (mismo principio activo y misma forma, nivel exacto): **809
grupos** comparan España con Francia, **781** España con el Reino Unido, **646** Francia con el
Reino Unido, y **574** existen en los tres países. Contando también el nivel "misma base" (ver
"Dos niveles"), el porcentaje de productos españoles con equivalente es:

| | exacto | misma base | sin equivalente |
|---|---|---|---|
| España → Francia | 71 % | 5 % | **24 %** |
| España → Reino Unido | 71 % | 6 % | **24 %** |
| España → ni Francia ni Reino Unido | | | **15 %** |
| Francia → Reino Unido | 59 % | 3 % | **38 %** |
| Reino Unido → Francia | 52 % | 3 % | **46 %** |

Con Italia (todos los productos, con y sin receta; entre paréntesis, solo sin receta):

| | exacto | misma base | sin equivalente |
|---|---|---|---|
| España → Italia | 82 % (58 %) | 1 % | **15 %** (41 %) |
| Francia → Italia | 64 % (36 %) | 2 % | **32 %** (63 %) |
| Reino Unido → Italia | 59 % (36 %) | 2 % | **37 %** (62 %) |
| Italia → España | 65 % (47 %) | 2 % | **31 %** (52 %) |
| Italia → Francia | 54 % (34 %) | 2 % | **42 %** (64 %) |
| Italia → Reino Unido | 55 % (33 %) | 2 % | **42 %** (65 %) |

Los sin receta de Italia quedan más huérfanos porque el catálogo italiano de venta libre es muy local
(muchas hierbas, antisépticos y combinaciones propias: econazol nitrato, sobrerolo, yodo + yoduro potásico...).

Antes de añadir las recetas y de ampliar los enlaces y las tablas de formas, España → Francia
estaba en 59 % sin equivalente y España → Reino Unido en 61 %. Lo que queda sin equivalente es,
sobre todo: (1) productos que de verdad no existen en el otro país (p. ej. el almagato, el
principio activo del Almax, no se vende en Francia ni en el Reino Unido: allí hay otros antiácidos
de aluminio y magnesio como Maalox, que son otra sustancia); (2) el mismo principio activo en otra
forma; (3) combinaciones que solo existen en un país; y (4) un pequeño resto de pares sin confirmar.
Cuando un nombre no tiene enlace con España pero es **idéntico en francés y en inglés** (p. ej.
*lactulose*), la comparación Francia-Reino Unido se hace por nombre idéntico: son nombres
internacionales (DCI), pero no están comprobados con Wikidata.

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
  que hace el `vtm` de CIMA. En el nivel **exacto** no cuentan los ésteres ni
  profármacos (el dipropionato de betametasona no es betametasona) ni las sales inorgánicas
  enteras (*carbonate de calcium* no es "calcium"); los ésteres se tratan en el nivel **base**
  (ver "Dos niveles").
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
  `sin_confirmar`, `sugerido`, `contradice` y `rechazado` no. Hoy hay **619 exactos
  confirmados** (eran 73 antes de añadir los de receta: el vocabulario español pasó de ~270 a más de
  1.500 nombres). Siguen sin comprobación independiente 33 pares exactos (parafina líquida,
  amilmetacresol, micofenolato mofetilo, proguanilo, polimixina B...): esperan que alguien con
  conocimiento farmacéutico los apruebe, cambiando `sin_confirmar` por `aprobado` en el archivo.
  La comprobación sigue descartando parecidos peligrosos (désonide ≠ budesonida, estazolam ≠
  ketazolam, procaïne ≠ prilocaïne, isoconazole ≠ tioconazol, amifampridine ≠ fampridina).
- Una curación completa tarda ~35 minutos (Wikidata y la AEMPS limitan las peticiones). Todas las
  consultas a Wikidata reintentan solas si responde 429/50x o agota el tiempo; antes, un lote
  perdido dejaba decenas de pares válidos "sin comprobar".
- `python curate_ingredient_links.py` vuelve a proponer y comprobar los
  pares (conserva las decisiones manuales). El importador **nunca** crea
  enlaces por su cuenta: solo lee el archivo.

**Formas** (`form_map_fr.csv`): cada fila lleva la forma francesa exacta, la
vía de administración que debe cumplir (un gel *cutanée* no es un gel
*ophtalmique*), la forma de CIMA y la evidencia de cómo clasifica CIMA esa
forma. La forma de destino se escribe siempre con el valor exacto que ya hay
en España (CIMA a veces la escribe con tildes, `SOLUCIÓN/SUSPENSIÓN ORAL`, y a
veces sin ellas). Son 88 filas y cubren el 94 % de los productos franceses (se añadieron las de liberación prolongada, inhaladores, sublinguales y pomadas oftálmicas, cada una con su evidencia de CIMA);
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
  la tabla (conserva las decisiones manuales). Hoy: **562 exactos confirmados**, 2 aprobados a
  mano, 41 sin confirmar y 23 sugeridos. Rechazados por la comprobación, entre otros: eszopiclone ≠
  zopiclona (es solo uno de los dos isómeros), promazine ≠ prometazina, cycloserine ≠ ciclosporina,
  potassium citrate ≠ ácido cítrico.
- Sales que antes faltaban en la lista cerrada (oxalato, hidrogenotartrato, xinafoato, hemifumarato,
  hidratos, arginina, tert-butilamina...) ya se reconocen. Los contraiones AMBIGUOS (acetato,
  benzoato, malato: a veces sal y a veces éster) solo se quitan para bases concretas (p. ej.
  *desmopressin acetate*, *flecainide acetate*, *rizatriptan benzoate*, *sunitinib malate*), nunca
  en general: *benzyl benzoate* y *hydrocortisone acetate* se quedan enteros.
- Un nombre que se queda reducido a un anión suelto no se interpreta (*acétate de sodium* se
  quedaba en "acétate" y compartía clave con *acétate de lysine*).
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

### Italia: el enlace se comprueba con el ATC de la AIFA

La AIFA da el código ATC de cada producto. Para un producto con **un solo** principio activo ese ATC es el del
principio activo, y se compara con el que la AEMPS da al nombre español (el maestro de CIMA): dos fuentes
oficiales distintas que no comparten nombres. Por eso `python curate_ingredient_links.py --country it` no necesita
Wikidata para casi nada (solo para los ~110 nombres que únicamente salen en combinaciones, donde se usa
Wikidata por el nombre italiano como en Francia y el Reino Unido). Los candidatos salen de tres sitios:
- **regla**: el nombre italiano pasado al español (idro- → hidro-, -ene → -eno, -one → -ona, ch → qu...) queda
  idéntico a uno que ya tenemos;
- **atc**: la AEMPS da el ATC de la AIFA a un nombre español que no se parece por regla (*ibuprofen*, *sildenafil*,
  *desametasone* → dexametasona). Para que cuente como confirmado hace falta además que los nombres se parezcan
  (similitud ≥ 0,75): un mismo ATC con nombres muy distintos queda como `sugerido` para revisarlo a mano (así
  se descartaron, por ejemplo, *benzalconio cloruro* → carmelosa o *procaina* → benzocaína, que comparten un código ATC
  genérico);
- **ester**: el nombre italiano es un éster o profármaco y su base está en España (*fluticasone propionato* →
  fluticasona): solo de nivel base, y se confirma si el ATC del éster coincide con el de la base.
`ingredient_links_it.csv` quedó con 799 pares confirmados, 22 aprobados a mano y 2 rechazados a mano; el resto
(sin confirmar, sugeridos, contradicen) no se usa. Dos ejemplos de lo que el ATC detecta: *delorazepam* no se enlaza
con lorazepam (se parecen los nombres, son sustancias distintas) y *fluticasone* (el ATC es el del furoato) no se
enlaza con fluticasona. **Aprobados a mano por Claude, pendientes de visto bueno de María y de un farmacéutico**:
sales y grafías con el mismo ATC (esomeprazol magnesio, risedronato, lattulosio → lactulosa, iodopovidone →
povidona iodada...) y tres que se aprobaron como en el Reino Unido: ácido ascórbico, cloruro sódico y bicarbonato
sódico (la AEMPS solo lista ATC de usos tópicos o nasales). Se rechazó *dimeticone* → simeticona (la simeticona es
dimeticona activada con sílice).

### Equivalencias rápidas de octubre de 2026 (plantas, formas parecidas, pares pendientes)

- **Plantas**: el parser francés quita la parte de la planta y el tipo de extracto entre paréntesis
  (`hydrocotyle (partie aérienne d') (extrait sec de)` → `hydrocotyle`). Se compara la **planta**;
  el tipo de extracto (seco, titulado...) y la dosis no se comparan. `hydrocotyle` → centella
  asiática está aprobado a mano (Wikidata Q324714 es «Hydrocotyle asiatica» en francés y «Centella
  asiática» en español); pendiente de visto bueno farmacéutico.
- **Forma parecida** (franja azul en la app): si un país no tiene el grupo exacto, ni de nivel base,
  pero sí el mismo principio activo en otra forma de la misma familia, se enseña aparte y avisa
  ("no es la misma forma"). Hoy solo hay una familia, **crema ↔ pomada** (`FORM_FAMILIES` en
  `MediPass.jsx`). OJO: en CIMA son dos clases separadas; es un criterio nuestro, apoyado en que la
  Farmacopea Europea agrupa ambas como "preparaciones semisólidas de aplicación cutánea". La crema es
  una emulsión aceite/agua y la pomada una base grasa casi sin agua, así que la absorción puede
  diferir. Pendiente de visto bueno farmacéutico; no se añaden más familias sin evidencia.
  Ejemplo: Blastoestimulina (pomada, España) → Madécassol (crema, Francia).
- **Pares aprobados a mano (exactos, pendientes de visto bueno farmacéutico)**: micofenolato mofetilo
  (FR y UK), ketotifeno (FR), bromacepam (FR), carmelosa (FR y UK), rabeprazol (UK), solifenacina
  (UK). Ni Wikidata ni la AEMPS dan ATC para comprobarlos automáticamente; en varios casos el mismo
  compuesto ya estaba confirmado en la otra tabla.

### Dosis y público: qué producto se enseña

Antes la app enseñaba, de cada país, el primer producto por orden alfabético: así salió un jarabe
infantil de 100 mg/5 ml frente a un sobre de adultos de 400 mg. Ahora **elige el mejor** y cada tarjeta lleva un
**desplegable con todos los productos** de esa forma en ese país (ordenados, el mejor primero, con su
dosis y una marca si es infantil) para elegir otro si no convence; el otro lado se reajusta contra el nuevo.

- **Dosis normalizada** (`doses.py`, columna `products.strengths`, JSON): para cada principio activo,
  los mg por unidad (comprimido, sobre, cápsula, dosis) o los mg por ml/g. Cada fuente se lee a su
  manera: España del texto libre de CIMA (22 formatos; se interpreta el 94 %), Francia de la composición
  (cantidad + referencia «un comprimé», «5 ml»; 79 %) y el Reino Unido de la concentración estructurada
  del dm+d (92 %). Lo que no se sabe interpretar con seguridad se deja **fuera**: es mejor decir «no se
  puede comparar» que inventar un número (p. ej. «400 mg/10 mg» para un solo principio activo,
  parches en mg/hora, unidades internacionales, homeopatía).
- **Público** (`products.audience`): heurística por palabras del nombre comercial (*Children's*, *Junior*,
  *infantil*, *enfants*, *3 Months Plus*, *6 Years Plus*...). Un nombre sin pistas queda sin clasificar,
  que es lo habitual en un producto general. **Se equivoca cuando el nombre no lo dice**: el Calprofen
  100 mg/5 ml es pediátrico y no se detecta.
- **Orden de elección**, dentro del mismo estatus de receta que el producto de origen: (1) mismo público
  (si el de origen no es infantil, los infantiles van al final; si lo es, primero los infantiles),
  (2) dosis más cercana (la comparable antes que la que no lo es), (3) nombre.
- **Solo se comparan dosis del mismo tipo** (por unidad con por unidad, concentración con
  concentración). Un sobre de 400 mg y una suspensión de 20 mg/ml no se comparan, y la app lo dice.
- **Limitaciones**: la cantidad puede referirse a la **sal** y no a la base (ibuprofeno arginina 684 mg
  equivale a ibuprofeno 400 mg) y no se corrige; los productos con receta de España no tienen composición
  (solo se pidió el detalle de los sin receta), así que su dosis sale del texto de CIMA; en Francia el
  79 % se debe a que muchas dosificaciones son homeopáticas o vienen sin referencia.
- La nota bajo las tarjetas dice si la cantidad declarada coincide, si es distinta, si no es comparable
  y si uno de los productos es infantil y el otro no.

### Dos niveles de equivalencia

CIMA nombra los medicamentos por la molécula **sin el éster o profármaco**: "fluticasona",
"candesartán", "olmesartán", "beclometasona". Francia y el Reino Unido los nombran **con** él:
*fluticasone propionate*, *candesartan cilexetil*, *olmesartan medoxomil*, *beclometasone
dipropionate*. Con nuestra regla estricta (un éster no es "el mismo") todos esos fármacos de
uso masivo quedaban sin equivalente, y mezclarlos sin más sería falso: un éster es otra molécula,
con potencia y dosis a veces distintas (el furoato de fluticasona, el de Relvar, no es el
propionato). Por eso hay **dos niveles**:

- **Exacto** (verde): misma molécula, aunque cambie la sal. Como siempre.
- **Misma base** (franja ámbar en la app): el mismo principio activo base con un nombre distinto
  que puede ser otro éster o sal. La app enseña el nombre exacto de cada país y avisa: "no está
  confirmado que sea exactamente la misma sustancia... consulta a un farmacéutico".

Cómo funciona:
- La base de datos guarda `active_ingredients.base_inn` (la vista `equivalences` lo expone como
  `base_inn`; sin base propia, es el propio nombre). Un producto con enlace de nivel base
  **conserva su propio nombre** (así no se mezcla con los exactos); el nivel ámbar se busca solo
  cuando no hay equivalente exacto.
- Los archivos de enlaces tienen una columna `nivel` (`exacto` o `base`). Los candidatos de nivel
  base salen de quitar palabras de éster/profármaco (`ESTER_WORDS`: propionate, dipropionate,
  furoate, valerate, butyrate, acetate, cilexetil, medoxomil, mofetil, etexilate, disoproxil...) y
  que la base sea un nombre español que ya tenemos. Pasan por la **misma comprobación ATC**, y esa
  comprobación distingue ésteres distintos de la misma base: `furoate de fluticasone` →
  fluticasona quedó rechazado (ATC R01AD12/R03BA09 frente a R03BA05).
- **Un enlace de nivel base nunca se usa como exacto** (`load_links(level=...)`,
  `resolve_levels()`); hay una prueba que lo garantiza.
- Hoy hay 307 productos franceses y 544 británicos con enlace de nivel base.

**Enlaces de nivel base aprobados a mano, pendientes del visto bueno de un farmacéutico.**
Wikidata tiene el elemento de muchos ésteres pero sin código ATC, así que no pueden confirmarse
con el método automático. Se aprobaron a mano los de manual o los que ya estaban confirmados por
ATC en la tabla del otro país:
- Francia (11): propionate de fluticasone; dipropionate de béclométasone (4 grafías);
  dabigatran étexilate; dipropionate y valérate de bétaméthasone; propionate de clobétasol.
- Reino Unido (10): fluticasone propionate; candesartan cilexetil; olmesartan medoxomil;
  abiraterone acetate; tenofovir disoproxil; cyproterone acetate; betamethasone valerate y
  dipropionate; dabigatran etexilate mesilate; clobetasol propionate.
Cada fila lleva la razón en `evidencia`. Si no estás de acuerdo con alguna, cambia `aprobado` por
`rechazado` en el CSV. Siguen sin confirmar (no se usan) otros 17 pares franceses y 8 británicos
(fludrocortisone acetate, hydrocortisone acetate, medroxyprogesterone acetate, estradiol
valerate, eslicarbazepine acetate, norethisterone acetate...).

**Pruebas**: `python -m unittest test_ingredients test_fetch_bdpm test_fetch_dmd test_prescription test_levels test_doses -v`
(111). Incluyen pares que **nunca** deben enlazarse (alanina / alantoína, ketoprofeno /
piketoprofeno, *hyoscine butylbromide* / hioscina, *benzyl benzoate*, ésteres y sus bases...),
combinaciones de forma y vía que no deben traducirse, un ZIP de dm+d en miniatura para comprobar
las reglas de qué entra (P/GSL/POM, inyectables, hospital, sin licencia, homeopáticos), las reglas
de exclusión de España y Francia, la sincronización con estatus legal, el interruptor de recetas y
los dos niveles.

**Avisos en la app** cuando un país no tiene el grupo que se mira: "hay
productos con este principio activo, pero en otra forma (…); no son
equivalentes"; "no hemos encontrado en [país] ningún producto de venta libre
con este principio activo"; y, para países sin datos reales, "todavía no
tenemos datos verificados". Las tarjetas de ejemplos manuales llevan la
etiqueta "Ejemplo sin verificar".

## Publicar una versión de prueba en internet (sin recetas)

La versión pública es una **web estática**: no necesita el backend de Flask. El catálogo se guarda en dos
archivos (`frontend/public/equivalences.json` y `config.json`) que genera `export_static.py` con **solo
medicamentos sin receta y datos de fuentes oficiales** (se excluyen los de receta y los ejemplos manuales
de Alemania y Portugal; los selectores solo ofrecen España, Francia, Italia y Reino Unido). Una prueba
garantiza que esos archivos nunca llevan recetas ni ejemplos. La versión completa, con recetas, sigue
corriendo solo en local.

```bash
python export_static.py                 # regenera el catálogo público (hacerlo cada vez que cambien los datos)
cd frontend && npm run build:static     # genera frontend/dist, lo que se publica
npm run preview -- --mode static        # (opcional) ver cómo queda, en http://localhost:4173
```

**Publicar en GitHub Pages** (el camino elegido; gratis). GitHub Pages gratuito solo publica repositorios
**públicos**, y este proyecto tiene dentro la base de datos con recetas. Por eso la web se publica desde un
repositorio **aparte, `medipass-web`**, que contiene solo la web ya construida (nada de base de datos, código
ni claves); el repositorio de trabajo `medipass` puede ser privado.
1. En GitHub, crea un repositorio **nuevo, público y vacío** llamado `medipass-web` (sin README ni
   `.gitignore`).
2. Clónalo **al lado** de este proyecto (la carpeta debe llamarse `medipass-web`):
   `cd ..` (la carpeta que contiene `medipass`) y `git clone https://github.com/TU_USUARIO/medipass-web.git`
3. `python publish_web.py` (en la carpeta `medipass`): regenera el catálogo público, construye la web, la
   copia a `medipass-web`, hace commit y push. Con `--no-push` hace todo menos subirlo. Antes de copiar
   comprueba que el catálogo no tiene recetas ni ejemplos manuales; si los tuviera, no publica nada.
4. En GitHub: `medipass-web` → *Settings* → *Pages* → *Source: Deploy from a branch* → rama `main`, carpeta
   `/ (root)` → *Save*. En un par de minutos la web aparece en `https://TU_USUARIO.github.io/medipass-web/`;
   ese es el enlace que se puede enviar.
5. Para actualizar los datos: `python publish_web.py` otra vez (no hace falta tocar nada más).

La web usa rutas relativas (`base: "./"` en `vite.config.js`, solo en modo `static`), así que funciona en una
subcarpeta como `/medipass-web/` y también en la raíz de otro servicio. Alternativas con el mismo contenido:
Netlify (arrastrar la carpeta `frontend/dist` a netlify.com), Cloudflare Pages o Vercel (`frontend/vercel.json`
ya fija el comando `npm run build:static` y la carpeta `dist`).

Medidas para que sea solo "para quien reciba el enlace": la página lleva `<meta name="robots" content="noindex">`,
así que los buscadores no deberían indexarla (en GitHub Pages `robots.txt` y `X-Robots-Tag` no se aplican, porque la
web vive en una subcarpeta del dominio); **pero el enlace no tiene contraseña**: cualquiera que lo conozca puede
entrar, y GitHub Pages no ofrece contraseña.

Avisos visibles en la versión pública: "Versión de prueba para valoración... no los ha revisado ningún
profesional sanitario", "Información orientativa, no sustituye el consejo de un farmacéutico o médico", y
en el pie las tres fuentes **con su fecha** y la atribución OGL v3.0 del NHS.

**Pendiente de comprobar antes de difundirlo más allá de gente cercana**: la licencia de la BDPM exige citar
la fuente y la fecha y **no alterar los datos**. La app conserva el nombre original de cada producto, pero
traduce las formas y enlaza los principios activos con su nombre español; hay que comprobar con quien
corresponda si eso cuenta como alteración. Y, como siempre, la consulta legal sobre mostrar medicamentos
(en esta versión, solo sin receta).

También conviene saber que `medipass.db` está en el repositorio de trabajo: si ese repositorio es público, la
base completa (con recetas) es visible para cualquiera, aunque la web publicada no las muestre. Por eso se
recomienda ponerlo **privado** (GitHub → Settings → Danger Zone → Change repository visibility); la web pública
no depende de él. Lo que ya fue público ha podido verse o copiarse mientras lo fue; quitar la base del
historial de git obligaría a reescribirlo y forzar el envío, y no se ha hecho.

## Alcance legal

Antes de mostrar esto a usuarios reales, investigamos la Directiva 2001/83/CE
de la UE, que en su artículo 88 prohíbe la publicidad de medicamentos sujetos
a receta médica dirigida al público general. La conclusión: el catálogo de
MediPass, para uso con usuarios reales, debería limitarse a tres categorías:

- **Medicamento sin receta** (OTC)
- **Producto sanitario**
- **Parafarmacia**

y excluir cualquier medicamento con receta del catálogo público.

**Decisión de María (octubre de 2026): la app muestra también los medicamentos con
receta**, con un aviso grande y llamativo, porque para quien viaja es más útil saber
que un producto existe pero necesita receta que no encontrarlo. Esto va en contra de la
conclusión de arriba, así que está pensado para poder deshacerse sin rehacer nada:

- **Interruptor `INCLUDE_PRESCRIPTION`** (variable de entorno del backend, `1` por
  defecto). Con `INCLUDE_PRESCRIPTION=0` la API no sirve ningún medicamento con receta ni
  como producto ni como grupo, y la app adapta sus textos (`GET /api/config`). Los datos
  siguen en `medipass.db`. Es lo que habría que apagar antes de publicar la app si un
  abogado lo recomienda. Hay una prueba que comprueba que, apagado, no sale ninguna.
- Cada producto guarda su **estatus legal** en `legal_category` (`libre`,
  `solo_farmacia` o `receta`) y la etiqueta original del país en `legal_note` (`GSL`, `P`,
  `POM`, `liste I`, "Medicamento sujeto a prescripción médica"...). Esto sustituye al
  `legal_category` pendiente de antes y distingue `GSL` de `P` en el Reino Unido.
- **Cómo se ve**: la tarjeta del producto con receta lleva borde rojo y una franja roja
  "SOLO CON RECETA MÉDICA EN [PAÍS]"; si un país es libre y el otro con receta aparece un
  banner rojo entre las dos tarjetas; el buscador y el listado marcan "CON RECETA".
  Si en un país un grupo tiene productos libres y con receta, se muestra el del mismo
  estatus que el de origen y se avisa de que existe el otro.
- **Qué NO se incluye (decisión de María, igual en los tres países)**: los **inyectables
  y parenterales** y los **productos de uso hospitalario**. Así las comparaciones son
  justas: si un país los incluyera y otro no, saldrían "sin equivalente" falsos.
  - *España*: se excluye "Uso hospitalario" (se administra en el hospital) y todo producto
    con forma inyectable/perfusión o con alguna vía parenteral. **No** se excluye
    "Diagnóstico hospitalario": lo receta un especialista pero el paciente lo compra en la
    farmacia (`fetch_cima.py`, `exclusion_reason`).
  - *Francia*: se excluyen "réservé à l'usage hospitalier", farmacias hospitalarias,
    uso profesional, urgencias y administración en un centro de salud, además de las vías
    parenterales y de diálisis. **No** se excluye "prescription hospitalière" (se dispensa en
    farmacia). Ver `HOSPITAL_CONDITIONS` y `PARENTERAL_ROUTES` en `fetch_bdpm.py`.
  - *Reino Unido*: se excluyen los productos cuyos envases activos llevan todos la marca
    `HOSP` ("hospital use only") del dm+d, y los inyectables por forma o vía. Ver
    `load_catalog` en `fetch_dmd.py`. Además, como antes, solo entran productos con
    licencia (los "unlicensed specials" de receta, unos 7.900, quedan fuera).
  Para volver a incluirlos hay que quitar esas comprobaciones en cada importador.
- Los **productos sanitarios y la parafarmacia** siguen sin fuente real (solo hay ejemplos
  manuales), y los ejemplos manuales de DE/IT/PT no están verificados; uno de ellos
  (Voltaren Schmerzgel Forte, Alemania) está marcado como "con receta", lo que es un dato
  de ejemplo, no una fuente.

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
- `fetch_aifa.py` — sincroniza Italia desde los CSV de la AIFA (ver abajo)
- `doses.py` — normaliza la dosis de los cuatro países y deduce el público (ver «Dosis y público»)
- `importers.py` — piezas comunes de los importadores extranjeros (tabla de
  formas, vocabulario español, sincronización de `products`)
- `ingredients.py` — enlace de principios activos entre idiomas (ver "Enlace
  entre idiomas")
- `ingredient_links.csv`, `ingredient_links_uk.csv`, `ingredient_links_it.csv` — tablas de enlaces
  revisadas (las usan los importadores)
- `curate_ingredient_links.py` — propone y comprueba enlaces nuevos
- `form_map_fr.csv`, `form_map_uk.csv`, `form_map_it.csv` — traducción de formas francesas,
  inglesas e italianas a las de CIMA
- `.env` — clave de API de NHS TRUD (no se sube a GitHub)
- `test_ingredients.py`, `test_fetch_bdpm.py`, `test_fetch_dmd.py`, `test_fetch_aifa.py`, `test_prescription.py`, `test_levels.py`, `test_doses.py` — pruebas
- `medipass.db` — la base ya construida
- `backend/app.py` — servidor Flask
- `frontend/` — app Vite + React

## Cómo correr el proyecto

Hacen falta dos terminales, una para el backend y otra para el frontend.

**Terminal 1 — backend:**
```bash
cd backend
pip install flask flask-cors waitress
python app.py
```
Queda escuchando en `http://127.0.0.1:5000`. **Instala `waitress`**: el servidor de desarrollo de Flask
en Windows tarda ~19 s en responder el catálogo con recetas (~6 MB); con waitress, menos de un segundo.
Para ocultar los medicamentos con receta: `set INCLUDE_PRESCRIPTION=0` antes de `python app.py`.

**Terminal 2 — frontend:**
```bash
cd frontend
npm install
npm run dev
```
Queda escuchando en `http://localhost:5173`.

Con ambos corriendo, abre **`http://localhost:5173`** en el navegador.

## Actualizar los datos de España, Francia, Italia y el Reino Unido

Los cuatro scripts son sincronizaciones: se pueden ejecutar cuando quieras sin
duplicar nada. Actualizan lo que existe, añaden lo nuevo, borran lo que ya
no cumpla el filtro, y quitan los ejemplos manuales de un país en cuanto
llega un dato real de la misma forma que los sustituye.

```bash
pip install requests

python fetch_cima.py                    # sincroniza y completa el detalle que falte
python fetch_cima.py --no-details       # solo el listado (rápido, sin ATC/composición)
python fetch_cima.py --refresh-details  # vuelve a pedir el detalle de todos (~5 min)
python fetch_cima.py --debug            # imprime el JSON crudo de 1 medicamento
python fetch_cima.py --only-otc         # solo sin receta (sin los 10.000 de receta)
python fetch_cima.py --details-rx       # pide también ATC/composición de los de receta (más de una hora)
python fetch_cima.py --dry-run          # cuenta qué se importaría, sin tocar medipass.db

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

Italia no necesita cuenta ni clave: `python fetch_aifa.py` descarga los CSV de la AIFA (unos 90 MB) y sincroniza
(`--dir CARPETA` usa unos ya descargados). Para volver a enlazar principios activos:
`python curate_ingredient_links.py --country it`; la primera vez consulta ~1.100 nombres al maestro de ATC de
la AEMPS (unos 6 minutos) y guarda la respuesta en `aemps_atc_cache.json`, que no se sube a git.

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
python fetch_aifa.py
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

- Los datos de Alemania y Portugal son ejemplos sin verificar.
- Italia: la AIFA no publica número de versión (se usa la fecha de descarga) y ~43 % de los envases sin receta
  no traen la cantidad en `PA_confezioni.csv`; la dosis se completa con el texto del envase. Las formas
  «colluttorio» (colutorio), «soluzione vaginale» y «sospensione rettale» no se traducen porque CIMA no tiene una
  clase con evidencia para ellas. La importación paralela está excluida (duplicados de marcas ya incluidas).
- Cada grupo enseña **un** producto por país, el mejor según su público y su dosis (ver «Dosis y
  público»), y un desplegable con todos los demás. **La dosis solo se compara cuando es del mismo tipo** y la
  cantidad puede referirse a la sal; «equivalente» significa mismo principio activo y misma forma, y el
  producto elegido puede tener otra concentración (la app lo dice).
- La forma de España es la "simplificada" de CIMA (unos 50 valores,
  bastante gruesa: "solución/suspensión oral" agrupa jarabes, polvos y
  granulados). La de Francia se traduce con `form_map_fr.csv` (94 % de los
  productos); el resto conserva su forma en francés y no se compara.
- De los 9.334 candidatos franceses, 6.927 (74 %) quedan enlazados con un principio activo español
  (6.620 de nivel exacto y 307 de nivel base); el resto tiene un principio activo que no existe en
  España, un nombre que no se interpreta con seguridad o es una combinación sin equivalente.
  En el Reino Unido, 14.359 de los 17.731 candidatos (13.815 exactos y 544 de nivel base).
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
- La tabla `active_ingredients` (2.956 filas) mezcla nombres en español, en francés y en inglés:
  un principio activo sin enlace exacto conserva su nombre en el idioma de su fuente.
- Reino Unido: `GSL` y `P` se guardan por separado (`legal_category` = `libre` o `solo_farmacia`,
  con la etiqueta original en `legal_note`) y la app muestra "Sin receta, solo en farmacia" para P.
  Un producto con envases P y POM a la vez cuenta como sin receta y su `legal_note` dice "P + POM".
  El dm+d cubre lo que circula por el NHS; si falta algún medicamento habitual, será por eso (no se
  ha auditado exhaustivamente).
- El estatus de receta de Francia sigue siendo una regla **inferida** (aparecer en el archivo de
  condiciones de prescripción): no hay campo explícito. La condición original se guarda en
  `legal_note` ("liste I", "liste II"...); no se ha auditado exhaustivamente.
- El público (adulto o niño) se deduce del nombre: un producto infantil cuyo nombre no lo diga
  (Calprofen) no se detecta.

## Próximos pasos

- Que alguien con conocimiento farmacéutico revise: los 33 pares exactos y 17 de nivel base sin
  comprobar en `ingredient_links.csv`, los 41 y 8 de `ingredient_links_uk.csv`, los 39 sin confirmar y
  los 91 sugeridos de `ingredient_links_it.csv`, y todo lo aprobado a mano (bicarbonato y cloruro
  sódicos; los 21 ésteres de la sección "Dos niveles"; los 22 pares de Italia)
- Mejorar la elección por dosis y público: corregir la dosis cuando se expresa como sal, deducir lo
  pediátrico por la concentración y la forma (no solo por el nombre) y pedir el detalle de los productos
  con receta de España para tener su composición
- **Alternativas "mismo uso, otra sustancia"** por código ATC (p. ej. Maalox para el Almax): es una
  recomendación, así que antes hay que revisarlo con un farmacéutico y con el asunto legal
- Priorizar los pares pendientes que más productos afectan: micofenolato mofetilo, bromacepam,
  ketotifeno, carmelosa, solifenacina y rabeprazol
- **Parafarmacia** (idea de María, octubre de 2026): añadir productos que no son medicamentos (cosmética,
  higiene, apósitos, productos sanitarios...). Hoy no hay fuente real; ver el punto siguiente. Habrá que decidir
  qué entra (la categoría del esquema ya prevé 'Producto sanitario', 'Higiene' y 'Belleza') y cómo se
  comparan: sin principio activo único, la unidad de equivalencia cambia (p. ej. tipo de producto + ingredientes
  clave, o código de producto).
- Conseguir acceso a **BotPlus/BADIS** o **Medipim** para datos reales de
  parafarmacia y productos sanitarios (hoy no hay ninguna fuente real);
  antes, preguntarles si su licencia permite una app para el público
- **Alemania y Portugal siguen sin fuente abierta utilizable** (lo que
  se encontró en octubre de 2026; Italia sí la tiene, ver arriba, y se integró después):
  - *Alemania*: el BfArM solo publica un ZIP con nombres de sustancias
    (`pnbez-*.zip`), no el catálogo de productos con forma y estatus.
  - *Alemania, alternativa*: Swissmedic (Suiza) sí publica datos abiertos y está en alemán.
  - *Portugal*: los datos abiertos de INFARMED son solo ensayos clínicos; el
    catálogo de medicamentos es de pago.
  Hay que volver a mirarlo (o pedir acceso a las agencias) antes de conectarlos.
- Cada país nuevo repite el proceso: su propia tabla de formas y volver a
  ejecutar `curate_ingredient_links.py` para enlazar sus principios activos
- Antes de publicar la app: decidir con un abogado si se muestran los medicamentos con receta; si
  no, arrancar el backend con `INCLUDE_PRESCRIPTION=0` (los datos siguen en la base)
- **Cuentas de usuario y «Mis medicamentos»** (idea de María, octubre de 2026): poder crear una
  cuenta, guardar medicamentos en favoritos y consultarlos después más rápido, en una sección «Mis
  medicamentos». Hay que decidir antes: cómo se inicia sesión (correo y contraseña, enlace por
  correo, o Google), dónde se guardan los datos (hoy la app es solo local; con cuentas hace falta
  un servidor y una base de datos de usuarios, es decir, desplegar) y la **privacidad**: la lista de
  medicamentos de una persona es un dato de salud (RGPD, categoría especial), así que habrá que
  limitar lo que se guarda, pedir consentimiento y permitir borrar la cuenta. Va junto con el
  despliegue a Vercel y con la consulta legal.
- Difundir la versión de prueba más allá de gente cercana (ver «Publicar una versión de prueba»); y poner el
  repositorio de trabajo `medipass` en privado

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
