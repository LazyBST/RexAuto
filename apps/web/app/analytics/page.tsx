import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { loadAnalytics, type Dim } from "@/lib/analytics";
import { withRetry } from "@/lib/db";
import "./analytics.css";

// Not linked from anywhere in the app: reached only by typing /analytics. Kept out of search engines.
// If ANALYTICS_KEY is set in the environment the page also needs ?key=<that value>.
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Analytics · Rex Auto", robots: { index: false, follow: false, nocache: true } };

const RANGES = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["0", "All time"]] as const;
const n = (v: number | string | null | undefined) => Number(v ?? 0).toLocaleString("en-IN");
const pct = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 100) + "%" : "–");

type Logos = { makes: Record<string, string>; brands: Record<string, string>; categories: Record<string, string> };
const Name = ({ name, url }: { name: string; url?: string }) => (
  <span className="nm">{url ? <img src={url} alt="" loading="lazy" /> : <i>{name.slice(0, 2).toUpperCase()}</i>}{name}</span>
);

function Bars({ data, label }: { data: { x: string; a: number; b?: number }[]; label: (d: { x: string; a: number; b?: number }) => string }) {
  const max = Math.max(1, ...data.map((d) => d.a));
  return (
    <div className="bars" role="img" aria-label="chart">
      {data.map((d) => (
        <div key={d.x} className="bar" title={label(d)}>
          <span style={{ height: Math.max(2, (d.a / max) * 100) + "%" }} />
          {d.b != null && <em style={{ height: Math.max(0, (d.b / max) * 100) + "%" }} />}
        </div>
      ))}
    </div>
  );
}

function DimTable({ title, rows, logos, kind, typed }: { title: string; rows: Dim[]; logos?: Record<string, string>; kind: string; typed?: boolean }) {
  const top = rows.slice(0, 15);
  const max = Math.max(1, ...top.map((r) => r.total));
  return (
    <section className="card">
      <h2>{title}</h2>
      {top.length === 0 ? <p className="mute">No data yet.</p> : (
        <table>
          <thead><tr><th>{kind}</th><th title="Shown as the dominant result of a search">In results</th>{typed && <th title="Named in the search text">Typed</th>}<th title="Picked as a filter">Filtered</th><th title="Product opened">Viewed</th><th>Total</th></tr></thead>
          <tbody>{top.map((r) => (
            <tr key={r.name}>
              <td><Name name={r.name} url={logos?.[r.name]} /><span className="meter"><b style={{ width: (r.total / max) * 100 + "%" }} /></span></td>
              <td>{n(r.searched)}</td>{typed && <td>{n(r.typed)}</td>}<td>{n(r.filtered)}</td><td>{n(r.viewed)}</td><td><b>{n(r.total)}</b></td>
            </tr>))}</tbody>
        </table>)}
    </section>
  );
}

export default async function Analytics({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const need = process.env.ANALYTICS_KEY;
  if (need && sp.key !== need) notFound();
  const days = ["7", "30", "90", "0"].includes(sp.days ?? "") ? Number(sp.days) : 30;
  let d: Awaited<ReturnType<typeof loadAnalytics>>;
  try { d = await withRetry(() => loadAnalytics(days), 25000); }
  catch (e: any) { return <main className="an"><h1>Analytics</h1><p className="mute">Could not load: {String(e?.message ?? e?.code ?? "database error").slice(0, 300)}</p></main>; }
  const s = d.summary;
  const keyQ = need ? `&key=${encodeURIComponent(sp.key ?? "")}` : "";
  const peak = d.hours.reduce((a, b) => (b.n > a.n ? b : a), d.hours[0]);

  return (
    <main className="an">
      <header>
        <div><h1>Analytics</h1><p className="mute">What people search for and open · times in IST</p></div>
        <nav className="ranges">{RANGES.map(([v, l]) => <a key={v} href={`?days=${v}${keyQ}`} className={String(days) === v ? "on" : ""}>{l}</a>)}</nav>
      </header>

      <div className="kpis">
        <div><span>Searches</span><b>{n(s.searches)}</b></div>
        <div><span>People searching</span><b>{n(s.people)}</b><small>{n(s.sessions)} sessions</small></div>
        <div><span>Product views</span><b>{n(s.views)}</b><small>{n(s.products)} different products</small></div>
        <div><span>Searches with no result</span><b>{n(s.zero)}</b><small>{pct(s.zero, s.searches)} of searches</small></div>
        <div><span>Click-through</span><b>{pct(s.click_through, s.click_searches)}</b><small>searches followed by opening a product</small></div>
        <div><span>Avg results / search</span><b>{n(s.avg_results)}</b><small>{n(s.corrected)} typo-corrected</small></div>
      </div>

      <section className="card wide">
        <h2>Per day <small className="mute">searches (bars) · product views (dark)</small></h2>
        <Bars data={d.daily.map((r: any) => ({ x: r.day, a: r.searches, b: r.views }))} label={(r) => `${r.x}: ${r.a} searches, ${r.b} views`} />
        <div className="axis"><span>{d.daily[0]?.day}</span><span>{d.daily[d.daily.length - 1]?.day}</span></div>
      </section>

      <section className="card wide">
        <h2>Time of day <small className="mute">searches by hour{peak?.n ? ` · busiest ${peak.h}:00–${peak.h + 1}:00` : ""}</small></h2>
        <Bars data={d.hours.map((r) => ({ x: String(r.h), a: r.n }))} label={(r) => `${r.x}:00 – ${r.a} searches`} />
        <div className="axis"><span>12 am</span><span>6 am</span><span>12 pm</span><span>6 pm</span><span>11 pm</span></div>
      </section>

      <div className="grid">
        <DimTable title="Vehicle makes" rows={d.makes} logos={d.logos.makes} kind="Make" typed />
        <DimTable title="Product brands" rows={d.brands} logos={d.logos.brands} kind="Brand" typed />
        <DimTable title="Categories" rows={d.categories} logos={d.logos.categories} kind="Category" />
        <DimTable title="Segments" rows={d.segments} kind="Segment" />
      </div>
      <p className="mute note">“In results” counts a search once under the make / brand / category / segment that dominated its top results. “Typed” counts searches that named it. “Filtered” counts filter picks. “Viewed” counts product opens. Total is the sum.</p>

      <div className="grid">
        <section className="card">
          <h2>Top searches</h2>
          {d.topQueries.length === 0 ? <p className="mute">No data yet.</p> : (
            <table><thead><tr><th>Query</th><th>Searches</th><th>People</th><th>Avg results</th></tr></thead>
              <tbody>{d.topQueries.map((r: any) => <tr key={r.q}><td className="q">{r.q}</td><td><b>{n(r.n)}</b></td><td>{n(r.people)}</td><td className={r.zero ? "bad" : ""}>{n(r.avg_results)}</td></tr>)}</tbody></table>)}
        </section>
        <section className="card">
          <h2>Searches with no result <small className="mute">what to add or fix</small></h2>
          {d.zeroQueries.length === 0 ? <p className="mute">None.</p> : (
            <table><thead><tr><th>Query</th><th>Times</th><th>Last</th></tr></thead>
              <tbody>{d.zeroQueries.map((r: any) => <tr key={r.q}><td className="q">{r.q}</td><td><b>{n(r.n)}</b></td><td>{r.last}</td></tr>)}</tbody></table>)}
        </section>
      </div>

      <div className="grid">
        <section className="card">
          <h2>Most viewed products</h2>
          {d.topViewed.length === 0 ? <p className="mute">No data yet.</p> : (
            <table><thead><tr><th>Product</th><th>Views</th><th>People</th><th>From search</th></tr></thead>
              <tbody>{d.topViewed.map((r: any) => (
                <tr key={r.id}><td><b className="pn">{r.part_no}</b> <span className="mute">{r.brand}</span><div className="sub">{r.description}{r.oem_name ? ` · ${r.oem_name}` : ""}</div></td>
                  <td><b>{n(r.views)}</b></td><td>{n(r.people)}</td><td>{pct(r.from_list, r.views)}</td></tr>))}</tbody></table>)}
        </section>
        <section className="card">
          <h2>Most shown in search results <small className="mute">top 10 of each search</small></h2>
          {d.topShown.length === 0 ? <p className="mute">No data yet.</p> : (
            <table><thead><tr><th>Product</th><th>Shown</th></tr></thead>
              <tbody>{d.topShown.map((r: any) => (
                <tr key={r.id}><td><b className="pn">{r.part_no}</b> <span className="mute">{r.brand}</span><div className="sub">{r.description}{r.oem_name ? ` · ${r.oem_name}` : ""}</div></td><td><b>{n(r.shown)}</b></td></tr>))}</tbody></table>)}
        </section>
      </div>

      <section className="card wide">
        <h2>Latest searches</h2>
        {d.recent.length === 0 ? <p className="mute">No data yet.</p> : (
          <table><thead><tr><th>When</th><th>Query</th><th>Filters</th><th>Results</th></tr></thead>
            <tbody>{d.recent.map((r: any, i: number) => (
              <tr key={i}><td className="mute">{r.at}</td><td className="q">{r.query || <span className="mute">(filters only)</span>}</td>
                <td>{Object.entries(r.filters ?? {}).map(([k, v]) => <span key={k} className="chip">{k.replace("_", " ")}: {String(v)}</span>)}</td>
                <td className={r.total === 0 ? "bad" : ""}>{n(r.total)}</td></tr>))}</tbody></table>)}
      </section>
    </main>
  );
}
