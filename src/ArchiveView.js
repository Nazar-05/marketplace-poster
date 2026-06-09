import { useState, useEffect, useMemo } from "react";

const SERVER = "http://localhost:5001";

function loadArchiveKeywords() {
  return fetch(`${SERVER}/archive-keywords`)
    .then(r => r.json())
    .catch(() => fetch("/archive_keywords.json").then(r => r.json()).catch(() => ({})))
    .then(data => (data && typeof data === "object" && !Array.isArray(data)) ? data : {});
}

export default function ArchiveView({ serverOnline, onSave, keywordCounts = {} }) {
  const [keywordsDict, setKeywordsDict] = useState({});
  const [originalKeywordsDict, setOriginalKeywordsDict] = useState({});
  const [telegramChannels, setTelegramChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Per-channel paste inputs: { channelId: "text" }
  const [pasteInputs, setPasteInputs] = useState({});
  // Per-channel: show paste area?
  const [showPaste, setShowPaste] = useState({});

  useEffect(() => {
    if (!serverOnline) {
      setLoading(false);
      return;
    }

    Promise.all([
      loadArchiveKeywords(),
      fetch(`${SERVER}/synced-products`).then(r => r.json()).catch(() => [])
    ])
      .then(([keywordsData, productsData]) => {
        const cleanedKeywords = keywordsData && typeof keywordsData === "object" && !Array.isArray(keywordsData) ? keywordsData : {};
        setKeywordsDict(cleanedKeywords);
        setOriginalKeywordsDict(JSON.parse(JSON.stringify(cleanedKeywords)));

        const channelsMap = new Map();
        productsData.forEach(p => {
          if (p.source === "telegram" && p.supplier) {
            const title = p.supplier_title || p.supplier;
            channelsMap.set(p.supplier, title);
          }
        });

        const channelsList = Array.from(channelsMap.entries())
          .map(([id, title]) => ({ id, title }))
          .sort((a, b) => a.title.localeCompare(b.title));

        setTelegramChannels(channelsList);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [serverOnline]);

  const isDirty = useMemo(() => {
    return JSON.stringify(keywordsDict) !== JSON.stringify(originalKeywordsDict);
  }, [keywordsDict, originalKeywordsDict]);

  const totalKeywords = useMemo(() => {
    return Object.values(keywordsDict).reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0);
  }, [keywordsDict]);

  const filteredChannels = useMemo(() => {
    return telegramChannels.filter(ch => {
      const q = searchQuery.toLowerCase();
      return ch.title.toLowerCase().includes(q) || ch.id.toLowerCase().includes(q);
    });
  }, [telegramChannels, searchQuery]);

  // Add a keyword (can be multiline — stored as single filter entry)
  const addKeyword = (channelId, kw) => {
    const normalized = kw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalized.split("\n").map(l => l.trim()).filter(l => l.length > 0);
    const cleanKw = lines.join("\n");
    if (!cleanKw) return;

    setKeywordsDict(prev => {
      const current = prev[channelId] || [];
      if (current.includes(cleanKw)) return prev;
      return { ...prev, [channelId]: [...current, cleanKw] };
    });

    setPasteInputs(prev => ({ ...prev, [channelId]: "" }));
    setShowPaste(prev => ({ ...prev, [channelId]: false }));
  };

  const removeKeyword = (channelId, kwIndex) => {
    setKeywordsDict(prev => {
      const current = prev[channelId] || [];
      const updated = current.filter((_, idx) => idx !== kwIndex);
      const next = { ...prev };
      if (updated.length === 0) {
        delete next[channelId];
      } else {
        next[channelId] = updated;
      }
      return next;
    });
  };

  // Save rules to server
  const handleSave = async () => {
    if (!serverOnline) {
      alert("Сервер не запущено. Запусти: python scripts/server.py");
      return;
    }
    setSaving(true);
    try {
      await fetch(`${SERVER}/archive-keywords`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keywords: keywordsDict })
      });
      setOriginalKeywordsDict(JSON.parse(JSON.stringify(keywordsDict)));
      onSave?.();
      alert("✓ Ключові слова збережено успішно!");
    } catch {
      alert("Помилка збереження");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (window.confirm("Скинути всі незбережені зміни?")) {
      setKeywordsDict(JSON.parse(JSON.stringify(originalKeywordsDict)));
      setPasteInputs({});
      setShowPaste({});
    }
  };

  const handleApplyRules = async () => {
    if (!serverOnline) {
      alert("Сервер не запущено.");
      return;
    }
    if (isDirty) {
      if (!window.confirm("У вас є незбережені зміни. Бажаєте спочатку зберегти їх та запустити архівацію?")) {
        return;
      }
      setSaving(true);
      try {
        await fetch(`${SERVER}/archive-keywords`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keywords: keywordsDict })
        });
        setOriginalKeywordsDict(JSON.parse(JSON.stringify(keywordsDict)));
        onSave?.();
      } catch {
        alert("Помилка збереження правил перед запуском");
        setSaving(false);
        return;
      } finally {
        setSaving(false);
      }
    }

    setApplying(true);
    try {
      const res = await fetch(`${SERVER}/apply-archive-rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      const data = await res.json();
      onSave?.();
      alert(`✓ Архівацію завершено! Переміщено в архів: ${data.archived_count || 0} товарів.`);
    } catch {
      alert("Помилка при виконанні архівації");
    } finally {
      setApplying(false);
    }
  };

  if (loading) {
    return (
      <div className="card" style={{ display: "flex", justifyContent: "center", padding: "80px 20px" }}>
        <div style={{ textAlign: "center" }}>
          <div className="empty-state">⏳ Завантаження налаштувань архіву...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="archive-view">
      {/* Header */}
      <div className="archive-header-card card">
        <div className="archive-header-left">
          <h2>📦 Автоматичне архівування</h2>
          <p className="hint" style={{ margin: "4px 0 0" }}>
            Налаштуйте фільтри для Telegram-каналів. Пости, що містять ці слова, автоматично потрапляють в архів при синхронізації.
          </p>
        </div>
        <div className="archive-header-actions">
          <button className="btn-secondary" onClick={handleReset} disabled={!isDirty || saving || applying}>
            ↩️ Скинути
          </button>
          <button className="btn-primary" onClick={handleSave} disabled={!isDirty || !serverOnline || saving || applying}>
            {saving ? "⏳ Збереження..." : "💾 Зберегти зміни"}
          </button>
          <button
            className="btn-sync"
            style={{ padding: "11px 20px", display: "inline-flex", alignItems: "center", gap: 6 }}
            onClick={handleApplyRules}
            disabled={!serverOnline || saving || applying}
          >
            {applying ? "⏳ Обробка..." : "⚡ Застосувати до наявних"}
          </button>
        </div>
      </div>

      {/* Widgets */}
      <div className="archive-widgets">
        <div className="archive-widget-card card">
          <div className="widget-label">Усього каналів</div>
          <div className="widget-value">{telegramChannels.length}</div>
        </div>
        <div className="archive-widget-card card">
          <div className="widget-label">Активних фільтрів</div>
          <div className="widget-value">{totalKeywords}</div>
        </div>
        <div className="archive-widget-card card">
          <div className="widget-label">Статус сервера</div>
          <div className={`server-status-pill ${serverOnline ? "online" : "offline"}`}>
            {serverOnline ? "● Онлайн" : "○ Офлайн"}
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="archive-search-container">
        <input
          className="filter-input search-input-large"
          placeholder="🔍 Пошук каналу за назвою або лінком..."
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Channels */}
      {telegramChannels.length === 0 ? (
        <div className="card empty-state">
          ℹ️ Немає Telegram-каналів. Спершу синхронізуйте дані з Telegram у вкладці "🔌 Джерела".
        </div>
      ) : filteredChannels.length === 0 ? (
        <div className="card empty-state">
          🔍 Не знайдено каналів, що відповідають запиту "{searchQuery}".
        </div>
      ) : (
        <div className="archive-grid">
          {filteredChannels.map(channel => {
            const keywords = keywordsDict[channel.id] || [];
            const pasteVal = pasteInputs[channel.id] || "";
            const isPasteOpen = showPaste[channel.id] || false;

            return (
              <div key={channel.id} className="archive-channel-card card">

                {/* Header */}
                <div className="archive-card-header">
                  <div className="channel-info-group">
                    <img
                      src="https://www.google.com/s2/favicons?domain=telegram.org&sz=64"
                      alt=""
                      className="channel-icon-mini"
                    />
                    <span className="channel-title-text">{channel.title}</span>
                    <span className="channel-id-sub">{channel.id}</span>
                  </div>
                  <div className="channel-badge-group">
                    {keywords.length > 0 && (
                      <span className="keyword-count-badge">{keywords.length}</span>
                    )}
                  </div>
                </div>

                {/* Existing filters list */}
                <div className="keyword-chips-container">
                  {keywords.length === 0 ? (
                    <div className="chips-empty-hint">Архівування вимкнене — додайте фільтр нижче.</div>
                  ) : (
                    keywords.map((kw, kwIdx) => {
                      const isMultiline = kw.includes("\n");
                      const firstLine = kw.split("\n")[0];
                      const displayKw = isMultiline ? firstLine + " …" : kw;
                      return (
                        <span
                          key={kwIdx}
                          className="keyword-chip-pill"
                          title={isMultiline ? kw : kw}
                          style={{ maxWidth: "100%", whiteSpace: "normal", wordBreak: "break-word" }}
                        >
                          <span className="chip-text" style={{ maxWidth: "none", whiteSpace: "normal" }}>
                            {displayKw}
                          </span>
                          {(keywordCounts?.[channel.id]?.[kw] !== undefined) && (
                            <span style={{
                              display: "inline-flex", alignItems: "center", justifyContent: "center",
                              minWidth: 18, height: 18, padding: "0 5px", borderRadius: 999,
                              background: keywordCounts[channel.id][kw] > 0 ? "#4f46e5" : "#e5e7eb",
                              color: keywordCounts[channel.id][kw] > 0 ? "#fff" : "#9ca3af",
                              fontSize: 10, fontWeight: 700, marginLeft: 4, flexShrink: 0,
                            }}>
                              {keywordCounts[channel.id][kw]}
                            </span>
                          )}
                          <button
                            className="chip-delete-btn"
                            onClick={() => removeKeyword(channel.id, kwIdx)}
                            aria-label={`Видалити фільтр`}
                          >
                            ✕
                          </button>
                        </span>
                      );
                    })
                  )}
                </div>

                {/* Paste area */}
                {isPasteOpen ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{
                      fontSize: 11,
                      color: "#6b7280",
                      background: "#f0fdf4",
                      border: "1px solid #bbf7d0",
                      borderRadius: 8,
                      padding: "8px 12px",
                      lineHeight: 1.5
                    }}>
                      📋 <strong>Вставте текст посту</strong> — весь блок збережеться як <strong>1 фільтр</strong>.<br/>
                      Пости, що містять усі ці рядки, будуть автоматично архівуватись.
                    </div>
                    <textarea
                      className="textarea"
                      rows={5}
                      autoFocus
                      value={pasteVal}
                      onChange={e => setPasteInputs(prev => ({ ...prev, [channel.id]: e.target.value }))}
                      placeholder={"Вставте текст посту тут...\n\nНаприклад:\n🔷 Замовляйте на нашому сайті GV-TOP.shop\nабо через бот натиснувши \"Замовити\"\n👩 t.me/girlgvshop Наш жіночий дроп 👩"}
                      style={{ fontSize: 12, resize: "vertical", fontFamily: "inherit" }}
                    />
                    <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                      <button
                        className="btn-sm"
                        onClick={() => {
                          setShowPaste(prev => ({ ...prev, [channel.id]: false }));
                          setPasteInputs(prev => ({ ...prev, [channel.id]: "" }));
                        }}
                      >
                        Скасувати
                      </button>
                      <button
                        className="btn-primary"
                        style={{ padding: "7px 16px", fontSize: 13 }}
                        onClick={() => addKeyword(channel.id, pasteVal)}
                        disabled={!pasteVal.trim()}
                      >
                        ✓ Додати як 1 фільтр
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowPaste(prev => ({ ...prev, [channel.id]: true }))}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      width: "100%",
                      padding: "10px 16px",
                      border: "2px dashed #c7d2fe",
                      borderRadius: 10,
                      background: "#f5f3ff",
                      color: "#4f46e5",
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "all 0.15s"
                    }}
                    onMouseOver={e => e.currentTarget.style.background = "#ede9fe"}
                    onMouseOut={e => e.currentTarget.style.background = "#f5f3ff"}
                  >
                    📋 Вставити текст посту як фільтр
                  </button>
                )}

              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
