"""Feature panel for BTCUSDT. All features at bar t use data <= t only."""
import numpy as np, pandas as pd
import sys, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from engine.indicators import *

def build(df, spot=None):
    """df: OHLCV+ taker_buy_base, quote_volume, count on the decision timeframe."""
    f = pd.DataFrame({"dt": df.dt})
    o,h,l,c = (df[x].to_numpy(float) for x in ("open","high","low","close"))
    v  = df.volume.to_numpy(float)
    tb = df.taker_buy_base.to_numpy(float)
    qv = df.quote_volume.to_numpy(float)
    nt = df["count"].to_numpy(float)
    r  = pd.Series(np.log(c)).diff().to_numpy()
    f["ret"] = r
    f["close"] = c

    # ---------------- order flow -------------------------------------------
    # Depth/trade imbalance in [-1,1]: 2*(taker_buy/volume - 0.5)
    imb = np.where(v > 0, 2*(tb/np.where(v==0,np.nan,v) - 0.5), 0.0)
    f["imb"] = imb
    for n in (3, 6, 12, 24, 48, 96):
        f[f"ofi{n}"] = pd.Series(imb).rolling(n).mean().to_numpy()
        f[f"zofi{n}"] = zscore(pd.Series(imb).rolling(n).mean().to_numpy(), 240)
    # signed notional flow normalised by its own trailing scale
    sflow = (2*tb - v) * c
    f["sflow_z"] = zscore(sflow, 96)
    for n in (6, 24, 96):
        f[f"sflow{n}_z"] = zscore(pd.Series(sflow).rolling(n).sum().to_numpy(), 240)
    # VPIN proxy: |imbalance| over rolling window (order-flow toxicity)
    f["vpin"] = pd.Series(np.abs(imb)).rolling(50).mean().to_numpy()
    # average trade size (retail vs institutional footprint)
    ats = np.where(nt > 0, qv/np.where(nt==0,np.nan,nt), np.nan)
    f["ats_z"] = zscore(ats, 240)

    # ---------------- returns / momentum ------------------------------------
    for n in (1, 2, 3, 4, 6, 8, 12, 24, 48, 96, 168, 336):
        f[f"mom{n}"] = pd.Series(np.log(c)).diff(n).to_numpy()
    f["sign1"] = np.sign(r)
    f["sign_run"] = pd.Series(np.sign(r)).groupby((pd.Series(np.sign(r)).diff()!=0).cumsum()).cumcount().to_numpy()+1

    # ---------------- volatility / regime -----------------------------------
    a14 = atr(h,l,c,14); f["atr14"] = a14
    f["atrp"] = a14/c
    for n in (24, 96, 336):
        f[f"rv{n}"] = realized_vol(c, n)
    f["vol_ratio"] = f["rv24"]/f["rv336"]
    f["vol_rank"] = rolling_rank(f["rv96"].to_numpy(), 720)
    ad, pdi, mdi = adx(h,l,c,14); f["adx"] = ad; f["di_diff"] = pdi-mdi
    f["ef"] = np.abs(pd.Series(np.log(c)).diff(24)) / pd.Series(np.abs(r)).rolling(24).sum()   # efficiency ratio

    # ---------------- location / structure ----------------------------------
    m,u,lo,bw = bbands(c,20,2.0); f["bbpos"] = (c-lo)/np.where(u-lo==0,np.nan,u-lo); f["bw"] = bw
    f["bw_rank"] = rolling_rank(bw, 480)
    hh,ll = donchian(h,l,20); f["dc_pos"] = (c-ll)/np.where(hh-ll==0,np.nan,hh-ll)
    hh55,ll55 = donchian(h,l,55); f["dc55_hi"] = hh55; f["dc55_lo"] = ll55
    f["rsi14"] = rsi(c,14); f["rsi4"] = rsi(c,4)
    f["ema_f"] = ema(c,20); f["ema_s"] = ema(c,100)
    f["ema_sp"] = (f["ema_f"]-f["ema_s"])/c
    md,ms,mh = macd(c); f["macd_h"] = mh/c
    f["z96"] = zscore(c, 96); f["z24"] = zscore(c, 24)
    # candle anatomy
    rng = np.where(h-l==0, np.nan, h-l)
    f["body"] = (c-o)/rng
    f["upwick"] = (h-np.maximum(o,c))/rng
    f["dnwick"] = (np.minimum(o,c)-l)/rng
    f["clv"] = ((c-l)-(h-c))/rng          # close location value

    # ---------------- volume -------------------------------------------------
    f["vol_z"] = zscore(v, 96)
    f["dollar_z"] = zscore(qv, 96)
    f["ntr_z"] = zscore(nt, 96)

    # ---------------- calendar ----------------------------------------------
    t = pd.to_datetime(df.dt)
    f["hour"] = t.dt.hour.to_numpy()
    f["dow"] = t.dt.dayofweek.to_numpy()
    return f


def add_basis(f, fut_df, spot_df):
    """Perp-vs-spot basis, aligned on bar open time."""
    s = spot_df[["dt","close"]].rename(columns={"close":"spot"})
    m = fut_df[["dt","close"]].rename(columns={"close":"perp"}).merge(s, on="dt", how="left")
    b = (m.perp/m.spot - 1.0).to_numpy()
    f = f.copy()
    f["basis"] = b
    f["basis_z"] = zscore(b, 240)
    f["basis_chg"] = pd.Series(b).diff(24).to_numpy()
    return f


def add_funding(f, funding_df, dt_col="dt"):
    """Most recent SETTLED funding rate and its trailing averages (no look-ahead:
    a rate settled at time T is only visible for bars starting at/after T)."""
    fr = funding_df.copy()
    fd = fr.dt.to_numpy(); rt = fr.rate.to_numpy()
    ed = pd.to_datetime(f[dt_col]).to_numpy()
    idx = np.searchsorted(fd, ed, side="right") - 1        # strictly past
    ok = idx >= 0
    cur = np.full(len(f), np.nan); cur[ok] = rt[idx[ok]]
    f = f.copy(); f["fund"] = cur
    s = pd.Series(rt)
    for n in (3, 9, 21):
        av = s.rolling(n).mean().to_numpy()
        x = np.full(len(f), np.nan); x[ok] = av[idx[ok]]
        f[f"fund{n}"] = x
    f["fund_z"] = zscore(cur, 240)
    return f


def add_metrics(f, met_1h, dt_col="dt"):
    """Open-interest and trader-positioning metrics.

    `met_1h` rows are labelled at the hour OPEN but hold the state observed at
    HH:55, i.e. inside that bar. Combined with the harness's one-bar lag, a
    value from decision bar t is only acted on from the open of bar t+1, so the
    observation always precedes the trade.
    """
    import numpy as np, pandas as pd
    from engine.indicators import zscore, rolling_rank
    m = met_1h.copy()
    m["dt"] = pd.to_datetime(m["dt"], utc=True).astype("datetime64[ns, UTC]")
    left = pd.DataFrame({"dt": pd.to_datetime(f[dt_col], utc=True).astype("datetime64[ns, UTC]")})
    g = pd.merge_asof(left.sort_values("dt"), m.sort_values("dt"),
                      on="dt", direction="backward")
    f = f.copy()
    oi = g.oi.to_numpy(float)
    f["oi"] = oi
    f["doi1"]  = pd.Series(oi).pct_change(1).to_numpy()
    f["doi6"]  = pd.Series(oi).pct_change(6).to_numpy()
    f["doi24"] = pd.Series(oi).pct_change(24).to_numpy()
    f["doi24_z"] = zscore(f["doi24"].to_numpy(), 480)
    f["oi_rank"] = rolling_rank(oi, 720)
    # OI relative to price: leverage build-up per unit of market cap traded
    f["oi_px"] = oi * f.close.to_numpy()
    f["oi_px_z"] = zscore(pd.Series(f["oi_px"]).pct_change(24).to_numpy(), 480)
    # positioning ratios
    for c in ("tt_acct", "tt_pos", "retail_acct", "taker_ratio"):
        v = g[c].to_numpy(float)
        f[c] = v
        f[c + "_z"] = zscore(v, 480)
    # smart money vs the crowd
    f["tt_vs_retail"] = zscore(np.log(g.tt_pos.to_numpy(float) /
                                      np.maximum(g.retail_acct.to_numpy(float), 1e-6)), 480)
    # leverage-flush detector: OI collapsing while price falls
    r24 = pd.Series(np.log(f.close)).diff(24).to_numpy()
    f["flush"] = np.where((f["doi24"].to_numpy() < -0.04) & (r24 < -0.03), 1.0, 0.0)
    f["quadrant"] = np.sign(r24) * np.sign(f["doi24"].to_numpy())
    return f
