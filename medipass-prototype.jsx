import React, { useState, useMemo } from "react";
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

/* ---------------------------------------------------------
   DATOS DE EJEMPLO (mock) — no verificados clínicamente.
   En producción vendrían de CIMA / BotPlus / EMA / equivalentes
   nacionales por país.
--------------------------------------------------------- */

const COUNTRIES = [
  { code: "ES", name: "España" },
  { code: "DE", name: "Alemania" },
  { code: "FR", name: "Francia" },
  { code: "IT", name: "Italia" },
  { code: "PT", name: "Portugal" },
  { code: "UK", name: "Reino Unido" },
];

const MEDS = [
  {
    id: "cera",
    name: "Disolvente de cerumen",
    principio: "Docusato sódico",
    uso: "Ablandar y eliminar la cera del oído",
    categoria: "Salud",
    icon: Droplet,
    equivalencias: {
      ES: { marca: "Cerumenex", receta: false },
      DE: { marca: "Otowaxol Ohrentropfen", receta: false },
      FR: { marca: "Cerulyse", receta: false },
      IT: { marca: "Cerumex Gocce", receta: false },
      PT: { marca: "Otex Gotas", receta: false },
      UK: { marca: "Earex Plus", receta: false },
    },
  },
  {
    id: "mareo",
    name: "Antimareo (cinetosis)",
    principio: "Dimenhidrinato",
    uso: "Prevención de mareo en viajes",
    categoria: "Salud",
    icon: Compass,
    equivalencias: {
      ES: { marca: "Biodramina", receta: false },
      DE: { marca: "Vomex A", receta: false },
      FR: { marca: "Nautamine", receta: false },
      IT: { marca: "Xamamina", receta: false },
      PT: { marca: "Enjomin", receta: false },
      UK: { marca: "Dramamine (import)", receta: false },
    },
  },
  {
    id: "antiinflamatorio",
    name: "Crema antiinflamatoria tópica",
    principio: "Diclofenaco 1%",
    uso: "Dolor e inflamación muscular/articular localizada",
    categoria: "Salud",
    icon: Pill,
    equivalencias: {
      ES: { marca: "Voltadol Gel", receta: false },
      DE: { marca: "Voltaren Schmerzgel Forte", receta: true },
      FR: { marca: "Voltarène Emulgel", receta: false },
      IT: { marca: "Dolorfast Gel", receta: false },
      PT: { marca: "Voltaren Emulgel", receta: false },
      UK: { marca: "Voltarol 12 Hour", receta: false },
    },
  },
  {
    id: "tiritas",
    name: "Apósito cicatrizante",
    principio: "Hidrocoloide + poliuretano",
    uso: "Heridas leves, protección y cicatrización",
    categoria: "Producto sanitario",
    icon: Package,
    equivalencias: {
      ES: { marca: "Cicatrin Tiritas", receta: false },
      DE: { marca: "Hansaplast Wundheilung", receta: false },
      FR: { marca: "Urgo Cicatrisant", receta: false },
      IT: { marca: "Hansaplast Cicatrizzante", receta: false },
      PT: { marca: "Cicaplast Penso", receta: false },
      UK: { marca: "Hansaplast Wound Healing", receta: false },
    },
  },
  {
    id: "ampollas",
    name: "Apósito para ampollas",
    principio: "Hidrocoloide avanzado",
    uso: "Protección y curación de ampollas por rozadura",
    categoria: "Producto sanitario",
    icon: Sparkles,
    equivalencias: {
      ES: { marca: "Compeed Ampollas", receta: false },
      DE: { marca: "Compeed Blasenpflaster", receta: false },
      FR: { marca: "Compeed Ampoules", receta: false },
      IT: { marca: "Compeed Vesciche", receta: false },
      PT: { marca: "Compeed Bolhas", receta: false },
      UK: { marca: "Compeed Blister Plasters", receta: false },
    },
  },
  {
    id: "llagas",
    name: "Enjuague para llagas bucales",
    principio: "Clorhexidina 0,2%",
    uso: "Higiene y alivio de aftas/llagas bucales",
    categoria: "Higiene",
    icon: Droplet,
    equivalencias: {
      ES: { marca: "Bexident Encías", receta: false },
      DE: { marca: "Chlorhexamed Fluid", receta: false },
      FR: { marca: "Eludril", receta: false },
      IT: { marca: "Curasept", receta: false },
      PT: { marca: "Eludril Bucal", receta: false },
      UK: { marca: "Corsodyl Mouthwash", receta: false },
    },
  },
];

const SCENARIOS = [
  {
    id: "maria",
    label: "María, Erasmus en Alemania",
    text: "Se le llena el oído de cera en el lago y necesita el equivalente en Alemania.",
    med: "cera",
    from: "ES",
    to: "DE",
  },
  {
    id: "raquel",
    label: "Raquel, viajera olvidadiza",
    text: "Se le olvidó el antimareo en la maleta antes de volar a Francia.",
    med: "mareo",
    from: "ES",
    to: "FR",
  },
];

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
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("cera");
  const [from, setFrom] = useState("ES");
  const [to, setTo] = useState("DE");

  const filtered = useMemo(() => {
    if (!query.trim()) return MEDS;
    const q = query.toLowerCase();
    return MEDS.filter(
      (m) => m.name.toLowerCase().includes(q) || m.principio.toLowerCase().includes(q)
    );
  }, [query]);

  const selected = MEDS.find((m) => m.id === selectedId);
  const fromData = selected?.equivalencias[from];
  const toData = selected?.equivalencias[to];
  const receWarning = selected && fromData && toData && fromData.receta !== toData.receta;

  const runScenario = (sc) => {
    setSelectedId(sc.med);
    setFrom(sc.from);
    setTo(sc.to);
    setQuery("");
  };

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
                  No hay resultados para "{query}" en el catálogo de ejemplo.
                </div>
              )}
              {filtered.map((m, i) => (
                <button
                  key={m.id}
                  onClick={() => {
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

        {/* ESCENARIOS DE EJEMPLO */}
        <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {SCENARIOS.map((sc) => (
            <button
              key={sc.id}
              onClick={() => runScenario(sc)}
              title={sc.text}
              style={{
                fontSize: 12,
                padding: "6px 12px",
                borderRadius: 999,
                border: `1px solid rgba(20,33,61,0.2)`,
                background: "transparent",
                color: COLORS.ink,
                cursor: "pointer",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = COLORS.ink;
                e.currentTarget.style.color = "#fff";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = COLORS.ink;
              }}
            >
              {sc.label}
            </button>
          ))}
        </div>

        {/* RESULTADO */}
        {selected && (
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
              <FlapCard country={from} data={fromData} />
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "0 2px" }}>
                <Plane size={16} color={COLORS.slateLight} />
              </div>
              <FlapCard country={to} data={toData} highlight />
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
                Datos de ejemplo para este prototipo — no verificados contra CIMA, BotPlus ni la EMA. No sustituye el consejo de un farmacéutico.
              </span>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
