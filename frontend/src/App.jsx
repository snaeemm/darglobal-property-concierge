import { createContext, useContext, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { T } from "./i18n.js";

const PreviewCtx = createContext(() => {});
const LangCtx = createContext(T.en);
const useT = () => useContext(LangCtx);
const isKnown = (u) => /darglobal\.co\.uk|wasalt\.sa/.test(u || "");
const SLIDE_IMGS = ["/hero.webp", "/aida.webp", "/golf.webp", "/lobby.webp"];

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

function CountUp({ value, suffix = "" }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (value == null) return;
    const start = performance.now(), dur = 1600;
    let raf;
    const tick = (t) => {
      const p = Math.min(1, (t - start) / dur);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    const id = setTimeout(() => (raf = requestAnimationFrame(tick)), 1500);
    return () => { clearTimeout(id); cancelAnimationFrame(raf); };
  }, [value]);
  return <>{n.toLocaleString("en-US")}{suffix}</>;
}

function HeroSlides() {
  const t = useT();
  const [i, setI] = useState(0);
  useEffect(() => { const id = setInterval(() => setI((x) => (x + 1) % SLIDE_IMGS.length), 7000); return () => clearInterval(id); }, []);
  return (
    <>
      {SLIDE_IMGS.map((img, k) => (
        <div key={img} className={"hero-img" + (k === i ? " on" : "")} style={{ backgroundImage: `url(${img})` }} />
      ))}
      <div className="caption" key={i + t.eyebrow}>
        <span className="caption-line" />
        <span>{t.slides[i].name}</span><em>{t.slides[i].place}</em>
      </div>
      <div className="dots">{SLIDE_IMGS.map((_, k) => <i key={k} className={k === i ? "on" : ""} />)}</div>
    </>
  );
}

const fmt = (n) => (n == null ? "" : "SAR " + Math.round(n).toLocaleString("en-US"));

function SmartLink({ href, children, className, style }) {
  const open = useContext(PreviewCtx);
  return (
    <a href={href} className={className} style={style} target="_blank" rel="noreferrer"
      onClick={(e) => { if (isKnown(href) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); open(href); } }}>
      {children}
    </a>
  );
}

function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <SmartLink href={href}>{children}</SmartLink> }}>
      {children}
    </ReactMarkdown>
  );
}

function ListingCard({ l, i }) {
  const t = useT();
  return (
    <SmartLink className="card" style={{ "--i": i }} href={l.url}>
      <div className="card-top">
        <span className="pill">{l.purpose === "rent" ? t.forRent : t.forSale}</span>
        <span className="card-type">{l.type}</span>
      </div>
      <div className="card-price" dir="ltr">{fmt(l.price_sar)}{l.rent_frequency ? <small> / {l.rent_frequency}</small> : null}</div>
      <div className="card-loc">{[l.district, l.city].filter(Boolean).join(", ")}</div>
      <div className="card-facts">
        {l.bedrooms != null && <span>{l.bedrooms} {t.bd}</span>}
        {l.bathrooms != null && <span>{l.bathrooms} {t.ba}</span>}
        {l.area_sqm && <span>{Math.round(l.area_sqm)} m²</span>}
      </div>
      {l.valuation_low && (
        <div className="card-val">{t.estimate} {fmt(l.valuation_low)} {t.to} {fmt(l.valuation_high)}</div>
      )}
      <div className="card-cta">{t.viewDetails} <span>↗</span></div>
    </SmartLink>
  );
}

function Assistant({ m, onAsk }) {
  const t = useT();
  return (
    <div className="msg bot">
      <div className={"avatar" + (m.pending ? " thinking" : "")}><img src="/globe.webp" alt="" /></div>
      <div className="bot-body">
        {m.steps?.length > 0 && (
          <div className="steps">
            {m.steps.map((s, i) => (
              <div key={i} className={"step" + (i === m.steps.length - 1 && m.pending && !m.text ? " live" : " done")}>
                <span className="dot" /> <span className="step-text">{t.steps[s.tool] || s.text}</span>
                {s.args?.query && <em> "{s.args.query}"</em>}
                {s.args?.city && <em> {s.args.city}</em>}
              </div>
            ))}
          </div>
        )}
        {m.pending && !m.text && !m.steps?.length && <div className="typing"><i /><i /><i /></div>}
        {m.text && <div className={"md" + (m.pending ? " streaming" : "")} dir="auto"><Markdown>{m.text}</Markdown></div>}
        {m.listings?.length > 0 && (
          <div className="cards">{m.listings.map((l, i) => <ListingCard key={l.id} l={l} i={i} />)}</div>
        )}
        {m.sources?.length > 0 && (
          <div className="sources"><span className="sources-label">{t.sources}</span>
            {m.sources.map((s) => (
              <SmartLink key={s.url} href={s.url} className={"src " + s.source}>
                <b>{s.source === "darglobal" ? t.tags.DarGlobal : t.tags.Wasalt}</b> {s.title}
              </SmartLink>
            ))}
          </div>
        )}
        {m.followups?.length > 0 && !m.pending && onAsk && (
          <div className="followups">
            {m.followups.map((f, i) => (
              <button key={f} style={{ "--i": i }} onClick={() => onAsk(f)} dir="auto">{f}<span>→</span></button>
            ))}
          </div>
        )}
        {m.error && <div className="err">{m.error}</div>}
      </div>
    </div>
  );
}

function Preview({ url, onClose }) {
  const t = useT();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  const isDG = /darglobal\.co\.uk/.test(url);
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    fetch("/api/page?url=" + encodeURIComponent(url)).then((r) => (r.ok ? r.json() : Promise.reject())).then(setData).catch(() => setErr(true));
    return () => window.removeEventListener("keydown", k);
  }, [url]);
  const host = isDG ? "darglobal.co.uk" : "wasalt.sa";
  const l = data?.kind === "listing" ? data : null;
  return (
    <div className="drawer-wrap" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div className="drawer-title">
            <span className={"tag " + (isDG ? "darglobal" : "wasalt")}>{isDG ? t.tags.DarGlobal : t.tags.Wasalt}</span>
            <strong dir="auto">{data?.title || host}</strong>
            <small dir="ltr">{url.replace(/^https?:\/\//, "")}</small>
          </div>
          <div className="drawer-actions">
            <a className="ghost" href={url} target="_blank" rel="noreferrer">{t.openOn} {host} ↗</a>
            <button className="x" onClick={onClose} aria-label={t.close}>×</button>
          </div>
        </header>
        <div className="drawer-body">
          {l ? (
            <div className="listing-detail">
              <div className="ld-price" dir="ltr">SAR {Math.round(l.price_sar).toLocaleString("en-US")}{l.rent_frequency ? <small> / {l.rent_frequency}</small> : null}</div>
              <div className="ld-loc">{l.type} · {[l.district, l.city].filter(Boolean).join(", ")}</div>
              <div className="ld-grid">
                {[["Bedrooms", l.bedrooms], ["Bathrooms", l.bathrooms], ["Area", l.area_sqm && Math.round(l.area_sqm) + " m²"], ["Furnishing", l.furnishing], ["Purpose", l.purpose === "rent" ? t.forRent : t.forSale], ["Listed", l.published]]
                  .filter(([, v]) => v != null && v !== "").map(([k, v]) => <div key={k}><span>{t.ld[k]}</span><b>{v}</b></div>)}
              </div>
              {l.valuation_low && (
                <div className="ld-val">
                  <span>{t.valuation}</span>
                  <div className="ld-bar" dir="ltr"><i style={{ left: `${Math.max(0, Math.min(100, ((l.price_sar - l.valuation_low * 0.8) / (l.valuation_high * 1.2 - l.valuation_low * 0.8)) * 100))}%` }} /></div>
                  <div className="ld-range" dir="ltr"><em>SAR {l.valuation_low.toLocaleString("en-US")}</em><em>SAR {l.valuation_high.toLocaleString("en-US")}</em></div>
                  <p>{l.price_sar > l.valuation_high ? t.above : l.price_sar < l.valuation_low ? t.below : t.within}</p>
                </div>
              )}
              {Object.keys(l.extra || {}).length > 0 && (
                <div className="ld-extra">{Object.entries(l.extra).slice(0, 12).map(([k, v]) => <div key={k}><span>{k}</span><b dir="auto">{String(v)}</b></div>)}</div>
              )}
              {l.description && <div className="ld-desc" dir="auto">{l.description}</div>}
              {l.lat && <a className="ghost" href={`https://www.google.com/maps?q=${l.lat},${l.lon}`} target="_blank" rel="noreferrer">{t.map} ↗</a>}
            </div>
          ) : data ? (
            <div className="page-sum" dir="auto">
              <p className="eyebrow">{data.section}</p>
              <h3>{data.title}</h3>
              {data.text.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
            </div>
          ) : err ? (
            <div className="page-sum"><p className="muted">{t.noPreview}</p><a className="ghost" href={url} target="_blank" rel="noreferrer">{t.openOn} {host} ↗</a></div>
          ) : (
            <div className="frame-loading"><span className="spin" /> {t.loading}</div>
          )}
        </div>
      </aside>
    </div>
  );
}

function About({ onClose, stats }) {
  const t = useT();
  const s = { pages: stats?.darglobal_pages ?? 116, index: (stats?.wasalt_index_listings ?? 60000).toLocaleString("en-US") };
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label={t.close}>×</button>
        <p className="eyebrow">{t.how}</p>
        <h2>{t.aboutTitle}</h2>
        <ol className="how stagger">
          {t.aboutSteps.map(([title, body]) => <li key={title}><b>{title}</b> {body(s)}</li>)}
        </ol>
        <p className="muted">{t.limits}</p>
      </div>
    </div>
  );
}

export default function App() {
  const [lang, setLang] = useState(() => (store.get("lang") === "ar" ? "ar" : "en"));
  const t = T[lang];
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);
  const [about, setAbout] = useState(false);
  const [intro, setIntro] = useState(true);
  const [preview, setPreview] = useState(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { const id = setTimeout(() => setIntro(false), 2300); return () => clearTimeout(id); }, []);
  useEffect(() => { fetch("/api/stats").then((r) => r.json()).then(setStats).catch(() => {}); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages]);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.title = lang === "ar" ? "دار جلوبال | مستشار العقارات" : "DarGlobal | Property Concierge";
    store.set("lang", lang);
  }, [lang]);

  const spot = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
    e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
  };
  const patchLast = (fn) => setMessages((ms) => { const c = [...ms]; c[c.length - 1] = fn({ ...c[c.length - 1] }); return c; });
  const toggleLang = () => setLang((l) => (l === "ar" ? "en" : "ar"));

  async function send(text) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    const history = [...messages.filter((m) => m.text).map((m) => ({ role: m.role, content: m.text })), { role: "user", content: q }];
    setMessages((ms) => [...ms, { role: "user", text: q }, { role: "assistant", text: "", steps: [], pending: true }]);
    setBusy(true);
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history }) });
      if (!res.ok) throw new Error(res.status === 429 ? t.busy429 : t.waking);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop();
        for (const p of parts) {
          if (!p.startsWith("data:")) continue;
          const ev = JSON.parse(p.slice(5));
          if (ev.type === "token") patchLast((m) => ({ ...m, text: m.text + ev.text }));
          else if (ev.type === "status") patchLast((m) => ({ ...m, steps: [...m.steps, ev] }));
          else if (ev.type === "listings") patchLast((m) => ({ ...m, listings: [...(m.listings || []), ...ev.items].slice(0, 10) }));
          else if (ev.type === "sources") patchLast((m) => ({ ...m, sources: ev.items }));
          else if (ev.type === "followups") patchLast((m) => ({ ...m, followups: ev.items }));
          else if (ev.type === "error") patchLast((m) => ({ ...m, error: ev.text }));
        }
      }
    } catch (e) {
      patchLast((m) => ({ ...m, error: e.message }));
    } finally {
      patchLast((m) => ({ ...m, pending: false }));
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  const LangSwitch = ({ className = "" }) => (
    <button className={"lang " + className} onClick={toggleLang} aria-label="Switch language">
      <span className={lang === "en" ? "on" : ""}>EN</span><i /><span className={lang === "ar" ? "on" : ""}>عربي</span>
    </button>
  );

  return (
    <LangCtx.Provider value={t}>
    <PreviewCtx.Provider value={setPreview}>
    <div className={"shell" + (intro ? " is-intro" : " is-ready") + (lang === "ar" ? " rtl" : "")}>
      <div className={"intro" + (intro ? "" : " gone")} aria-hidden>
        <img src="/logo.webp" alt="" />
        <span className="intro-line" />
        <p>{t.eyebrow}</p>
      </div>
      <aside className="hero">
        <HeroSlides />
        <div className="hero-inner">
          <img className="logo" src="/logo.webp" alt="DarGlobal" />
          <div key={lang}>
            <p className="eyebrow">{t.eyebrow}</p>
            <h1>
              {t.headline.map((w, k) => (
                <span className="reveal" key={w} style={{ "--i": k }}><span>{w}</span></span>
              ))}
            </h1>
            <p className="lede">{t.lede}</p>
          </div>
          <div className="stats">
            <div><b><CountUp value={stats?.darglobal_pages} /></b><span>{t.stats[0]}</span></div>
            <div><b><CountUp value={stats ? Math.round(stats.wasalt_index_listings / 1000) : null} suffix="K" /></b><span>{t.stats[1]}</span></div>
            <div><b><CountUp value={stats?.wasalt_detailed_listings} /></b><span>{t.stats[2]}</span></div>
          </div>
          <button className="link" onClick={() => setAbout(true)}>{t.how} {lang === "ar" ? "←" : "→"}</button>
        </div>
      </aside>

      <main className="chat" onMouseMove={spot}>
        <header className="topbar">
          <img src="/logo.webp" alt="DarGlobal" />
          <div className="topbar-right">
            <LangSwitch />
            <button className="link" onClick={() => setAbout(true)}>{t.how}</button>
          </div>
        </header>
        <LangSwitch className="floating" />

        <div className={"progress" + (busy ? " on" : "")} />
        <div className="scroll">
          {messages.length === 0 ? (
            <div className="welcome" key={lang}>
              <p className="eyebrow">{t.welcome}</p>
              <h2>{t.welcomeTitle}</h2>
              <p className="muted">{t.welcomeSub}</p>
              <div className="suggest">
                {t.suggestions.map((s, i) => (
                  <button key={s.text} style={{ "--i": i }} onClick={() => send(s.text)}>
                    <span className={"tag " + s.tag.toLowerCase()}>{t.tags[s.tag]}</span>
                    {s.text}
                    <span className="arrow">{lang === "ar" ? "←" : "→"}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread">
              {messages.map((m, i) => m.role === "user"
                ? <div key={i} className="msg user"><div className="bubble" dir="auto">{m.text}</div></div>
                : <Assistant key={i} m={m} onAsk={i === messages.length - 1 ? send : null} />)}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <form className={"composer" + (busy ? " busy" : "")} onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} placeholder={t.placeholder} maxLength={1000} autoFocus dir="auto" />
          <button type="submit" disabled={busy || !input.trim()} aria-label="Send">
            {busy ? <span className="spin" /> : <svg viewBox="0 0 24 24" width="18" height="18" style={lang === "ar" ? { transform: "scaleX(-1)" } : undefined}><path d="M4 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="1.6" fill="none" /></svg>}
          </button>
        </form>
        <p className="foot">{t.foot}</p>
      </main>
      {about && <About onClose={() => setAbout(false)} stats={stats} />}
      {preview && <Preview key={preview} url={preview} onClose={() => setPreview(null)} />}
    </div>
    </PreviewCtx.Provider>
    </LangCtx.Provider>
  );
}
