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
};

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

/* Convierte las filas planas de GET /api/equivalences (una fila por
   producto) en una lista agrupada por principio activo, con una tarjeta
   por país. España puede tener varios productos por principio activo
   (datos reales de CIMA); nos quedamos con el primero que llega para
   mantener el diseño original de "una marca por país". */
function groupEquivalences(rows) {
  const byIngredient = new Map();

  for (const row of rows) {
    const key = row.inn_name;
    if (!byIngredient.has(key)) {
      byIngredient.set(key, {
        id: key,
        name: capitalize(row.inn_name),
        principio: capitalize(row.inn_name),
        uso: row.common_use,
        categoria: row.category,
        icon: ICONS_BY_CATEGORY[row.category] || Pill,
        equivalencias: {},
      });
    }

    const med = byIngredient.get(key);
    if (!med.equivalencias[row.country_code]) {
      med.equivalencias[row.country_code] = {
        marca: row.brand_name,
        receta: !!row.requires_prescription,
      };
    }
  }

  return Array.from(byIngredient.values());
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

function FlapCard({ country, data, highlight }) {
  const countryName = COUNTRIES.find((c) => c.code === country)?.name ?? country;
  return (
    <div
      style={{
        flex: 1,
        minWidth: 220,
        background: COLORS.inkDark,
        borderRadius: 10,
        border: `1px solid ${COLORS.inkBorder}`,
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
        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 6 }}>
          {data.receta ? (
            <>
              <AlertTriangle size={14} color={COLORS.warnIcon} />
              <span style={{ fontSize: 12, fontWeight: 500, color: COLORS.warnIcon }}>
                Con receta en este país
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 size={14} color={COLORS.green} />
              <span style={{ fontSize: 12, fontWeight: 500, color: COLORS.green }}>
                Venta libre
              </span>
            </>
          )}
        </div>
      </div>
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
  // Cuando el usuario encuentra un principio activo buscando por una marca
  // concreta (ej. "Cristalmina"), recordamos esa marca para mostrarla en
  // vez del producto representativo por defecto de ese país.
  const [preferredBrand, setPreferredBrand] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/equivalences`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setRows(data);
        const grouped = groupEquivalences(data);
        setMeds(grouped);
        setSelectedId(grouped[0]?.id ?? null);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim()) return meds;
    const q = query.toLowerCase();
    // Busca también por nombre de marca (ej. "Cristalmina"), no solo por
    // principio activo — hay muchas marcas por principio activo en España.
    const ingredientsWithMatchingBrand = new Set(
      rows.filter((r) => r.brand_name.toLowerCase().includes(q)).map((r) => r.inn_name)
    );
    return meds.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.principio.toLowerCase().includes(q) ||
        ingredientsWithMatchingBrand.has(m.id)
    );
  }, [meds, rows, query]);

  const esProducts = useMemo(
    () =>
      rows
        .filter((r) => r.country_code === "ES")
        .sort((a, b) => a.brand_name.localeCompare(b.brand_name)),
    [rows]
  );

  const selected = meds.find((m) => m.id === selectedId);

  function equivalenceFor(countryCode) {
    if (
      preferredBrand &&
      preferredBrand.ingredientId === selectedId &&
      preferredBrand.countryCode === countryCode
    ) {
      return { marca: preferredBrand.marca, receta: preferredBrand.receta };
    }
    return selected?.equivalencias[countryCode];
  }

  const fromData = selected && equivalenceFor(from);
  const toData = selected && equivalenceFor(to);
  const receWarning = selected && fromData && toData && fromData.receta !== toData.receta;

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
              {filtered.length === 0 && (
                <div style={{ padding: 12, fontSize: 14, color: COLORS.slate }}>
                  No hay resultados para "{query}".
                </div>
              )}
              {filtered.map((m, i) => (
                <button
                  key={m.id}
                  onClick={() => {
                    const q = query.trim().toLowerCase();
                    const matchedRow = rows.find(
                      (r) => r.inn_name === m.id && r.brand_name.toLowerCase().includes(q)
                    );
                    setPreferredBrand(
                      matchedRow
                        ? {
                            ingredientId: m.id,
                            countryCode: matchedRow.country_code,
                            marca: matchedRow.brand_name,
                            receta: !!matchedRow.requires_prescription,
                          }
                        : null
                    );
                    setSelectedId(m.id);
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
                  <m.icon size={16} color={COLORS.ink} />
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{m.name}</div>
                    <div style={{ fontSize: 12, color: COLORS.slate }}>{m.principio}</div>
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
            <div style={{ border: `1px solid ${COLORS.cardBorder}`, borderRadius: 10, overflow: "hidden", background: "#fff" }}>
              {esProducts.map((p, i) => (
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
                    <div style={{ fontSize: 12, color: COLORS.slate }}>{capitalize(p.inn_name)}</div>
                  </div>
                  {p.requires_prescription ? (
                    <span style={{ fontSize: 11, fontWeight: 500, color: COLORS.warnIcon, whiteSpace: "nowrap" }}>
                      Con receta
                    </span>
                  ) : (
                    <span style={{ fontSize: 11, fontWeight: 500, color: COLORS.green, whiteSpace: "nowrap" }}>
                      Venta libre
                    </span>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* RESULTADO */}
        {!showESList && selected && (
          <section key={`${selected.id}-${from}-${to}`} className="flap-enter" style={{ marginTop: 28 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <selected.icon size={16} color={COLORS.ink} />
              <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{selected.name}</h2>
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
              Principio activo: {selected.principio} · {selected.uso}
            </p>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "stretch" }}>
              {fromData ? <FlapCard country={from} data={fromData} /> : (
                <div style={{ flex: 1, minWidth: 220, padding: 16, color: COLORS.slateLight, fontSize: 13 }}>
                  Sin datos para este país.
                </div>
              )}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "0 2px" }}>
                <Plane size={16} color={COLORS.slateLight} />
              </div>
              {toData ? <FlapCard country={to} data={toData} highlight /> : (
                <div style={{ flex: 1, minWidth: 220, padding: 16, color: COLORS.slateLight, fontSize: 13 }}>
                  Sin datos para este país.
                </div>
              )}
            </div>

            {receWarning && (
              <div
                style={{
                  marginTop: 14,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  background: COLORS.warnBg,
                  border: `1px solid ${COLORS.warnBorder}`,
                  borderRadius: 10,
                  padding: 12,
                  fontSize: 14,
                  color: COLORS.warnText,
                }}
              >
                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>
                  El estatus de venta cambia entre países: revisa si necesitas receta antes de acudir a la farmacia en destino.
                </span>
              </div>
            )}

            <div style={{ marginTop: 12, display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: COLORS.slateLight }}>
              <Info size={13} style={{ flexShrink: 0, marginTop: 2 }} />
              <span>
                Datos servidos por el backend local desde medipass.db (CIMA para España, placeholders manuales para el resto). No sustituye el consejo de un farmacéutico.
              </span>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
