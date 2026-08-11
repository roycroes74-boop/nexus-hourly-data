# Tick-niveau pilot — 11 aug 2026

## Metadata

### Raw book snapshot formaat
```json
{
  "type": "book",
  "symbol": "ES",
  "ts_ms": 1786456800123,     // UTC milliseconden sinds epoch
  "bids": [[prijs, volume], ...],  // 32 levels, gesorteerd hoog→laag
  "asks": [[prijs, volume], ...]   // 32 levels, gesorteerd laag→hoog
}
```
- **Volumes** = aantal contracts (lots) op dat prijsniveau
- **Prijs** = ES futures prijs (tick size 0.25)
- **Snapshot-frequentie**: event-driven (bij elke book-change), ~50/sec bij actieve markt
- **Timestamps**: UTC milliseconden

### Tijdzone-bevestiging
- Alle `ts_ms` velden zijn **UTC milliseconden**
- NL (CEST) = UTC + 2 uur
- 15:40 NL = 13:40 UTC = ts_ms 1786456800000 (circa)

### Bekende gaps/reconnects
- Geen gaps gedetecteerd in deze vensters. Engine uptime 9+ uur zonder restart.

---

## Bestanden

| File | Inhoud | Snapshots/Events | Grootte |
|---|---|---|---|
| `W1_1540-1555_book.jsonl.gz` | Raw 32-level book, 15:39-15:56 NL | 71.985 snapshots | 817 KB |
| `W1_1540-1555_events.jsonl.gz` | Orderflow events + analytics, 15:39-15:56 NL | 4.931 events | 432 KB |
| `W2_0958-1008_book.jsonl.gz` | Raw 32-level book, 09:57-10:09 NL | 9.257 snapshots | 129 KB |
| `W2_0958-1008_events.jsonl.gz` | Orderflow events + analytics, 09:57-10:09 NL | 2.463 events | 230 KB |

---

## Gzip-meting volledige dag

```
Origineel: 430 MB (ES_raw_20260811.jsonl, 867.000+ snapshots, ~16 uur)
Gegzipt:   ~12 MB
```

**Conclusie:** de volledige dag past gegzipt in ~12MB. Per uur = ~0.75MB gegzipt.
Dit is klein genoeg om ALLES per uur naar GitHub te pushen zonder filtering.

---

## Venster-details

### W1: 15:40-15:55 NL (crash-bodem zone 7770-7772)
- 71.985 book snapshots (~4.500/min = ~75/sec — zeer actief, US open)
- 4.931 events (absorption, sweep, iceberg, state changes)
- Bevat: mes-vang 15:44 (long 7780 → -3) EN echte bodem 15:48-15:51 (7771.5, +6 rally)

### W2: 09:58-10:08 NL (spoof-top 7780.5 + bid-muur-collapse)
- 9.257 book snapshots (~925/min = ~15/sec — London sessie)
- 2.463 events
- Bevat: sniper-signatuur 10:03:17 op 7779.5, entry 10:05 op 7777
