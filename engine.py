#!/usr/bin/env python3
"""Rohstoff-Signal-Engine: laedt Tageskurse, berechnet Signale + Backtest, schreibt docs/data.json.
Nur Standardbibliothek. Keine Anlageberatung."""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone

# name, Yahoo-Symbol (Futures), geschaetzter Spread in % des Kurses (Hin+Rueck gesamt)
INSTRUMENTS = [
    ("Gold", "GC=F", 0.03), ("Silber", "SI=F", 0.08), ("Platin", "PL=F", 0.20),
    ("Palladium", "PA=F", 0.40), ("Kupfer", "HG=F", 0.10), ("Rohöl WTI", "CL=F", 0.06),
    ("Rohöl Brent", "BZ=F", 0.06), ("Erdgas", "NG=F", 0.30),
]
SWAP_PCT_PER_NIGHT = 0.02          # geschaetzte Uebernacht-Finanzierung pro Nacht in %
P = dict(sma_trend=200, rsi_len=2, rsi_long=10, rsi_short=90, atr_len=14,
         stop_atr=2.5, exit_sma=5, max_days=10, allow_short=False)


def fetch(symbol, rng="15y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d"
           % (urllib.parse.quote(symbol), rng))
    last = None
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except Exception as e:  # noqa
            last = e
            time.sleep(2 ** i)
    else:
        raise last
    q = res["indicators"]["quote"][0]
    bars = []
    for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        bars.append((t, o, h, l, c))
    return bars, res["meta"]


def sma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi(c, n):
    out = [None] * len(c)
    ag = al = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            ag += g / n; al += l / n
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(bars, n):
    out, a = [None] * len(bars), 0.0
    for i in range(1, len(bars)):
        _, o, h, l, c = bars[i]
        pc = bars[i - 1][4]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        a = a + tr / n if i <= n else (a * (n - 1) + tr) / n
        if i >= n:
            out[i] = a
    return out


def indicators(bars, p):
    c = [b[4] for b in bars]
    return dict(c=c, trend=sma(c, p["sma_trend"]), fast=sma(c, p["exit_sma"]),
                rsi=rsi(c, p["rsi_len"]), atr=atr(bars, p["atr_len"]))


def setup(ind, i, p):
    """+1 = Kaufsignal, -1 = Verkaufssignal, 0 = nichts (auf Schlusskurs von Tag i)."""
    if ind["trend"][i] is None or ind["rsi"][i] is None or ind["atr"][i] is None:
        return 0
    if ind["c"][i] > ind["trend"][i] and ind["rsi"][i] < p["rsi_long"]:
        return 1
    if p["allow_short"] and ind["c"][i] < ind["trend"][i] and ind["rsi"][i] > p["rsi_short"]:
        return -1
    return 0


def backtest(bars, p, spread_pct, start_ts=0, end_ts=9e18):
    """Einstieg zur naechsten Eroeffnung, Stop = stop_atr*ATR, Ausstieg wenn Schluss ueber/unter
    SMA(exit_sma) oder nach max_days. Ergebnis je Trade in R (Vielfache des Risikos), nach Kosten."""
    ind = indicators(bars, p)
    trades, pos, n = [], None, len(bars)
    for i in range(1, n):
        t, o, h, l, c = bars[i]
        if pos:
            d = pos["dir"]; exitp = None
            hit = l <= pos["stop"] if d == 1 else h >= pos["stop"]
            if hit:
                exitp = min(o, pos["stop"]) if d == 1 else max(o, pos["stop"])
            elif (c - ind["fast"][i]) * d > 0 or i - pos["i"] + 1 >= p["max_days"]:
                exitp = c
            if exitp is not None:
                nights = i - pos["i"]
                cost = pos["entry"] * (spread_pct + SWAP_PCT_PER_NIGHT * nights) / 100
                r = ((exitp - pos["entry"]) * d - cost) / pos["risk"]
                trades.append(dict(t=pos["t"], x=t, dir=d, r=r))
                pos = None
        if not pos and start_ts <= bars[i - 1][0] < end_ts:
            s = setup(ind, i - 1, p)
            if s and i < n:
                risk = p["stop_atr"] * ind["atr"][i - 1]
                pos = dict(dir=s, entry=o, stop=o - s * risk, risk=risk, i=i, t=t)
                # Stop kann schon am Einstiegstag fallen
                if (s == 1 and l <= pos["stop"]) or (s == -1 and h >= pos["stop"]):
                    cost = o * spread_pct / 100
                    trades.append(dict(t=t, x=t, dir=s, r=-1 - cost / risk)); pos = None
    return trades, pos, ind


def stats(trades):
    if not trades:
        return dict(n=0)
    rs = [t["r"] for t in trades]
    w = [r for r in rs if r > 0]; lo = [r for r in rs if r <= 0]
    eq = peak = dd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = max(dd, peak - eq)
    return dict(n=len(rs), win=round(100 * len(w) / len(rs), 1), exp=round(sum(rs) / len(rs), 3),
                total=round(sum(rs), 1), pf=round(sum(w) / -sum(lo), 2) if lo and sum(lo) else None,
                maxdd=round(dd, 1))


TP = dict(mom=252, atr_len=20, stop_atr=4.0, reentry_sma=50)


def trend_backtest(bars, p, spread_pct):
    """Trendfolge (12-Monats-Momentum), nur Long: Einstieg zur naechsten Eroeffnung, wenn Schluss ueber
    dem Schluss von vor 252 Handelstagen UND ueber SMA50. Ausstieg, wenn Momentum negativ wird,
    oder am Notfall-Stop (stop_atr*ATR unter Einstieg). Ergebnis in R nach Spread + Finanzierung."""
    c = [b[4] for b in bars]
    at, s50 = atr(bars, p["atr_len"]), sma(c, p["reentry_sma"])
    trades, pos, n = [], None, len(bars)
    mom = [None if i < p["mom"] else c[i] / c[i - p["mom"]] - 1 for i in range(n)]
    for i in range(p["mom"] + 1, n):
        t, o, h, l, cl = bars[i]
        j = i - 1
        if pos:
            exitp = None
            if mom[j] <= 0:
                exitp = o
            elif l <= pos["stop"]:
                exitp = min(o, pos["stop"])
            if exitp is not None:
                cost = pos["entry"] * (spread_pct + SWAP_PCT_PER_NIGHT * (i - pos["i"])) / 100
                trades.append(dict(t=pos["t"], x=t, dir=1, r=(exitp - pos["entry"] - cost) / pos["risk"]))
                pos = None
                continue
        if not pos and mom[j] > 0 and c[j] > s50[j]:
            risk = p["stop_atr"] * at[j]
            pos = dict(dir=1, entry=o, stop=o - risk, risk=risk, i=i, t=t)
    i = n - 1
    want = mom[i] > 0 and c[i] > s50[i]
    exit_now = bool(pos) and mom[i] <= 0
    return trades, pos, dict(mom=mom[i], atr=at[i], sma50=s50[i], want=want, exit_now=exit_now)


def main(out="docs/data.json"):
    items, all_t, all_p = [], [], []
    for name, sym, spread in INSTRUMENTS:
        try:
            bars, meta = fetch(sym)
        except Exception as e:
            print("FEHLER", sym, e, file=sys.stderr); continue
        tt, tpos, tnow = trend_backtest(bars, TP, spread)
        pt, _, ind = backtest(bars, P, spread)
        all_t += tt; all_p += pt
        i = len(bars) - 1
        close = bars[i][4]
        if tpos and tnow["exit_now"]:
            state, entry, stop = "SCHLIESSEN", tpos["entry"], tpos["stop"]
        elif tpos:
            state, entry, stop = "HALTEN", tpos["entry"], tpos["stop"]
        elif tnow["want"]:
            state, entry, stop = "KAUFEN", close, close - TP["stop_atr"] * tnow["atr"]
        else:
            state, entry, stop = "WARTEN", None, None
        open_r = (close - tpos["entry"]) / tpos["risk"] if tpos else None
        items.append(dict(
            name=name, symbol=sym, price=meta.get("regularMarketPrice") or close, close=close,
            date=bars[i][0], state=state, entry=entry, stop=stop, open_r=open_r,
            entry_date=tpos["t"] if tpos else None,
            mom12=round(100 * tnow["mom"], 1), atr=tnow["atr"], sma50=tnow["sma50"], sma200=ind["trend"][i],
            rsi2=round(ind["rsi"][i], 1), pullback=setup(ind, i, P) == 1,
            closes=[round(x, 4) for x in ind["c"][-250:]],
            trend_stats=stats(tt), pullback_stats=stats(pt),
            last_trades=[dict(t=t["t"], x=t["x"], r=round(t["r"], 2)) for t in tt[-4:]],
        ))
    if not items:
        sys.exit("keine Daten")
    all_t.sort(key=lambda t: t["x"]); all_p.sort(key=lambda t: t["x"])
    data = dict(updated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                trend_params=TP, pullback_params=P, swap=SWAP_PCT_PER_NIGHT, years=15,
                trend_all=stats(all_t), pullback_all=stats(all_p), items=items)
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print("ok", out, "Trend:", data["trend_all"], "Ruecksetzer:", data["pullback_all"])
    for it in items:
        print("  %-12s %-10s mom12 %+6.1f%%  %s" % (it["name"], it["state"], it["mom12"], it["trend_stats"]))


if __name__ == "__main__":
    main(*sys.argv[1:])
