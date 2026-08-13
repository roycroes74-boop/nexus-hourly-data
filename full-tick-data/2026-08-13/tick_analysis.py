import gzip, json, sys
from datetime import datetime, timezone, timedelta

nl = timezone(timedelta(hours=2))

def analyze_window(filename, hour, min_start, min_end, label):
    print('=' * 90)
    print(f'  {label}')
    print(f'  TICK-BY-TICK MBO-32 ANALYSE — {hour:02d}:{min_start:02d} tot {hour:02d}:{min_end:02d} NL')
    print('=' * 90)
    print()
    
    with gzip.open(filename, 'rt') as f:
        for line in f:
            obj = json.loads(line)
            ts = obj.get('ts_ms')
            if not ts: continue
            t = datetime.fromtimestamp(ts/1000, nl)
            
            if not (t.hour == hour and min_start <= t.minute <= min_end):
                continue
            
            rtype = obj.get('type', '')
            
            if rtype == 'book':
                bids = obj.get('bids', [])
                asks = obj.get('asks', [])
                if bids and asks:
                    # bids/asks can be [[price, size], ...] or [{"price":x,"size":y}, ...]
                    if isinstance(bids[0], list):
                        top_bid_p, top_bid_s = bids[0][0], bids[0][1]
                        top_ask_p, top_ask_s = asks[0][0], asks[0][1]
                        bid5 = sum(b[1] for b in bids[:5])
                        ask5 = sum(a[1] for a in asks[:5])
                    else:
                        top_bid_p = bids[0].get('price', 0)
                        top_bid_s = bids[0].get('size', 0)
                        top_ask_p = asks[0].get('price', 0)
                        top_ask_s = asks[0].get('size', 0)
                        bid5 = sum(b.get('size', 0) for b in bids[:5])
                        ask5 = sum(a.get('size', 0) for a in asks[:5])
                    
                    ratio = bid5 / ask5 if ask5 > 0 else 99
                    # Print every 5 seconds
                    if t.second % 5 == 0 and t.microsecond < 200000:
                        mid = (top_bid_p + top_ask_p) / 2
                        print(f'  {t.strftime("%H:%M:%S")}  📖 BOOK | mid={mid:.2f} | bid={top_bid_p}×{top_bid_s} ask={top_ask_p}×{top_ask_s} | 5lvl: bid={bid5} ask={ask5} | B/A ratio={ratio:.2f}')
            
            elif rtype == 'trade':
                price = obj.get('price')
                vol = obj.get('volume', 1)
                side = obj.get('side', '?')
                if vol >= 3:  # Only show significant trades
                    arrow = '🔴' if side == 'sell' else '🟢'
                    print(f'  {t.strftime("%H:%M:%S.%f")[:12]}  {arrow} TRADE | {side.upper():4} {vol}× @ {price}')
            
            elif rtype == 'orderflow_event':
                p = obj.get('payload', obj)
                kind = p.get('kind', '')
                price = p.get('price', p.get('level_price', ''))
                vol = p.get('volume', p.get('executed_volume', 0)) or 0
                repl = p.get('replenishments', '')
                
                if 'ABSORPTION' in kind or 'SWEEP' in kind or 'STACK' in kind:
                    print(f'  {t.strftime("%H:%M:%S.%f")[:12]}  ⚡ {kind} @ {price} | vol={vol} repl={repl}')
                elif 'STATE' in kind:
                    new_state = p.get('new_state', p.get('state_name', ''))
                    print(f'  {t.strftime("%H:%M:%S.%f")[:12]}  🔄 STATE_CHANGE → {new_state} @ {price}')
                elif 'ICEBERG' in kind and vol >= 80:
                    side_label = 'BID(koper)' if 'BID' in kind else 'ASK(verkoper)'
                    print(f'  {t.strftime("%H:%M:%S.%f")[:12]}  🧊 ICEBERG {side_label} @ {price} vol={vol}')
            
            elif rtype == 'analytics_state':
                p = obj.get('payload', obj)
                mid = p.get('mid')
                dq = p.get('dq', 100)
                imb = p.get('imbalance', 0)
                ms = p.get('market_state', {})
                state_name = ms.get('name', '') if isinstance(ms, dict) else ''
                if t.second % 10 == 0 and t.microsecond < 200000:
                    print(f'  {t.strftime("%H:%M:%S")}  📊 NEXUS | mid={mid} imbalance={imb:.3f} dq={dq} state={state_name}')
    print()

# TRADE 1: LONG bounce at 7768 around 04:33-04:37
analyze_window('04h00_06h00_NL_FULL_MBO32.jsonl.gz', 4, 33, 37, 
    'TRADE 1: LONG @ 7768 — Prijs daalt naar 7768, bounce naar 7774+')

print('\n' + '─' * 90 + '\n')

# TRADE 2: LONG bounce at 7772 around 06:19-06:24
analyze_window('06h00_08h00_NL_FULL_MBO32.jsonl.gz', 6, 19, 24,
    'TRADE 2: LONG @ 7772 — Prijs daalt naar 7772, bounce naar 7777+')
