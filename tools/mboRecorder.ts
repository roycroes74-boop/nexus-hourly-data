/**
 * MBO Recorder — eigen opnamelaag naast NEXUS (route B).
 *
 * Schrijft drie stromen. NEXUS ziet hier niets van; het boekbericht naar de
 * fanout blijft ongewijzigd [price, size].
 *
 *   A  level_YYYY-MM-DD_HH.jsonl.gz   niveau-aggregaten, elke emit (~3-10/s)
 *   B  order_YYYY-MM-DD_HH.jsonl.gz   orderlevenscyclus, 1 regel per order bij einde
 *   C  raw_YYYY-MM-DD_HH.jsonl.gz     ruwe MBO-berichten, alleen als RAW_MBO=1
 *
 * BELANGRIJK — cadans-afhankelijkheid (Nicolas, punt 6 en 9):
 *   Bestand A wordt geschreven op de emit-cadans en is dus cadans-GEBONDEN.
 *   Bestand B is event-gedreven (1 regel per order, bij zijn einde) en dus
 *   cadans-ONAFHANKELIJK. Bestand C is de ruwe berichtenstroom.
 *   Elke regel draagt `cad` met het regimelabel zodat ze nooit gepoold worden.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as zlib from 'zlib';

/** Regimelabel. Gaat naar 25MS zodra de emit-throttle op 25 ms staat. */
export const BOOK_CADENCE_REGIME = process.env.BOOK_CADENCE_REGIME || 'PRE25MS';

const OUT_DIR = process.env.MBO_REC_DIR || '/var/data/mbo-recording';
const RAW_ENABLED = process.env.RAW_MBO === '1';
/** Ring buffer: 10 s vóór en 10 s ná een gebeurtenis (Nicolas, A2). */
const RING_SECONDS = Number(process.env.CROSSED_RING_S || 10);
/**
 * Piekdrempel, exact zoals Nicolas hem formuleerde in A2:
 *   spike = count_60s >= max(5, 4 × rolling_median_count_60s)
 * De ondergrens van 5 is essentieel: bij een mediaan van nul zou een zuiver
 * multiplicatieve drempel bij elke enkele gebeurtenis afgaan.
 */
const SPIKE_FACTOR = Number(process.env.CROSSED_SPIKE_FACTOR || 4);
const SPIKE_FLOOR = Number(process.env.CROSSED_SPIKE_FLOOR || 5);
/**
 * Tweede, onafhankelijke trigger (Nicolas, A2): een prune binnen de dichtstbijzijnde
 * 5 boekniveaus wordt ALTIJD forensisch vastgelegd, ook onder de teldrempel.
 * "A transient crossed condition 25 levels away is very different from one
 *  touching executable top-of-book structure."
 *   diep + zeldzaam  → telemetrie (alleen tellen)
 *   dicht bij markt  → ruwe forensische opname
 */
const NEAR_MARKET_LEVELS = Number(process.env.CROSSED_NEAR_LEVELS || 5);
const TICK = 0.25;

type Level = {
  price: number;
  size: number;
  orders: number;
  largest: number;
  mean: number;
  median: number;
  oldestAgeMs: number;
  medianAgeMs: number;
  newQty1s: number;
  cancelQty1s: number;
};

/** Per-order boekhouding voor bestand B. */
export type OrderLife = {
  side: number;
  price: number;
  firstSeen: number;
  lastSeen: number;
  initialSize: number;
  maxSize: number;
  lastSize: number;
  modifyCount: number;
  /** aantal keer dat de grootte omhoog ging na een verlaging = herladen */
  reloadCount: number;
  /** som van alle verlagingen die met een trade samenvielen (heuristiek) */
  executedQty: number;
  /** som van alle verlagingen zonder trade (heuristiek) */
  cancelledQty: number;
};

class Stream {
  private gz: zlib.Gzip | null = null;
  private hour = '';
  constructor(private prefix: string) {}

  write(obj: unknown, ts: number): void {
    const h = new Date(ts).toISOString().slice(0, 13).replace('T', '_');
    if (h !== this.hour) {
      this.gz?.end();
      fs.mkdirSync(OUT_DIR, { recursive: true });
      const f = path.join(OUT_DIR, `${this.prefix}_${h}.jsonl.gz`);
      this.gz = zlib.createGzip({ level: 6 });
      this.gz.pipe(fs.createWriteStream(f, { flags: 'a' }));
      this.hour = h;
      console.log(`[MBORec] nieuw bestand: ${f}`);
    }
    this.gz!.write(JSON.stringify(obj) + '\n');
  }

  close(): void {
    this.gz?.end();
    this.gz = null;
    this.hour = '';
  }
}

export class MboRecorder {
  private lvl = new Stream('level');
  private ord = new Stream('order');
  private raw = new Stream('raw');

  /** ruwe berichten van de laatste RING_SECONDS, voor het geval er een piek komt */
  private ring: Array<{ ts: number; msg: unknown }> = [];
  /** tijdstempels van crossed_pruned-gebeurtenissen, laatste 10 min */
  private crossedTs: number[] = [];
  private crossedTotal = 0;
  private spikeDumpUntil = 0;

  /** prijs → tijdstip van de laatste trade daar; voor executed-vs-cancelled */
  private lastTradeAt = new Map<number, number>();
  private static readonly TRADE_MATCH_MS = 250;

  /** per 1 s, per prijs+side: nieuw geplaatst en geannuleerd volume */
  private flow = new Map<string, { newQty: number; cancelQty: number }>();
  private flowSecond = 0;

  // ───────────────────────── trades ─────────────────────────

  /** Aanroepen bij elke trade, zodat DELETE's aan een trade gekoppeld kunnen worden. */
  onTrade(price: number, ts: number): void {
    this.lastTradeAt.set(price, ts);
    if (this.lastTradeAt.size > 4000) {
      for (const [p, t] of this.lastTradeAt) {
        if (ts - t > 5000) this.lastTradeAt.delete(p);
      }
    }
  }

  /**
   * Was er een trade op deze prijs vlak voor dit moment?
   * HEURISTIEK — Rithmic zegt niet waarom een order verdwijnt. Alles wat hierop
   * steunt heet daarom `*_inferred` en mag nooit als feit gerapporteerd worden.
   */
  private tradedRecently(price: number, ts: number): boolean {
    const t = this.lastTradeAt.get(price);
    return t !== undefined && ts - t <= MboRecorder.TRADE_MATCH_MS;
  }

  // ───────────────────── ruwe berichten + flow ─────────────────────

  private keysLogged = false;

  /**
   * Aanroepen bij élk binnenkomend DepthByOrder-bericht, vóór verwerking.
   *
   * Het volledige gedecodeerde bericht gaat ongewijzigd de opname in, zodat alle
   * native Rithmic-vlaggen bewaard blijven (Nicolas, B1). Daarnaast normaliseren
   * we de beurstijd apart: `ssboe`/`usecs` worden in het huidige diepte-pad
   * weggegooid, terwijl B1 die expliciet vereist voor ordening en
   * levenscyclus-reconstructie.
   */
  onRawMessage(msg: any, ts: number): void {
    // eenmalig: welke velden geeft Rithmic ons werkelijk? Voor de documentatie
    // van het fixture-formaat, zodat we niet op aannames bouwen.
    if (!this.keysLogged && msg && typeof msg === 'object') {
      this.keysLogged = true;
      console.log(`[MBORec] DepthByOrder velden: ${Object.keys(msg).sort().join(', ')}`);
    }

    // beurstijd in ms; valt terug op onze ontvangsttijd als Rithmic hem niet meestuurt
    const exTs =
      msg?.ssboe !== undefined && msg?.usecs !== undefined
        ? msg.ssboe * 1000 + msg.usecs / 1000
        : null;

    if (RAW_ENABLED) this.raw.write({ ts, ex_ts_ms: exTs, cad: BOOK_CADENCE_REGIME, msg }, ts);

    this.ring.push({ ts, msg });
    const cutoff = ts - RING_SECONDS * 1000;
    while (this.ring.length && this.ring[0].ts < cutoff) this.ring.shift();

    // dump-venster na een piek: schrijf alles weg tot spikeDumpUntil
    if (ts <= this.spikeDumpUntil && !RAW_ENABLED) {
      this.raw.write({ ts, cad: BOOK_CADENCE_REGIME, forensic: true, phase: 'post', msg }, ts);
    }
  }

  /** Per order-update: houd nieuw/geannuleerd volume per seconde per niveau bij. */
  onOrderDelta(price: number, side: number, deltaQty: number, ts: number): void {
    const sec = Math.floor(ts / 1000);
    if (sec !== this.flowSecond) {
      this.flow.clear();
      this.flowSecond = sec;
    }
    const k = `${side}:${price}`;
    const e = this.flow.get(k) || { newQty: 0, cancelQty: 0 };
    if (deltaQty > 0) e.newQty += deltaQty;
    else if (deltaQty < 0 && !this.tradedRecently(price, ts)) e.cancelQty += -deltaQty;
    this.flow.set(k, e);
  }

  private flowFor(price: number, side: number): { newQty: number; cancelQty: number } {
    return this.flow.get(`${side}:${price}`) || { newQty: 0, cancelQty: 0 };
  }

  // ─────────────────────── crossed_pruned ───────────────────────

  /** Aantal crossed-gebeurtenissen per minuut over de laatste 10 min, voor de mediaan. */
  private rollingMedianPerMin(ts: number): number {
    const buckets = new Array(10).fill(0);
    for (const t of this.crossedTs) {
      const idx = Math.floor((ts - t) / 60_000);
      if (idx >= 0 && idx < 10) buckets[idx]++;
    }
    const s = [...buckets].sort((a, b) => a - b);
    return (s[4] + s[5]) / 2;
  }

  /**
   * Aanroepen bij elke crossed-opruiming, ook als er 0 orders verwijderd zijn.
   * Permanent geteld; ruwe forensische opname alleen bij een piek of dicht bij de markt.
   *
   * LET OP (Nicolas, A2): dit verandert NIETS aan het boekgedrag. Alleen opnemen.
   */
  onCrossedPruned(
    removed: number,
    ts: number,
    detail: {
      price: number;
      side: number;
      bestBid: number;
      bestAsk: number;
      orderIds?: string[];
      bookBefore?: unknown;
      bookAfter?: unknown;
      seq?: number;
    },
  ): void {
    this.crossedTotal += 1;
    this.crossedTs.push(ts);
    while (this.crossedTs.length && this.crossedTs[0] < ts - 600_000) this.crossedTs.shift();

    const count60 = this.crossedTs.filter((t) => t > ts - 60_000).length;
    const median60 = this.rollingMedianPerMin(ts);

    // trigger 1 — teldrempel met ondergrens (mediaan nul mag niet alles laten afgaan)
    const spike = count60 >= Math.max(SPIKE_FLOOR, SPIKE_FACTOR * median60);

    // trigger 2 — dicht bij de uitvoerbare structuur, ongeacht de telling
    const mid = (detail.bestBid + detail.bestAsk) / 2;
    const levelsAway = Math.round(Math.abs(detail.price - mid) / TICK);
    const nearMarket = levelsAway <= NEAR_MARKET_LEVELS;

    if ((spike || nearMarket) && ts > this.spikeDumpUntil) {
      const reason = nearMarket ? 'near_market' : 'count_spike';
      console.warn(
        `[MBORec] crossed_pruned FORENSISCH (${reason}): ${count60}/min, mediaan ${median60.toFixed(1)}, ${levelsAway} niveaus van mid → ruwe sequentie bewaard`,
      );
      // 10 s vóór, uit de ringbuffer
      for (const r of this.ring) {
        this.raw.write({ ts: r.ts, cad: BOOK_CADENCE_REGIME, forensic: reason, phase: 'pre', msg: r.msg }, r.ts);
      }
      // 10 s ná: onRawMessage schrijft door tot spikeDumpUntil
      this.spikeDumpUntil = ts + RING_SECONDS * 1000;
    }

    this.lvl.write(
      {
        t: ts,
        cad: BOOK_CADENCE_REGIME,
        type: 'crossed_pruned',
        removed,
        count_60s: count60,
        rolling_median_60s: median60,
        levels_from_mid: levelsAway,
        near_market: nearMarket,
        spike,
        total: this.crossedTotal,
        price: detail.price,
        side: detail.side,
        best_bid: detail.bestBid,
        best_ask: detail.bestAsk,
        order_ids: detail.orderIds ?? null,
        seq: detail.seq ?? null,
        book_before: detail.bookBefore ?? null,
        book_after: detail.bookAfter ?? null,
      },
      ts,
    );
  }

  // ─────────────────────── bestand A ───────────────────────

  /**
   * Aanroepen op het moment van emit naar de fanout, met de per-order details
   * per niveau. `orders` is per niveau de lijst van (size, firstSeenMs).
   */
  onSnapshot(
    ts: number,
    bestBid: number,
    bestAsk: number,
    bids: Array<{ price: number; side: number; orders: Array<{ size: number; firstSeen: number }> }>,
    asks: Array<{ price: number; side: number; orders: Array<{ size: number; firstSeen: number }> }>,
  ): void {
    const pack = (
      rows: Array<{ price: number; side: number; orders: Array<{ size: number; firstSeen: number }> }>,
    ): number[][] =>
      rows.slice(0, 12).map((r) => {
        const sizes = r.orders.map((o) => o.size).sort((a, b) => a - b);
        const ages = r.orders.map((o) => ts - o.firstSeen).sort((a, b) => a - b);
        const n = sizes.length || 1;
        const total = sizes.reduce((a, b) => a + b, 0);
        const f = this.flowFor(r.price, r.side);
        return [
          r.price,
          total,
          sizes.length,
          sizes[sizes.length - 1] || 0,
          Math.round((total / n) * 100) / 100,
          sizes[Math.floor(sizes.length / 2)] || 0,
          ages[ages.length - 1] || 0,
          ages[Math.floor(ages.length / 2)] || 0,
          f.newQty,
          f.cancelQty,
        ];
      });

    this.lvl.write(
      {
        t: ts,
        cad: BOOK_CADENCE_REGIME,
        type: 'level',
        // uitvoerbare prijzen op het beslismoment (Nicolas, punt 12)
        bb: bestBid,
        ba: bestAsk,
        b: pack(bids),
        a: pack(asks),
      },
      ts,
    );
  }

  // ─────────────────────── bestand B ───────────────────────

  /** Aanroepen wanneer een order definitief verdwijnt. */
  onOrderEnd(key: string, o: OrderLife, ts: number): void {
    this.ord.write(
      {
        id: key,
        cad: BOOK_CADENCE_REGIME,
        side: o.side,
        price: o.price,
        first_seen: o.firstSeen,
        last_seen: ts,
        initial_size: o.initialSize,
        max_size: o.maxSize,
        // HEURISTIEK, geen feit — zie tradedRecently()
        executed_qty_inferred: o.executedQty,
        cancelled_qty_inferred: o.cancelledQty,
        modify_count: o.modifyCount,
        reload_count: o.reloadCount,
        lifetime_ms: ts - o.firstSeen,
      },
      ts,
    );
  }

  close(): void {
    this.lvl.close();
    this.ord.close();
    this.raw.close();
  }
}
