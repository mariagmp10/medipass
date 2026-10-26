import React, { useEffect, useMemo, useState } from "react";
import {
  Search,
  Plane,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Info,
  Droplet,
  Pill,
  Sparkles,
  Package,
  Compass,
} from "lucide-react";

const API_BASE_URL = "http://127.0.0.1:5000";

/* ---------------------------------------------------------
   PALETA / TOKENS
--------------------------------------------------------- */
const COLORS = {
  ink: "#14213D",
  inkDark: "#0F1B2E",
  inkBorder: "#28405C",
  paper: "#EEF0EC",
  paperCard: "#F5F4F0",
  cardBorder: "#E2E0D8",
  amber: "#FFB627",
  green: "#4C9A6A",
  warnBg: "#FDF3E3",
  warnBorder: "#F0D9A8",
  warnText: "#7A5A16",
  warnIcon: "#E4A13B",
  slate: "#5C6470",
  slateLight: "#94A0AE",
  rx: "#C62828",
  rxDark: "#8E1B1B",
  rxBg: "#FDECEA",
  info: "#2F6FA8",
  infoBg: "#EAF2FA",
};

/* Familias de formas "parecidas": mismo principio activo en otra forma que se usa de manera parecida.
   Solo crema <-> pomada. OJO: en CIMA son dos clases SEPARADAS (CREMA y POMADA); esto es un criterio
   nuestro, apoyado en que la Farmacopea Europea agrupa ambas (con geles y pastas) como "preparaciones
   semisólidas de aplicación cutánea". La crema es una emulsión aceite/agua; la pomada, una base grasa
   casi sin agua: la absorción puede diferir. Se enseña como nivel aparte ("forma parecida"), nunca
   como equivalente exacto. Pendiente de visto bueno farmacéutico; añadir más familias solo con evidencia. */
const FORM_FAMILIES = [["CREMA", "POMADA"]];

function relatedForms(rawForm) {
  const family = FORM_FAMILIES.find((f) => f.includes((rawForm ?? "").toUpperCase()));
  return family ? family.filter((f) => f !== (rawForm ?? "").toUpperCase()) : [];
}

const COUNTRIES = [
  { code: "ES", name: "España" },
  { code: "DE", name: "Alemania" },
  { code: "FR", name: "Francia" },
  { code: "IT", name: "Italia" },
  { code: "PT", name: "Portugal" },
  { code: "UK", name: "Reino Unido" },
];

const ICONS_BY_CATEGORY = {
  Salud: Pill,
  "Producto sanitario": Package,
  Higiene: Droplet,
  Belleza: Sparkles,
};

function capitalize(text) {
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/* CIMA da las formas en mayúsculas y a veces sin tildes ("LIQUIDO USO TOPICO").
   Las pasamos a minúsculas y restauramos las tildes de las palabras habituales. */
const FORM_ACCENTS = {
  liquido: "líquido",
  topico: "tópico",
  capsula: "cápsula",
  solucion: "solución",
  suspension: "suspensión",
  inhalacion: "inhalación",
  aposito: "apósito",
  emulsion: "emulsión",
  supositorio: "supositorio",
  efervescente: "efervescente",
};

function formLabel(form) {
  if (!form) return "";
  const text = form
    .toLowerCase()
    .replace(/[a-záéíóúñ]+/g, (word) => FORM_ACCENTS[word] ?? word);
  return capitalize(text);
}

/* La unidad de equivalencia es principio activo + forma farmacéutica
   ("diclofenaco · gel"), no solo el principio activo: un gel y unas pastillas
   del mismo principio activo no son intercambiables. */
function groupId(row) {
  return `${row.inn_name}||${row.form ?? ""}`;
}

function productFromRow(row) {
  return {
    marca: row.brand_name,
    receta: !!row.requires_prescription,
    strengths: row.strengths ? JSON.parse(row.strengths) : null,
    audience: row.audience,
    innName: row.inn_name,
    baseInn: row.base_inn,
    legalCategory: row.legal_category,
    legalNote: row.legal_note,
    source: row.source,
    sourceRef: row.source_ref,
    dose: row.dose,
    form: row.form,
    composition: row.composition,
    photoUrl: row.photo_url,
  };
}

/* Convierte las filas planas de GET /api/equivalences (una fila por
   producto) en una lista de grupos (principio activo + forma), con una
   tarjeta por país. España tiene muchos productos por grupo (datos reales de
   CIMA); mostramos el primero y contamos cuántos hay en total. */
function groupEquivalences(rows) {
  const groups = new Map();

  for (const row of rows) {
    const id = groupId(row);
    if (!groups.has(id)) {
      groups.set(id, {
        id,
        innName: row.inn_name,
        baseInn: row.base_inn ?? row.inn_name,
        rawForm: row.form ?? "",
        name: capitalize(row.inn_name),
        forma: formLabel(row.form),
        principio: capitalize(row.inn_name),
        commonUse: row.common_use,
        atcGroup: null,
        categoria: row.category,
        icon: ICONS_BY_CATEGORY[row.category] || Pill,
        equivalencias: {},
      });
    }

    const med = groups.get(id);
    const product = productFromRow(row);
    const slot = (med.equivalencias[row.country_code] ??= { otc: [], rx: [] });
    slot[product.receta ? "rx" : "otc"].push(product);
    if (row.country_code === "ES" && row.atc_group && !med.atcGroup) {
      med.atcGroup = row.atc_group;
    }
  }

  // Descripción: el grupo terapéutico (ATC) de los productos españoles describe
  // mejor cada grupo que la nota genérica del principio activo.
  return Array.from(groups.values()).map((med) => ({
    ...med,
    uso: med.atcGroup ?? med.commonUse,
  }));
}

/* DOSIS Y PÚBLICO. Cada producto trae su dosis normalizada (`strengths`, en mg por unidad o por ml/g,
   ver doses.py) y su público (`audience`, 'child' si el nombre lo dice). Solo se comparan dosis del MISMO
   tipo (por unidad con por unidad, concentración con concentración): lo demás es "no comparable". */
function doseDistance(ref, cand) {
  if (!ref?.strengths?.length || !cand?.strengths?.length || ref.strengths.length !== cand.strengths.length) return null;
  const byName = new Map(cand.strengths.map((s) => [s.i, s]));
  let sum = 0;
  for (const r of ref.strengths) {
    const c = byName.get(r.i);
    if (!c || c.b !== r.b || !(r.v > 0) || !(c.v > 0)) return null;
    sum += Math.abs(Math.log2(c.v / r.v));
  }
  return sum / ref.strengths.length; // 0 = misma dosis; 1 = el doble o la mitad
}

function fmtMg(v) {
  if (v >= 1000) return `${+(v / 1000).toPrecision(3)} g`;
  if (v >= 1) return `${+v.toPrecision(3)} mg`;
  return `${+(v * 1000).toPrecision(3)} µg`;
}

function formatStrengths(strengths, form) {
  if (!strengths?.length) return null;
  const semisolid = /crema|pomada|gel|pasta|semisolido|polvo|champu/i.test(form ?? "");
  return strengths
    .map((s) => `${strengths.length > 1 ? `${capitalize(s.i)} ` : ""}${fmtMg(s.v)}${s.b === "conc" ? (semisolid ? "/g" : "/ml") : ""}`)
    .join(" + ");
}

/* Ordena los candidatos de un país: primero los del mismo público que el producto de referencia (si la
   referencia no es infantil, los productos infantiles van al final), luego la dosis más cercana (la
   comparable antes que la que no lo es) y por último el nombre. */
function rankCandidates(list, ref) {
  const refChild = ref?.audience === "child";
  const score = (c) => {
    let s = refChild ? (c.audience === "child" ? 0 : 100) : c.audience === "child" ? 100 : 0;
    if (ref) {
      const d = doseDistance(ref, c);
      s += d === null ? 10 : d;
    }
    return s;
  };
  return list
    .map((c) => [score(c), c])
    .sort((a, b) => a[0] - b[0] || a[1].marca.localeCompare(b[1].marca))
    .map((x) => x[1]);
}

/* En un país, un mismo grupo puede tener productos sin receta y con receta (ibuprofeno 400 mg libre,
   600 mg con receta). Se elige la lista del mismo estatus que el producto de origen (wantRx) y, si no
   hay, la otra: el aviso de receta se ve igualmente. Dentro de la lista se elige el mejor según el
   producto de referencia (`ref`), salvo que el usuario haya elegido uno a mano (`pickedName`).
   Devuelve el producto con: total, index (posición en el ranking), ranked (todos los productos, ya
   ordenados, para el desplegable), key (dónde guardar la elección) y otherStatus. */
function pickVariant(entry, wantRx, ref = null, pickedName = null, key = null) {
  if (!entry) return null;
  const preferred = wantRx ? entry.rx : entry.otc;
  const other = wantRx ? entry.otc : entry.rx;
  let list = preferred.length ? preferred : other;
  if (pickedName && !list.some((c) => c.marca === pickedName) && other.some((c) => c.marca === pickedName)) {
    list = other; // el producto elegido (p. ej. buscando una marca) es del otro estatus
  }
  if (!list.length) return null;
  const ranked = rankCandidates(list, ref);
  const index = Math.max(0, ranked.findIndex((c) => c.marca === pickedName));
  const others = list === preferred ? other : preferred;
  return {
    ...ranked[index],
    total: ranked.length,
    index,
    ranked,
    key,
    otherStatus: others.length ? { receta: !!others[0].receta, total: others.length } : null,
  };
}

/* Resumen de la dosis y el público de los dos productos que se enseñan. */
function doseSummary(a, b, nameA, nameB) {
  const parts = [];
  let warn = false;
  const fa = formatStrengths(a.strengths, a.form);
  const fb = formatStrengths(b.strengths, b.form);
  const d = doseDistance(a, b);
  if (d !== null) {
    if (d < 0.05) {
      parts.push(`Misma cantidad declarada (${fa}); puede referirse a la sal.`);
    } else {
      parts.push(`La dosis es distinta: ${fa} en ${nameA} frente a ${fb} en ${nameB}.`);
      warn = true;
    }
  } else if (fa && fb) {
    parts.push(`No se puede comparar la dosis: ${fa} en ${nameA} y ${fb} en ${nameB} se expresan de forma distinta.`);
    warn = true;
  } else {
    parts.push("No tenemos la dosis de uno de los dos productos, así que no se puede comparar.");
    warn = true;
  }
  if (a.audience === "child" && b.audience !== "child") {
    parts.push(`El de ${nameA} es infantil y el de ${nameB} no lo parece.`);
    warn = true;
  } else if (a.audience !== "child" && b.audience === "child") {
    parts.push(`El de ${nameB} es infantil y el de ${nameA} no lo parece.`);
    warn = true;
  }
  return { text: parts.join(" "), warn };
}

/* --------------------------------------------------------- */

function CountryPicker({ label, value, onChange }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
      <span
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.14em",
          color: COLORS.slateLight,
          fontFamily: "'IBM Plex Mono', monospace",
        }}
      >
        {label}
      </span>
      <div style={{ position: "relative" }}>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{
            width: "100%",
            appearance: "none",
            background: COLORS.inkDark,
            color: COLORS.amber,
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 17,
            letterSpacing: "0.02em",
            border: `1px solid ${COLORS.inkBorder}`,
            borderRadius: 8,
            padding: "10px 36px 10px 12px",
            outline: "none",
          }}
        >
          {COUNTRIES.map((c) => (
            <option key={c.code} value={c.code} style={{ background: COLORS.inkDark, color: "#fff" }}>
              {c.name}
            </option>
          ))}
        </select>
        <ChevronDown
          size={16}
          style={{
            position: "absolute",
            right: 12,
            top: "50%",
            transform: "translateY(-50%)",
            color: COLORS.amber,
            pointerEvents: "none",
          }}
        />
      </div>
    </label>
  );
}

function FlapCard({ country, data, highlight, approx, similarForm, onPick }) {
  const countryName = COUNTRIES.find((c) => c.code === country)?.name ?? country;
  return (
    <div
      style={{
        flex: 1,
        minWidth: 220,
        background: COLORS.inkDark,
        borderRadius: 10,
        border: data.receta
          ? `2px solid ${COLORS.rx}`
          : approx
          ? `2px solid ${COLORS.amber}`
          : similarForm
          ? `2px solid ${COLORS.info}`
          : `1px solid ${COLORS.inkBorder}`,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 16px",
          background: COLORS.ink,
          borderBottom: `1px solid ${COLORS.inkBorder}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.14em",
            fontFamily: "'IBM Plex Mono', monospace",
            color: COLORS.slateLight,
          }}
        >
          {countryName}
        </span>
        {highlight && (
          <span style={{ width: 6, height: 6, borderRadius: 999, background: COLORS.amber }} />
        )}
      </div>
      <div style={{ padding: 16 }}>
        <div
          style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 24,
            lineHeight: 1.2,
            color: "#F5F3ED",
            letterSpacing: "-0.01em",
            wordBreak: "break-word",
          }}
        >
          {data.marca}
        </div>
        {data.source !== "manual_seed" && (
          <div style={{ marginTop: 8, fontSize: 13, color: "#F5F3ED" }}>
            {formatStrengths(data.strengths, data.form)
              ? `Dosis: ${formatStrengths(data.strengths, data.form)}`
              : "Dosis: no disponible"}
            {data.audience === "child" && (
              <span style={{ marginLeft: 8, fontSize: 11, padding: "1px 7px", borderRadius: 6, background: COLORS.info, color: "#fff" }}>
                Infantil
              </span>
            )}
          </div>
        )}
        {data.total > 1 && (
          <div style={{ marginTop: 8, fontSize: 12, color: COLORS.slateLight }}>
            <div>
              Producto {data.index + 1} de {data.total} de esta forma en {countryName}
            </div>
            {onPick && (
              <select
                aria-label={`Elegir otro producto en ${countryName}`}
                value={data.index}
                onChange={(e) => onPick(data.ranked[Number(e.target.value)].marca)}
                style={{
                  marginTop: 6,
                  width: "100%",
                  fontSize: 12,
                  padding: "6px 8px",
                  borderRadius: 8,
                  border: `1px solid ${COLORS.slateLight}`,
                  background: COLORS.ink,
                  color: "#F5F3ED",
                  cursor: "pointer",
                }}
              >
                {data.ranked.map((c, i) => (
                  <option key={`${c.marca}-${i}`} value={i}>
                    {[`${i + 1}. ${c.marca}`, formatStrengths(c.strengths, c.form), c.audience === "child" ? "infantil" : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
        {data.source === "manual_seed" && (
          <div
            style={{
              marginTop: 10,
              display: "inline-block",
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 6,
              border: `1px solid ${COLORS.amber}`,
              color: COLORS.amber,
            }}
          >
            Ejemplo sin verificar
          </div>
        )}
        {similarForm && (
          <div
            style={{
              marginTop: 12,
              padding: "8px 12px",
              borderRadius: 8,
              background: COLORS.info,
              color: "#fff",
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 12, letterSpacing: "0.03em" }}>
              MISMO PRINCIPIO ACTIVO · FORMA PARECIDA
            </div>
            <div style={{ marginTop: 3, fontSize: 12 }}>
              En {countryName}: {similarForm.label}
            </div>
          </div>
        )}
        {approx && (
          <div
            style={{
              marginTop: 12,
              padding: "8px 12px",
              borderRadius: 8,
              background: COLORS.amber,
              color: COLORS.inkDark,
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 12, letterSpacing: "0.03em" }}>
              MISMO PRINCIPIO ACTIVO BASE · POSIBLE OTRO ÉSTER, SAL O EXTRACTO
            </div>
            <div style={{ marginTop: 3, fontSize: 12 }}>
              En {countryName}: {approx.names.join(", ")}
            </div>
          </div>
        )}
        {data.receta ? (
          <div
            role="alert"
            style={{
              marginTop: 14,
              padding: "10px 12px",
              borderRadius: 8,
              background: COLORS.rx,
              color: "#fff",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14, letterSpacing: "0.02em" }}>
              <AlertTriangle size={20} />
              <span>SOLO CON RECETA MÉDICA EN {countryName.toUpperCase()}</span>
            </div>
            {data.legalNote && (
              <div style={{ marginTop: 4, fontSize: 11, opacity: 0.9 }}>{data.legalNote}</div>
            )}
          </div>
        ) : (
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <CheckCircle2 size={14} color={data.legalCategory === "solo_farmacia" ? COLORS.amber : COLORS.green} />
            <span
              style={{
                fontSize: 12,
                fontWeight: 500,
                color: data.legalCategory === "solo_farmacia" ? COLORS.amber : COLORS.green,
              }}
            >
              {data.legalCategory === "solo_farmacia" ? "Sin receta, solo en farmacia" : "Venta libre"}
            </span>
          </div>
        )}
        {data.otherStatus && (
          <div style={{ marginTop: 8, fontSize: 11, color: COLORS.slateLight }}>
            En {countryName} también hay {data.otherStatus.total}{" "}
            {data.otherStatus.receta ? "con receta" : "sin receta"} de esta forma.
          </div>
        )}
      </div>
    </div>
  );
}

/* Qué decir cuando un país no tiene el grupo (principio activo + forma) que se
   está mirando. Solo afirmamos lo que sabemos: de un país sin datos reales no
   decimos que el producto no exista, y de uno con datos reales decimos "no
   hemos encontrado", no "no existe", porque solo conocemos nuestros datos. */
function CountryNotice({ country, group, rows, isReal, includeRx }) {
  const countryName = COUNTRIES.find((c) => c.code === country)?.name ?? country;
  let text;
  if (!isReal) {
    text = `Todavía no tenemos datos verificados de ${countryName}.`;
  } else {
    const otherForms = [
      ...new Set(
        rows
          .filter(
            (r) =>
              r.country_code === country &&
              r.inn_name === group.innName &&
              r.source !== "manual_seed" &&
              r.form
          )
          .map((r) => formLabel(r.form))
      ),
    ];
    const shown = otherForms.slice(0, 5).join(", ");
    const more = otherForms.length > 5 ? ` y ${otherForms.length - 5} más` : "";
    text = otherForms.length
      ? `Hay productos con este principio activo en ${countryName}, pero en otra forma (${shown}${more}). No son equivalentes.`
      : includeRx
        ? `No hemos encontrado en ${countryName} ningún producto con este principio activo (no incluimos inyectables ni productos de uso hospitalario).`
        : `No hemos encontrado en ${countryName} ningún producto de venta libre con este principio activo.`;
  }
  return (
    <div
      style={{
        flex: 1,
        minWidth: 220,
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        padding: 16,
        background: "#fff",
        border: `1px dashed ${COLORS.cardBorder}`,
        borderRadius: 10,
        color: COLORS.slate,
        fontSize: 13,
        lineHeight: 1.4,
      }}
    >
      <Info size={15} style={{ flexShrink: 0, marginTop: 1 }} />
      <span>
        <strong style={{ fontWeight: 600 }}>{countryName}.</strong> {text}
      </span>
    </div>
  );
}

export default function MediPass() {
  const [rows, setRows] = useState([]);
  const [meds, setMeds] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | error | ready
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [from, setFrom] = useState("ES");
  const [to, setTo] = useState("DE");
  const [showESList, setShowESList] = useState(false);
  const [includeRx, setIncludeRx] = useState(true); // lo confirma el backend (INCLUDE_PRESCRIPTION)
  const [listFilter, setListFilter] = useState("all"); // all | otc | rx
  const [listLimit, setListLimit] = useState(200);
  // Cuando el usuario encuentra un principio activo buscando por una marca
  // concreta (ej. "Cristalmina"), recordamos esa marca para mostrarla en
  // vez del producto representativo por defecto de ese país.
  // Producto elegido a mano: al buscar una marca concreta o al pulsar "Ver otro producto".
  // Clave: grupo|país (marca buscada) o grupo|país|producto de referencia (botón).
  const [picked, setPicked] = useState({});

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/config`)
      .then((res) => res.json())
      .then((cfg) => setIncludeRx(!!cfg.include_prescription))
      .catch(() => {});
    fetch(`${API_BASE_URL}/api/equivalences`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setRows(data);
        const grouped = groupEquivalences(data);
        setMeds(grouped);
        // Al abrir, mostramos el primer grupo que ya se puede comparar
        // (tiene España y al menos otro país).
        const comparable = grouped.find(
          (g) => g.equivalencias.ES && Object.keys(g.equivalencias).length > 1
        );
        setSelectedId((comparable ?? grouped[0])?.id ?? null);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  // Resultados del buscador: hasta 6 grupos (principio activo + forma) que
  // coinciden por nombre o forma (ej. "diclofenaco gel") y hasta 8 productos
  // cuya marca coincide (ej. "Cristalmina"), para no saturar la lista.
  const searchResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];

    const results = [];

    meds
      .filter((m) => `${m.name} ${m.forma}`.toLowerCase().includes(q))
      .slice(0, 6)
      .forEach((m) => {
        results.push({
          key: `group-${m.id}`,
          groupId: m.id,
          title: m.forma ? `${m.name} · ${m.forma}` : m.name,
          subtitle: m.uso ?? "",
          icon: m.icon,
          brandMatch: null,
        });
      });

    rows
      .filter((r) => r.brand_name.toLowerCase().includes(q))
      .slice(0, 8)
      .forEach((r) => {
        const gid = groupId(r);
        const med = meds.find((m) => m.id === gid);
        const countryName = COUNTRIES.find((c) => c.code === r.country_code)?.name ?? r.country_code;
        results.push({
          key: `product-${gid}-${r.brand_name}-${r.country_code}`,
          groupId: gid,
          title: r.brand_name,
          subtitle: [capitalize(r.inn_name), formLabel(r.form), countryName, r.requires_prescription ? "CON RECETA" : null]
            .filter(Boolean)
            .join(" · "),
          icon: med?.icon ?? Pill,
          brandMatch: { countryCode: r.country_code, data: productFromRow(r) },
        });
      });

    return results;
  }, [meds, rows, query]);

  const esProducts = useMemo(
    () =>
      rows
        .filter((r) => r.country_code === "ES")
        .sort((a, b) => a.brand_name.localeCompare(b.brand_name)),
    [rows]
  );
  const esFiltered = useMemo(
    () =>
      esProducts.filter((p) =>
        listFilter === "all" ? true : listFilter === "rx" ? !!p.requires_prescription : !p.requires_prescription
      ),
    [esProducts, listFilter]
  );

  // Países con datos reales de una agencia oficial; el resto solo tiene ejemplos
  // manuales sin verificar (hoy: España, Francia y Reino Unido tienen datos reales).
  const realCountries = useMemo(
    () => new Set(rows.filter((r) => r.source !== "manual_seed").map((r) => r.country_code)),
    [rows]
  );

  // Índice por principio activo BASE + forma, por país: sirve para el nivel "misma base, otro éster
  // o sal" (fluticasone propionate ~ fluticasona) cuando no hay equivalente exacto.
  const baseIndex = useMemo(() => {
    const index = {};
    for (const row of rows) {
      if (row.source === "manual_seed" || !row.base_inn) continue;
      const key = `${row.base_inn}||${row.form ?? ""}`;
      const slotMap = (index[row.country_code] ??= new Map());
      const slot = slotMap.get(key) ?? { otc: [], rx: [], names: new Set() };
      slotMap.set(key, slot);
      slot.names.add(row.inn_name);
      const product = productFromRow(row);
      slot[product.receta ? "rx" : "otc"].push(product);
    }
    return index;
  }, [rows]);

  const selected = meds.find((m) => m.id === selectedId);

  // El mejor producto de `entry` para un país según el producto de referencia `ref` (el del otro lado),
  // o el que el usuario haya elegido a mano.
  function choose(entry, countryCode, wantRx, ref) {
    const key = `${selectedId}|${countryCode}|${ref?.marca ?? ""}`;
    const explicit = picked[key] ?? picked[`${selectedId}|${countryCode}`] ?? null;
    return pickVariant(entry, wantRx, ref, explicit, key);
  }

  function approxVariant(countryCode, wantRx, ref) {
    if (!selected) return null;
    const slot = baseIndex[countryCode]?.get(`${selected.baseInn}||${selected.rawForm}`);
    const data = choose(slot, countryCode, wantRx, ref);
    if (!data) return null;
    // Solo cuenta si el nombre difiere del del grupo (si no, sería un equivalente exacto).
    const names = [...slot.names].filter((n) => n !== selected.innName).sort();
    return names.length ? { data, names } : null;
  }

  function equivalenceFor(countryCode, wantRx, ref) {
    return choose(selected?.equivalencias[countryCode], countryCode, wantRx, ref);
  }

  const fromData = selected && equivalenceFor(from, false, null);
  const toData = selected && equivalenceFor(to, !!fromData?.receta, fromData);
  // Nivel "forma parecida": el mismo principio activo (exacto) en una forma de la misma familia.
  function similarFormVariant(countryCode, wantRx, ref) {
    if (!selected) return null;
    for (const otherForm of relatedForms(selected.rawForm)) {
      const slot = baseIndex[countryCode]?.get(`${selected.baseInn}||${otherForm}`);
      if (slot && slot.names.has(selected.innName)) {
        const data = choose(slot, countryCode, wantRx, ref);
        if (data) return { data, label: formLabel(otherForm) };
      }
    }
    return null;
  }

  // Nivel "misma base": solo si ese país no tiene el grupo exacto.
  const approxFrom = selected && !fromData ? approxVariant(from, !!toData?.receta, toData) : null;
  const approxTo = selected && !toData ? approxVariant(to, !!fromData?.receta, fromData) : null;
  const similarFrom = selected && !fromData && !approxFrom ? similarFormVariant(from, !!toData?.receta, toData) : null;
  const similarTo = selected && !toData && !approxTo ? similarFormVariant(to, !!fromData?.receta, fromData) : null;
  const shownFrom = fromData ?? approxFrom?.data ?? similarFrom?.data ?? null;
  const shownTo = toData ?? approxTo?.data ?? similarTo?.data ?? null;
  const receWarning = selected && shownFrom && shownTo && shownFrom.receta !== shownTo.receta;
  const countryNameOf = (code) => COUNTRIES.find((c) => c.code === code)?.name ?? code;
  const dose =
    shownFrom && shownTo && shownFrom.source !== "manual_seed" && shownTo.source !== "manual_seed"
      ? doseSummary(shownFrom, shownTo, countryNameOf(from), countryNameOf(to))
      : null;
  // Desplegable de productos: guarda el elegido a mano para ese país (y para ese producto de referencia).
  const next = (d) =>
    d && d.total > 1 ? (name) => setPicked((prev) => ({ ...prev, [d.key]: name })) : undefined;

  // Foto y composición solo existen para los productos de España (vienen de CIMA).
  const esSideData = from === "ES" ? shownFrom : to === "ES" ? shownTo : null;

  if (status === "loading") {
    return (
      <div style={{ minHeight: "100vh", background: COLORS.paper, color: COLORS.ink, fontFamily: "sans-serif", padding: 40 }}>
        Cargando datos de MediPass…
      </div>
    );
  }

  if (status === "error") {
    return (
      <div style={{ minHeight: "100vh", background: COLORS.paper, color: COLORS.warnText, fontFamily: "sans-serif", padding: 40 }}>
        No se pudo conectar con el backend en {API_BASE_URL}.
        <br />
        ¿Está corriendo <code>python app.py</code> dentro de la carpeta <code>backend/</code>?
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: COLORS.paper, color: COLORS.ink, fontFamily: "'Inter', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');
        @media (prefers-reduced-motion: no-preference) {
          .flap-enter { animation: flapIn 0.35s ease-out; }
        }
        @keyframes flapIn {
          0% { transform: scaleY(0.4); opacity: 0; }
          60% { transform: scaleY(1.05); opacity: 1; }
          100% { transform: scaleY(1); }
        }
        select:focus, input:focus, button:focus-visible {
          outline: 2px solid ${COLORS.ink};
          outline-offset: 2px;
        }
      `}</style>

      {/* HEADER */}
      <header style={{ background: COLORS.ink, color: "#fff" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 20px 28px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: COLORS.amber }}>
            <Plane size={18} />
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.2em" }}>
              MediPass
            </span>
          </div>
          <h1 style={{ marginTop: 12, fontSize: 30, lineHeight: 1.15, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Tu medicamento, en el idioma
            <br />
            de cualquier farmacia.
          </h1>
          <p style={{ marginTop: 10, color: "#C7CEDA", fontSize: 14, maxWidth: 440 }}>
            Busca lo que ya tomas en tu país y encuentra su equivalente antes de pisar la farmacia fuera.
          </p>
        </div>
      </header>

      <main style={{ maxWidth: 720, margin: "0 auto", padding: "0 20px 64px" }}>
        {/* DISCLAIMER */}
        <div
          style={{
            marginTop: 20,
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "rgba(255,182,39,0.1)",
            border: `1px solid rgba(255,182,39,0.35)`,
            borderRadius: 10,
            padding: "10px 14px",
            fontSize: 13,
            lineHeight: 1.4,
            color: COLORS.ink,
          }}
        >
          <Info size={16} color={COLORS.warnIcon} style={{ flexShrink: 0 }} />
          <span>
            Información orientativa, no sustituye el consejo de un farmacéutico o médico.
          </span>
        </div>

        {/* BUSCADOR */}
        <div
          style={{
            marginTop: -16,
            background: "#fff",
            borderRadius: 14,
            boxShadow: "0 4px 20px rgba(20,33,61,0.12)",
            border: `1px solid ${COLORS.cardBorder}`,
            padding: 18,
          }}
        >
          <div style={{ position: "relative" }}>
            <Search size={17} style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: COLORS.slateLight }} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Busca por nombre o principio activo…"
              style={{
                width: "100%",
                background: COLORS.paperCard,
                borderRadius: 10,
                border: "none",
                padding: "12px 12px 12px 40px",
                fontSize: 15,
                boxSizing: "border-box",
              }}
            />
          </div>

          {query.trim() && (
            <div style={{ marginTop: 8, border: `1px solid ${COLORS.cardBorder}`, borderRadius: 10, overflow: "hidden" }}>
              {searchResults.length === 0 && (
                <div style={{ padding: 12, fontSize: 14, color: COLORS.slate }}>
                  No hay resultados para "{query}".
                </div>
              )}
              {searchResults.map((r, i) => (
                <button
                  key={r.key}
                  onClick={() => {
                    if (r.brandMatch) {
                      setPicked((prev) => ({ ...prev, [`${r.groupId}|${r.brandMatch.countryCode}`]: r.brandMatch.data.marca }));
                    }
                    setSelectedId(r.groupId);
                    setQuery("");
                  }}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: 12,
                    textAlign: "left",
                    background: "none",
                    border: "none",
                    borderTop: i === 0 ? "none" : `1px solid ${COLORS.cardBorder}`,
                    cursor: "pointer",
                  }}
                >
                  <r.icon size={16} color={COLORS.ink} />
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{r.title}</div>
                    <div style={{ fontSize: 12, color: COLORS.slate }}>{r.subtitle}</div>
                  </div>
                </button>
              ))}
            </div>
          )}

          <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
            <CountryPicker label="Desde" value={from} onChange={setFrom} />
            <CountryPicker label="Hacia" value={to} onChange={setTo} />
          </div>
        </div>

        {/* TOGGLE LISTADO ESPAÑA */}
        <div style={{ marginTop: 16 }}>
          <button
            onClick={() => setShowESList((v) => !v)}
            style={{
              fontSize: 12,
              padding: "6px 12px",
              borderRadius: 999,
              border: `1px solid rgba(20,33,61,0.2)`,
              background: showESList ? COLORS.ink : "transparent",
              color: showESList ? "#fff" : COLORS.ink,
              cursor: "pointer",
            }}
          >
            {showESList ? "Volver al buscador" : `Ver todos los medicamentos en España (${esProducts.length})`}
          </button>
        </div>

        {/* LISTADO ESPAÑA */}
        {showESList && (
          <section style={{ marginTop: 20 }}>
            {includeRx && (
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                {[
                  ["all", "Todos"],
                  ["otc", "Sin receta"],
                  ["rx", "Con receta"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => {
                      setListFilter(value);
                      setListLimit(200);
                    }}
                    style={{
                      fontSize: 12,
                      padding: "5px 12px",
                      borderRadius: 999,
                      border: `1px solid rgba(20,33,61,0.2)`,
                      background: listFilter === value ? COLORS.ink : "transparent",
                      color: listFilter === value ? "#fff" : COLORS.ink,
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                ))}
                <span style={{ fontSize: 12, color: COLORS.slate, alignSelf: "center" }}>
                  {esFiltered.length} productos
                </span>
              </div>
            )}
            <div style={{ border: `1px solid ${COLORS.cardBorder}`, borderRadius: 10, overflow: "hidden", background: "#fff" }}>
              {esFiltered.slice(0, listLimit).map((p, i) => (
                <div
                  key={`${p.inn_name}-${p.brand_name}-${i}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    padding: 12,
                    borderTop: i === 0 ? "none" : `1px solid ${COLORS.cardBorder}`,
                  }}
                >
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{p.brand_name}</div>
                    <div style={{ fontSize: 12, color: COLORS.slate }}>
                      {[capitalize(p.inn_name), p.dose, formLabel(p.form)].filter(Boolean).join(" · ")}
                    </div>
                  </div>
                  {p.requires_prescription ? (
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: "#fff",
                        background: COLORS.rx,
                        padding: "3px 8px",
                        borderRadius: 6,
                        whiteSpace: "nowrap",
                      }}
                    >
                      CON RECETA
                    </span>
                  ) : (
                    <span style={{ fontSize: 11, fontWeight: 500, color: COLORS.green, whiteSpace: "nowrap" }}>
                      Venta libre
                    </span>
                  )}
                </div>
              ))}
            </div>
            {esFiltered.length > listLimit && (
              <button
                onClick={() => setListLimit((n) => n + 200)}
                style={{
                  marginTop: 12,
                  fontSize: 13,
                  padding: "8px 16px",
                  borderRadius: 999,
                  border: `1px solid rgba(20,33,61,0.2)`,
                  background: "transparent",
                  color: COLORS.ink,
                  cursor: "pointer",
                }}
              >
                Mostrar 200 más ({esFiltered.length - listLimit} restantes)
              </button>
            )}
          </section>
        )}

        {/* RESULTADO */}
        {!showESList && selected && (
          <section key={`${selected.id}-${from}-${to}`} className="flap-enter" style={{ marginTop: 28 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <selected.icon size={16} color={COLORS.ink} />
              <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
                {selected.forma ? `${selected.name} · ${selected.forma}` : selected.name}
              </h2>
              <span
                style={{
                  fontSize: 11,
                  fontFamily: "'IBM Plex Mono', monospace",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  color: COLORS.slate,
                  background: COLORS.cardBorder,
                  padding: "2px 8px",
                  borderRadius: 6,
                }}
              >
                {selected.categoria}
              </span>
            </div>
            <p style={{ fontSize: 12, color: COLORS.slate, marginBottom: 14 }}>
              Principio activo: {selected.principio}
              {selected.uso ? ` · ${selected.uso}` : ""}
            </p>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "stretch" }}>
              {fromData ? (
                <FlapCard country={from} data={fromData} onPick={next(fromData)} />
              ) : approxFrom ? (
                <FlapCard country={from} data={approxFrom.data} approx={{ names: approxFrom.names }} onPick={next(approxFrom.data)} />
              ) : similarFrom ? (
                <FlapCard country={from} data={similarFrom.data} similarForm={{ label: similarFrom.label }} onPick={next(similarFrom.data)} />
              ) : (
                <CountryNotice country={from} group={selected} rows={rows} isReal={realCountries.has(from)} includeRx={includeRx} />
              )}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "0 2px" }}>
                <Plane size={16} color={COLORS.slateLight} />
              </div>
              {toData ? (
                <FlapCard country={to} data={toData} highlight onPick={next(toData)} />
              ) : approxTo ? (
                <FlapCard country={to} data={approxTo.data} highlight approx={{ names: approxTo.names }} onPick={next(approxTo.data)} />
              ) : similarTo ? (
                <FlapCard country={to} data={similarTo.data} highlight similarForm={{ label: similarTo.label }} onPick={next(similarTo.data)} />
              ) : (
                <CountryNotice country={to} group={selected} rows={rows} isReal={realCountries.has(to)} includeRx={includeRx} />
              )}
            </div>

            {fromData && toData && fromData.source !== "manual_seed" && toData.source !== "manual_seed" && (
              <p style={{ marginTop: 10, fontSize: 12, color: COLORS.slate }}>
                Mismo principio activo y misma forma.
              </p>
            )}
            {dose && (
              <p
                style={{
                  marginTop: 10,
                  fontSize: 13,
                  color: dose.warn ? COLORS.warnText : COLORS.slate,
                  background: dose.warn ? COLORS.warnBg : "transparent",
                  border: dose.warn ? `1px solid ${COLORS.warnBorder}` : "none",
                  borderRadius: 8,
                  padding: dose.warn ? "8px 12px" : 0,
                }}
              >
                <strong>Dosis y público.</strong> {dose.text}
              </p>
            )}
            {(similarFrom || similarTo) && shownFrom && shownTo && (
              <p style={{ marginTop: 10, fontSize: 13, color: COLORS.info, background: COLORS.infoBg, border: `1px solid ${COLORS.info}`, borderRadius: 8, padding: "8px 12px" }}>
                <strong>No es la misma forma.</strong> Es el mismo principio activo, pero en {(similarTo ?? similarFrom).label.toLowerCase()} en lugar de {selected.forma.toLowerCase()}.
                Se usan de manera parecida, pero pueden diferir en textura y absorción. Consulta a un farmacéutico.
              </p>
            )}
            {(approxFrom || approxTo) && shownFrom && shownTo && (
              <p style={{ marginTop: 10, fontSize: 13, color: COLORS.warnText, background: COLORS.warnBg, border: `1px solid ${COLORS.warnBorder}`, borderRadius: 8, padding: "8px 12px" }}>
                <strong>No está confirmado que sea exactamente la misma sustancia.</strong> Comparten el principio activo base
                ({selected.baseInn}), pero figuran con nombres distintos ({selected.innName} y {(approxTo ?? approxFrom).names.join(", ")}):
                puede tratarse de otro éster, sal o extracto y diferir en potencia y dosis. Consulta a un farmacéutico.
              </p>
            )}

            {esSideData?.sourceRef ? (
              <div style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center" }}>
                {esSideData.photoUrl && (
                  <img
                    src={esSideData.photoUrl}
                    alt={esSideData.marca}
                    style={{ width: 72, height: 72, objectFit: "contain", background: "#fff", borderRadius: 8, border: `1px solid ${COLORS.cardBorder}` }}
                  />
                )}
                <p style={{ fontSize: 12, color: COLORS.slate, margin: 0 }}>
                  {[esSideData.composition, esSideData.dose, formLabel(esSideData.form)]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            ) : (
              <p style={{ marginTop: 14, fontSize: 12, color: COLORS.slateLight }}>
                Sin foto ni composición disponibles para este producto.
              </p>
            )}

            {receWarning && (
              <div
                role="alert"
                style={{
                  marginTop: 14,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  background: COLORS.rxBg,
                  border: `2px solid ${COLORS.rx}`,
                  borderRadius: 10,
                  padding: 14,
                  fontSize: 15,
                  fontWeight: 600,
                  color: COLORS.rxDark,
                }}
              >
                <AlertTriangle size={22} style={{ flexShrink: 0 }} />
                <span>
                  ATENCIÓN: en {COUNTRIES.find((c) => c.code === (fromData.receta ? from : to))?.name} este medicamento solo se
                  vende con receta médica, y en {COUNTRIES.find((c) => c.code === (fromData.receta ? to : from))?.name} se vende
                  sin receta. Consulta a un médico o farmacéutico antes de comprarlo.
                </span>
              </div>
            )}

            <div style={{ marginTop: 12, display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: COLORS.slateLight }}>
              <Info size={13} style={{ flexShrink: 0, marginTop: 2 }} />
              <span>
                Datos servidos por el backend local desde medipass.db. España (CIMA), Francia (BDPM) y Reino Unido (NHS dm+d): medicamentos comercializados, de fuentes oficiales
                {includeRx
                  ? ", sin receta y con receta (los con receta se marcan en rojo). No se incluyen inyectables ni productos de uso hospitalario. Una franja ámbar indica el mismo principio activo base con un nombre distinto (otro éster, sal o extracto); una azul, el mismo principio activo en una forma parecida (crema o pomada)."
                  : ", solo sin receta."}{" "}
                En el Reino Unido, «solo en farmacia» (P) no requiere receta pero lo dispensa un farmacéutico. Alemania, Italia y Portugal: ejemplos manuales sin verificar. Contains public sector information licensed under the Open Government Licence v3.0.
              </span>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
