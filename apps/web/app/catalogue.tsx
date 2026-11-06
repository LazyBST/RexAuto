"use client";

import VisitorCounter from "./visitor-counter";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Hit = { id: string; part_no: string; variant_label: string; description: string | null; application: string | null; oem_name: string | null;
  category: string | null; segment: string | null; mrp: number | null; price_basis: string; image_url: string | null; brand: string };
type Facet = { value: string; label: string; n: number };
type Result = { total: number; hits: Hit[]; ms: number; facets: Record<string, Facet[]>; corrected_from?: string; query?: string };
const PAGE = 30, DEPTH = 300;
const FILTERS = ["brand", "make", "segment", "category", "min_price", "max_price"] as const;
type F = Partial<Record<(typeof FILTERS)[number], string>>;

const NAME = "Rex Auto";
const KIND = { make: "k-make", brand: "k-brand", category: "k-cat", segment: "k-seg" } as const;
const ROWS = [["make", "Vehicle"], ["segment", "Segment"], ["category", "Category"], ["brand", "Brand"]] as const;
const Lbl = ({ children }: { children: React.ReactNode }) => <span className="lbl">{children}</span>;

// Logos: name -> image URL, loaded once from /api/logos. A missing logo falls back to a monogram badge, so the list still reads.
type Logos = { makes: Record<string, string>; brands: Record<string, string>; categories: Record<string, string> };
const NO_LOGOS: Logos = { makes: {}, brands: {}, categories: {} };
const initials = (n: string) => n.split(/[\s&/-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
function Logo({ kind, name, logos, withName }: { kind: keyof Logos; name: string; logos: Logos; withName?: boolean }) {
  const url = logos[kind][name];
  return (
    <span className={"lg lg-" + kind + (withName ? " named" : "")} title={name}>
      {url ? <img src={url} alt={withName ? "" : name} loading="lazy" decoding="async" /> : <i className="mono" aria-hidden={withName || undefined}>{initials(name)}</i>}
      {withName && <span className="lgname">{name}</span>}
    </span>
  );
}
// Segment shown as a vehicle emoji in the lists: car, light truck, heavy truck, tractor, and a crane for "other" (construction / industrial)
const SEG_EMOJI: Record<string, string> = { CAR: "🚗", LCV: "🚚", HCV: "🚛", TRACTOR: "🚜", OTHER: "🏗️" };
const segEmoji = (s: string | null | undefined) => (s ? SEG_EMOJI[s.toUpperCase()] ?? "🚘" : "");
const makesOf = (oem: string | null) => (oem ? oem.split(" / ").map((s) => s.trim()).filter(Boolean) : []);

const inr = (n: number | null) => (n == null ? null : "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const basisText = (b: string) => (b === "ex_tax" ? " (excl. GST)" : b === "incl_tax" ? " (incl. GST)" : "");

export default function Catalogue() {
  const [cfg, setCfg] = useState({ whatsapp: "" });
  const [q, setQ] = useState("");
  const [f, setF] = useState<F>({});
  const [view, setView] = useState<"list" | "compact">("list");
  const [data, setData] = useState<Result | null>(null);
  const [home, setHome] = useState<Result | null>(null);
  const [open, setOpen] = useState<any>(null);
  const [panel, setPanel] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [toast, setToast] = useState("");
  const [logos, setLogos] = useState<Logos>(NO_LOGOS);
  const req = useRef(0);
  const sidRef = useRef("");
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingMore = useRef(false);
  const lastTracked = useRef("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const compact = mobile || view === "compact";
  useEffect(() => {
    const m = window.matchMedia("(max-width:820px)");
    const on = () => setMobile(m.matches);
    on(); m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);
  const hasQuery = !!q.trim() || Object.values(f).some(Boolean);

  // usage analytics: anonymous tab-session id + fire-and-forget events (see /api/track)
  const getSid = () => {
    if (sidRef.current) return sidRef.current;
    let s = "";
    try { s = sessionStorage.getItem("rx_sid") || ""; if (!s) { s = crypto.randomUUID(); sessionStorage.setItem("rx_sid", s); } }
    catch { s = Math.random().toString(36).slice(2) + Date.now().toString(36); }
    return (sidRef.current = s);
  };
  const track = (body: Record<string, unknown>) => {
    try {
      const payload = JSON.stringify({ sid: getSid(), ...body });
      if (navigator.sendBeacon) navigator.sendBeacon("/api/track", new Blob([payload], { type: "application/json" }));
      else fetch("/api/track", { method: "POST", body: payload, keepalive: true, headers: { "Content-Type": "application/json" } }).catch(() => {});
    } catch {}
  };

  // one "search" event per settled search (the user stopped typing / changing filters for 1.5 s), never per keystroke
  useEffect(() => {
    if (!data || !hasQuery) return;
    const key = JSON.stringify([q.trim().toLowerCase(), f]);
    const t = setTimeout(() => {
      if (lastTracked.current === key) return;
      lastTracked.current = key;
      track({ t: "search", q: q.trim(), f, total: data.total, ms: data.ms, corrected: !!data.corrected_from, top: data.hits.slice(0, 10).map((h) => h.id) });
    }, 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, q, f, hasQuery]);

  const run = useCallback(async (query: string, filters: F, offset = 0, append = false) => {
    const id = ++req.current;
    const p = new URLSearchParams({ q: query, limit: String(PAGE), offset: String(offset) });
    for (const [k, v] of Object.entries(filters)) if (v) p.set(k, v);
    const r = await fetch("/api/search?" + p);
    if (!r.ok) return;
    const d: Result = await r.json();
    if (id !== req.current) return;
    setData((prev) => (append && prev ? { ...d, hits: prev.hits.concat(d.hits) } : d));
  }, []);

  // infinite scroll: when the "Loading more…" marker nears the screen, fetch the next page (up to DEPTH results)
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !data || data.hits.length >= data.total || data.hits.length >= DEPTH) return;
    const io = new IntersectionObserver((es) => {
      if (es[0].isIntersecting && !loadingMore.current) {
        loadingMore.current = true;
        run(q, f, data.hits.length, true).finally(() => { loadingMore.current = false; });
      }
    }, { rootMargin: "700px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [data, q, f, run]);

  // first load: config, url state, home tiles
  useEffect(() => {
    fetch("/api/config").then((r) => r.json()).then((c) => { setCfg(c); }).catch(() => {});
    fetch("/api/search?limit=1").then((r) => r.json()).then(setHome).catch(() => {});
    fetch("/api/logos").then((r) => r.json()).then(setLogos).catch(() => {});
    const u = new URLSearchParams(location.search);
    const nf: F = {}; for (const k of FILTERS) if (u.get(k)) nf[k] = u.get(k)!;
    const nq = u.get("q") ?? "";
    setQ(nq); setF(nf);
    if (nq || Object.keys(nf).length) run(nq, nf);
    const m = location.hash.match(/^#p=([0-9a-f-]{36})$/);
    if (m) openProduct(m[1], "link");
    setView((localStorage.getItem("view") as any) === "compact" ? "compact" : "list");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sync = (query: string, filters: F) => {
    const u = new URLSearchParams(); if (query) u.set("q", query);
    for (const [k, v] of Object.entries(filters)) if (v) u.set(k, v);
    history.replaceState(null, "", u.toString() ? "?" + u : location.pathname);
  };
  const go = (query: string, filters: F) => { setQ(query); setF(filters); sync(query, filters); if (query.trim() || Object.values(filters).some(Boolean)) run(query, filters); else setData(null); };
  const onType = (v: string) => { setQ(v); clearTimeout(timer.current); timer.current = setTimeout(() => go(v, f), 180); };
  const toggle = (k: keyof F, v: string) => { go(q, { ...f, [k]: f[k] === v ? "" : v }); window.scrollTo({ top: 0 }); };
  const openProduct = async (id: string, src: "list" | "related" | "link" = "list") => {
    const r = await fetch("/api/product/" + id); if (!r.ok) return;
    setOpen(await r.json()); history.replaceState(null, "", location.search + "#p=" + id);
    track({ t: "view", id, src, q: q.trim() });
  };
  const close = () => { setOpen(null); history.replaceState(null, "", location.pathname + location.search); };
  const copy = (e: React.MouseEvent, s: string) => { e.stopPropagation(); navigator.clipboard?.writeText(s); setToast("Copied " + s); setTimeout(() => setToast(""), 1400); };
  const wa = (text: string) => `https://wa.me/${cfg.whatsapp}?text=${encodeURIComponent(text)}`;
  const askLink = (h: { brand: string; part_no: string; variant_label?: string; id: string }) =>
    wa(`Hi, is this available?\n${h.brand} ${h.part_no}${h.variant_label ? " (" + h.variant_label + ")" : ""}\n${typeof location !== "undefined" ? location.origin : ""}/#p=${h.id}`);

  const facets = data?.facets ?? home?.facets ?? {};
  // facet rows (choosing a filter) keep the name next to the logo; the result list below shows logos only
  const FACET_KIND: Record<string, keyof Logos | undefined> = { make: "makes", brand: "brands", category: "categories" };
  const facetLabel = (k: string, label: string) => (FACET_KIND[k] ? <Logo kind={FACET_KIND[k]!} name={label} logos={logos} withName /> : k === "segment" ? <>{segEmoji(label)} {label}</> : label);
  const chips = useMemo(() => Object.entries(f).filter(([, v]) => v), [f]);
  const activeN = chips.length;
  const countText = data ? <><b>{data.total.toLocaleString("en-IN")}</b> result{data.total === 1 ? "" : "s"} <small>· {data.ms} ms</small></> : "Searching…";

  return (
    <>
      <header><div className="bar">
        <div className="logo" onClick={() => go("", {})} aria-label={NAME}><span className="full">{NAME}</span><span className="short">RX</span></div>
        <div className="search">
          <input value={q} onChange={(e) => onType(e.target.value)} type="search" inputMode="search" autoComplete="off" autoCapitalize="off" spellCheck={false}
            placeholder="Part number, or vehicle + part (e.g. tata 1612 brake valve)" autoFocus />
          {q && <button className="x" style={{ display: "block" }} aria-label="Clear" onClick={() => go("", f)}>×</button>}
        </div>
        <button className={"mfilter" + (panel ? " open" : "") + (activeN ? " has" : "")} aria-label="Filters" aria-expanded={panel} onClick={() => setPanel(!panel)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M6 5l6 6 6-6M6 12l6 6 6-6" /></svg>
          {activeN > 0 && <i>{activeN}</i>}
        </button>
      </div>
      {panel && <div className="fpanel">{ROWS.map(([k, title]) => (
        <div key={k} className={"frow " + KIND[k]}><span className="flab">{title}</span><div className="fscroll">{(facets[k] ?? []).map((r) => (
          <button key={r.value} className={"fchip" + (f[k] === r.value ? " on" : "")} onClick={() => toggle(k, r.value)}>{facetLabel(k, r.label)}<small>{r.n}</small></button>))}</div></div>))}</div>}
      {hasQuery && <div className="countm">{countText}{data?.corrected_from && <> · for <b>{data.query}</b></>}</div>}
      </header>

      <main>
        {!hasQuery ? (
          <>
            <p className="hint">{home ? home.total.toLocaleString("en-IN") : "…"} parts · search by part number, or by vehicle and part.</p>
            <div className="examples">{["tata brake valve", "head lamp swift", "MB04015028", "oil filter", "brake lining ashok leyland", "clutch"].map((x) => (
              <button key={x} className="chipbtn" onClick={() => go(x, {})}>{x}</button>))}</div>
            {([["make", "Browse by vehicle"], ["category", "Browse by category"], ["brand", "Browse by brand"]] as const).map(([k, title]) => (
              <section key={k}><h2 className={KIND[k]}>{title}</h2><div className="tiles">{(home?.facets?.[k] ?? []).map((r) => (
                <button key={r.value} className={"tile " + KIND[k]} onClick={() => toggle(k, r.value)}><span>{facetLabel(k, r.label)}</span><small>{r.n.toLocaleString("en-IN")}</small></button>))}</div></section>))}
          </>
        ) : (
          <div className="layout">
            <aside className="filters">
              {ROWS.map(([k, title]) => (
                <div key={k} className={KIND[k]}><h3>{title}</h3>{(facets[k] ?? []).map((r) => (
                  <button key={r.value} className={"opt" + (f[k] === r.value ? " on" : "")} onClick={() => toggle(k, r.value)}><span>{facetLabel(k, r.label)}</span><span>{r.n}</span></button>))}</div>))}
              <h3 className="plain">MRP (₹)</h3>
              <div className="price">
                <input inputMode="numeric" placeholder="min" defaultValue={f.min_price} onBlur={(e) => go(q, { ...f, min_price: e.target.value })} />
                <span>–</span>
                <input inputMode="numeric" placeholder="max" defaultValue={f.max_price} onBlur={(e) => go(q, { ...f, max_price: e.target.value })} />
              </div>
            </aside>
            <section>
              <div className="toolbar">
                <span className="count">{countText}</span>
                <span className="seg">{(["list", "compact"] as const).map((v) => (
                  <button key={v} className={view === v ? "on" : ""} onClick={() => { setView(v); localStorage.setItem("view", v); }}>{v === "list" ? "Cards" : "Compact"}</button>))}</span>
              </div>
              {data?.corrected_from && <p className="hint corr">Showing results for <b>{data.query}</b> (you typed “{data.corrected_from}”)</p>}
              {chips.length > 0 && <div className="active">{chips.map(([k, v]) => (
                <button key={k} className={"chipbtn " + (KIND[k as keyof typeof KIND] ?? "")} onClick={() => toggle(k as keyof F, v!)}>{k === "min_price" ? "from ₹" : k === "max_price" ? "up to ₹" : ""}{v} ×</button>))}</div>}
              <div className={"list" + (compact ? " compact" : "")}>
                {!data ? [0, 1, 2, 3].map((i) => <div key={i} className="skeleton" />) : data.hits.map((h) => (
                  <article key={h.id} className={"card" + (h.image_url && !compact ? " hasimg" : "")} onClick={() => openProduct(h.id)}>
                    {h.image_url && !compact && <div className="ph"><img loading="lazy" src={h.image_url} alt="" /></div>}
                    <div className="body">
                      <div className="meta lgrow"><Logo kind="brands" name={h.brand} logos={logos} />{h.segment && <span className="segemoji" title={h.segment} aria-label={h.segment} role="img">{segEmoji(h.segment)}</span>}{h.category && <Logo kind="categories" name={h.category} logos={logos} />}</div>
                      <div className="title">{h.description || h.part_no}</div>
                      <div className="ids"><button className="pn" title="Tap to copy" onClick={(e) => copy(e, h.part_no)}>{h.part_no}</button>
                        {h.variant_label && <span className="tag">{h.variant_label}</span>}
                        {makesOf(h.oem_name).slice(0, 3).map((m) => <Logo key={m} kind="makes" name={m} logos={logos} />)}
                        {makesOf(h.oem_name).length > 3 && <span className="tag" title={h.oem_name ?? ""}>+{makesOf(h.oem_name).length - 3}</span>}</div>
                      {h.application && <div className="used"><Lbl>For</Lbl> <span className="val">{h.application}</span></div>}
                    </div>
                    <div className="side">
                      {h.mrp != null ? <div className="mrp"><Lbl>MRP</Lbl><span className="val">{inr(h.mrp)}</span>{basisText(h.price_basis) && <small>{basisText(h.price_basis).replace(/[() ]/g, " ").trim()}</small>}</div>
                        : <div className="mrp"><small>On request</small></div>}
                      <a className="ask" href={askLink(h)} target="_blank" rel="noopener" onClick={(e) => e.stopPropagation()}>Ask availability</a>
                    </div>
                  </article>))}
              </div>
              {data && !data.hits.length && <div className="empty"><p><b>No results.</b></p><p>Try the part number or the vehicle name, or <a href={wa("Hi, I could not find: " + q)} target="_blank" rel="noopener">ask us on WhatsApp</a>.</p></div>}
              {data && data.hits.length < data.total && data.hits.length < DEPTH && <div ref={sentinel} className="sentinel" aria-live="polite">Loading more…</div>}
              {data && data.hits.length < data.total && data.hits.length >= DEPTH && <p className="hint" style={{ textAlign: "center" }}>Showing the first {DEPTH} of {data.total.toLocaleString("en-IN")}. Narrow the search with a make, category or part number.</p>}
            </section>
          </div>
        )}
      </main>
      <VisitorCounter hidden={hasQuery} />

      {open && (
        <div className="backdrop" onClick={close}>
          <div className="dlg" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <button className="close" onClick={close} aria-label="Close">×</button>
            <div className="meta lgrow big"><Logo kind="brands" name={open.brand} logos={logos} withName />{open.segment && <span className="segp c-seg"><span aria-hidden>{segEmoji(open.segment)}</span> {open.segment}</span>}{open.category && <Logo kind="categories" name={open.category} logos={logos} withName />}</div>
            <h1>{open.description || open.part_no}</h1>
            <div><button className="pn" onClick={(e) => copy(e, open.part_no)}>{open.part_no}</button>{open.variant_label && <span className="tag">{open.variant_label}</span>}</div>
            <dl className="kv">
              {([["MRP", open.mrp != null ? inr(open.mrp) + basisText(open.price_basis) : "Price on request"], ["Used for", open.application], ["Vehicle make", makesOf(open.oem_name).length ? <span className="lgrow wrap">{makesOf(open.oem_name).map((m) => <Logo key={m} kind="makes" name={m} logos={logos} withName />)}</span> : null],
                ["OEM code (as printed)", open.oem_raw], ["Segment", open.segment ? <span>{segEmoji(open.segment)} {open.segment}</span> : null], ["HSN", open.hsn], ["GST", open.gst_pct != null ? open.gst_pct + "%" : null],
                ["Min. order qty", open.moq], ["Pack", open.pack_qty ? `${open.pack_qty} ${open.unit ?? ""}` : null],
                ["Price list date", open.price_effective_from ? new Date(open.price_effective_from).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null],
                ["OEM / reference nos.", open.cross_refs?.length ? open.cross_refs.map((r: any) => r.ref_part_no).join(" · ") : null],
                ["Availability", "Ask us — most items are in stock or available within ~7 days"]] as [string, any][])
                .filter(([, v]) => v != null && v !== "").map(([k, v]) => (<div key={k} style={{ display: "contents" }}><dt className="lbl">{k}</dt><dd className="val">{typeof v === "object" ? v : String(v)}</dd></div>))}
            </dl>
            <p><a className="btn primary" style={{ textDecoration: "none", display: "inline-block" }} href={askLink(open)} target="_blank" rel="noopener">Ask availability on WhatsApp</a></p>
            {([["Other sizes / variants", open.variants], ["Same part number, other brands", open.same_number_elsewhere], ["Related parts", open.related]] as const)
              .filter(([, rows]) => rows?.length).map(([title, rows]) => (
              <div key={title}><h2>{title}</h2><div className="rel">{rows.map((x: Hit) => (
                <button key={x.id} onClick={() => openProduct(x.id, "related")}><b>{x.brand}</b> <span className="pnx">{x.part_no}</span> {x.variant_label ? `(${x.variant_label})` : ""} — {x.description} {x.mrp != null ? "· " + inr(x.mrp) : ""}</button>))}</div></div>))}
            {open.images?.length > 0 && <div><h2>Photos</h2><div className="photos">{open.images.map((i: any) => <img key={i.url} src={i.url} alt="" />)}</div></div>}
          </div>
        </div>
      )}
      <div className={"toast" + (toast ? " on" : "")}>{toast}</div>
    </>
  );
}
