#!/usr/bin/env python3
"""
V2 Sniper Backtest Engine (Server-side, Option A) - OPTIMIZED
Only loads orderflow events + states (small). Uses states for price tracking.
"""
import json, gzip, os, sys
from datetime import datetime, timezone, timedelta

nl = timezone(timedelta(hours=2))

# === V2 SNIPER SETTINGS ===
ICE_ONLY_VOL = 150
EXHAUSTION_WINDOW_MS = 5000
ICE_FIGHT_RATIO = 1.5
CONFIRM_WINDOW_S = 15
COOLDOWN_S = 30
MAX_RISK_USD = 100
TICK_VALUE = 5.0
NOODSTOP_PTS = 4.0
THESIS_TIMEOUT_S = 180
EXIT_DOMINANCE_RATIO = 1.5

BLOCKED_LONG_STATES = ['BREAKOUT_UP']
BLOCKED_SHORT_STATES = ['BREAKOUT_DOWN']

def run_backtest(date_str, start_hour=0, end_hour=24):
    base = f"/home/ubuntu/nexus-hourly-export/full-tick-data/{date_str}"
    if not os.path.isdir(base):
        return {"error": f"No data for {date_str}", "trades": []}
    
    # Only load events and states (skip book_snapshot and trade - too large)
    events = []
    states = []
    
    for f in sorted(os.listdir(base)):
        if not f.endswith('.jsonl.gz'):
            continue
        try:
            file_start_h = int(f[:2])
            file_end_h = int(f[5:7])
            if file_end_h <= start_hour or file_start_h >= end_hour:
                continue
        except:
            pass
        
        with gzip.open(os.path.join(base, f), 'rt') as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    rt = rec.get('_record_type', '')
                    ts = rec.get('ts_ms', 0)
                    if rt == 'nexus_orderflow_event':
                        payload = rec.get('payload', rec)
                        events.append({
                            'ts_ms': ts,
                            'kind': payload.get('kind', ''),
                            'price': payload.get('price'),
                            'volume': payload.get('volume', 0),
                            'repl': payload.get('reloads', payload.get('repl', 0)),
                        })
                    elif rt == 'nexus_state':
                        payload = rec.get('payload', rec)
                        bid = payload.get('bid', 0)
                        ask = payload.get('ask', 0)
                        if bid and ask:
                            states.append({
                                'ts_ms': ts,
                                'market_state': payload.get('market_state', ''),
                                'mid': (bid + ask) / 2,
                            })
                except:
                    pass
    
    if not events:
        return {"error": f"No events for {date_str}", "trades": []}
    
    events.sort(key=lambda x: x['ts_ms'])
    states.sort(key=lambda x: x['ts_ms'])
    
    # Build price index for fast lookup
    def get_mid_at(ts):
        # Binary search in states
        lo, hi = 0, len(states) - 1
        while lo <= hi:
            m = (lo + hi) // 2
            if states[m]['ts_ms'] <= ts:
                lo = m + 1
            else:
                hi = m - 1
        return states[hi]['mid'] if hi >= 0 else 0
    
    def get_state_at(ts):
        lo, hi = 0, len(states) - 1
        while lo <= hi:
            m = (lo + hi) // 2
            if states[m]['ts_ms'] <= ts:
                lo = m + 1
            else:
                hi = m - 1
        return states[hi]['market_state'] if hi >= 0 else ''
    
    def get_mfe_mae(entry_ts, exit_ts, entry_price, side):
        """Get MFE/MAE from states between entry and exit"""
        mfe = 0.0
        mae = 0.0
        for s in states:
            if s['ts_ms'] < entry_ts:
                continue
            if s['ts_ms'] > exit_ts:
                break
            pnl = (s['mid'] - entry_price) if side == 'LONG' else (entry_price - s['mid'])
            if pnl > mfe:
                mfe = pnl
            if pnl < mae:
                mae = pnl
        return mfe, mae
    
    # === RUN V2 ENGINE ===
    journal = []
    active_trade = None
    last_signal_ts = 0
    recent_events = []
    
    for ev in events:
        ts = ev['ts_ms']
        kind = ev['kind']
        price = ev['price']
        vol = ev['volume'] or 0
        
        current_state = get_state_at(ts)
        
        # Maintain recent events (30s window)
        recent_events = [e for e in recent_events if ts - e['ts_ms'] <= 30000]
        recent_events.append(ev)
        
        # === TRADE MANAGEMENT ===
        if active_trade:
            mid = get_mid_at(ts)
            if not mid:
                continue
            entry_p = active_trade['entry_price']
            side = active_trade['side']
            pnl = (mid - entry_p) if side == 'LONG' else (entry_p - mid)
            
            exit_reason = None
            
            # 1. Noodstop
            if pnl <= -NOODSTOP_PTS:
                exit_reason = f"noodstop -{NOODSTOP_PTS}pt"
            
            # 2. Opposing force dominates
            if not exit_reason:
                if side == 'LONG' and 'ASK' in kind and ('ICEBERG' in kind or 'ABSORPTION' in kind):
                    if vol >= active_trade['entry_vol'] * EXIT_DOMINANCE_RATIO:
                        exit_reason = f"tegenpartij domineert ({kind} vol={vol})"
                elif side == 'SHORT' and 'BID' in kind and ('ICEBERG' in kind or 'ABSORPTION' in kind):
                    if vol >= active_trade['entry_vol'] * EXIT_DOMINANCE_RATIO:
                        exit_reason = f"tegenpartij domineert ({kind} vol={vol})"
            
            # 3. Thesis timeout
            if not exit_reason:
                defense_kinds = ['BID_ABSORPTION', 'ICEBERG_BID'] if side == 'LONG' else ['ASK_ABSORPTION', 'ICEBERG_ASK']
                last_defense = max([e['ts_ms'] for e in recent_events if any(dk in e['kind'] for dk in defense_kinds)], default=active_trade['entry_ts'])
                if ts - last_defense > THESIS_TIMEOUT_S * 1000 and pnl < 2.0:
                    exit_reason = f"thesis verdwenen ({THESIS_TIMEOUT_S}s)"
            
            # 4. State flip
            if not exit_reason:
                if side == 'LONG' and 'BREAKOUT_DOWN' in current_state:
                    exit_reason = "state flip"
                elif side == 'SHORT' and 'BREAKOUT_UP' in current_state:
                    exit_reason = "state flip"
            
            if exit_reason:
                exit_price = mid
                final_pnl = (exit_price - entry_p) if side == 'LONG' else (entry_p - exit_price)
                contracts = active_trade['contracts']
                mfe, mae = get_mfe_mae(active_trade['entry_ts'], ts, entry_p, side)
                
                journal.append({
                    'side': side,
                    'entry_price': entry_p,
                    'entry_time': datetime.fromtimestamp(active_trade['entry_ts']/1000, nl).strftime('%H:%M:%S'),
                    'exit_price': round(exit_price, 2),
                    'exit_time': datetime.fromtimestamp(ts/1000, nl).strftime('%H:%M:%S'),
                    'pnl_pts': round(final_pnl, 2),
                    'pnl_usd': round(final_pnl * contracts * TICK_VALUE, 2),
                    'mfe_pts': round(mfe, 2),
                    'mae_pts': round(mae, 2),
                    'contracts': contracts,
                    'sl_pts': active_trade['sl_pts'],
                    'duration_s': round((ts - active_trade['entry_ts']) / 1000),
                    'exit_reason': exit_reason,
                    'pattern': active_trade['pattern'],
                    'score': active_trade['score'],
                })
                active_trade = None
            continue
        
        # === ENTRY DETECTION ===
        if ts - last_signal_ts < COOLDOWN_S * 1000:
            continue
        
        signal = None
        
        # Pattern A: ICE-ONLY
        if 'ICEBERG_BID' in kind and vol >= ICE_ONLY_VOL:
            if current_state not in BLOCKED_LONG_STATES:
                signal = {'side': 'LONG', 'price': price, 'pattern': 'ICE-ONLY', 'score': 3, 'vol': vol}
        elif 'ICEBERG_ASK' in kind and vol >= ICE_ONLY_VOL:
            if current_state not in BLOCKED_SHORT_STATES:
                signal = {'side': 'SHORT', 'price': price, 'pattern': 'ICE-ONLY', 'score': 3, 'vol': vol}
        
        # Pattern B: EXHAUSTION
        if not signal:
            if 'BUY_SWEEP' in kind:
                sells = [e for e in recent_events if 'SELL_SWEEP' in e['kind'] and ts - e['ts_ms'] <= EXHAUSTION_WINDOW_MS]
                if sells and current_state not in BLOCKED_LONG_STATES:
                    signal = {'side': 'LONG', 'price': price, 'pattern': 'EXHAUSTION', 'score': 4, 'vol': vol}
            elif 'SELL_SWEEP' in kind:
                buys = [e for e in recent_events if 'BUY_SWEEP' in e['kind'] and ts - e['ts_ms'] <= EXHAUSTION_WINDOW_MS]
                if buys and current_state not in BLOCKED_SHORT_STATES:
                    signal = {'side': 'SHORT', 'price': price, 'pattern': 'EXHAUSTION', 'score': 4, 'vol': vol}
        
        # Pattern C: ICE-FIGHT
        if not signal:
            bid_ices = [e for e in recent_events if 'ICEBERG_BID' in e['kind'] and e['volume'] >= 80]
            ask_ices = [e for e in recent_events if 'ICEBERG_ASK' in e['kind'] and e['volume'] >= 80]
            max_bid = max([e['volume'] for e in bid_ices], default=0)
            max_ask = max([e['volume'] for e in ask_ices], default=0)
            
            if max_bid > max_ask * ICE_FIGHT_RATIO and max_bid >= 100:
                if current_state not in BLOCKED_LONG_STATES:
                    signal = {'side': 'LONG', 'price': price, 'pattern': 'ICE-FIGHT', 'score': 3, 'vol': max_bid}
            elif max_ask > max_bid * ICE_FIGHT_RATIO and max_ask >= 100:
                if current_state not in BLOCKED_SHORT_STATES:
                    signal = {'side': 'SHORT', 'price': price, 'pattern': 'ICE-FIGHT', 'score': 3, 'vol': max_ask}
        
        # Pattern D: ORIGINAL
        if not signal:
            if 'BID_ABSORPTION' in kind and price:
                confirms = [e for e in recent_events if 'ICEBERG_BID' in e['kind'] and abs(ts - e['ts_ms']) <= CONFIRM_WINDOW_S * 1000]
                if confirms and current_state not in BLOCKED_LONG_STATES:
                    signal = {'side': 'LONG', 'price': price, 'pattern': 'ORIGINAL', 'score': 2, 'vol': vol or confirms[0]['volume']}
            elif 'ASK_ABSORPTION' in kind and price:
                confirms = [e for e in recent_events if 'ICEBERG_ASK' in e['kind'] and abs(ts - e['ts_ms']) <= CONFIRM_WINDOW_S * 1000]
                if confirms and current_state not in BLOCKED_SHORT_STATES:
                    signal = {'side': 'SHORT', 'price': price, 'pattern': 'ORIGINAL', 'score': 2, 'vol': vol or confirms[0]['volume']}
        
        if signal and signal['price']:
            sl_pts = 1.5
            contracts = max(1, int(MAX_RISK_USD / (sl_pts * TICK_VALUE)))
            active_trade = {
                'side': signal['side'],
                'entry_price': signal['price'],
                'entry_ts': ts,
                'entry_vol': signal['vol'],
                'contracts': contracts,
                'sl_pts': sl_pts,
                'pattern': signal['pattern'],
                'score': signal['score'],
            }
            last_signal_ts = ts
    
    # Close remaining trade
    if active_trade and states:
        mid = states[-1]['mid']
        entry_p = active_trade['entry_price']
        side = active_trade['side']
        final_pnl = (mid - entry_p) if side == 'LONG' else (entry_p - mid)
        contracts = active_trade['contracts']
        mfe, mae = get_mfe_mae(active_trade['entry_ts'], states[-1]['ts_ms'], entry_p, side)
        journal.append({
            'side': side, 'entry_price': entry_p,
            'entry_time': datetime.fromtimestamp(active_trade['entry_ts']/1000, nl).strftime('%H:%M:%S'),
            'exit_price': round(mid, 2), 'exit_time': 'END',
            'pnl_pts': round(final_pnl, 2), 'pnl_usd': round(final_pnl * contracts * TICK_VALUE, 2),
            'mfe_pts': round(mfe, 2), 'mae_pts': round(mae, 2),
            'contracts': contracts, 'sl_pts': active_trade['sl_pts'],
            'duration_s': round((states[-1]['ts_ms'] - active_trade['entry_ts']) / 1000),
            'exit_reason': 'end_of_data', 'pattern': active_trade['pattern'], 'score': active_trade['score'],
        })
    
    # Summary
    total_pnl = sum(t['pnl_usd'] for t in journal)
    winners = [t for t in journal if t['pnl_pts'] > 0]
    losers = [t for t in journal if t['pnl_pts'] <= 0]
    
    return {
        "date": date_str, "hours": f"{start_hour:02d}:00-{end_hour:02d}:00 NL",
        "total_events": len(events), "total_states": len(states),
        "trades": journal,
        "summary": {
            "total_trades": len(journal), "winners": len(winners), "losers": len(losers),
            "winrate": round(len(winners)/len(journal)*100, 1) if journal else 0,
            "total_pnl_pts": round(sum(t['pnl_pts'] for t in journal), 2),
            "total_pnl_usd": round(total_pnl, 2),
            "avg_mfe": round(sum(t['mfe_pts'] for t in journal)/len(journal), 2) if journal else 0,
            "avg_mae": round(sum(t['mae_pts'] for t in journal)/len(journal), 2) if journal else 0,
            "avg_duration_s": round(sum(t['duration_s'] for t in journal)/len(journal)) if journal else 0,
        }
    }

if __name__ == '__main__':
    date = sys.argv[1] if len(sys.argv) > 1 else '2026-08-12'
    start_h = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    end_h = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    result = run_backtest(date, start_h, end_h)
    print(json.dumps(result, indent=2))
