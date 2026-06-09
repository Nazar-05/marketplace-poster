import { useState, useRef, useEffect } from "react";

const SORT_OPTIONS = [
  { value: "newest",     label: "Нові",                   icon: "🕐", desc: "Спочатку нові" },
  { value: "oldest",     label: "Старі",                  icon: "📅", desc: "Спочатку старі" },
  { value: "price_asc",  label: "Від дешевих до дорогих", icon: "💰", desc: "Зростання ціни" },
  { value: "price_desc", label: "Від дорогих до дешевих", icon: "💎", desc: "Спадання ціни" },
];

export default function SortDropdown({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = SORT_OPTIONS.find(o => o.value === value) || SORT_OPTIONS[0];

  useEffect(() => {
    const handler = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} style={{ position: "relative", minWidth: 160 }}>
      <div
        className="btn-sm"
        onClick={() => setOpen(o => !o)}
        style={{ display:"flex", alignItems:"center", gap:6, cursor:"pointer", userSelect:"none" }}
      >
        <span>{selected.icon}</span>
        <span style={{flex:1}}>{selected.label}</span>
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none"
          style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform 0.2s", flexShrink:0, opacity:.5 }}>
          <path d="M2 4L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </div>

      {open && (
        <div className="sort-dropdown">
          <div style={{ padding: "6px 10px 4px", fontSize: 10, fontWeight: 700, color: "#aaa", letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Сортування
          </div>
          {SORT_OPTIONS.map((opt, i) => (
            <div key={opt.value}>
              <div
                className={`sort-option ${opt.value === value ? "active" : ""}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}
              >
                <span style={{ fontSize: 16, flexShrink: 0 }}>{opt.icon}</span>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 1 }}>
                  <span style={{ fontWeight: opt.value === value ? 600 : 400 }}>{opt.label}</span>
                  <span style={{ fontSize: 11, color: opt.value === value ? "#7c6ee6" : "#aaa" }}>{opt.desc}</span>
                </div>
                {opt.value === value && (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
                    <path d="M2.5 7L5.5 10L11.5 4" stroke="#4f46e5" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </div>
              {i < SORT_OPTIONS.length - 1 && (
                <div style={{ height: 1, background: "#f0f0f0", margin: "0 10px" }} />
              )}
            </div>
          ))}
          <div style={{ height: 6 }} />
        </div>
      )}
    </div>
  );
}