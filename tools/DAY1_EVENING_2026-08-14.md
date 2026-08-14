# DAY 1 — EVENING REPORT · 2026-08-14 (00:00–22:00 NL)

Engine: EVENING-REPORT-LITE v1.1.0 · config hash `9624bb9e`
Scope per Option B: behavioural analysis **12:00–15:30 only** (00:00–12:00 was covered in the midday report; the US session 15:30–22:00 is the untouched holdout). US window: integrity checks only.

**Read the honesty panel first tonight (section 5) — the analysis environment was reset again overnight and this report comes from a rebuilt (LITE) pipeline.**

---

## 1. Integrity — full day 00:00–22:00

Loaded: 11 full-tick files · 141k+ state records · 983k trades · 280,576 book snapshots (day portion) · 42.6k orderflow events · 14.3k memory snapshots.

- **Crossed book snapshots: 0 / 280,576 (0.00%)** — the 13-Aug fix continues to hold. Yesterday full day: 0 / 358,973 (0.00%).
- **DQ median = 100.0 in every single hour, 00:00 through 21:59.**
- Median book_age_ms per hour: 87–458 ms, with the familiar profile — slower overnight (250–460 ms), tightening through the sessions to 87–107 ms from 16:00 onward.
- Momentary DQ dips (min values 0–55) appear in several hours, consistent with the overnight/quiet-regime dip profile we baselined on 12/13 Aug. Medians are unaffected; these remain logged as the known watch item, not a new anomaly.

## 2. Behaviour — 12:00–15:30 (London afternoon / pre-US)

**Turning points** (2.5pt reversal): **12** in the window —
12:00 7827.00 B · 12:05 7829.50 T · 12:42 7825.50 B · 13:00 7829.50 T · 13:16 7826.50 B · 13:52 7830.50 T · 14:13 7823.00 B · 14:33 7831.50 T · 14:40 7828.00 B · 14:54 7831.00 T · 15:14 7826.00 B · 15:17 7829.50 T. A rotational afternoon: 7823–7831.50 range, no sustained trend.

**Brick locations qualified in window: 15** (wall ≥ max(50, 4× trailing-hour median), ≥3 qualification snapshots within 5 min). Notable: two-sided bricks at 7827.00 and 7827.75 (both BID and ASK qualified at different times) — the market fought over the same shelf for most of the window; ask-side bricks stacked 7829.75–7835 during the 13:37–13:58 build-up, bid-side support layered 7824–7826.

**Episodes under the frozen definition** (tolerance entry 0.50, end only ≥1.50 from location center):
- 106 episodes, 100 closed, 6 open at window boundary (not counted)
- **HOLD 59/100 = 59%**
- Duration: median 157s · p25 53s · p75 402s

Note: this 59% is from the rebuilt LITE engine on a 3.5-hour rotational window and is **not directly comparable** to the Day 0 (71%) or Day 1 morning figures — different window, different engine build (see section 5).

**NEXUS events in window:** BID_ABSORPTION 201 · ASK_ABSORPTION 273 · BUY_SWEEP 15 · SELL_SWEEP 11 · ICEBERG_BID 2,822 · ICEBERG_ASK 2,187 · LIQUIDITY_STACK 53 · MARKET_STATE_CHANGE 920.

## 3. US session 15:30–22:00 — HELD OUT

Per Option B this window gets **no behavioural analysis, no armings evaluation, no episodes** until v0.1 is frozen. Integrity only: 45,599 state records and 513,543 trades present, continuous coverage, DQ medians 100 every hour, crossed 0. The window is preserved untouched — including Roy's paper armings — as our clean test set.

## 4. Day-over-day DQ comparison (vs 2026-08-13)

Hour-by-hour DQ medians: **identical at 100.0 for all 22 hours on both days.** Crossed: 0.00% both days. Book-age profile also matches. Two consecutive clean days since the 13-Aug fix.

## 5. Honesty panel

- **The analysis workspace was reset overnight for the third time** (restored to a 13-Aug snapshot). Lost again: the consolidated evening pipeline and the armings evaluator. The recorder source and deploy package for tonight survived / were rebuilt and verified.
- Tonight's report therefore comes from a **rebuilt LITE pipeline (v1.1.0, config `9624bb9e`)** implementing the frozen definitions from scratch.
- **Rebuild validation:** the zigzag control on 00:00–12:00 gives 31 turning points today and 34 yesterday, where the previous engine gave 30 on both days. Close, but not identical — so section 2 counts are **indicative** and must not be compared 1:1 against numbers from the previous engine build. Definitions (tolerance 0.50 / departure 1.50 / wall rule) are unchanged.
- **Chain-recall is deliberately absent tonight.** The chain engine was lost in the reset and I will not rebuild-and-trust it in one evening. It returns after the weekend migration, version-pinned in the repository so a reset can never take it again.
- Durability fix in progress tonight: all analysis tools go into the git repository (write token being restored in tonight's maintenance window), so this failure mode ends this weekend with the ChartVPS migration.
- The RAW MBO recorder deploy is scheduled in tonight's 22:00–23:00 window; confirmation follows separately once the first raw rows are verified on disk.
