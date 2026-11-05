"use client";

import { useEffect, useRef, useState } from "react";

// One flip-clock digit: the old value folds down like a calendar page and the new one lands.
function Digit({ v }: { v: string }) {
  const [cur, setCur] = useState(v);
  const [low, setLow] = useState(v);   // what the static bottom half shows until the flap lands
  const [prev, setPrev] = useState(v);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (v === cur) return;
    setPrev(cur); setCur(v); setN((k) => k + 1);
    const t = setTimeout(() => setLow(v), 620);
    return () => clearTimeout(t);
  }, [v]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span className="fd" aria-hidden>
      <span className="h t"><b>{cur}</b></span>
      <span className="h b"><b>{low}</b></span>
      {n > 0 && <span key={"t" + n} className="h t flap-t"><b>{prev}</b></span>}
      {n > 0 && <span key={"b" + n} className="h b flap-b"><b>{cur}</b></span>}
    </span>
  );
}

export default function VisitorCounter() {
  const [total, setTotal] = useState<number | null>(null);
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    (async () => {
      let counted = false;
      try { counted = sessionStorage.getItem("rx_visit") === "1"; } catch {}
      try {
        const g = await fetch("/api/visit").then((r) => r.json());
        if (g.total == null) return;
        setTotal(g.total);
        if (counted) return;
        await new Promise((r) => setTimeout(r, 900));   // let the number appear, then flip it
        const p = await fetch("/api/visit", { method: "POST" }).then((r) => r.json());
        if (p.total != null) setTotal(p.total);
        try { sessionStorage.setItem("rx_visit", "1"); } catch {}
      } catch {}
    })();
  }, []);

  if (total == null) return null;
  const digits = String(total).padStart(6, "0").split("");
  return (
    <footer className="visits" aria-label={`${total.toLocaleString("en-IN")} visitors`}>
      <div className="cal">
        <div className="cal-head"><i /><i /><span>Visitors</span><i /><i /></div>
        <div className="cal-body">{digits.map((d, i) => <Digit key={digits.length - i} v={d} />)}</div>
      </div>
    </footer>
  );
}
