"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Hit = { id: string; part_no: string; variant_label: string; description: string | null; application: string | null; oem_name: string | null;
  category: string | null; segment: string | null; mrp: number | null; price_basis: string; image_url: string | null; brand: string };
type Facet = { value: string; label: string; n: number };
type Result = { total: number; hits: Hit[]; ms: number; facets: Record<string, Facet[]>; corrected_from?: string; query?: string };
const PAGE = 30, DEPTH = 300;
const FILTERS = ["brand", "make", "segment", "category", "min_price", "max_price"] as const;
type F = Partial<Record<(typeof FILTERS)[number], string>>;

const inr = (n: number | null) => (n == null ? null : "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 }));
const basisText = (b: string) => (b === "ex_tax" ? " (excl. GST)" : b === "incl_tax" ? " (incl. GST)" : "");

export default function Catalogue() {
  const [cfg, setCfg] = useState({ name: "Parts Catalogue", whatsapp: "" });
  const [q, setQ] = useState("");
  const [f, setF] = useState<F>({});
  const [view, setView] = useState<"list" | "compact">("list");
  const [data, setData] = useState<Result | null>(null);
  const [home, setHome] = useState<Result | null>(null);
  const [open, setOpen] = useState<any>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [toast, setToast] = useState("");
  const req = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const hasQuery = !!q.trim() || Object.values(f).some(Boolean);

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

  // first load: config, url state, home tiles
  useEffect(() => {
    fetch("/api/config").then((r) => r.json()).then((c) => { setCfg(c); document.title = c.name; }).catch(() => {});
    fetch("/api/search?limit=1").then((r) => r.json()).then(setHome).catch(() => {});
    const u = new URLSearchParams(location.search);
    const nf: F = {}; for (const k of FILTERS) if (u.get(k)) nf[k] = u.get(k)!;
    const nq = u.get("q") ?? "";
    setQ(nq); setF(nf);
    if (nq || Object.keys(nf).length) run(nq, nf);
    const m = location.hash.match(/^#p=([0-9a-f-]{36})$/);
    if (m) openProduct(m[1]);
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
  const openProduct = async (id: string) => {
    const r = await fetch("/api/product/" + id); if (!r.ok) return;
    setOpen(await r.json()); history.replaceState(null, "", location.search + "#p=" + id);
  };
  const close = () => { setOpen(null); history.replaceState(null, "", location.pathname + location.search); };
  const copy = (e: React.MouseEvent, s: string) => { e.stopPropagation(); navigator.clipboard?.writeText(s); setToast("Copied " + s); setTimeout(() => setToast(""), 1400); };
  const wa = (text: string) => `https://wa.me/${cfg.whatsapp}?text=${encodeURIComponent(text)}`;
  const askLink = (h: { brand: string; part_no: string; variant_label?: string; id: string }) =>
    wa(`Hi, is this available?\n${h.brand} ${h.part_no}${h.variant_label ? " (" + h.variant_label + ")" : ""}\n${typeof location !== "undefined" ? location.origin : ""}/#p=${h.id}`);

  const facets = data?.facets ?? {};
  const chips = useMemo(() => Object.entries(f).filter(([, v]) => v), [f]);

  return (
    <>
      <header><div className="bar">
        <div className="logo" onClick={() => go("", {})}>{cfg.name}</div>
        <div className="search">
          <input value={q} onChange={(e) => onType(e.target.value)} type="search" inputMode="search" autoComplete="off" autoCapitalize="off" spellCheck={false}
            placeholder="Part number, or vehicle + part (e.g. tata 1612 brake valve)" autoFocus />
          {q && <button className="x" style={{ display: "block" }} aria-label="Clear" onClick={() => go("", f)}>×</button>}
        </div>
      </div></header>

      <main>
        {!hasQuery ? (
          <>
            <p className="hint">{home ? home.total.toLocaleString("en-IN") : "…"} parts · search by part number, or by vehicle and part.</p>
            <div className="examples">{["tata brake valve", "head lamp swift", "MB04015028", "oil filter", "brake lining ashok leyland", "clutch"].map((x) => (
              <button key={x} className="chipbtn" onClick={() => go(x, {})}>{x}</button>))}</div>
            {([["make", "Browse by vehicle make"], ["category", "Browse by category"], ["brand", "Browse by brand"]] as const).map(([k, title]) => (
              <section key={k}><h2>{title}</h2><div className="tiles">{(home?.facets?.[k] ?? []).map((r) => (
                <button key={r.value} className="tile" onClick={() => toggle(k, r.value)}><span>{r.label}</span><small>{r.n.toLocaleString("en-IN")}</small></button>))}</div></section>))}
          </>
        ) : (
          <div className="layout">
            <aside className={"filters" + (filtersOpen ? " open" : "")}>
              {([["brand", "Brand"], ["make", "Vehicle make"], ["segment", "Segment"], ["category", "Category"]] as const).map(([k, title]) => (
                <div key={k}><h3>{title}</h3>{(facets[k] ?? []).map((r) => (
                  <button key={r.value} className={"opt" + (f[k] === r.value ? " on" : "")} onClick={() => toggle(k, r.value)}><span>{r.label}</span><span>{r.n}</span></button>))}</div>))}
              <h3>MRP (₹)</h3>
              <div className="price">
                <input inputMode="numeric" placeholder="min" defaultValue={f.min_price} onBlur={(e) => go(q, { ...f, min_price: e.target.value })} />
                <span>–</span>
                <input inputMode="numeric" placeholder="max" defaultValue={f.max_price} onBlur={(e) => go(q, { ...f, max_price: e.target.value })} />
              </div>
            </aside>
            <section>
              <div className="toolbar">
                <span className="count">{data ? <>{data.total.toLocaleString("en-IN")} result{data.total === 1 ? "" : "s"} <small>· {data.ms} ms</small></> : "Searching…"}</span>
                <span><button className="btn" id="fbtn" onClick={() => setFiltersOpen(!filtersOpen)}>Filters</button>
                  <span className="seg">{(["list", "compact"] as const).map((v) => (
                    <button key={v} className={view === v ? "on" : ""} onClick={() => { setView(v); localStorage.setItem("view", v); }}>{v === "list" ? "Cards" : "Compact"}</button>))}</span></span>
              </div>
              {data?.corrected_from && <p className="hint">Showing results for <b>{data.query}</b> (you typed “{data.corrected_from}”)</p>}
              {chips.length > 0 && <div className="active">{chips.map(([k, v]) => (
                <button key={k} className="chipbtn" onClick={() => toggle(k as keyof F, v!)}>{k === "min_price" ? "from ₹" : k === "max_price" ? "up to ₹" : ""}{v} ×</button>))}</div>}
              <div className={"list" + (view === "compact" ? " compact" : "")}>
                {!data ? [0, 1, 2, 3].map((i) => <div key={i} className="skeleton" />) : data.hits.map((h) => (
                  <article key={h.id} className="card" onClick={() => openProduct(h.id)}>
                    <div className="ph">{h.image_url ? <img loading="lazy" src={h.image_url} alt="" /> : "No image"}</div>
                    <div>
                      <div className="meta"><span className="brand">{h.brand}</span> · {h.category}</div>
                      <div className="title">{h.description || h.part_no}</div>
                      <div><button className="pn" title="Tap to copy" onClick={(e) => copy(e, h.part_no)}>{h.part_no}</button>
                        {h.variant_label && <span className="tag">{h.variant_label}</span>}{h.oem_name && <span className="tag">{h.oem_name}</span>}</div>
                      {h.application && <div className="used">Used for: {h.application}</div>}
                    </div>
                    <div className="side">
                      {h.mrp != null ? <div className="mrp">{inr(h.mrp)}<small>MRP{basisText(h.price_basis)}</small></div> : <div className="mrp"><small>Price on request</small></div>}
                      <a className="ask" href={askLink(h)} target="_blank" rel="noopener" onClick={(e) => e.stopPropagation()}>Ask availability</a>
                    </div>
                  </article>))}
              </div>
              {data && !data.hits.length && <div className="empty"><p><b>No results.</b></p><p>Try the part number or the vehicle name, or <a href={wa("Hi, I could not find: " + q)} target="_blank" rel="noopener">ask us on WhatsApp</a>.</p></div>}
              {data && data.hits.length < data.total && data.hits.length < DEPTH && <button className="btn more" onClick={() => run(q, f, data.hits.length, true)}>Show more ({data.total - data.hits.length} left)</button>}
              {data && data.hits.length < data.total && data.hits.length >= DEPTH && <p className="hint" style={{ textAlign: "center" }}>Showing the first {DEPTH} of {data.total.toLocaleString("en-IN")}. Narrow the search with a make, category or part number.</p>}
            </section>
          </div>
        )}
      </main>

      {open && (
        <div className="backdrop" onClick={close}>
          <div className="dlg" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <button className="close" onClick={close} aria-label="Close">×</button>
            <div className="meta"><span className="brand">{open.brand}</span> · {open.category}</div>
            {open.images?.length > 0 && <div style={{ display: "flex", gap: 8, overflow: "auto", margin: "10px 0" }}>{open.images.map((i: any) => <img key={i.url} src={i.url} alt="" style={{ height: 160, borderRadius: 10 }} />)}</div>}
            <h1>{open.description || open.part_no}</h1>
            <div><button className="pn" onClick={(e) => copy(e, open.part_no)}>{open.part_no}</button>{open.variant_label && <span className="tag">{open.variant_label}</span>}</div>
            <dl className="kv">
              {([["MRP", open.mrp != null ? inr(open.mrp) + basisText(open.price_basis) : "Price on request"], ["Used for", open.application], ["Vehicle make", open.oem_name],
                ["OEM code (as printed)", open.oem_raw], ["Segment", open.segment], ["HSN", open.hsn], ["GST", open.gst_pct != null ? open.gst_pct + "%" : null],
                ["Min. order qty", open.moq], ["Pack", open.pack_qty ? `${open.pack_qty} ${open.unit ?? ""}` : null],
                ["Price list date", open.price_effective_from ? new Date(open.price_effective_from).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : null],
                ["OEM / reference nos.", open.cross_refs?.length ? open.cross_refs.map((r: any) => r.ref_part_no).join(" · ") : null],
                ["Availability", "Ask us — most items are in stock or available within ~7 days"]] as [string, any][])
                .filter(([, v]) => v != null && v !== "").map(([k, v]) => (<div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{String(v)}</dd></div>))}
            </dl>
            <p><a className="btn primary" style={{ textDecoration: "none", display: "inline-block" }} href={askLink(open)} target="_blank" rel="noopener">Ask availability on WhatsApp</a></p>
            {([["Other sizes / variants", open.variants], ["Same part number, other brands", open.same_number_elsewhere], ["Related parts", open.related]] as const)
              .filter(([, rows]) => rows?.length).map(([title, rows]) => (
              <div key={title}><h2>{title}</h2><div className="rel">{rows.map((x: Hit) => (
                <button key={x.id} onClick={() => openProduct(x.id)}><b>{x.brand}</b> {x.part_no} {x.variant_label ? `(${x.variant_label})` : ""} — {x.description} {x.mrp != null ? "· " + inr(x.mrp) : ""}</button>))}</div></div>))}
          </div>
        </div>
      )}
      <div className={"toast" + (toast ? " on" : "")}>{toast}</div>
    </>
  );
}
