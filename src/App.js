import { useState, useEffect, useMemo, useCallback } from "react";
import "./App.css";
import PhotoManager from "./PhotoManager";
import SourcesView from "./SourcesView";

const SERVER = "http://localhost:5001";

const MARKETPLACES = [
  { id:"rozetka", name:"Rozetka",     color:"#00a046", method:"REST API", photoReq:"1280×1280, білий фон" },
  { id:"prom",    name:"Prom / Bigl", color:"#f36d21", method:"XML",      photoReq:"мін 1280×1280, до 10 фото" },
  { id:"shafa",   name:"Shafa.ua",    color:"#e91e8c", method:"→ Prom",   photoReq:"квадратні фото, без фільтрів" },
  { id:"kasta",   name:"Kasta",       color:"#6c2d91", method:"Excel",    photoReq:"фото на моделі або манекені" },
  { id:"olx",     name:"OLX",         color:"#002f34", method:"OAuth API",photoReq:"до 15 фото, мін 640×480" },
  { id:"mono",    name:"Mono базар",  color:"#aaa",    method:"Закритий", disabled:true },
];

const SOURCE_LABELS = { telegram:"Telegram", mydrop:"MyDrop", keycrm:"KeyCRM", manual:"Вручну" };
const SOURCE_COLORS = { telegram:"#2AABEE",  mydrop:"#FF6B35", keycrm:"#4F46E5", manual:"#888" };

// ── localStorage ─────────────────────────────────────────
const LS_PUB = "mp_pub_v2", LS_MKT = "mp_mkt_v2", LS_MANUAL = "mp_manual";

function simpleHash(s){ let h=0; for(let i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h|=0;} return Math.abs(h).toString(16); }
function makeKey(p){ return p.sku?`sku_${p.sku}`:`hash_${simpleHash(`${(p.name||"").toLowerCase()}|${p.price}|${(p.photos||"").split(",")[0]?.trim()}`)}`; }
function getPub()    { try{return JSON.parse(localStorage.getItem(LS_PUB)||"{}");}catch{return{};} }
function isPublished(p){ return !!getPub()[makeKey(p)]; }
function markPublished(p,markets){ const db=getPub(); db[makeKey(p)]={name:p.name,at:new Date().toISOString(),markets}; localStorage.setItem(LS_PUB,JSON.stringify(db)); }
function getPubInfo(p){ return getPub()[makeKey(p)]||null; }
function getEnabledMkts(){ try{return JSON.parse(localStorage.getItem(LS_MKT)||"null")||{rozetka:true,prom:true,shafa:true,kasta:false,olx:false};}catch{return{rozetka:true,prom:true,shafa:true,kasta:false,olx:false};} }
function saveEnabledMkts(v){ localStorage.setItem(LS_MKT,JSON.stringify(v)); }
function getManual(){ try{return JSON.parse(localStorage.getItem(LS_MANUAL)||"[]");}catch{return[];} }
function saveManual(a){ localStorage.setItem(LS_MANUAL,JSON.stringify(a)); }

// ── Generate output ───────────────────────────────────────
function generateOutput(product, id) {
  const photos=(product.photos||"").split(",").map(p=>p.trim()).filter(Boolean);
  switch(id){
    case "rozetka": return {format:"json",content:JSON.stringify({name:product.name,brand:product.brand,price:+product.price||0,attributes:{size:product.size,color:product.color,material:product.material,gender:product.gender},description:product.description,images:photos},null,2)};
    case "prom": case "shafa": return {format:"xml",content:`<?xml version="1.0" encoding="UTF-8"?>\n<yml_catalog date="${new Date().toISOString().split("T")[0]}">\n  <shop><offers>\n    <offer id="${product.id||1}" available="true">\n      <name>${product.name}</name><vendor>${product.brand}</vendor><price>${product.price}</price><currencyId>UAH</currencyId>\n      <description><![CDATA[${product.description}]]></description>\n      <param name="Розмір">${product.size}</param><param name="Колір">${product.color}</param>\n      <param name="Матеріал">${product.material}</param><param name="Стать">${product.gender}</param>\n${photos.map(p=>`      <picture>${p}</picture>`).join("\n")}\n    </offer>\n  </offers></shop>\n</yml_catalog>`};
    case "kasta":  return {format:"csv",content:["Назва,Бренд,Ціна,Розмір,Колір,Матеріал,Стать,Стан,Опис,Фото1",[product.name,product.brand,product.price,product.size,product.color,product.material,product.gender,product.condition,`"${(product.description||"").replace(/"/g,'""')}"`,photos[0]||""].join(",")].join("\n")};
    case "olx":    return {format:"json",content:JSON.stringify({title:product.name,price:{value:+product.price||0,currency:"UAH"},description:product.description,attributes:[{code:"state",value:"new"},{code:"size",value:product.size}],images:photos.slice(0,15)},null,2)};
    default: return {format:"txt",content:""};
  }
}

function dlFile(content,name,fmt){ const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([content],{type:"text/plain;charset=utf-8"})); a.download=`${name}.${fmt}`; a.click(); }

const emptyProduct = {id:"",sku:"",name:"",brand:"",price:"",size:"",color:"",material:"",gender:"Жіноче",condition:"Нове",category:"",photos:"",description:"",source:"manual",supplier:"",addedAt:new Date().toISOString()};
const defaultFilters = {search:"",source:"",supplier:"",brand:"",category:"",size:"",gender:"",priceMin:"",priceMax:"",dateFrom:"",dateTo:"",showPublished:false};

// ════════ Toast ════════
function Toast({ msg, onClose }) {
  useEffect(()=>{ const t=setTimeout(onClose,3500); return()=>clearTimeout(t); },[onClose]);
  return <div className="toast">{msg}</div>;
}

// ════════ ProductCard ════════
function ProductCard({ product, selected, onSelect, published }) {
  const photo = product.photos?.split(",")[0]?.trim();
  const pubInfo = published ? getPubInfo(product) : null;
  const pubDate = pubInfo?.at ? new Date(pubInfo.at).toLocaleDateString("uk-UA") : "";

  return (
    <div className={`pcard ${selected?"pcard-sel":""} ${published?"pcard-pub":""}`}
      onClick={()=>!published && onSelect(product.id)}
      title={published?`Опубліковано ${pubDate}`:""}>
      <div className="pcard-img-wrap">
        {photo ? <img src={photo} alt={product.name} className="pcard-img" onError={e=>e.target.style.display="none"}/> : <div className="pcard-no-img">📷</div>}
        {published && <div className="pcard-pub-overlay">✓ Опубліковано<br/><span style={{fontSize:10,opacity:.85}}>{pubDate}</span></div>}
        {!published && <div className={`pcard-check ${selected?"checked":""}`}>{selected?"✓":""}</div>}
      </div>
      <div className="pcard-body">
        <div className="pcard-top">
          <span className="pcard-src" style={{background:SOURCE_COLORS[product.source]||"#888"}}>{SOURCE_LABELS[product.source]||product.source}</span>
          <span className="pcard-date">{product.addedAt?new Date(product.addedAt).toLocaleDateString("uk-UA"):""}</span>
        </div>
        <div className="pcard-name">{product.name}</div>
        <div className="pcard-brand">{product.brand}</div>
        <div className="pcard-row">
          <span className="pcard-price">{product.price?`${product.price} грн`:"—"}</span>
          {product.size&&<span className="pcard-size">{product.size}</span>}
        </div>
        {product.supplier&&<div className="pcard-supplier">📦 {product.supplier}</div>}
      </div>
    </div>
  );
}

// ════════ FiltersBar ════════
function FiltersBar({ filters, setFilters, products }) {
  const suppliers  = useMemo(()=>[...new Set(products.map(p=>p.supplier).filter(Boolean))],[products]);
  const brands     = useMemo(()=>[...new Set(products.map(p=>p.brand).filter(Boolean))],[products]);
  const categories = useMemo(()=>[...new Set(products.map(p=>p.category).filter(Boolean))],[products]);
  const sizes      = useMemo(()=>[...new Set(products.flatMap(p=>(p.size||"").split(",").map(s=>s.trim())).filter(Boolean))],[products]);
  const set=(k,v)=>setFilters(f=>({...f,[k]:v}));
  return (
    <div className="filters">
      <div className="filters-title">🔍 Фільтри</div>
      <input className="filter-input" placeholder="Пошук за назвою або брендом..." value={filters.search} onChange={e=>set("search",e.target.value)}/>
      {[
        ["Джерело","source", Object.entries(SOURCE_LABELS).map(([k,v])=>({val:k,label:v}))],
        ["Постачальник","supplier", suppliers.map(s=>({val:s,label:s}))],
        ["Бренд","brand", brands.map(b=>({val:b,label:b}))],
        ["Категорія","category", categories.map(c=>({val:c,label:c}))],
        ["Розмір","size", sizes.map(s=>({val:s,label:s}))],
        ["Стать","gender", [{val:"Жіноче",label:"Жіноче"},{val:"Чоловіче",label:"Чоловіче"},{val:"Унісекс",label:"Унісекс"},{val:"Дитяче",label:"Дитяче"}]],
      ].map(([label,key,opts])=>(
        <div key={key}>
          <label className="filter-label">{label}</label>
          <select className="filter-select" value={filters[key]} onChange={e=>set(key,e.target.value)}>
            <option value="">Всі</option>
            {opts.map(o=><option key={o.val} value={o.val}>{o.label}</option>)}
          </select>
        </div>
      ))}
      <label className="filter-label">Ціна від — до (грн)</label>
      <div className="filter-row">
        <input className="filter-input filter-half" type="number" placeholder="від" value={filters.priceMin} onChange={e=>set("priceMin",e.target.value)}/>
        <input className="filter-input filter-half" type="number" placeholder="до"  value={filters.priceMax} onChange={e=>set("priceMax",e.target.value)}/>
      </div>
      <label className="filter-label">Дата від</label>
      <input className="filter-input" type="date" value={filters.dateFrom} onChange={e=>set("dateFrom",e.target.value)}/>
      <label className="filter-label">Дата до</label>
      <input className="filter-input" type="date" value={filters.dateTo} onChange={e=>set("dateTo",e.target.value)}/>
      <label className="filter-check">
        <input type="checkbox" checked={filters.showPublished} onChange={e=>set("showPublished",e.target.checked)}/>
        <span>Показати опубліковані</span>
      </label>
      <button className="filter-reset" onClick={()=>setFilters(defaultFilters)}>Скинути фільтри</button>
    </div>
  );
}

// ════════ ProductForm ════════
function ProductForm({ product, setProduct, onSave, onBack, backLabel="← Назад", serverOnline }) {
  const set=(k,v)=>setProduct(p=>({...p,[k]:v}));
  // photos зберігаємо як масив всередині форми
  const photosArr = Array.isArray(product.photos) ? product.photos : (product.photos||"").split(",").map(p=>p.trim()).filter(Boolean);
  const setPhotos = (arr) => setProduct(p=>({...p, photos:arr}));

  return (
    <div>
      <div className="grid2">
        {[["name","Назва товару"],["brand","Бренд"],["price","Ціна (грн)"],["size","Розмір"],["color","Колір"],["material","Матеріал"],["supplier","Постачальник"],["category","Категорія"]].map(([k,l])=>(
          <div key={k} className="field">
            <label className="field-label">{l}</label>
            <input className="input" value={product[k]||""} onChange={e=>set(k,e.target.value)} placeholder={l}/>
          </div>
        ))}
        <div className="field">
          <label className="field-label">Стать</label>
          <select className="input" value={product.gender} onChange={e=>set("gender",e.target.value)}>
            <option>Жіноче</option><option>Чоловіче</option><option>Унісекс</option><option>Дитяче</option>
          </select>
        </div>
        <div className="field">
          <label className="field-label">Стан</label>
          <select className="input" value={product.condition} onChange={e=>set("condition",e.target.value)}>
            <option>Нове</option><option>Б/у — відмінний стан</option><option>Б/у — хороший стан</option>
          </select>
        </div>
      </div>
      <div className="mt12">
        <PhotoManager photos={photosArr} onChange={setPhotos} serverOnline={serverOnline}/>
      </div>
      <div className="field mt12">
        <label className="field-label">Опис</label>
        <textarea className="textarea" rows={3} value={product.description||""} onChange={e=>set("description",e.target.value)}/>
      </div>
      <div className="row-btns mt16">
        {onBack && <button className="btn-secondary" onClick={onBack}>{backLabel}</button>}
        <button className="btn-primary" onClick={onSave}>✓ Зберегти товар</button>
      </div>
    </div>
  );
}

// ════════ AddProductModal ════════
function AddProductModal({ onClose, onAdd, serverOnline }) {
  const [tab, setTab]         = useState("link");
  const [url, setUrl]         = useState("");
  const [text, setText]       = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [product, setProduct] = useState(emptyProduct);
  const [showForm, setShowForm] = useState(false);

  async function fetchByUrl() {
    if (!url) return;
    if (!serverOnline) { setError("Сервер не запущено. Відкрий термінал і запусти: python scripts/server.py"); return; }
    setLoading(true); setError("");
    try {
      const res = await fetch(`${SERVER}/fetch`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url}) });
      const data = await res.json();
      if (data.error) { setError(data.error); }
      else { setProduct({...emptyProduct, ...data, id:Date.now().toString(), addedAt:new Date().toISOString()}); setShowForm(true); }
    } catch(e) { setError("Сервер недоступний. Запусти: python scripts/server.py"); }
    setLoading(false);
  }

  async function parseText() {
    if (!text.trim()) return;
    if (!serverOnline) {
      // Парсимо локально якщо сервер не запущено
      const lines = text.split("\n");
      const p = {...emptyProduct, description:text, source:"telegram", id:Date.now().toString(), addedAt:new Date().toISOString()};
      for (const line of lines) {
        const lower = line.toLowerCase();
        const val = line.includes(":") ? line.split(":").slice(1).join(":").trim() : "";
        if (lower.startsWith("бренд") || lower.startsWith("brand"))        p.brand = val || p.brand;
        if (lower.startsWith("розмір") || lower.startsWith("size"))        p.size = val || p.size;
        if (lower.startsWith("колір") || lower.startsWith("color"))        p.color = val || p.color;
        if (lower.startsWith("матеріал"))                                   p.material = val || p.material;
        if (lower.includes("ціна") || lower.includes("грн")) { const m=line.match(/\d+/); if(m) p.price=m[0]; }
      }
      if (!p.name) p.name = lines.find(l=>l.trim()&&!l.includes(":"))||"";
      setProduct(p); setShowForm(true); return;
    }
    setLoading(true); setError("");
    try {
      const res = await fetch(`${SERVER}/parse-text`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({text}) });
      const data = await res.json();
      if (data.error) setError(data.error);
      else { setProduct({...emptyProduct, ...data, source:"telegram", id:Date.now().toString(), addedAt:new Date().toISOString()}); setShowForm(true); }
    } catch { setError("Помилка з'єднання з сервером"); }
    setLoading(false);
  }

  function handleSave() {
    if (!product.name) { alert("Введіть назву товару"); return; }
    onAdd({...product, id:product.id||Date.now().toString()});
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="modal-header">
          <h3>Додати товар</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        {!showForm ? (
          <>
            <div className="modal-tabs">
              {[["link","🔗 Посилання"],["text","📝 Текст посту"],["manual","✍️ Вручну"]].map(([t,l])=>(
                <button key={t} className={`modal-tab ${tab===t?"active":""}`} onClick={()=>{setTab(t);setError("");}}>
                  {l}
                </button>
              ))}
            </div>

            <div className="modal-body">
              {/* Вкладка: Посилання */}
              {tab === "link" && (
                <div>
                  {!serverOnline && <div className="warn-box mb12">⚠️ Для автозаповнення запусти в терміналі:<br/><code>python scripts/server.py</code></div>}
                  <label className="field-label">Посилання на пост або товар:</label>
                  <input className="input mt4" value={url} onChange={e=>setUrl(e.target.value)}
                    placeholder="https://t.me/channel/123  або  https://mydrop.com.ua/..."
                    onKeyDown={e=>e.key==="Enter"&&fetchByUrl()}/>
                  <p className="hint mt8">Підтримується: t.me, mydrop.com.ua, keycrm</p>
                  {error && <div className="error-box mt8">{error}</div>}
                  <button className="btn-primary mt12" onClick={fetchByUrl} disabled={!url||loading}>
                    {loading ? "⏳ Завантажую..." : "Завантажити та заповнити →"}
                  </button>
                </div>
              )}

              {/* Вкладка: Текст поста */}
              {tab === "text" && (
                <div>
                  <label className="field-label">Вставте текст з поста Telegram або CRM:</label>
                  <textarea className="textarea mt4" rows={8} value={text} onChange={e=>setText(e.target.value)}
                    placeholder={"Куртка Nike Air\nБренд: Nike\nРозмір: M, L\nКолір: чорний\nЦіна: 2800 грн\nМатеріал: поліестер\n\nЛегка куртка для активного відпочинку..."}/>
                  <p className="hint mt8">💡 Автоматично розпізнає бренд, розмір, колір, ціну з тексту.</p>
                  {error && <div className="error-box mt8">{error}</div>}
                  <button className="btn-primary mt12" onClick={parseText} disabled={!text.trim()||loading}>
                    {loading ? "⏳ Розпізнаю..." : "Розпізнати та заповнити →"}
                  </button>
                </div>
              )}

              {/* Вкладка: Вручну */}
              {tab === "manual" && (
                <div>
                  <button className="btn-primary" onClick={()=>{ setProduct({...emptyProduct,id:Date.now().toString(),addedAt:new Date().toISOString()}); setShowForm(true); }}>
                    Заповнити форму →
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="modal-body">
            <ProductForm
              product={product}
              setProduct={setProduct}
              onSave={handleSave}
              onBack={()=>setShowForm(false)}
              backLabel="← Назад"
              serverOnline={serverOnline}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ════════ SettingsView ════════
function SettingsView({ serverOnline }) {
  const [form, setForm] = useState({ telegram_mode:"public", telegram_channels:"", mydrop_token:"", keycrm_key:"", telegram_api_id:"", telegram_api_hash:"" });
  const [status, setStatus] = useState(null); // {has_mydrop_token, has_keycrm_key, has_telegram_api}
  const [saved, setSaved]   = useState(false);
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));

  useEffect(()=>{
    if(!serverOnline) return;
    fetch(`${SERVER}/settings`).then(r=>r.json()).then(d=>{
      setStatus(d);
      setForm(f=>({...f, telegram_mode:d.telegram_mode||"public", telegram_channels:(d.telegram_channels||[]).join(", ")}));
    }).catch(()=>{});
  },[serverOnline]);

  async function save() {
    if(!serverOnline) return;
    const payload = { ...form, telegram_channels: form.telegram_channels.split(",").map(c=>c.trim()).filter(Boolean) };
    await fetch(`${SERVER}/settings`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
    setSaved(true); setTimeout(()=>setSaved(false),2500);
  }

  return (
    <div className="card">
      <h2>⚙️ Налаштування</h2>
      {!serverOnline && <div className="warn-box mb16">Для збереження налаштувань запусти:<br/><code>python scripts/server.py</code><br/><br/>Або відредагуй файл <code>scripts/.env</code> вручну.</div>}

      <div className="settings-section">
        <h3 className="settings-title">📱 Telegram</h3>
        <label className="filter-label">Режим каналів</label>
        <div className="radio-group">
          <label className="radio-label">
            <input type="radio" name="tg" value="public" checked={form.telegram_mode==="public"} onChange={()=>set("telegram_mode","public")}/>
            <span>Тільки публічні канали <span className="badge-green">Рекомендовано</span></span>
          </label>
          <label className="radio-label">
            <input type="radio" name="tg" value="public_private" checked={form.telegram_mode==="public_private"} onChange={()=>set("telegram_mode","public_private")}/>
            <span>Публічні + Приватні (потребує API ключів)</span>
          </label>
        </div>

        <div className="field mt12">
          <label className="field-label">Канали постачальників <span className="hint-inline">(через кому, з @ або без)</span></label>
          <textarea className="textarea" rows={2} value={form.telegram_channels} onChange={e=>set("telegram_channels",e.target.value)} placeholder="@channel1, @channel2, @channel3"/>
        </div>

        {form.telegram_mode==="public_private" && (
          <div className="grid2 mt12">
            <div className="field">
              <label className="field-label">API ID {status?.has_telegram_api&&<span className="badge-green ml4">✓</span>} <a href="https://my.telegram.org" target="_blank" rel="noreferrer" className="link-btn">отримати →</a></label>
              <input className="input" type="password" value={form.telegram_api_id} onChange={e=>set("telegram_api_id",e.target.value)} placeholder="12345678"/>
            </div>
            <div className="field">
              <label className="field-label">API Hash</label>
              <input className="input" type="password" value={form.telegram_api_hash} onChange={e=>set("telegram_api_hash",e.target.value)} placeholder="abc123..."/>
            </div>
          </div>
        )}
      </div>

      <div className="settings-section">
        <h3 className="settings-title">🗂 MyDrop {status?.has_mydrop_token&&<span className="badge-green" style={{fontSize:11}}>✓ Збережено</span>}</h3>
        <div className="field">
          <label className="field-label">API Токен <span className="hint-inline">(MyDrop → Інтеграції → API)</span></label>
          <input className="input" type="password" value={form.mydrop_token} onChange={e=>set("mydrop_token",e.target.value)} placeholder="Вставте токен..."/>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-title">🗂 KeyCRM {status?.has_keycrm_key&&<span className="badge-green" style={{fontSize:11}}>✓ Збережено</span>}</h3>
        <div className="field">
          <label className="field-label">API Ключ <span className="hint-inline">(KeyCRM → Налаштування → API)</span></label>
          <input className="input" type="password" value={form.keycrm_key} onChange={e=>set("keycrm_key",e.target.value)} placeholder="Вставте ключ..."/>
        </div>
      </div>

      <div className="info-box mt12" style={{fontSize:12}}>
        💡 Всі ключі зберігаються локально у файлі <code>scripts/.env</code> — тільки на твоєму комп'ютері.
      </div>

      <button className="btn-primary mt16" onClick={save} disabled={!serverOnline}>
        {saved ? "✓ Збережено!" : "Зберегти налаштування"}
      </button>
    </div>
  );
}

// ════════ MAIN APP ════════
export default function App() {
  const [view, setView]         = useState("feed");
  const [allProducts, setAll]   = useState([]);
  const [filters, setFilters]   = useState(defaultFilters);
  const [selected, setSelected] = useState(new Set());
  const [enabled, setEnabled]   = useState(getEnabledMkts);
  const [showAdd, setShowAdd]   = useState(false);
  const [generated, setGen]     = useState([]);
  const [pubV, setPubV]         = useState(0);
  const [serverOnline, setServerOnline] = useState(false);
  const [toast, setToast]       = useState("");

  // Перевірка сервера
  useEffect(()=>{
    fetch(`${SERVER}/health`).then(()=>setServerOnline(true)).catch(()=>setServerOnline(false));
    const t = setInterval(()=>{ fetch(`${SERVER}/health`).then(()=>setServerOnline(true)).catch(()=>setServerOnline(false)); }, 10000);
    return ()=>clearInterval(t);
  },[]);

  // Завантаження товарів
  useEffect(()=>{
    Promise.all([
      fetch("/products.json").then(r=>r.json()).catch(()=>[]),
      fetch("/synced_products.json").then(r=>r.json()).catch(()=>[]),
    ]).then(([base, synced]) => {
      const manual = getManual();
      const all = [...base, ...synced, ...manual];
      const unique = Array.from(new Map(all.map(p=>[p.id||Math.random(),p])).values());
      setAll(unique);
    });
  },[pubV]);

  const filtered = useMemo(()=>allProducts.filter(p=>{
    const pub=isPublished(p);
    if(!filters.showPublished&&pub) return false;
    if(filters.search&&!`${p.name} ${p.brand}`.toLowerCase().includes(filters.search.toLowerCase())) return false;
    if(filters.source   &&p.source   !==filters.source)   return false;
    if(filters.supplier &&p.supplier !==filters.supplier)  return false;
    if(filters.brand    &&p.brand    !==filters.brand)     return false;
    if(filters.category &&p.category !==filters.category)  return false;
    if(filters.gender   &&p.gender   !==filters.gender)    return false;
    if(filters.size     &&!p.size?.includes(filters.size)) return false;
    if(filters.priceMin &&+p.price<+filters.priceMin)      return false;
    if(filters.priceMax &&+p.price>+filters.priceMax)      return false;
    if(filters.dateFrom &&p.addedAt<filters.dateFrom)      return false;
    if(filters.dateTo   &&p.addedAt>filters.dateTo+"T23:59:59") return false;
    return true;
  }),[allProducts,filters,pubV]);

  function toggleSelect(id){ setSelected(s=>{const n=new Set(s);n.has(id)?n.delete(id):n.add(id);return n;}); }
  function selectAll(){ setSelected(new Set(filtered.filter(p=>!isPublished(p)).map(p=>p.id))); }
  function clearSel() { setSelected(new Set()); }

  function handleAdd(p){ const m=getManual(); m.push(p); saveManual(m); setAll(prev=>[...prev,p]); setToast(`✓ Товар "${p.name}" додано`); }

  function handlePublish(){
    const toPublish=allProducts.filter(p=>selected.has(p.id));
    const active=MARKETPLACES.filter(m=>enabled[m.id]&&!m.disabled);
    const gen=toPublish.flatMap(product=>active.map(m=>{const{format,content}=generateOutput(product,m.id);return{product,marketplace:m,format,content};}));
    toPublish.forEach(p=>markPublished(p,active.map(m=>m.id)));
    setGen(gen); setSelected(new Set()); setPubV(v=>v+1); setView("result");
    setToast(`✓ Опубліковано ${toPublish.length} товарів на ${active.length} маркетплейсах`);
  }

  const activeCount=MARKETPLACES.filter(m=>enabled[m.id]&&!m.disabled).length;
  const newCount=allProducts.filter(p=>!isPublished(p)).length;

  return (
    <div className="app">
      {toast && <Toast msg={toast} onClose={()=>setToast("")}/>}

      <header className="app-header">
        <div>
          <h1>🛍 Постинг товарів на маркетплейси</h1>
          <p className="subtitle">Одяг та взуття · Telegram / CRM → Маркетплейси</p>
        </div>
        <div className="header-right">
          <div className="header-stats">
            <span className="stat-badge">{newCount} нових</span>
            <span className="stat-badge stat-markets">{activeCount} маркетплейсів</span>
          </div>
          <div className={`server-badge ${serverOnline?"online":"offline"}`}>
            {serverOnline?"🟢 Сервер":"🔴 Сервер вимкнено"}
          </div>
        </div>
      </header>

      <nav className="nav">
        {[["feed","📋 Стрічка"],["sources","🔌 Джерела"],["markets","🛒 Маркетплейси"],["result","📦 Результат"],["settings","⚙️ Налаштування"]].map(([v,l])=>(
          <button key={v} className={`nav-btn ${view===v?"active":""}`} onClick={()=>setView(v)}>{l}</button>
        ))}
      </nav>

      {/* ── FEED ── */}
      {view==="feed" && (
        <div className="feed-layout">
          <FiltersBar filters={filters} setFilters={setFilters} products={allProducts}/>
          <div className="feed-main">
            <div className="feed-toolbar">
              <div className="feed-toolbar-left">
                <button className="btn-sm" onClick={selectAll}>Вибрати всі</button>
                <button className="btn-sm" onClick={clearSel}>Скинути</button>
                <span className="sel-count">{selected.size>0?`Вибрано: ${selected.size}`:`${filtered.length} товарів`}</span>
              </div>
              <div className="feed-toolbar-right">
                <button className="btn-add" onClick={()=>setShowAdd(true)}>+ Додати товар</button>
                <button className="btn-publish" disabled={selected.size===0||activeCount===0} onClick={handlePublish}>
                  Публікувати {selected.size>0?`(${selected.size})`:""} →
                </button>
              </div>
            </div>
            {activeCount===0&&<div className="info-box mb12">⚠️ Жоден маркетплейс не увімкнений. <button className="link-btn" onClick={()=>setView("markets")}>Перейти →</button></div>}
            {filtered.length===0
              ?<div className="empty-state">😕 Товарів не знайдено.<br/><button className="link-btn" onClick={()=>setShowAdd(true)}>Додайте перший товар →</button></div>
              :<div className="feed-grid">{filtered.map(p=><ProductCard key={p.id} product={p} selected={selected.has(p.id)} onSelect={toggleSelect} published={isPublished(p)}/>)}</div>
            }
          </div>
        </div>
      )}

      {/* ── SOURCES ── */}
      {view==="sources" && <SourcesView serverOnline={serverOnline} onProductsLoaded={()=>setPubV(v=>v+1)}/>}
      {view==="markets" && (
        <div className="card">
          <h2>Маркетплейси</h2>
          <p className="hint">Увімкни потрібні — налаштування зберігаються автоматично.</p>
          <div className="market-list">
            {MARKETPLACES.map(m=>(
              <div key={m.id} className={`market-item ${enabled[m.id]&&!m.disabled?"market-on":""} ${m.disabled?"market-disabled":""}`} style={{borderColor:enabled[m.id]&&!m.disabled?m.color:"#e5e5e5"}}>
                <div className="market-top">
                  <div className="toggle" style={{background:enabled[m.id]&&!m.disabled?m.color:"#ccc"}}
                    onClick={()=>{if(!m.disabled){const n={...enabled,[m.id]:!enabled[m.id]};setEnabled(n);saveEnabledMkts(n);}}}>
                    <div className="toggle-knob" style={{left:enabled[m.id]&&!m.disabled?23:3}}/>
                  </div>
                  <span className="market-name">{m.name}</span>
                  <span className="market-method">{m.method}</span>
                </div>
                {m.photoReq&&!m.disabled&&<p className="photo-req">📸 {m.photoReq}</p>}
                {m.disabled&&<p className="market-note">Публічного API немає. Тільки запрошені партнери.</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── RESULT ── */}
      {view==="result" && (
        <div className="card">
          <h2>📦 Результат публікації</h2>
          {generated.length===0
            ?<div className="empty-state">Ще нічого не публікувалось.<br/>Поверніться до стрічки та оберіть товари.</div>
            :<>
              <p className="hint">Завантажте файли та завантажте на відповідні маркетплейси.</p>
              {generated.map((g,i)=>(
                <div key={i} className="result-block">
                  <div className="result-header" style={{background:`${g.marketplace.color}18`}}>
                    <div>
                      <span className="market-name">{g.marketplace.name}</span>
                      <span className="market-method ml8">· {g.product.name}</span>
                      <span className="market-method ml8">.{g.format}</span>
                    </div>
                    <button className="btn-download" style={{background:g.marketplace.color}}
                      onClick={()=>dlFile(g.content,`${g.marketplace.id}_${g.product.name.slice(0,20)}`,g.format)}>
                      ⬇ Завантажити
                    </button>
                  </div>
                  <pre className="code-preview">{g.content}</pre>
                </div>
              ))}
              <button className="btn-secondary mt12" onClick={()=>setView("feed")}>← До стрічки</button>
            </>
          }
        </div>
      )}

      {/* ── SETTINGS ── */}
      {view==="settings" && <SettingsView serverOnline={serverOnline}/>}

      {showAdd && <AddProductModal onClose={()=>setShowAdd(false)} onAdd={handleAdd} serverOnline={serverOnline}/>}
    </div>
  );
}
