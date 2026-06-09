import { useState, useEffect, useMemo, useCallback } from "react";
import "./App.css";
import PhotoManager from "./PhotoManager";
import SourcesView from "./SourcesView";
import SortDropdown from "./SortDropdown";
import ArchiveView from "./ArchiveView";
function decodeHtml(str) {
  const txt = document.createElement("textarea");
  txt.innerHTML = str;
  return txt.value;
}

const SERVER = "http://localhost:5001";

function loadArchiveKeywords() {
  return fetch(`${SERVER}/archive-keywords`)
    .then(r => r.json())
    .catch(() => fetch("/archive_keywords.json").then(r => r.json()).catch(() => ({})))
    .then(data => (data && typeof data === "object" && !Array.isArray(data)) ? data : {});
}

function productMatchesArchiveRules(product, keywordsDict) {
  if (!product || !keywordsDict || typeof keywordsDict !== "object") return false;

  const channelKeys = [
    product.supplier,
    product.source_channel,
    product.channel,
  ].map(v => String(v || "").trim()).filter(Boolean);

  const keywords = channelKeys.flatMap(key => Array.isArray(keywordsDict[key]) ? keywordsDict[key] : []);
  if (!keywords.length) return false;

  const text = [
  product.name,
  product.description,
  product.text,
  product.post_text,
  product.postText,
  product.raw_text,
  product.rawText,
  ].map(v => String(v || "")).join(" ").toLowerCase();

  return keywords.some(kw => {
    const needle = String(kw || "").trim().toLowerCase();
    return needle && text.includes(needle);
  });
}

const MARKETPLACES = [
  { id:"rozetka", name:"Rozetka",     link:"https://rozetka.com.ua",  logo:"https://www.google.com/s2/favicons?domain=rozetka.com.ua&sz=64", color:"#00a046", method:"REST API", photoReq:"1280×1280, білий фон" },
  { id:"prom",    name:"Prom / Bigl", link:"https://prom.ua",          logo:"https://www.google.com/s2/favicons?domain=prom.ua&sz=64",        color:"#f36d21", method:"XML",      photoReq:"мін 1280×1280, до 10 фото" },
  { id:"shafa",   name:"Shafa.ua",    link:"https://shafa.ua",          logo:"https://www.google.com/s2/favicons?domain=shafa.ua&sz=64",       color:"#e91e8c", method:"→ Prom",   photoReq:"квадратні фото, без фільтрів" },
  { id:"kasta",   name:"Kasta",       link:"https://kasta.ua",          logo:"https://www.google.com/s2/favicons?domain=kasta.ua&sz=64",       color:"#FF5000", method:"Excel",    photoReq:"фото на моделі або манекені" },
  { id:"olx",     name:"OLX",         link:"https://olx.ua",            logo:"https://www.google.com/s2/favicons?domain=olx.ua&sz=64",         color:"#5C307F", method:"OAuth API",photoReq:"до 15 фото, мін 640×480" },
  { id:"mono",    name:"Mono базар",  link:"https://monobank.ua",       logo:"https://www.google.com/s2/favicons?domain=monobank.ua&sz=64",    color:"#1A1A1A", method:"Закритий", disabled:true },
];

const SOURCE_LABELS = { telegram:"Telegram", mydrop:"MyDrop", keycrm:"KeyCRM", manual:"Вручну" };
const SOURCE_COLORS = { telegram:"#2AABEE",  mydrop:"#FF6B35", keycrm:"#4F46E5", manual:"#888" };
const supplierDisplayName = (value = "") => (
  String(value)
    .replace(/.*t\.me\//i, "")
    .replace(/\/$/, "")
    .replace(/:(A|B|C|AUTO)$/i, "")
) || value;
const filterDisplayValue = (key, value) => {
  if (key === "source") return SOURCE_LABELS[value] || value;
  if (key === "supplier") return supplierDisplayName(value);
  return value;
};

// ── localStorage ─────────────────────────────────────────
const LS_PUB = "mp_pub_v2", LS_MKT = "mp_mkt_v2", LS_MANUAL = "mp_manual";
const LS_HIDDEN = "mp_hidden", LS_VIEW = "mp_active_view";
const LS_THEME = "mp_theme";
const VIEWS = new Set(["feed", "sources", "duplicates", "markets", "result", "settings", "archive"]);
function getActiveView(){ const v = localStorage.getItem(LS_VIEW); return VIEWS.has(v) ? v : "feed"; }
function getTheme(){
  const saved = localStorage.getItem(LS_THEME);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function getHidden(){ try{return new Set(JSON.parse(localStorage.getItem(LS_HIDDEN)||"[]"));}catch{return new Set();} }
function saveHidden(s){ localStorage.setItem(LS_HIDDEN,JSON.stringify([...s])); }

function simpleHash(s){ let h=0; for(let i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h|=0;} return Math.abs(h).toString(16); }
function makeKey(p){ return p.sku?`sku_${p.sku}`:`hash_${simpleHash(`${(p.name||"").toLowerCase()}|${p.price}|${(p.photos||"").split(",")[0]?.trim()}`)}`; }
function getPub()    { try{return JSON.parse(localStorage.getItem(LS_PUB)||"{}");}catch{return{};} }
function isPublished(p){ return !!getPub()[makeKey(p)]; }
function markPublished(p,markets){ const db=getPub(); db[makeKey(p)]={name:p.name,at:new Date().toISOString(),markets}; localStorage.setItem(LS_PUB,JSON.stringify(db)); }
function getPubInfo(p){ return getPub()[makeKey(p)]||null; }
function clearPublished(keys){ if(keys){const db=getPub();keys.forEach(k=>delete db[k]);localStorage.setItem(LS_PUB,JSON.stringify(db));}else{localStorage.removeItem(LS_PUB);} }
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
const defaultFilters = {search:"",source:[],supplier:[],brand:[],category:[],color:[],size:[],gender:[],priceMin:"",priceMax:"",dateFrom:"",dateTo:"",showPublished:false};

// ════════ Lightbox ════════
function Lightbox({ images, startIndex, onClose }) {
  const [idx, setIdx] = useState(startIndex);
  const prev = useCallback(() => setIdx(i => (i - 1 + images.length) % images.length), [images.length]);
  const next = useCallback(() => setIdx(i => (i + 1) % images.length), [images.length]);

  useEffect(() => {
    const handler = e => {
      if (e.key === "ArrowLeft")  prev();
      if (e.key === "ArrowRight") next();
      if (e.key === "Escape")     onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [prev, next, onClose]);

  return (
    <div onClick={onClose} style={{
      position:"fixed", inset:0, zIndex:10000,
      background:"rgba(0,0,0,.92)",
      display:"flex", flexDirection:"column",
      alignItems:"center", justifyContent:"center",
      animation:"lb-in .18s ease"
    }}>
      <style>{`
        @keyframes lb-in { from{opacity:0} to{opacity:1} }
        .lb-arrow-btn {
          position:absolute; top:50%; transform:translateY(-50%);
          background:rgba(255,255,255,.12); border:none; color:#fff;
          font-size:44px; line-height:1; cursor:pointer;
          padding:6px 16px; border-radius:8px;
          transition:background .15s; user-select:none;
        }
        .lb-arrow-btn:hover { background:rgba(255,255,255,.26); }
        .lb-thumb-strip img { transition:opacity .15s, border-color .15s; }
        .lb-thumb-strip img:hover { opacity:.9 !important; }
      `}</style>

      {/* Кнопка закрити */}
      <button
        onClick={onClose}
        style={{position:"absolute",top:16,right:20,background:"none",border:"none",color:"#fff",fontSize:30,cursor:"pointer",opacity:.8,lineHeight:1}}
      >✕</button>

      {/* Головне фото */}
      <div onClick={e => e.stopPropagation()} style={{display:"flex",alignItems:"center",gap:8,maxWidth:"92vw"}}>
        {images.length > 1 && (
          <button className="lb-arrow-btn" style={{position:"static",transform:"none"}} onClick={prev}>‹</button>
        )}
        <img
          src={images[idx]}
          alt=""
          style={{maxWidth:"80vw", maxHeight:"75vh", objectFit:"contain", borderRadius:8, boxShadow:"0 8px 40px rgba(0,0,0,.7)", display:"block"}}
          onError={e => e.target.style.display="none"}
        />
        {images.length > 1 && (
          <button className="lb-arrow-btn" style={{position:"static",transform:"none"}} onClick={next}>›</button>
        )}
      </div>

      {/* Лічильник */}
      {images.length > 1 && (
        <div style={{color:"rgba(255,255,255,.6)",fontSize:13,marginTop:10}}>{idx + 1} / {images.length}</div>
      )}

      {/* Мініатюри */}
      {images.length > 1 && (
        <div className="lb-thumb-strip" onClick={e => e.stopPropagation()}
          style={{display:"flex",gap:7,marginTop:12,flexWrap:"wrap",justifyContent:"center",maxWidth:"88vw"}}>
          {images.map((src, i) => (
            <img key={i} src={src} alt="" onClick={() => setIdx(i)}
              style={{width:58,height:58,objectFit:"cover",borderRadius:6,cursor:"pointer",
                border: i === idx ? "2px solid #fff" : "2px solid transparent",
                opacity: i === idx ? 1 : 0.5}}
              onError={e => e.target.style.display="none"}/>
          ))}
        </div>
      )}
    </div>
  );
}

// ════════ DuplicatesView ════════
function DuplicatesView({ allProducts, onRefresh }) {
  const [hidden, setHiddenState] = useState(getHidden);

  function getArt(p) {
    const m = (p.description||"").match(/арт\.\s*([^\n,]+)/i);
    return m ? m[1].trim().toLowerCase() : null;
  }

  const groups = useMemo(() => {
    const map = {};
    allProducts.forEach(p => {
      const art = getArt(p);
      if (!art) return;
      if (!map[art]) map[art] = [];
      map[art].push(p);
    });
    return Object.entries(map).filter(([,ps]) => ps.length > 1);
  }, [allProducts]);

  function hideProduct(id) {
    const n = new Set(hidden); n.add(id); saveHidden(n); setHiddenState(n); onRefresh();
  }
  function restoreProduct(id) {
    const n = new Set(hidden); n.delete(id); saveHidden(n); setHiddenState(n); onRefresh();
  }

  if (groups.length === 0) return (
    <div className="card"><h2>🔁 Дублікати</h2><div className="empty-state">Дублікатів не знайдено.</div></div>
  );

  return (
    <div className="card">
      <h2>🔁 Дублікати</h2>
      <p className="hint">
        Згруповані по артикулу. Перший — основний, решта — можливі дублікати. &nbsp;
        <span style={{fontWeight:600, color:"#e53935"}}>
          Всього дублікатів: {groups.reduce((sum, [, ps]) => sum + ps.length - 1, 0)}
        </span>
      </p>
      {groups.map(([art, products]) => (
        <div key={art} style={{marginBottom:20,border:"1px solid #e5e5e5",borderRadius:12,overflow:"hidden"}}>
          <div style={{padding:"10px 16px",background:"#f5f5f5",fontWeight:600,fontSize:13}}>
            арт. {art} · {products.length} товари
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(180px,1fr))",gap:12,padding:12}}>
            {products.map((p, idx) => {
              const photo = p.photos?.split(",")[0]?.trim();
              const isHidden = hidden.has(p.id);
              return (
                <div key={p.id} style={{border:`2px solid ${idx===0?"#4f46e5":"#e5e5e5"}`,borderRadius:10,overflow:"hidden",opacity:isHidden?0.45:1}}>
                  {photo && <img src={photo} alt="" style={{width:"100%",aspectRatio:"1",objectFit:"cover"}} onError={e=>e.target.style.display="none"}/>}
                  <div style={{padding:8}}>
                    {idx===0 && <span style={{fontSize:10,background:"#4f46e5",color:"#fff",padding:"2px 6px",borderRadius:4,marginBottom:4,display:"inline-block"}}>Основний</span>}
                    {isHidden && <span style={{fontSize:10,background:"#e5e5e5",color:"#666",padding:"2px 6px",borderRadius:4,marginBottom:4,display:"inline-block"}}>Прихований</span>}
                    <div style={{fontSize:12,fontWeight:600,marginBottom:2,lineHeight:1.3}}>{p.name}</div>
                    <div style={{fontSize:11,color:"#aaa",marginBottom:4}}>{p.post_date}</div>
                    {p.post_url && <a href={p.post_url} target="_blank" rel="noreferrer" style={{fontSize:11,color:"#4f46e5"}}>&#128279; &#1055;&#1086;&#1089;&#1090;</a>}
                    <div style={{display:"flex",gap:4,marginTop:6}}>
                      {idx!==0 && !isHidden && <button className="btn-sm" style={{fontSize:11,padding:"3px 8px",color:"#e53935",borderColor:"#e53935"}} onClick={()=>hideProduct(p.id)}>&#1055;&#1088;&#1080;&#1093;&#1086;&#1074;&#1072;&#1090;&#1080;</button>}
                      {isHidden && <button className="btn-sm" style={{fontSize:11,padding:"3px 8px"}} onClick={()=>restoreProduct(p.id)}>&darr; &#1055;&#1086;&#1074;&#1077;&#1088;&#1085;&#1091;&#1090;&#1080;</button>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// ════════ Toast ════════
function Toast({ msg, onClose }) {
  useEffect(()=>{ const t=setTimeout(onClose,3500); return()=>clearTimeout(t); },[onClose]);
  return <div className="toast">{msg}</div>;
}

// ════════ ProductCard ════════
function ProductCard({ product, selected, onSelect, published, onDelete, onView, archived }) {
  const photo = product.photos?.split(",")[0]?.trim();
  const pubInfo = published ? getPubInfo(product) : null;
  const pubDate = pubInfo?.at ? new Date(pubInfo.at).toLocaleDateString("uk-UA") : "";
  const sourceTitle = supplierDisplayName(product.supplier_title||product.supplier||"");
  const sourceParts = sourceTitle.match(/^(\S+)\s+(.+)$/);
  const sourceName = sourceParts ? sourceParts[1] : sourceTitle;
  const sourceMeta = sourceParts ? sourceParts[2] : "";

  return (
    <div className={`pcard ${selected?"pcard-sel":""} ${published?"pcard-pub":""} ${archived?"pcard-archived":""}`}>
      <div className="pcard-img-wrap" onClick={()=>onSelect(product.id)}>
        {photo ? <img src={photo} alt={product.name} className="pcard-img" onError={e=>e.target.style.display="none"}/> : <div className="pcard-no-img">📷</div>}
        {(() => { const cnt = (product.photos||"").split(",").filter(s=>s.trim()).length; return cnt > 1 ? <div className="pcard-photo-count">{cnt}</div> : null; })()}
        {published && <div className="pcard-pub-overlay">✓ Опубліковано<br/><span style={{fontSize:10,opacity:.85}}>{pubDate}</span></div>}
        {archived && <div className="pcard-archived-overlay">📦 Архів</div>}
        <div className={`pcard-check ${selected?"checked":""}`}>{selected?"✓":""}</div>
      </div>
      <div className="pcard-body" onClick={()=>onView(product)} style={{cursor:"pointer"}}>
        <div className="pcard-top">
          <span className="pcard-src" style={{background:"transparent", padding:0}}>
            {product.source === "telegram"
              ? <img src="https://www.google.com/s2/favicons?domain=telegram.org&sz=64" alt="" className="pcard-src-icon"/>
              : SOURCE_LABELS[product.source]||product.source}
            <span className="pcard-src-name">{sourceName}</span>
            {sourceMeta && <span className="pcard-src-meta">{sourceMeta}</span>}
          </span>
          <span className="pcard-date">{product.post_date || (product.addedAt?new Date(product.addedAt).toLocaleDateString("uk-UA"):"")}</span>
        </div>
        <div className="pcard-name">{product.name}</div>
        <div className="pcard-brand">{product.brand}</div>
        <div className="pcard-meta">
          <div className="pcard-row">
            <span className="pcard-price">{product.price?`${product.price} грн`:"—"}</span>
            {product.size&&<span className="pcard-size">{product.size}</span>}
          </div>
          {product.source_url
            ? <div className="pcard-supplier"><a href={product.source_url} target="_blank" rel="noreferrer" onClick={e=>e.stopPropagation()} style={{color:"inherit",textDecoration:"none"}}>🔗 {product.source_url}</a></div>
            : product.supplier&&<div className="pcard-supplier">📦 {supplierDisplayName(product.supplier_title||product.supplier)}</div>
          }
        </div>
        <div className="pcard-actions">
          <button className="pcard-btn-view" onClick={e=>{e.stopPropagation();onView(product);}}>
            <img src="/eye-emoji.png" alt="" className="eye-icon" aria-hidden="true"/> Переглянути
          </button>
          <button className="pcard-btn-del" onClick={e=>{e.stopPropagation();onDelete(product.id);}} title="Видалити" aria-label="Видалити">
            <img src="/trash-emoji.png" alt="" className="trash-icon" aria-hidden="true"/>
          </button>
        </div>
      </div>
    </div>
  );
}

// ════════ ProductViewModal ════════
function ProductViewModal({ product, onClose, onPublish, onDelete, published, onPrev, onNext, hasPrev, hasNext, onArchive, archived }) {
  const photos = (product.photos||"").split(",").map(p=>p.trim()).filter(Boolean);
  const [photoIdx, setPhotoIdx] = useState(0);
  const [lightboxIdx, setLightboxIdx] = useState(null); // null = закрито
  const pubInfo = published ? getPubInfo(product) : null;

  useEffect(() => {
    const handler = e => {
      if (lightboxIdx !== null) return;
      if (e.key === "ArrowLeft")  onPrev?.();
      if (e.key === "ArrowRight") onNext?.();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [lightboxIdx, onPrev, onNext]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="post-nav-shell" onClick={e=>e.stopPropagation()}>
        {hasPrev && (
          <button
            className="post-nav-btn post-nav-prev"
            onClick={e=>{e.stopPropagation();onPrev();}}
            aria-label="Попередній товар"
            type="button"
          />
        )}
        {hasNext && (
          <button
            className="post-nav-btn post-nav-next"
            onClick={e=>{e.stopPropagation();onNext();}}
            aria-label="Наступний товар"
            type="button"
          />
        )}
        <div className="modal" style={{width:"100%"}}>
        <div className="modal-header">
          <h3 style={{fontSize:16}}>{product.name||"Без назви"}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {photos.length>0 && (
            <div style={{marginBottom:16}}>
              {/* Головне фото — кліком відкриває lightbox */}
              <img
                src={photos[photoIdx]}
                alt=""
                onClick={() => setLightboxIdx(photoIdx)}
                style={{
                  width:"100%", maxHeight:320, objectFit:"contain",
                  borderRadius:8, background:"#f5f5f5",
                  cursor:"zoom-in", display:"block"
                }}
                onError={e=>e.target.style.display="none"}
              />
              {/* Мініатюри */}
              {photos.length>1 && (
                <div style={{display:"flex",gap:6,marginTop:8,overflowX:"auto"}}>
                  {photos.map((ph,i)=>(
                    <img key={i} src={ph} alt=""
                      onClick={() => setPhotoIdx(i)}
                      onDoubleClick={() => setLightboxIdx(i)}
                      style={{
                        width:56, height:56, objectFit:"cover", borderRadius:6,
                        cursor:"pointer", flexShrink:0,
                        border: i===photoIdx ? "2px solid #4F46E5" : "2px solid transparent"
                      }}
                      onError={e=>e.target.style.display="none"}/>
                  ))}
                </div>
              )}
              <div style={{textAlign:"center",fontSize:11,color:"#bbb",marginTop:6}}>
                Клікни на фото щоб відкрити на весь екран
              </div>
            </div>
          )}

          <div className="grid2" style={{gap:8,marginBottom:12}}>
            {[["Бренд",product.brand],["Ціна",product.price?`${product.price} грн`:"—"],["Розмір",product.size],["Колір",product.color],["Матеріал",product.material],["Стать",product.gender],["Стан",product.condition],["Категорія",product.category],["Постачальник",supplierDisplayName(product.supplier_title||product.supplier)],["Джерело",SOURCE_LABELS[product.source]||product.source],["Дата поста",product.post_date],["Посилання на пост",product.post_url]].filter(([,v])=>v).map(([l,v])=>(
              <div key={l} style={{background:"var(--color-background-secondary)",borderRadius:6,padding:"6px 10px"}}>
                <div style={{fontSize:11,color:"var(--color-text-secondary)",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.04em"}}>{l}</div>
                {v?.startsWith("http") ? <a href={v} target="_blank" rel="noreferrer" style={{fontSize:13,color:"#4F46E5",wordBreak:"break-all"}}>{v}</a> : <div style={{fontSize:13}}>{v}</div>}
              </div>
            ))}
          </div>

          {product.description && (
            <div style={{marginBottom:12}}>
              <div style={{fontSize:12,color:"var(--color-text-secondary)",marginBottom:4}}>Опис</div>
              <div style={{fontSize:13,lineHeight:1.6,whiteSpace:"pre-wrap"}}>{product.description}</div>
            </div>
          )}

          {published && pubInfo && (
            <div className="info-box" style={{marginBottom:12}}>
              ✓ Опубліковано {new Date(pubInfo.at).toLocaleDateString("uk-UA")} · {(pubInfo.markets||[]).join(", ")}
            </div>
          )}

          <div className="row-btns">
            <button className="btn-secondary" style={{color:"#c0392b",borderColor:"#c0392b",display:"inline-flex",alignItems:"center",gap:6}} onClick={()=>{onDelete(product.id);onClose();}}>
              <img src="/trash-emoji.png" alt="" className="trash-icon" aria-hidden="true"/> Видалити
            </button>
            {onArchive && (
              <button
                className="btn-secondary"
                style={{color:"#7c3aed",borderColor:"#7c3aed",display:"inline-flex",alignItems:"center",gap:6}}
                onClick={()=>{onArchive(product.id, !archived);onClose();}}>
                {archived ? "↩️ Розархівувати" : "📦 В архів"}
              </button>
            )}
            {!published && <button className="btn-primary" onClick={()=>{onPublish(product.id);onClose();}}>Публікувати →</button>}
          </div>
        </div>
      </div>
      </div>

      {/* Lightbox — рендеримо поза модалкою щоб перекрити все */}
      {lightboxIdx !== null && (
        <Lightbox
          images={photos}
          startIndex={lightboxIdx}
          onClose={() => setLightboxIdx(null)}
        />
      )}
    </div>
  );
}

// ════════ MultiSelect ════════
function MultiSelect({ label, filterKey, options, filters, setFilters, openKey, setOpenKey }) {
  const open = openKey === filterKey;
  const selected = filters[filterKey] || [];
  const optionLabels = useMemo(() => Object.fromEntries(options.map(o => [o.val, o.label])), [options]);
  const toggle = (val) => {
    const next = selected.includes(val) ? selected.filter(v=>v!==val) : [...selected, val];
    setFilters(f => ({...f, [filterKey]: next}));
  };
  const label_text = selected.length === 0 ? "Всі" : selected.length === 1 ? (optionLabels[selected[0]] || filterDisplayValue(filterKey, selected[0])) : `${selected.length} обрано`;
  return (
    <div style={{position:"relative"}}>
      <label className="filter-label">{label}</label>
      <div className="filter-select" style={{cursor:"pointer",userSelect:"none",display:"flex",justifyContent:"space-between",alignItems:"center"}}
        onClick={()=>setOpenKey(open ? null : filterKey)}>
        <span style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",maxWidth:"85%"}}>{label_text}</span>
        <span style={{fontSize:10,opacity:.5}}>{open?"▲":"▼"}</span>
      </div>
      {open && (
        <div style={{position:"absolute",top:"100%",left:0,right:0,zIndex:100,background:"var(--color-surface)",border:"1.5px solid var(--color-border)",borderRadius:8,boxShadow:"0 4px 16px rgba(0,0,0,.12)",maxHeight:200,overflowY:"auto"}}>
          {selected.length > 0 && (
            <div style={{padding:"6px 10px",borderBottom:"1px solid var(--color-border-tertiary)"}}>
              <button style={{fontSize:11,color:"#4f46e5",background:"none",border:"none",cursor:"pointer",padding:0}} onClick={()=>setFilters(f=>({...f,[filterKey]:[]}))}>Скинути вибір</button>
            </div>
          )}
          {options.map(o=>(
            <label key={o.val} style={{display:"flex",alignItems:"center",gap:8,padding:"6px 10px",cursor:"pointer",fontSize:12,background:selected.includes(o.val)?"var(--color-background-secondary)":"transparent"}}>
              <input type="checkbox" checked={selected.includes(o.val)} onChange={()=>toggle(o.val)} style={{flexShrink:0}}/>
              <span style={{flex:1,minWidth:0}}>{o.label}</span>
              {o.count !== undefined && (
                <span style={{
                  fontSize:11, padding:"1px 7px", borderRadius:10, flexShrink:0,
                  background: selected.includes(o.val) ? "#ede9fe" : "var(--color-background-secondary)",
                  color: selected.includes(o.val) ? "#5b21b6" : "var(--color-text-secondary)",
                  border: selected.includes(o.val) ? "0.5px solid #c4b5fd" : "0.5px solid var(--color-border-tertiary)",
                  opacity: o.count === 0 ? 0.4 : 1,
                }}>
                  {o.count}
                </span>
              )}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ════════ FiltersBar ════════
function FiltersBar({ filters, setFilters, products }) {
  const supplierMap = useMemo(() => {
    const m = {};
    products.forEach(p => {
      if (p.supplier) m[p.supplier] = p.supplier_title || p.supplier;
    });
    return m;
  }, [products]);
  const suppliers  = useMemo(()=>[...new Set(products.map(p=>p.supplier).filter(Boolean))],[products]);
  const brands     = useMemo(()=>[...new Set(products.map(p=>p.brand).filter(Boolean))],[products]);
  const categories = useMemo(()=>[...new Set(products.map(p=>p.category).filter(Boolean))],[products]);
  const sizes      = useMemo(()=>[...new Set(products.flatMap(p=>(p.size||"").split(",").map(s=>s.trim())).filter(Boolean))],[products]);

  const counts = useMemo(() => {
    function filterExcept(excludeKey) {
      return products.filter(p => {
        if(filters.search && !`${p.name} ${p.brand} ${p.description||""}`.toLowerCase().includes(filters.search.toLowerCase())) return false;
        if(excludeKey !== "source"   && filters.source?.length   && !filters.source.includes(p.source))     return false;
        if(excludeKey !== "supplier" && filters.supplier?.length && !filters.supplier.includes(p.supplier)) return false;
        if(excludeKey !== "brand"    && filters.brand?.length    && !filters.brand.includes(p.brand))       return false;
        if(excludeKey !== "category" && filters.category?.length && !filters.category.includes(p.category)) return false;
        if(excludeKey !== "gender"   && filters.gender?.length   && !filters.gender.includes(p.gender))     return false;
        if(excludeKey !== "color"    && filters.color?.length    && !filters.color.some(c=>(p.color||"").split(",").map(s=>s.trim()).includes(c))) return false;
        if(excludeKey !== "size"     && filters.size?.length     && !filters.size.some(s=>(p.size||"").includes(s))) return false;
        if(filters.priceMin && +p.price < +filters.priceMin) return false;
        if(filters.priceMax && +p.price > +filters.priceMax) return false;
        return true;
      });
    }
    function tally(arr, key) {
      const m = {};
      arr.forEach(p => { if(p[key]) m[p[key]] = (m[p[key]]||0)+1; });
      return m;
    }
    function tallyMulti(arr, key) {
      const m = {};
      arr.forEach(p => { (p[key]||"").split(",").map(s=>s.trim()).filter(Boolean).forEach(v=>{ m[v]=(m[v]||0)+1; }); });
      return m;
    }
    return {
      source:   tally(filterExcept("source"),   "source"),
      supplier: tally(filterExcept("supplier"), "supplier"),
      brand:    tally(filterExcept("brand"),    "brand"),
      category: tally(filterExcept("category"), "category"),
      gender:   tally(filterExcept("gender"),   "gender"),
      color:    tallyMulti(filterExcept("color"), "color"),
      size:     tallyMulti(filterExcept("size"),  "size"),
    };
  }, [products, filters]);
  const [openKey, setOpenKey] = useState(null);
  const set=(k,v)=>setFilters(f=>({...f,[k]:v}));
  return (
    <div className="filters">
      <div className="filters-scroll">
      <div className="filters-title" style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <span>🔍 Фільтри</span>
        <button
          className={`pub-toggle-btn ${filters.showPublished?"active":""}`}
          onClick={()=>setFilters(f=>({...f,showPublished:!f.showPublished}))}
        >{filters.showPublished ? "Не опубліковані" : "Опубліковані"}</button>
      </div>
      <input className="filter-input" placeholder="Пошук за назвою або брендом..." value={filters.search} onChange={e=>set("search",e.target.value)}/>
      <MultiSelect label="Джерело" filterKey="source" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={Object.entries(SOURCE_LABELS).map(([k,v])=>({val:k,label:v,count:counts.source[k]||0}))}/>
      <MultiSelect label="Постачальник" filterKey="supplier" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={suppliers.map(s=>({val:s,label:supplierDisplayName(s),count:counts.supplier[s]||0}))}/>
      <MultiSelect label="Бренд" filterKey="brand" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={brands.map(b=>({val:b,label:b,count:counts.brand[b]||0}))}/>
      <MultiSelect label="Категорія" filterKey="category" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={categories.map(c=>({val:c,label:c,count:counts.category[c]||0}))}/>
      <MultiSelect label="Колір" filterKey="color" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={[...new Set(products.flatMap(p=>(p.color||"").split(",").map(s=>s.trim())).filter(Boolean))].sort().map(c=>({val:c,label:c,count:counts.color[c]||0}))}/>
      <MultiSelect label="Розмір" filterKey="size" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={sizes.map(s=>({val:s,label:s,count:counts.size[s]||0}))}/>
      <MultiSelect label="Стать" filterKey="gender" filters={filters} setFilters={setFilters} openKey={openKey} setOpenKey={setOpenKey}
        options={[{val:"Жіноче",label:"Жіноче"},{val:"Чоловіче",label:"Чоловіче"},{val:"Унісекс",label:"Унісекс"},{val:"Дитяче",label:"Дитяче"}].map(o=>({...o,count:counts.gender[o.val]||0}))}/>
      <label className="filter-label">Ціна від — до (грн)</label>
      <div className="filter-row">
        <input className="filter-input filter-half" type="number" placeholder="від" value={filters.priceMin} onChange={e=>set("priceMin",e.target.value)}/>
        <input className="filter-input filter-half" type="number" placeholder="до"  value={filters.priceMax} onChange={e=>set("priceMax",e.target.value)}/>
      </div>
      <label className="filter-label">Дата від</label>
      <input className="filter-input" type="date" value={filters.dateFrom} onChange={e=>set("dateFrom",e.target.value)}/>
      <label className="filter-label">Дата до</label>
      <input className="filter-input" type="date" value={filters.dateTo} onChange={e=>set("dateTo",e.target.value)}/>
      </div>
      <button className="filter-reset" onClick={()=>setFilters(defaultFilters)}>Скинути фільтри</button>
    </div>
  );
}

// ════════ ProductForm ════════
function ProductForm({ product, setProduct, onSave, onBack, backLabel="← Назад", serverOnline }) {
  const set=(k,v)=>setProduct(p=>({...p,[k]:v}));
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
      else { const decoded = Object.fromEntries(
  Object.entries(data).map(([k, v]) => [k, typeof v === "string" ? decodeHtml(v) : v])
);
setProduct({...emptyProduct, ...decoded, id:Date.now().toString(), addedAt:new Date().toISOString()}); setShowForm(true); }
    } catch(e) { setError("Сервер недоступний. Запусти: python scripts/server.py"); }
    setLoading(false);
  }

  async function parseText() {
    if (!text.trim()) return;
    if (!serverOnline) {
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

// ════════ ResetPublishedWidget ════════
function ResetPublishedWidget({ onReset }) {
  const [pubDb, setPubDb] = useState(getPub);
  const [selected, setSelected] = useState(new Set());
  const [confirm, setConfirm] = useState(false);
  const entries = Object.entries(pubDb);

  function refresh(){ setPubDb(getPub()); setSelected(new Set()); setConfirm(false); onReset(); }
  function toggleKey(k){ setSelected(s=>{const n=new Set(s);n.has(k)?n.delete(k):n.add(k);return n;}); }
  function resetSelected(){ clearPublished([...selected]); refresh(); }
  function resetAll(){ clearPublished(); refresh(); }

  if(entries.length===0) return <div className="info-box">Немає опублікованих товарів.</div>;

  return (
    <div>
      <div style={{maxHeight:220,overflowY:"auto",border:"1px solid var(--color-border-tertiary)",borderRadius:8,marginBottom:12}}>
        {entries.map(([k,info])=>(
          <label key={k} style={{display:"flex",alignItems:"center",gap:10,padding:"7px 12px",
            borderBottom:"1px solid var(--color-border-tertiary)",cursor:"pointer",
            background:selected.has(k)?"var(--color-background-secondary)":"transparent"}}>
            <input type="checkbox" checked={selected.has(k)} onChange={()=>toggleKey(k)}/>
            <div style={{flex:1,minWidth:0}}>
              <div style={{fontWeight:500,fontSize:14,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{info.name||k}</div>
              <div style={{fontSize:12,color:"var(--color-text-secondary)"}}>{new Date(info.at).toLocaleDateString("uk-UA")} · {(info.markets||[]).join(", ")}</div>
            </div>
          </label>
        ))}
      </div>
      <div className="row-btns">
        {selected.size>0 && <button className="btn-secondary" onClick={resetSelected}>Скинути вибрані ({selected.size})</button>}
        {!confirm
          ? <button className="btn-secondary" style={{color:"#c0392b",borderColor:"#c0392b"}} onClick={()=>setConfirm(true)}>Скинути всі ({entries.length})</button>
          : <>
              <button className="btn-primary" style={{background:"#c0392b"}} onClick={resetAll}>Підтвердити</button>
              <button className="btn-secondary" onClick={()=>setConfirm(false)}>Скасувати</button>
            </>
        }
      </div>
    </div>
  );
}

// ════════ SettingsView ════════
function SettingsView({ serverOnline, onReset }) {
  const [form, setForm] = useState({ telegram_mode:"public", telegram_channels:"", mydrop_token:"", keycrm_key:"", telegram_api_id:"", telegram_api_hash:"" });
  const [status, setStatus] = useState(null);
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
        <h3 className="settings-title">
          <img src="https://www.google.com/s2/favicons?domain=telegram.org&sz=64" alt="Telegram" className="source-logo" style={{verticalAlign:"middle",marginRight:8}}/>
          Telegram
        </h3>
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
        <h3 className="settings-title">
          <img src="https://www.google.com/s2/favicons?domain=mydrop.com.ua&sz=64" alt="MyDrop" className="source-logo" style={{verticalAlign:"middle",marginRight:8}}/>
          <a href="https://mydrop.com.ua" target="_blank" rel="noreferrer" style={{textDecoration:"none",color:"inherit",fontWeight:600}}>MyDrop</a> {status?.has_mydrop_token&&<span className="badge-green" style={{fontSize:11}}>✓ Збережено</span>}
        </h3>
        <div className="field">
          <label className="field-label">API Токен <span className="hint-inline">(MyDrop → Інтеграції → API)</span></label>
          <input className="input" type="password" value={form.mydrop_token} onChange={e=>set("mydrop_token",e.target.value)} placeholder="Вставте токен..."/>
        </div>
      </div>

      <div className="settings-section">
        <h3 className="settings-title">
          <img src="https://www.google.com/s2/favicons?domain=keycrm.app&sz=64" alt="KeyCRM" className="source-logo" style={{verticalAlign:"middle",marginRight:8}}/>
          <a href="https://keycrm.app" target="_blank" rel="noreferrer" style={{textDecoration:"none",color:"inherit",fontWeight:600}}>KeyCRM</a> {status?.has_keycrm_key&&<span className="badge-green" style={{fontSize:11}}>✓ Збережено</span>}
        </h3>
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

      <div className="settings-section" style={{marginTop:24}}>
        <h3 className="settings-title"><img src="/trash-emoji.png" alt="" className="trash-icon" aria-hidden="true"/> Скинути публікації</h3>
        <p className="hint">Товари знову з'являться у стрічці як нові.</p>
        <ResetPublishedWidget onReset={onReset}/>
      </div>
    </div>
  );
}

// ════════ MAIN APP ════════
export default function App() {
  const [view, setView]         = useState(getActiveView);
  const [theme, setTheme]       = useState(getTheme);
  const [sourceDirty, setSourceDirty] = useState(false);

  useEffect(() => {
    localStorage.setItem(LS_VIEW, view);
  }, [view]);

  useEffect(() => {
    document.body.dataset.theme = theme;
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  function safeSetView(newView) {
    console.log("safeSetView викликано з:", newView, new Error().stack);
    if (sourceDirty && newView !== "sources") {
      if (window.confirm("Є незбережені зміни. Покинути без збереження?")) {
        setSourceDirty(false);
        setView(newView);
      }
    } else {
      setView(newView);
    }
  }
  const [allProducts, setAll]   = useState([]);
  const [filters, setFilters]   = useState(defaultFilters);
  const [selected, setSelected] = useState(new Set());
  const [enabled, setEnabled]   = useState(getEnabledMkts);
  const [showAdd, setShowAdd]   = useState(false);
  const [generated, setGen]     = useState([]);
  const [pubV, setPubV]         = useState(0);
  const [serverOnline, setServerOnline] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [toast, setToast]       = useState("");
  const [viewProduct, setViewProduct] = useState(null);
  const [sortOrder, setSortOrder] = useState("newest");
  const [archiveKeywords, setArchiveKeywords] = useState({});
  const [disabledChannels, setDisabledChannels] = useState(() => {
    try { return JSON.parse(localStorage.getItem("mp_disabled_channels") || "[]"); } catch { return []; }
  });

  useEffect(()=>{
    fetch(`${SERVER}/health`).then(()=>setServerOnline(true)).catch(()=>setServerOnline(false));
    fetch(`${SERVER}/last-sync`).then(r=>r.json()).then(d=>setLastSync(d.synced_at)).catch(()=>{});
    const t = setInterval(()=>{ fetch(`${SERVER}/health`).then(()=>setServerOnline(true)).catch(()=>setServerOnline(false)); }, 10000);
    return ()=>clearInterval(t);
  },[]);

  useEffect(()=>{
    Promise.all([
      fetch("/products.json").then(r=>r.json()).catch(()=>[]),
      fetch(`${SERVER}/synced-products`).then(r=>r.json()).catch(()=>[]),
      loadArchiveKeywords(),
    ]).then(([base, synced, archiveData]) => {
      const manual = getManual();
      const all = [...base, ...synced, ...manual];
      const unique = Array.from(new Map(all.map(p=>[p.id||Math.random(),p])).values());
      setArchiveKeywords(archiveData);
      setAll(unique);
    });
  },[pubV]);

  const filtered = useMemo(()=>allProducts.filter(p=>{
    if (disabledChannels.some(ch => ch && (p.supplier?.includes(ch) || p.source_channel?.includes(ch) || p.channel?.includes(ch)))) return false;
    // Фільтруємо архівні пости за замовчуванням
    if (p.archived || productMatchesArchiveRules(p, archiveKeywords)) return false;
    const pub=isPublished(p);
    if(filters.showPublished && !pub) return false;
    if(!filters.showPublished && pub) return false;
    if(filters.search&&!`${p.name} ${p.brand} ${p.description||""}`.toLowerCase().includes(filters.search.toLowerCase())) return false;
    if(filters.source?.length   && !filters.source.includes(p.source))     return false;
    if(filters.supplier?.length && !filters.supplier.includes(p.supplier)) return false;
    if(filters.brand?.length    && !filters.brand.includes(p.brand))       return false;
    if(filters.category?.length && !filters.category.includes(p.category)) return false;
    if(filters.gender?.length   && !filters.gender.includes(p.gender))     return false;
    if(filters.color?.length && !filters.color.some(c=>(p.color||"").split(",").map(s=>s.trim()).includes(c))) return false;
    if(filters.size?.length  && !filters.size.some(s=>(p.size||"").includes(s))) return false;
    if(filters.priceMin &&+p.price<+filters.priceMin)      return false;
    if(filters.priceMax &&+p.price>+filters.priceMax)      return false;
    const itemDate = p.post_date
      ? p.post_date.split(".").reverse().join("-")
      : (p.addedAt||"").slice(0,10);
    if(filters.dateFrom && itemDate < filters.dateFrom) return false;
    if(filters.dateTo   && itemDate > filters.dateTo)   return false;
    return true;
  }),[allProducts,filters,pubV,disabledChannels,archiveKeywords]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    switch (sortOrder) {
      case "newest": return arr.sort((a,b) => {
        const da = a.post_datetime || (a.post_date ? a.post_date.split(".").reverse().join("-") : (a.addedAt||"").slice(0,10));
        const db = b.post_datetime || (b.post_date ? b.post_date.split(".").reverse().join("-") : (b.addedAt||"").slice(0,10));
        return db.localeCompare(da);
      });
      case "oldest": return arr.sort((a,b) => {
        const da = a.post_date ? a.post_date.split(".").reverse().join("-") : (a.addedAt||"").slice(0,10);
        const db = b.post_date ? b.post_date.split(".").reverse().join("-") : (b.addedAt||"").slice(0,10);
        return da.localeCompare(db);
      });
      case "price_asc":  return arr.sort((a,b) => (+a.price||0) - (+b.price||0));
      case "price_desc": return arr.sort((a,b) => (+b.price||0) - (+a.price||0));
      default: return arr;
    }
  }, [filtered, sortOrder]);

  function toggleSelect(id){ setSelected(s=>{const n=new Set(s);n.has(id)?n.delete(id):n.add(id);return n;}); }
  function selectAll(){ setSelected(new Set(filtered.filter(p=>!isPublished(p)).map(p=>p.id))); }
  function clearSel() { setSelected(new Set()); }

  function handleAdd(p){ const m=getManual(); m.push(p); saveManual(m); setAll(prev=>[...prev,p]); setToast(`✓ Товар "${p.name}" додано`); }

  async function handleDelete(id){
    const product = allProducts.find(p => p.id === id);
    if(!window.confirm("Видалити товар, запис поста та невикористані фото?")) return;

    const manualBefore = getManual();
    const manual = manualBefore.filter(p=>p.id!==id);
    const isManual = manual.length !== manualBefore.length || product?.source === "manual";

    if (!isManual) {
      if (!serverOnline) {
        window.alert("Сервер вимкнено. Щоб видалити товар із synced_products.json і фото, запусти python scripts/server.py");
        return;
      }
      try {
        const res = await fetch(`${SERVER}/synced-products/delete`, {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({id})
        });
        if (!res.ok) {
          const data = await res.json().catch(()=>({}));
          throw new Error(data.error || "Не вдалося видалити товар на сервері");
        }
        const data = await res.json();
        setToast(`Видалено товар і фото: ${data.deleted_photos || 0}`);
      } catch (e) {
        window.alert(e.message || "Не вдалося видалити товар");
        return;
      }
    } else {
      saveManual(manual);
      setToast("Товар видалено");
    }

    if (product) clearPublished([makeKey(product)]);
    setAll(prev=>prev.filter(p=>p.id!==id));
    setSelected(s=>{const n=new Set(s);n.delete(id);return n;});
    setViewProduct(p => p?.id === id ? null : p);
  }

  function handlePublishOne(id){
    const product=allProducts.find(p=>p.id===id); if(!product) return;
    const active=MARKETPLACES.filter(m=>enabled[m.id]&&!m.disabled);
    const gen=active.map(m=>{const{format,content}=generateOutput(product,m.id);return{product,marketplace:m,format,content};});
    markPublished(product,active.map(m=>m.id));
    setGen(gen); setSelected(new Set()); setPubV(v=>v+1); setView("result");
    setToast(`✓ Опубліковано "${product.name}"`);
  }

  function handlePublish(){
    const toPublish=allProducts.filter(p=>selected.has(p.id));
    const active=MARKETPLACES.filter(m=>enabled[m.id]&&!m.disabled);
    const gen=toPublish.flatMap(product=>active.map(m=>{const{format,content}=generateOutput(product,m.id);return{product,marketplace:m,format,content};}));
    toPublish.forEach(p=>markPublished(p,active.map(m=>m.id)));
    setGen(gen); setSelected(new Set()); setPubV(v=>v+1); setView("result");
    setToast(`✓ Опубліковано ${toPublish.length} товарів на ${active.length} маркетплейсах`);
  }

  async function handleArchive(productId, archived) {
    if (!serverOnline) {
      alert("Сервер не запущено. Запусти: python scripts/server.py");
      return;
    }
    try {
      const res = await fetch(`${SERVER}/archive-product`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: productId, archived })
      });
      if (!res.ok) throw new Error("Помилка архівування");
      setAll(prev => prev.map(p => p.id === productId ? { ...p, archived } : p));
      setToast(archived ? "✓ Переміщено в архів" : "✓ Розархівовано");
    } catch (e) {
      alert("Не вдалося архівувати товар");
    }
  }

  const activeCount=MARKETPLACES.filter(m=>enabled[m.id]&&!m.disabled).length;
  const newCount = allProducts.filter(p =>
  !isPublished(p) && !p.archived && !productMatchesArchiveRules(p, archiveKeywords)
).length;

// Рахунок постів по кожному ключовому слову
const archiveKeywordCounts = useMemo(() => {
  const result = {};
  Object.entries(archiveKeywords).forEach(([channel, keywords]) => {
    if (!result[channel]) result[channel] = {};
    (keywords || []).forEach(kw => {
      const needle = String(kw || "").trim().toLowerCase();
      if (!needle) return;
      result[channel][kw] = allProducts.filter(p => {
        const channelKeys = [p.supplier, p.source_channel, p.channel]
          .map(v => String(v || "").trim()).filter(Boolean);
        if (!channelKeys.includes(channel)) return false;
        const text = [p.name, p.description, p.text, p.post_text, p.postText, p.raw_text, p.rawText]
          .map(v => String(v || "")).join(" ").toLowerCase();
        return text.includes(needle);
      }).length;
    });
  });
  return result;
}, [allProducts, archiveKeywords]);

  return (
    <div className="app">
      {toast && <Toast msg={toast} onClose={()=>setToast("")}/>}

      <header className="app-header">
        <div>
          <h1>🛍 Постинг товарів на маркетплейси</h1>
          <p className="subtitle">Одяг та взуття · Telegram / CRM → Маркетплейси</p>
        </div>
        <div className="header-right" style={{display:"flex",alignItems:"center",gap:12,flexWrap:"nowrap"}}>
          <div style={{display:"flex",alignItems:"center",gap:8,border:"1px solid #7c3aed",borderRadius:8,padding:"4px 10px"}}>
            <span style={{fontSize:13,color:"#5b21b6"}}>📦 {newCount} товарів</span>
            <span style={{color:"#7c3aed",fontSize:14}}>•</span>
            <span style={{fontSize:13,color:"#5b21b6"}}>🏪 {activeCount} маркетплейсів</span>
            <span style={{color:"#7c3aed",fontSize:14}}>•</span>
            <span style={{fontSize:13,color:"#5b21b6"}}>{serverOnline?"🟢 Сервер працює":"🔴 Сервер вимкнено"}</span>
            {lastSync && (
              <span style={{display:"flex",flexDirection:"column",alignItems:"flex-end",lineHeight:1.2}}>
                <span style={{fontSize:12,fontWeight:500,color:"#5b21b6"}}>{new Date(lastSync).toLocaleTimeString("uk-UA", {hour:"2-digit",minute:"2-digit"})}</span>
                <span style={{fontSize:10,opacity:.6}}>{new Date(lastSync).toLocaleDateString("uk-UA")}</span>
              </span>
            )}
          </div>
          <button
            className="theme-toggle"
            type="button"
            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Увімкнути світлий режим" : "Увімкнути темний режим"}
            title={theme === "dark" ? "Світлий режим" : "Темний режим"}
          >
            <img
              className="theme-toggle-img"
              src={theme === "dark" ? "/theme-toggle-dark.png" : "/theme-toggle-light.png"}
              alt=""
              aria-hidden="true"
            />
          </button>
        </div>
      </header>

      <nav className="nav">
        {[["feed","📋 Стрічка"],["sources","🔌 Джерела"],["duplicates","🔁 Дублікати"],["archive","📦 Архів"],["markets","🛒 Маркетплейси"],["result","📦 Результат"],["settings","⚙️ Налаштування"]].map(([v,l])=>(
          <button key={v} className={`nav-btn ${view===v?"active":""}`} onClick={()=>safeSetView(v)}>{l}</button>
        ))}
      </nav>

      {view==="feed" && (
        <div className="feed-layout">
          <FiltersBar filters={filters} setFilters={setFilters} products={allProducts}/>
          <div className="feed-main">
            <div className="feed-toolbar">
              <div className="feed-toolbar-left">
                <SortDropdown value={sortOrder} onChange={setSortOrder} />
                <div style={{width:"0.5px",height:18,background:"var(--color-border-secondary)"}}/>
                <button className="btn-sm" onClick={selectAll}>Вибрати всі</button>
                <button className="btn-sm" onClick={clearSel}>Скинути</button>
                <span className="sel-count">{selected.size>0?`Вибрано: ${selected.size}`:`${filtered.length} товарів`}</span>
                {(() => {
                  const activeTags = [
                    ...(filters.source||[]).map(v=>({key:"source",val:v})),
                    ...(filters.supplier||[]).map(v=>({key:"supplier",val:v})),
                    ...(filters.brand||[]).map(v=>({key:"brand",val:v})),
                    ...(filters.category||[]).map(v=>({key:"category",val:v})),
                    ...(filters.color||[]).map(v=>({key:"color",val:v})),
                    ...(filters.size||[]).map(v=>({key:"size",val:v})),
                    ...(filters.gender||[]).map(v=>({key:"gender",val:v})),
                    ...(filters.priceMin?[{key:"priceMin",val:`від ${filters.priceMin}`}]:[]),
                    ...(filters.priceMax?[{key:"priceMax",val:`до ${filters.priceMax}`}]:[]),
                    ...(filters.dateFrom?[{key:"dateFrom",val:`з ${filters.dateFrom}`}]:[]),
                    ...(filters.dateTo?[{key:"dateTo",val:`до ${filters.dateTo}`}]:[]),
                    ...(filters.search?[{key:"search",val:filters.search}]:[]),
                  ];
                  return activeTags.length > 0 ? (
                    <div style={{display:"flex",gap:4,flexWrap:"wrap",alignItems:"center"}}>
                      {activeTags.map(({key,val})=>(
                        <span key={key+val} className="filter-tag" onClick={()=>{
                          const arr = ["source","supplier","brand","category","color","size","gender"];
                          if(arr.includes(key)) setFilters(f=>({...f,[key]:(f[key]||[]).filter(v=>v!==val)}));
                          else setFilters(f=>({...f,[key]:""}));
                        }}>
                          {filterDisplayValue(key, val)} ✕
                        </span>
                      ))}
                    </div>
                  ) : null;
                })()}
              </div>
              <div className="feed-toolbar-right">
                {!filters.showPublished && <button className="btn-add" onClick={()=>setShowAdd(true)}>+ Додати товар</button>}
                {filters.showPublished
                  ? <button className="btn-publish" style={{background:"#c0392b"}} disabled={selected.size===0} onClick={()=>{ clearPublished([...selected].map(id=>makeKey(allProducts.find(p=>p.id===id)))); setSelected(new Set()); setPubV(v=>v+1); setToast(`✓ Скинуто публікацію для ${selected.size} товарів`); }}>
                      Скинути публікації {selected.size>0?`(${selected.size})`:""} →
                    </button>
                  : <button className="btn-publish" disabled={selected.size===0||activeCount===0} onClick={handlePublish}>
                      Публікувати {selected.size>0?`(${selected.size})`:""} →
                    </button>
                }
              </div>
            </div>
            {activeCount===0&&<div className="info-box mb12">⚠️ Жоден маркетплейс не увімкнений. <button className="link-btn" onClick={()=>setView("markets")}>Перейти →</button></div>}
            {filtered.length===0
              ? <div className="empty-state">
                  {filters.showPublished
                    ? <>📂 Ще нічого не опубліковано.<br/><span style={{fontSize:13,color:"var(--color-text-secondary)"}}>Поверніться до стрічки, оберіть товари та натисніть "Публікувати"</span></>
                    : <>📦 Нових товарів немає.<br/><span style={{fontSize:13,color:"var(--color-text-secondary)"}}>Всі товари вже опубліковані або </span><button className="link-btn" onClick={()=>setView("sources")}>додайте нові джерела →</button></>
                  }
                </div>
              : <div className="feed-grid">{sorted.map(p=><ProductCard key={p.id} product={p} selected={selected.has(p.id)} onSelect={toggleSelect} published={isPublished(p)} onDelete={handleDelete} onView={setViewProduct} archived={p.archived}/>)}</div>
            }
          </div>
        </div>
      )}

      {view==="sources" && <SourcesView serverOnline={serverOnline} onProductsLoaded={()=>setPubV(v=>v+1)} onChannelToggle={()=>{ setDisabledChannels(JSON.parse(localStorage.getItem("mp_disabled_channels")||"[]")); }} onDirtyChange={(val)=>{ setSourceDirty(val); }}/>}
      {view==="duplicates" && <DuplicatesView allProducts={allProducts} onRefresh={()=>setPubV(v=>v+1)}/>}

      {view==="markets" && (
        <div className="card">
          <h2>🛒 Маркетплейси</h2>
          <p className="hint">Увімкни потрібні — налаштування зберігаються автоматично.</p>
          <div className="market-list">
            {MARKETPLACES.map(m=>(
              <div key={m.id} className={`market-item ${enabled[m.id]&&!m.disabled?"market-on":""} ${m.disabled?"market-disabled":""}`} style={{borderColor:enabled[m.id]&&!m.disabled?m.color:"#e5e5e5"}}>
                <div className="market-top">
                  <div className="toggle" style={{background:enabled[m.id]&&!m.disabled?m.color:"#ccc"}}
                    onClick={()=>{if(!m.disabled){const n={...enabled,[m.id]:!enabled[m.id]};setEnabled(n);saveEnabledMkts(n);}}}>
                    <div className="toggle-knob" style={{left:enabled[m.id]&&!m.disabled?23:3}}/>
                  </div>
                  <img src={m.logo} alt={m.name} className="source-logo" style={{verticalAlign:"middle",marginRight:6}} onError={e=>e.target.style.display="none"}/>
                  <a href={m.link} target="_blank" rel="noreferrer" className="market-name" style={{textDecoration:"none",color:"inherit"}}>{m.name}</a>
                  <span className="market-method">{m.method}</span>
                </div>
                {m.photoReq&&!m.disabled&&<p className="photo-req">📸 {m.photoReq}</p>}
                {m.disabled&&<p className="market-note">Публічного API немає. Тільки запрошені партнери.</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {view==="result" && (
        <div className="card">
          <h2>📦 Результат публікації</h2>
          {generated.length===0
            ? <div className="empty-state">Ще нічого не публікувалось.<br/>Поверніться до стрічки та оберіть товари.</div>
            : <>
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

      {view==="settings" && <SettingsView serverOnline={serverOnline} onReset={()=>setPubV(v=>v+1)}/>}
      {view==="archive" && <ArchiveView serverOnline={serverOnline} onSave={()=>setPubV(v=>v+1)} keywordCounts={archiveKeywordCounts}/>}

      {showAdd && <AddProductModal onClose={()=>setShowAdd(false)} onAdd={handleAdd} serverOnline={serverOnline}/>}
      {viewProduct && (()=>{
        const idx = sorted.findIndex(p => p.id === viewProduct.id);
        return <ProductViewModal
          product={viewProduct}
          onClose={()=>setViewProduct(null)}
          onDelete={handleDelete}
          onPublish={handlePublishOne}
          published={isPublished(viewProduct)}
          onArchive={handleArchive}
          archived={viewProduct.archived}
          hasPrev={idx > 0}
          hasNext={idx < sorted.length - 1}
          onPrev={()=>{ if(idx > 0) setViewProduct(sorted[idx-1]); }}
          onNext={()=>{ if(idx < sorted.length-1) setViewProduct(sorted[idx+1]); }}
        />;
      })()}
    </div>
  );
}
