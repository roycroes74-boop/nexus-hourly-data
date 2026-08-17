#!/usr/bin/env python3
"""
CANONICAL PIPELINE v1.0.0 — het ene officiele meetinstrument (Nicolas punt 5).

Bouwt VOORT op de bevroren kern evening_lite v1.1.0 (config 9624bb9e), die de
fixture al reproduceert. Deze module voegt de canonieke onderdelen toe die in de
workspace-resets verloren gingen, nu versioned en fixture-gedekt:

  1. CHAIN-ENGINE  - volgt de NEXUS market_state machine (state_id 0-7) rond
                     armed levels/turning points als causale opbouwketen.
  2. RECALL/PRECISIE - unified match-tolerantie 0.50pt primair / 0.25 strict
                     (Nicolas, bevroren): welk deel van de turning points werd
                     voorafgegaan door een chain-opbouw (recall), en welk deel
                     van de chain-fires leidde tot een turning point (precisie).
  3. EPISODE-RAPPORT - bevroren episodedefinitie (entry tol 0.50, einde >=1.50
                     vanaf center) uit evening_lite, met HOLD/BREAK en duren.
  4. DAGRAPPORT    - een chapter-gestructureerd rapport uit 1-3.

BELANGRIJK - continuiteitsverklaring:
  De chain-definitie hieronder is een HERIMPLEMENTATIE volgens de gedocumenteerde
  semantiek (venster CHAIN_PRE_MIN voor / CHAIN_POST_MIN na, bucket 10s). De
  originele engine ging verloren; historische chain-getallen van voor deze versie
  zijn NIET 1:1 vergelijkbaar. Vanaf deze versie geldt: fixture = waarheid.
"""
import sys, os, json, gzip, glob, hashlib, statistics
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evening_lite as ev   # bevroren kern v1.1.0 - NIET wijzigen

CANON = dict(
    ENGINE="CANONICAL-PIPELINE", VERSION="1.0.0",
    CORE_ENGINE=ev.CONFIG["ENGINE"], CORE_VERSION=ev.CONFIG["VERSION"],
    CORE_HASH=ev.CFG_HASH,
    # chain (bevroren herimplementatie)
    CHAIN_BUCKET_MS=10_000,        # tijdresolutie van de state-reeks
    CHAIN_PRE_MIN=10,              # venster voor een TP waarin opbouw mag tellen
    CHAIN_POST_MIN=5,              # venster na chain-fire waarin een TP mag tellen
    CHAIN_MIN_DISTINCT=3,          # minimaal aantal onderscheiden actieve states
    CHAIN_ACTIVE_STATES=(2, 3, 4, 5, 6, 7),  # niet-neutrale NEXUS states
    CHAIN_FIRE_STATES=(4, 5),      # absorptiestates = keten "vuurt"
    # unified recall-tolerantie (Nicolas, bevroren)
    MATCH_TOL_PT=0.50, MATCH_TOL_STRICT=0.25,
)
CANON_HASH = hashlib.sha256(json.dumps(CANON, sort_keys=True).encode()).hexdigest()[:8]


def state_series(S, t0=None, t1=None):
    """(bucket_ts, state_id, mid) per CHAIN_BUCKET_MS, laatste waarneming per bucket."""
    out = {}
    for ts, mid, sid, dq, bid, ask in S:
        if sid is None or mid is None:
            continue
        if (t0 is not None and ts < t0) or (t1 is not None and ts >= t1):
            continue
        b = (ts // CANON["CHAIN_BUCKET_MS"]) * CANON["CHAIN_BUCKET_MS"]
        out[b] = (sid, mid)
    return sorted((b, sid, mid) for b, (sid, mid) in out.items())


def chain_fires(series):
    """Chain-fire: binnen het lopende venster >= CHAIN_MIN_DISTINCT verschillende
    actieve states gezien EN huidige state is een fire-state. Een fire sluit het
    venster (herbewapening daarna)."""
    fires = []
    window = []
    pre_ms = CANON["CHAIN_PRE_MIN"] * 60_000
    for b, sid, mid in series:
        window = [(t, s) for (t, s) in window if b - t <= pre_ms]
        if sid in CANON["CHAIN_ACTIVE_STATES"]:
            window.append((b, sid))
        if sid in CANON["CHAIN_FIRE_STATES"]:
            distinct = {s for (_, s) in window}
            if len(distinct) >= CANON["CHAIN_MIN_DISTINCT"]:
                fires.append((b, mid))
                window = []
    return fires


def recall_precision(S, tps, t0=None, t1=None):
    """Unified matching: TP gedekt als een fire binnen [-PRE, +POST] minuten EN
    |fire_mid - tp_price| <= tolerantie. Primair 0.50, strict 0.25."""
    series = state_series(S, t0, t1)
    fires = chain_fires(series)
    pre = CANON["CHAIN_PRE_MIN"] * 60_000
    post = CANON["CHAIN_POST_MIN"] * 60_000
    res = {}
    for label, tol in (("primary", CANON["MATCH_TOL_PT"]),
                       ("strict", CANON["MATCH_TOL_STRICT"])):
        covered = 0
        used = set()
        for ts, price, kind in tps:
            hit = None
            for i, (fb, fmid) in enumerate(fires):
                if i in used:
                    continue
                if -pre <= (ts - fb) <= post and abs(fmid - price) <= tol:
                    hit = i
                    break
            if hit is not None:
                covered += 1
                used.add(hit)
        res[label] = dict(
            tps=len(tps), covered=covered,
            recall=round(covered / len(tps), 4) if tps else None,
            fires=len(fires), matched_fires=len(used),
            precision=round(len(used) / len(fires), 4) if fires else None,
        )
    return res, fires


def day_report(day, upto_h=24, behaviour_t0_h=0, behaviour_t1_h=None):
    """Volledig canoniek dagrapport. Gedragsvenster instelbaar (holdout-discipline)."""
    D = ev.load_day(day, upto_h=upto_h)
    S = D["S"]
    base = S[0][0]
    day0 = ((base + ev.NL_OFFSET_MS) // 86400000) * 86400000 - ev.NL_OFFSET_MS
    def nlms(h, m=0):
        return day0 + (h * 3600 + m * 60) * 1000
    t0 = nlms(behaviour_t0_h)
    t1 = nlms(behaviour_t1_h) if behaviour_t1_h is not None else None

    tps = ev.zigzag(S, t0, t1)
    locs = ev.brick_locations(D["B"], t0, t1 or S[-1][0])
    eps = ev.episodes(S, locs, t0, t1 or S[-1][0])
    closed = [e for e in eps if e["outcome"] in ("HOLD", "BREAK")]
    holds = sum(1 for e in closed if e["outcome"] == "HOLD")
    rp, fires = recall_precision(S, tps, t0, t1)

    dq_all = [d for h in D["dq"] for d in D["dq"][h]]
    return dict(
        engine=CANON["ENGINE"], version=CANON["VERSION"], config_hash=CANON_HASH,
        core=f"{CANON['CORE_ENGINE']} v{CANON['CORE_VERSION']} ({CANON['CORE_HASH']})",
        day=day, upto_h=upto_h,
        behaviour_window=[behaviour_t0_h, behaviour_t1_h],
        integrity=dict(
            snapshots=D["snaps"], crossed=D["crossed"],
            dq_median=statistics.median(dq_all) if dq_all else None,
            states=len(S), trades=len(D["T"]), events=len(D["E"]),
        ),
        behaviour=dict(
            turning_points=len(tps),
            tp_list=[[int(t), float(p), k] for t, p, k in tps],
            brick_locations=len(locs),
            episodes=len(eps), episodes_closed=len(closed),
            hold=holds,
            hold_pct=round(100 * holds / len(closed), 1) if closed else None,
            dur_median_s=sorted(e["dur_s"] for e in closed)[len(closed)//2] if closed else None,
        ),
        chain=dict(fires=len(fires), **{k: v for k, v in rp.items()}),
    )


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-08-13"
    upto = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    r = day_report(day, upto_h=upto, behaviour_t1_h=upto)
    print(json.dumps(r, indent=1))
