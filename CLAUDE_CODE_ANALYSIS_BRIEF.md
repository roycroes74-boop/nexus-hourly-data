# NEXUS MBO-32 Data Analysis Brief for Claude Code

## Doel
Analyseer NEXUS orderflow events voor ES futures. De data bevat ALLE MBO-32 level features.
Claude Code kan deze bestanden direct lezen van GitHub (roycroes74-boop/tradingalgo).

## Data locatie
- **GitHub repo:** `roycroes74-boop/tradingalgo`
- **Pad:** `nexus-hourly-export/hourly-data/YYYY-MM-DD/hour_HH.jsonl`
- **Formaat:** JSONL (één JSON object per regel)
- **Update frequentie:** elk uur automatisch
- **Retentie:** 7 dagen

## Hoe te gebruiken
1. User stuurt een chart screenshot + tijdstip + prijslevel
2. Open het juiste uur-bestand (bv. `2026-08-11/hour_16.jsonl`)
3. Filter events rond het gevraagde tijdstip en prijslevel
4. Analyseer alle MBO-32 features en geef conclusies

## Event envelope structuur
```json
{
  "schema": "nexus.feed.v1",
  "stream": "roy-es",
  "session_id": "abc123",
  "seq": 418,
  "type": "orderflow_event",
  "symbol": "ES",
  "ts_ms": 1786111207090,
  "source": "NEXUS_HEADLESS_RITHMIC_FANOUT",
  "payload": { ... }
}
```

**Tijdstip:** `ts_ms` = Unix epoch milliseconds (UTC). NL = UTC+2 (zomer).

## ALLE event types (payload.kind)

### 1. MARKET_STATE_CHANGE
Regime-transitie. 14 mogelijke states:
| ID | State | Betekenis |
|---|---|---|
| 0 | UNKNOWN | Geen data |
| 1 | BALANCED | Evenwicht |
| 2 | BID DOMINANT | Kopers sterker |
| 3 | ASK DOMINANT | Verkopers sterker |
| 4 | BID ABSORPTION | Bids absorberen sells |
| 5 | ASK ABSORPTION | Asks absorberen buys |
| 6 | BREAKOUT BUILDUP UP | Opwaartse druk bouwt op |
| 7 | BREAKOUT BUILDUP DN | Neerwaartse druk bouwt op |
| 8 | BULL TRAP RISK | Valse uitbraak omhoog |
| 9 | BEAR TRAP RISK | Valse uitbraak omlaag |
| 10 | VACUUM UP | Gat in asks → snelle move omhoog |
| 11 | VACUUM DN | Gat in bids → snelle move omlaag |
| 12 | REVERSAL RISK UP | Mogelijke top |
| 13 | REVERSAL RISK DN | Mogelijke bodem |

Velden: `state_id`, `state`, `previous_state_id`, `previous_state`, `confidence`, `reason`

### 2. BUY_SWEEP / SELL_SWEEP
Agressieve doorbraak door meerdere levels.
Velden:
- `direction`: buy/sell
- `price`: eindprijs
- `volume`: totaal agressief volume
- `raw_score`: ruwe sterkte
- `calibrated_score`: gekalibreerde score (betrouwbaarder)
- `dq`: data quality (0-100)
- `duration_ms`: hoe snel de sweep was
- `trade_count`: aantal trades in de sweep
- `levels_swept`: hoeveel prijslevels doorbroken
- `first_price`: startprijs

Thresholds: 140ms window, min 18 vol, 4 trades, 3 levels

### 3. BID_ABSORPTION / ASK_ABSORPTION
Level wordt verdedigd — agressieve orders worden geabsorbeerd.
Velden:
- `price`: het verdedigde level
- `volume`: agressief volume dat geabsorbeerd is
- `raw_score` / `calibrated_score`
- `dq`
- `features.replenishments`: RELOAD COUNT (hoe vaak het level is aangevuld) — KEY METRIC
- `features.resting_size`: hoeveel er rust op het level
- `features.aggressive_volume`: hoeveel er tegenaan is gegooid
- `features.delta`: netto koop-verkoop druk

**Belangrijk:** replenishments ≥ 50 = sterke verdediging (Nicolas' richtlijn)

### 4. LIQUIDITY_STACK
Grote resting order(s) op een level — "muur".
Velden:
- `price`: waar de muur staat
- `direction`: bid (steun) of ask (weerstand)
- `volume`: grootte van de muur
- Geeft TP-targets en steun/weerstand levels

### 5. LIQUIDITY_PULL
Grote resting order VERDWIJNT van een level — kant geeft op.
Velden:
- `price`: waar de order verdween
- `direction`: bid/ask
- `volume`: hoeveel verdween
- Signaal: die kant is zwak, prijs gaat die richting op

**BELANGRIJK:** PULL = 0 met TBBO (1 level). Werkt ALLEEN met 32 levels.

### 6. ICEBERG_BID_CANDIDATE / ICEBERG_ASK_CANDIDATE
Verborgen volume gedetecteerd — iemand koopt/verkoopt meer dan zichtbaar.
Velden:
- `price`: level waar iceberg zit
- `volume`: uitgevoerd volume (niet de hidden grootte!)
- `direction`: bid/ask

**Let op:** ~15.000 iceberg candidates per dag per side. Niet elke iceberg is een signaal.
Combineer met absorption voor betrouwbare entries.

### 7. BID_LIQUIDITY_BEHAVIOR_RISK / ASK_LIQUIDITY_BEHAVIOR_RISK
Verdacht gedrag gedetecteerd (spoof/layering).
- Hangt af van PULL data (werkt alleen met 32 levels)

### 8. LIQUIDITY_MEMORY (via /liquidity-memory endpoint, ook in events)
Historische liquidity zones — levels waar eerder grote activiteit was.
Velden per node:
- `price`: het level
- `side`: bid/ask
- `absorbed_volume`: gewogen geabsorbeerd volume
- `pulled_volume`: gewogen verdwenen volume
- `stacked_volume`: gewogen gestapeld volume
- `swept_volume`: gewogen gesweept volume
- `touches`: hoe vaak prijs hier was
- `score`: composiet sterkte-score
- `historical_weight`: genormaliseerd (0-1) tegen sterkste node
- `active`: actief of inactief

Configuratie: 8-uur half-life, 5-dag retentie, max 320 nodes, top 40 in snapshots.

## Score interpretatie
- `raw_score`: deterministische regel-score
- `calibrated_score`: gecombineerd met empirische forward-outcome data
- `dq`: data quality (0-100). Hoe hoger, hoe betrouwbaarder het event.
  - DQ ~50 = TBBO (1 level) — beperkt
  - DQ ~90-100 = 32 levels — volledig betrouwbaar
- `calibration_status`: cold_start / blended / empirical

## Analyse workflow

### Bij een chart screenshot + tijdstip + level:
1. **Filter events** ±60 seconden rond het tijdstip, ±5 punten rond het level
2. **Check ABSORPTION**: was er verdediging? Hoeveel reloads?
3. **Check SWEEP**: was er een doorbraak?
4. **Check STACK**: waar liggen de muren (= TP targets)?
5. **Check PULL**: verdwijnt er liquidity (= zwakke kant)?
6. **Check ICEBERG**: verborgen kopers/verkopers?
7. **Check MARKET_STATE**: welk regime? Trap risk?
8. **Check MEMORY**: historisch sterk level?
9. **Conclusie**: entry/exit/TP/richting/sterkte

### Voor trade entry analyse:
- Sniper 3-step: Level touch → Absorption (repl≥50) → Iceberg/Sweep = ENTRY
- Market state 8 (Bull Trap) blokkeert LONG
- Market state 9 (Bear Trap) blokkeert SHORT
- Time-decay: bevestiging binnen 4s = score 1.0, na 52s = score 0.4

### Voor TP target analyse:
- Volgende STACK level = eerste TP
- MEMORY zones met hoge score = sterke levels
- PULL op het TP level = level gaat breken → door naar volgende
- Geen PULL + nieuwe STACK = level houdt → exit

### Voor exit analyse (thesis deterioration):
- Prijs stalt (geen nieuwe high/low in 30s)
- Geen nieuwe absorption in je richting
- Market state flipt naar tegengesteld
- PULL op jouw kant (verdediging verdwijnt)
- Meerdere van deze tegelijk = EXIT

### Voor contract add-on analyse:
- Pullback + nieuwe absorption op entry-level = ADD
- ICEBERG groeit op jouw kant = ADD
- Geen PULL op jouw kant (verdediging intact) = veilig
- Market state nog steeds in je richting = ADD
- 7-punt checklist: alle 7 moeten "ja" zijn

## Tijdzone conversie
- Data is in UTC (ts_ms)
- NL = UTC + 2 (zomertijd aug 2026)
- Voorbeeld: 16:42 NL = 14:42 UTC = ts_ms rond 1786...(bereken)
- `datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc) + timedelta(hours=2)`

## ES tick size
- 1 tick = 0.25 punt
- 1 punt = $50 (ES) of $5 (MES)
- Spread normaal = 0.25 (1 tick)
