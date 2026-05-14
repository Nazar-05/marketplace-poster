import { useState } from "react";
import "./PhotoManager.css";

const SERVER = "http://localhost:5001";

/**
 * PhotoManager — компонент для управління фото товару.
 * photos: string[] — масив URL фото
 * onChange: (photos: string[]) => void
 * serverOnline: boolean
 */
export default function PhotoManager({ photos = [], onChange, serverOnline }) {
  const [addUrl, setAddUrl]     = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");

  // Перемістити фото вгору
  function moveUp(i) {
    if (i === 0) return;
    const arr = [...photos];
    [arr[i-1], arr[i]] = [arr[i], arr[i-1]];
    onChange(arr);
  }

  // Перемістити фото вниз
  function moveDown(i) {
    if (i === photos.length - 1) return;
    const arr = [...photos];
    [arr[i], arr[i+1]] = [arr[i+1], arr[i]];
    onChange(arr);
  }

  // Видалити фото
  function remove(i) {
    onChange(photos.filter((_,idx) => idx !== i));
  }

  // Додати по URL (скачати локально через сервер)
  async function addByUrl() {
    if (!addUrl.trim()) return;
    setLoading(true); setError("");
    try {
      if (serverOnline) {
        const res  = await fetch(`${SERVER}/download-photo`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:addUrl}) });
        const data = await res.json();
        if (data.error) { setError(data.error); }
        else { onChange([...photos, data.url]); setAddUrl(""); }
      } else {
        // Без сервера — просто додаємо URL напряму
        onChange([...photos, addUrl.trim()]);
        setAddUrl("");
      }
    } catch { setError("Помилка з'єднання з сервером"); }
    setLoading(false);
  }

  // Завантажити з комп'ютера (base64 preview + локальне збереження)
  function handleFileUpload(e) {
    const files = Array.from(e.target.files);
    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = () => onChange([...photos, reader.result]);
      reader.readAsDataURL(file);
    });
    e.target.value = "";
  }

  return (
    <div className="photo-manager">
      <div className="pm-label">
        Фото товару
        <span className="pm-count">{photos.length} / 10</span>
      </div>

      {/* Сітка фото */}
      {photos.length > 0 && (
        <div className="pm-grid">
          {photos.map((url, i) => (
            <div key={i} className={`pm-item ${i===0?"pm-main":""}`}>
              {i === 0 && <div className="pm-main-badge">Головне</div>}
              <img
                src={url}
                alt={`Фото ${i+1}`}
                className="pm-img"
                onError={e => { e.target.src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80'%3E%3Crect width='80' height='80' fill='%23f0f0f0'/%3E%3Ctext x='40' y='45' text-anchor='middle' fill='%23aaa' font-size='24'%3E📷%3C/text%3E%3C/svg%3E"; }}
              />
              <div className="pm-controls">
                <button className="pm-btn" onClick={()=>moveUp(i)}   disabled={i===0}              title="Вгору">↑</button>
                <button className="pm-btn" onClick={()=>moveDown(i)} disabled={i===photos.length-1} title="Вниз">↓</button>
                <button className="pm-btn pm-del" onClick={()=>remove(i)} title="Видалити">✕</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {photos.length === 0 && (
        <div className="pm-empty">Фото ще не додані</div>
      )}

      {/* Додати фото */}
      {photos.length < 10 && (
        <div className="pm-add">
          <div className="pm-add-row">
            <input
              className="pm-url-input"
              value={addUrl}
              onChange={e=>setAddUrl(e.target.value)}
              placeholder="Вставте посилання на фото..."
              onKeyDown={e=>e.key==="Enter"&&addByUrl()}
            />
            <button className="pm-add-btn" onClick={addByUrl} disabled={!addUrl||loading}>
              {loading ? "⏳" : "+ Додати"}
            </button>
          </div>
          <div className="pm-or">або</div>
          <label className="pm-upload-btn">
            📁 Завантажити з комп'ютера
            <input type="file" accept="image/*" multiple style={{display:"none"}} onChange={handleFileUpload}/>
          </label>
        </div>
      )}

      {error && <div className="pm-error">{error}</div>}

      <p className="pm-hint">Перше фото — головне на маркетплейсі. Стрілками змінюй порядок.</p>
    </div>
  );
}
