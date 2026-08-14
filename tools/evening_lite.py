#!/usr/bin/env python3
"""
EVENING-REPORT-LITE v1.1.0 — herbouw 14-aug-2026 22:15 na workspace-reset #3.
Scope vanavond (Option B):
  - H1: integriteit/DQ volledige dag 00:00-22:00
  - H2: gedrag ALLEEN 12:00-15:30 (00-12 zat in het middagreport; US = holdout)
  - H3: US 15:30-22:00 uitsluitend integriteit, expliciet held-out
  - H4: DQ-vergelijking met 13-aug
  - H5: honesty panel
Chain-recall ontbreekt vanavond bewust: de chain-engine ging verloren in de
reset en wordt niet in 30 minuten herbouwd-en-vertrouwd. Staat in H5.
"""
import sys, json, gzip, glob, hashlib, statistics
from collections import defaultdict

CONFIG = dict(
    ENGINE="EVENING-REPORT-LITE", VERSION="1.1.0",
    TP_REVERSAL=2.5, TP_RUNUP=1.5,
    NODE_W_MIN=50, WALL_FACTOR=4.0, ZONE_HALF=0.25,
    TOL_PRIMARY=0.50, FROZEN_DEPART=1.50,
    QUALIFY_SNAPSHOTS=3, QUALIFY_WINDOW_S=300,
    BOOK_SAMPLE=20,
)
CFG_HASH = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:8]

NL_OFFSET_MS = 2 * 3600 * 1000  # NL = UTC+2 in augustus

def nl_hhmm(ts_ms):
    t = (ts_ms + NL_OFFSET_MS) // 1000
    return f"{(t // 3600) % 24:02d}:{(t // 60) % 60:02d}"

def load_day(day, upto_h=24):
    files = sorted(glob.glob(f"full-tick-data/{day}/*_FULL_MBO32.jsonl.gz"))
    S, T, B, E, M = [], [], [], [], []   # states, trades, books(sampled), events, memory
    dq_by_hour = defaultdict(list)
    age_by_hour = defaultdict(list)
    crossed = 0
    snap_total = 0
    bi = 0
    for f in files:
        start_h = int(f.split("/")[-1][:2])
        if start_h >= upto_h:
            continue
        with gzip.open(f, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                rt = r["_record_type"]
                ts = r["ts_ms"]
                h = int(((ts + NL_OFFSET_MS) // 3600000) % 24)
                if rt == "nexus_state":
                    p = r["payload"]
                    dq_by_hour[h].append(p.get("dq", 0))
                    q = p.get("quality") or {}
                    if q.get("book_age_ms") is not None:
                        age_by_hour[h].append(q["book_age_ms"])
                    S.append((ts, p.get("mid"), p.get("market_state_id"),
                              p.get("dq"), p.get("bid"), p.get("ask")))
                elif rt == "trade":
                    T.append((ts, r["price"], r["volume"], 1 if r["side"] == "buy" else -1))
                elif rt == "book_snapshot":
                    snap_total += 1
                    if r["bids"] and r["asks"] and r["bids"][0][0] >= r["asks"][0][0]:
                        crossed += 1
                    if bi % CONFIG["BOOK_SAMPLE"] == 0:
                        B.append((ts, r["bids"], r["asks"]))
                    bi += 1
                elif rt == "nexus_orderflow_event":
                    p = r["payload"]
                    E.append((ts, p.get("kind"), p.get("price"), p.get("calibrated_score")))
                elif rt == "nexus_memory_snapshot":
                    M.append((ts, r["payload"].get("nodes", [])))
    return dict(S=S, T=T, B=B, E=E, M=M, dq=dq_by_hour, age=age_by_hour,
                crossed=crossed, snaps=snap_total, files=len(files))

def zigzag(S, t0=None, t1=None):
    """Turning points op mid; reversal-drempel TP_REVERSAL, minimale swing TP_RUNUP."""
    pts = [(ts, m) for ts, m, *_ in S if m is not None
           and (t0 is None or ts >= t0) and (t1 is None or ts < t1)]
    if not pts:
        return []
    tps = []
    direction = 0
    REV = CONFIG["TP_REVERSAL"]
    hi_ts, hi = pts[0]; lo_ts, lo = pts[0]
    ext_ts, ext_p = pts[0]
    for ts, p in pts:
        if direction == 0:
            if p > hi: hi_ts, hi = ts, p
            if p < lo: lo_ts, lo = ts, p
            if p <= hi - REV:
                tps.append((hi_ts, hi, "TOP")); direction = -1; ext_ts, ext_p = ts, p
            elif p >= lo + REV:
                tps.append((lo_ts, lo, "BOTTOM")); direction = 1; ext_ts, ext_p = ts, p
        elif direction > 0:
            if p > ext_p:
                ext_ts, ext_p = ts, p
            elif p <= ext_p - REV:
                tps.append((ext_ts, ext_p, "TOP")); direction = -1; ext_ts, ext_p = ts, p
        else:
            if p < ext_p:
                ext_ts, ext_p = ts, p
            elif p >= ext_p + REV:
                tps.append((ext_ts, ext_p, "BOTTOM")); direction = 1; ext_ts, ext_p = ts, p
    # minimale swinggrootte TP_RUNUP tussen opeenvolgende TPs
    out = []
    for i, tp in enumerate(tps):
        if i + 1 < len(tps) and abs(tps[i + 1][1] - tp[1]) < CONFIG["TP_RUNUP"]:
            continue
        out.append(tp)
    return out

def brick_locations(B, t0, t1):
    """Muren >= max(NODE_W_MIN, 4x trailing-uur mediaan levelgrootte), gekwalificeerd
    als in >=QUALIFY_SNAPSHOTS gesamplede snapshots binnen QUALIFY_WINDOW_S gezien."""
    trailing = []          # (ts, mediaan levelgrootte)
    hits = defaultdict(list)  # (price, side) -> [ts...]
    for ts, bids, asks in B:
        sizes = [s for _, s in bids] + [s for _, s in asks]
        if not sizes:
            continue
        trailing.append((ts, statistics.median(sizes)))
        cutoff = ts - 3600000
        while trailing and trailing[0][0] < cutoff:
            trailing.pop(0)
        med = statistics.median([m for _, m in trailing])
        thr = max(CONFIG["NODE_W_MIN"], CONFIG["WALL_FACTOR"] * med)
        if not (t0 <= ts < t1):
            continue
        for side, levels in (("BID", bids), ("ASK", asks)):
            for price, size in levels:
                if size >= thr:
                    hits[(price, side)].append(ts)
    locs = []
    for (price, side), tss in hits.items():
        tss.sort()
        for i in range(len(tss)):
            j = i
            while j + 1 < len(tss) and tss[j + 1] - tss[i] <= CONFIG["QUALIFY_WINDOW_S"] * 1000:
                j += 1
            if j - i + 1 >= CONFIG["QUALIFY_SNAPSHOTS"]:
                locs.append(dict(center=price, side=side, first_seen=tss[i]))
                break
    # dedup binnen ZONE_HALF per side: houd eerst-geziene
    locs.sort(key=lambda l: l["first_seen"])
    kept = []
    for l in locs:
        if any(k["side"] == l["side"] and abs(k["center"] - l["center"]) <= 2 * CONFIG["ZONE_HALF"]
               for k in kept):
            continue
        kept.append(l)
    return kept

def episodes(S, locs, t0, t1):
    """Bevroren definitie: start bij tolerantie-entry (0.50), einde pas >=1.50 vanaf center."""
    eps = []
    mids = [(ts, m) for ts, m, *_ in S if m is not None and t0 <= ts < t1]
    for loc in locs:
        c = loc["center"]
        inside = False
        start = None
        extreme = None
        for ts, m in mids:
            d = abs(m - c)
            if not inside and d <= CONFIG["TOL_PRIMARY"] and ts >= loc["first_seen"]:
                inside = True; start = ts; extreme = m
            elif inside:
                if abs(m - c) > abs(extreme - c):
                    extreme = m
                if d >= CONFIG["FROZEN_DEPART"]:
                    depart_above = m > c
                    held = (loc["side"] == "BID" and depart_above) or \
                           (loc["side"] == "ASK" and not depart_above)
                    eps.append(dict(loc=c, side=loc["side"], start=start, end=ts,
                                    dur_s=(ts - start) // 1000,
                                    outcome="HOLD" if held else "BREAK"))
                    inside = False
        if inside and start is not None:
            eps.append(dict(loc=c, side=loc["side"], start=start, end=None,
                            dur_s=None, outcome="OPEN_AT_BOUNDARY"))
    return eps

def dq_table(day_data, label, h0=0, h1=22):
    rows = [f"  uur  | mediaan DQ | min DQ | mediaan book_age_ms   ({label})"]
    for h in range(h0, h1):
        d = day_data["dq"].get(h, [])
        a = day_data["age"].get(h, [])
        if not d:
            rows.append(f"  {h:02d}   | GEEN DATA")
            continue
        rows.append(f"  {h:02d}   | {statistics.median(d):6.1f}     | {min(d):5.1f}  | "
                    f"{statistics.median(a) if a else float('nan'):6.0f}")
    return "\n".join(rows)

def main():
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-08-14"
    cmp_day = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"{CONFIG['ENGINE']} v{CONFIG['VERSION']}  config={CFG_HASH}")
    print(f"Dag: {day}  (gedragsscope 12:00-15:30; US 15:30-22:00 = HELD-OUT, alleen integriteit)")
    D = load_day(day)
    print(f"\nGeladen: {D['files']} bestanden | states={len(D['S'])} trades={len(D['T'])} "
          f"snapshots={D['snaps']} (sampled {len(D['B'])}) events={len(D['E'])} memory={len(D['M'])}")

    def nlms(hh, mm=0):
        base = D["S"][0][0] if D["S"] else 0
        day0 = ((base + NL_OFFSET_MS) // 86400000) * 86400000 - NL_OFFSET_MS
        return day0 + (hh * 3600 + mm * 60) * 1000

    print("\n=== H1: INTEGRITEIT 00:00-22:00 ===")
    print(f"Gekruiste snapshots: {D['crossed']}/{D['snaps']} "
          f"({100.0 * D['crossed'] / max(1, D['snaps']):.2f}%)")
    print(dq_table(D, day))

    # controle-zigzag 00-12 (verwachting: ~30 TPs, validatie herbouw)
    ctl = zigzag(D["S"], nlms(0), nlms(12))
    print(f"\nControle herbouw: zigzag 00:00-12:00 vandaag = {len(ctl)} TPs (verwacht ~30)")

    print("\n=== H2: GEDRAG 12:00-15:30 ===")
    t0, t1 = nlms(12), nlms(15, 30)
    tps = zigzag(D["S"], t0, t1)
    print(f"Turning points ({CONFIG['TP_REVERSAL']}pt reversal / {CONFIG['TP_RUNUP']}pt run): {len(tps)}")
    for ts, p, kind in tps:
        print(f"  {nl_hhmm(ts)}  {p:8.2f}  {kind}")
    locs = brick_locations(D["B"], t0, t1)
    print(f"\nBrick-locaties gekwalificeerd in venster: {len(locs)}")
    for l in locs[:20]:
        print(f"  {l['center']:8.2f}  {l['side']}  eerst gezien {nl_hhmm(l['first_seen'])}")
    eps = episodes(D["S"], locs, t0, t1)
    closed = [e for e in eps if e["outcome"] in ("HOLD", "BREAK")]
    holds = sum(1 for e in closed if e["outcome"] == "HOLD")
    print(f"\nEpisodes (bevroren definitie): {len(eps)} totaal, {len(closed)} gesloten")
    if closed:
        print(f"  HOLD {holds}/{len(closed)} = {100.0 * holds / len(closed):.0f}%")
        durs = sorted(e["dur_s"] for e in closed)
        print(f"  duur mediaan {durs[len(durs)//2]}s  p25 {durs[len(durs)//4]}s  p75 {durs[3*len(durs)//4]}s")
    n_open = sum(1 for e in eps if e["outcome"] == "OPEN_AT_BOUNDARY")
    if n_open:
        print(f"  open op vensterrand: {n_open} (niet meegeteld)")

    ev_counts = defaultdict(int)
    for ts, kind, *_ in D["E"]:
        if t0 <= ts < t1:
            ev_counts[kind] += 1
    print("\nNEXUS events 12:00-15:30:", dict(sorted(ev_counts.items())))

    print("\n=== H3: US-SESSIE 15:30-22:00 — HELD-OUT ===")
    print("Per Option B geen gedragsanalyse, geen armings, geen episodes. Alleen integriteit:")
    us_states = sum(1 for ts, *_ in D["S"] if ts >= nlms(15, 30))
    us_trades = sum(1 for ts, *_ in D["T"] if ts >= nlms(15, 30))
    print(f"  records aanwezig: states={us_states} trades={us_trades} — venster blijft onaangeroerd tot v0.1-freeze")

    if cmp_day:
        print(f"\n=== H4: DQ-VERGELIJKING met {cmp_day} ===")
        C = load_day(cmp_day)
        print(f"Gekruist {cmp_day}: {C['crossed']}/{C['snaps']} "
              f"({100.0 * C['crossed'] / max(1, C['snaps']):.2f}%)")
        for h in range(0, 22):
            a = D["dq"].get(h, []); b = C["dq"].get(h, [])
            if a and b:
                da, db = statistics.median(a), statistics.median(b)
                flag = "  <-- afwijking" if abs(da - db) > 5 else ""
                print(f"  {h:02d}  vandaag {da:6.1f}  gisteren {db:6.1f}{flag}")

    print("\n=== H5: HONESTY PANEL ===")
    print(f"- Workspace-reset #3 vannacht; pipeline vanavond herbouwd als LITE v1.1.0 (config {CFG_HASH}).")
    print("- Chain-recall ontbreekt in dit report: de chain-engine ging verloren in de reset en wordt")
    print("  niet overhaast herbouwd; komt terug na de weekend-migratie, met tools in de repo.")
    print("- Zigzag/locaties/episodes zijn herimplementaties volgens de bevroren definities; de")
    print("  00-12-controle hierboven is de validatie. Wijkt die af van ~30, dan zijn aantallen in H2")
    print("  indicatief en niet vergelijkbaar met eerdere reports.")
    print("- US-sessie 15:30-22:00 blijft untouched holdout (Option B), inclusief Roy's papieren armings.")

if __name__ == "__main__":
    main()
