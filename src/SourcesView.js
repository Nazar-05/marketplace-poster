import { useState, useEffect, useRef } from "react";
import SortDropdown from "./SortDropdown";

const SERVER = "http://localhost:5001";

const CRM_TYPES = [
  { id:"mydrop", name:"MyDrop", logo:"https://www.google.com/s2/favicons?domain=mydrop.com.ua&sz=64", field:"mydrop_token", label:"API Токен", hint:"MyDrop → Інтеграції → API", placeholder:"Вставте токен...", link:"https://mydrop.com.ua" },
  { id:"keycrm", name:"KeyCRM", logo:"https://www.google.com/s2/favicons?domain=keycrm.app&sz=64",   field:"keycrm_key",  label:"API Ключ",  hint:"KeyCRM → Налаштування → API", placeholder:"Вставте ключ...",  link:"https://keycrm.app" },
];

const STATUS_LEGEND = [
  { emoji:"✅", label:"Синхронізовано",       desc:"Товари успішно завантажені" },
  { emoji:"❌", label:"Вимкнено",              desc:"Відключено вручну" },
  { emoji:"⏳", label:"Очікує API",            desc:"Приватний канал — потрібен API ID + Hash" },
  { emoji:"🛑", label:"Помилка синхронізації", desc:"Перевір API ключ або з'єднання" },
  { emoji:"🔘", label:"Не синхронізовано",     desc:"Канал ще не перевірявся" },
];

function StatusLegendPopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position:"relative", display:"inline-flex" }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Що означають статуси?"
        style={{
          width:20, height:20, borderRadius:"50%",
          border:"1.5px solid #bbb", background:"none",
          cursor:"pointer", fontSize:11, fontWeight:700,
          color:"#888", lineHeight:1, padding:0,
          display:"flex", alignItems:"center", justifyContent:"center",
          flexShrink:0,
        }}
      >?</button>

      {open && (
        <div style={{
          position:"absolute", top:"calc(100% + 6px)", left:"50%",
          transform:"translateX(-50%)",
          background:"#fff", border:"1px solid #e5e7eb",
          borderRadius:10, boxShadow:"0 4px 16px rgba(0,0,0,0.10)",
          padding:"10px 14px", zIndex:999, minWidth:260,
          fontSize:13, color:"#222",
        }}>
          <div style={{ fontWeight:600, marginBottom:8, color:"#555", fontSize:12 }}>
            Статус каналу
          </div>
          {STATUS_LEGEND.map(({ emoji, label, desc }) => (
            <div key={emoji} style={{ display:"flex", gap:8, alignItems:"flex-start", marginBottom:6 }}>
              <span style={{ fontSize:15, flexShrink:0, lineHeight:"1.4" }}>{emoji}</span>
              <span>
                <span style={{ fontWeight:500 }}>{label}</span>
                <span style={{ color:"#888", marginLeft:4 }}>— {desc}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SourcesView({ serverOnline, onProductsLoaded, onChannelToggle }) {
  const [settings, setSettings] = useState({ telegram_mode:"public", telegram_channels:[], has_mydrop_token:false, has_keycrm_key:false, has_telegram_api:false });
  const [channels, setChannels] = useState([""]);
  const [apiKeys, setApiKeys]   = useState({ mydrop_token:"", keycrm_key:"", telegram_api_id:"", telegram_api_hash:"" });
  const [tgMode, setTgMode]     = useState("public");
  const [syncing, setSyncing]   = useState({});
  const [logs, setLogs]         = useState({});
  const [saved, setSaved]             = useState(false);
  const [pendingPrivate, setPendingPrivate] = useState([]);
  const [disabledChannels, setDisabledChannels] = useState(() => {
    try { return JSON.parse(localStorage.getItem("mp_disabled_channels") || "[]"); } catch { return []; }
  });
  const [channelStatus, setChannelStatus] = useState(() => {
    try { return JSON.parse(localStorage.getItem("mp_channel_status") || "{}"); } catch { return {}; }
  });

  function toggleChannel(ch) {
    setDisabledChannels(prev => {
      const next = prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch];
      localStorage.setItem("mp_disabled_channels", JSON.stringify(next));
      if (onChannelToggle) onChannelToggle();
      return next;
    });
  }

  function getChannelStatus(ch) {
    if (disabledChannels.includes(ch)) return "❌";
    if (pendingPrivate.includes(ch))   return "⏳";
    if (channelStatus[ch] === "ok")    return "✅";
    if (channelStatus[ch] === "error") return "🛑";
    return "🔘";
  }

  function getChannelRowClass(ch) {
    if (disabledChannels.includes(ch))      return "channel-row status-off";
    if (pendingPrivate.includes(ch))        return "channel-row status-pending";
    if (channelStatus[ch] === "ok")         return "channel-row status-ok";
    if (channelStatus[ch] === "error")      return "channel-row status-error";
    return "channel-row status-unknown";
  }

  useEffect(() => {
    if (!serverOnline) return;
    fetch(`${SERVER}/pending-private-channels`)
      .then(r => r.json())
      .then(d => setPendingPrivate(d || []))
      .catch(() => {});
  }, [serverOnline]);

  useEffect(() => {
    if (!serverOnline) return;
    fetch(`${SERVER}/settings`).then(r => r.json()).then(d => {
      setSettings(d);
      setTgMode(d.telegram_mode || "public");
      setChannels(d.telegram_channels?.length ? d.telegram_channels : [""]);
    }).catch(() => {});
  }, [serverOnline]);

  useEffect(() => {
    localStorage.setItem("mp_channel_status", JSON.stringify(channelStatus));
  }, [channelStatus]);

  function addLog(source, msg) {
    setLogs(l => ({ ...l, [source]: [...(l[source] || []), msg] }));
  }

  async function save() {
    if (!serverOnline) return;
    const chs = channels.filter(c => c.trim());
    await fetch(`${SERVER}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...apiKeys, telegram_mode: tgMode, telegram_channels: chs }),
    });
    const fresh = await fetch(`${SERVER}/settings`).then(r => r.json());
    setSettings(fresh);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  async function sync(source) {
    if (!serverOnline) return;
    setSyncing(s => ({ ...s, [source]: true }));
    setLogs(l => ({ ...l, [source]: [] }));
    addLog(source, `🔄 Синхронізація з ${source}...`);
    try {
      const res  = await fetch(`${SERVER}/sync/${source}`, { method: "POST" });
      const data = await res.json();
      if (data.error) {
        addLog(source, `🛑 ${data.error}`);
        if (source === "telegram") {
          setChannelStatus(prev => {
            const next = {...prev};
            channels.filter(c=>c.trim()).forEach(ch => { next[ch] = "error"; });
            return next;
          });
        }
      } else {
        addLog(source, `✅ Отримано: ${data.total} товарів`);
        addLog(source, `🆕 Нових: ${data.new_count}`);
        addLog(source, `🔁 Дублікатів пропущено: ${data.skipped}`);
        if (source === "telegram" && data.channel_results) {
          setChannelStatus(prev => {
            const next = {...prev};
            Object.entries(data.channel_results).forEach(([ch, res]) => {
              next[ch] = res.status;
            });
            return next;
          });
        }
        if (onProductsLoaded) onProductsLoaded();
      }
    } catch {
      addLog(source, "❌ Сервер недоступний");
    }
    setSyncing(s => ({ ...s, [source]: false }));
  }

  function setChannel(i, val) { const arr = [...channels]; arr[i] = val; setChannels(arr); }
  function addChannel()       { setChannels(c => [...c, ""]); }
  function removeChannel(i)   { setChannels(c => c.filter((_, idx) => idx !== i)); }

  const hasKey = { mydrop: settings.has_mydrop_token, keycrm: settings.has_keycrm_key };

  const [allProducts, setAllProducts] = useState([]);
  useEffect(() => {
    Promise.all([
      fetch("/products.json").then(r=>r.json()).catch(()=>[]),
      fetch(`${SERVER}/synced-products`).then(r=>r.json()).catch(()=>[]),
    ]).then(([base, synced]) => {
      try {
        const manual = JSON.parse(localStorage.getItem("mp_manual") || "[]");
        setAllProducts([...base, ...synced, ...manual]);
      } catch { setAllProducts([...base, ...synced]); }
    });
  }, []);

  function getChannelCount(ch) {
    return allProducts.filter(p => p.supplier === ch || p.source_channel === ch || p.channel === ch).length;
  }

  return (
    <div className="card">
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:16 }}>
        <div style={{ display:"flex", alignItems:"center", gap:8 }}>
          <h2 style={{ margin:0 }}>🔌 Джерела даних</h2>
          <StatusLegendPopover />
        </div>
        <button className="btn-primary" onClick={save} disabled={!serverOnline} style={{ fontSize:13, padding:"8px 16px" }}>
          {saved ? "✓ Збережено!" : "💾 Зберегти"}
        </button>
      </div>

      {!serverOnline && (
        <div className="warn-box mb16">
          Для синхронізації запусти сервер:<br/>
          <code>cd scripts → python server.py</code><br/><br/>
          Або відредагуй <code>scripts/.env</code> вручну.
        </div>
      )}

      <div className="sources-grid">

        {/* ── Telegram ── */}
        <div className={`source-card ${channels.filter(c=>c.trim()).length ? "active" : ""}`}>
          <div className="source-header">
            <span className="source-icon">
              <img src="https://www.google.com/s2/favicons?domain=telegram.org&sz=64" alt="Telegram" className="source-logo"
                onError={e=>{e.target.style.display="none"; e.target.parentElement.innerHTML="📱";}}/>
            </span>
            <div className="source-info">
              <div className="source-name">Telegram канали</div>
              <div className="source-meta">{channels.filter(c=>c.trim()).length} каналів додано</div>
            </div>
            <span className={`source-status ${channels.filter(c=>c.trim()).length ? "ok" : "off"}`}>
              {channels.filter(c=>c.trim()).length ? "✓ Активно" : "Не налаштовано"}
            </span>
          </div>

          <div className="source-body">
            <label className="field-label">Режим</label>
            <div className="radio-group">
              <label className="radio-label">
                <input type="radio" name="tg" value="public" checked={tgMode==="public"} onChange={() => setTgMode("public")}/>
                <span>Тільки публічні <span className="badge-green">Рекомендовано</span></span>
              </label>
              <label className="radio-label">
                <input type="radio" name="tg" value="public_private" checked={tgMode==="public_private"} onChange={() => setTgMode("public_private")}/>
                <span>Публічні + Приватні</span>
              </label>
            </div>

            {tgMode === "public_private" && (
              <div className="grid2 mt8">
                <div className="field">
                  <label className="field-label">API ID — <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="link-btn">отримати →</a></label>
                  <input className="input" type="password" value={apiKeys.telegram_api_id} onChange={e => setApiKeys(k=>({...k,telegram_api_id:e.target.value}))} placeholder="12345678"/>
                </div>
                <div className="field">
                  <label className="field-label">API Hash {settings.has_telegram_api && <span className="badge-green ml4">✓</span>}</label>
                  <input className="input" type="password" value={apiKeys.telegram_api_hash} onChange={e => setApiKeys(k=>({...k,telegram_api_hash:e.target.value}))} placeholder="abc123..."/>
                </div>
              </div>
            )}

            <label className="field-label mt8">Канали постачальників</label>
            <div className="channel-list">
              {channels.map((ch, i) => (
                <div key={i} className={getChannelRowClass(ch)}>
                  <span style={{fontSize:14,minWidth:20,textAlign:"center"}} title={
                    disabledChannels.includes(ch) ? "Вимкнено" :
                    pendingPrivate.includes(ch)   ? "Очікує API" :
                    channelStatus[ch] === "ok"    ? "Синхронізовано" :
                    channelStatus[ch] === "error" ? "Помилка синхронізації" : ""
                  }>{getChannelStatus(ch)}</span>
                  <input className="channel-input" value={ch} onChange={e => setChannel(i, e.target.value)}
                    title={ch && getChannelCount(ch) > 0 ? `${getChannelCount(ch)} товарів` : ""}
                    placeholder="@назва_каналу або https://t.me/назва"
                    style={{opacity: disabledChannels.includes(ch) ? 0.4 : 1}}/>
                  {ch && getChannelCount(ch) > 0 && (
                    <span style={{fontSize:11,color:"#888",whiteSpace:"nowrap",flexShrink:0}}>{getChannelCount(ch)} шт</span>
                  )}
                  <button
                    title={disabledChannels.includes(ch) ? "Увімкнути канал" : "Вимкнути канал"}
                    style={{background:"none",border:"none",cursor:"pointer",fontSize:14,opacity:0.6,padding:"0 2px"}}
                    onClick={() => toggleChannel(ch)}>
                    {disabledChannels.includes(ch) ? "▶" : "⏸"}
                  </button>
                  {channels.length > 1 && <button className="btn-remove-ch" onClick={() => removeChannel(i)}>✕</button>}
                </div>
              ))}
              <button className="btn-add-channel" onClick={addChannel}>+ Додати канал</button>
            </div>

            <div className="source-actions">
              <button className="btn-sync" disabled={!serverOnline || syncing.telegram || !channels.filter(c=>c.trim()).length}
                onClick={() => sync("telegram")}>
                {syncing.telegram ? "⏳ Синхронізую..." : "🔄 Синхронізувати"}
              </button>
            </div>

            {logs.telegram?.length > 0 && (
              <div className="sync-log">{logs.telegram.map((l,i) => <div key={i}>{l}</div>)}</div>
            )}
          </div>
        </div>

        {/* ── CRM картки ── */}
        {CRM_TYPES.map(crm => (
          <div key={crm.id} className={`source-card ${hasKey[crm.id] ? "active" : ""}`}>
            <div className="source-header">
              <span className="source-icon">
                <img src={crm.logo} alt={crm.name} className="source-logo"
                  onError={e=>{e.target.style.display="none";}}/>
              </span>
              <div className="source-info">
                <div className="source-name">
                  <a href={crm.link} target="_blank" rel="noreferrer" style={{textDecoration:"none",color:"inherit",fontWeight:600}}>{crm.name}</a>
                </div>
              </div>
              <span className={`source-status ${hasKey[crm.id] ? "ok" : "off"}`}>
                {hasKey[crm.id] ? "✓ Підключено" : "Не підключено"}
              </span>
            </div>

            <div className="source-body">
              <div className="field">
                <label className="field-label">{crm.label} <span className="hint-inline">({crm.hint})</span></label>
                <input className="input" type="password" value={apiKeys[crm.field]||""}
                  onChange={e => setApiKeys(k=>({...k,[crm.field]:e.target.value}))}
                  placeholder={hasKey[crm.id] ? "••••••• (збережено)" : crm.placeholder}/>
              </div>

              <div className="source-actions">
                <button className="btn-sync" disabled={!serverOnline || syncing[crm.id] || !hasKey[crm.id]}
                  onClick={() => sync(crm.id)}>
                  {syncing[crm.id] ? "⏳ Синхронізую..." : "🔄 Синхронізувати"}
                </button>
                {!hasKey[crm.id] && <span style={{fontSize:12,color:"#aaa",alignSelf:"center"}}>Спочатку збережи ключ</span>}
              </div>

              {logs[crm.id]?.length > 0 && (
                <div className="sync-log">{logs[crm.id].map((l,i) => <div key={i}>{l}</div>)}</div>
              )}
            </div>
          </div>
        ))}

      </div>

      {pendingPrivate.length > 0 && (
        <div className="info-box mt16" style={{borderLeft:"3px solid #f59e0b",background:"#fffbeb"}}>
          <div style={{fontWeight:600,marginBottom:8}}>⏳ Приватні канали очікують підключення API</div>
          {pendingPrivate.map((ch, i) => (
            <div key={i} style={{fontSize:13,padding:"4px 0",color:"#92400e"}}>{ch}</div>
          ))}
          <p style={{fontSize:12,color:"#aaa",marginTop:8}}>
            Переключи режим на <b>Публічні + Приватні</b>, введи API ключі — і ці канали запрацюють автоматично.
          </p>
          <button style={{fontSize:12,color:"#aaa",background:"none",border:"none",cursor:"pointer",marginTop:4}}
            onClick={() => {
              fetch(`${SERVER}/pending-private-channels/clear`, {method:"POST"});
              setPendingPrivate([]);
            }}>
            🗑 Очистити список
          </button>
        </div>
      )}

      <div className="info-box mt16" style={{fontSize:12}}>
        💡 Всі ключі зберігаються локально у <code>scripts/.env</code> — тільки на твоєму комп'ютері.
      </div>
    </div>
  );
}