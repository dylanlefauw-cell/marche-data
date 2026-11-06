#!/usr/bin/env python3
"""Cours journaliers de l'univers élargi (Yahoo Finance via yfinance), au format de la base S&P 500 du comité.

Usage : python scripts/prix.py complet   -> tout l'historique depuis 2000 (le dimanche, ou au premier lancement)
        python scripts/prix.py jour      -> les 15 dernières séances, fusionnées avec la publication précédente

Sorties dans out/ :
- prices_full.parquet : date, ticker, open, high, low, close, volume, adj_close, dividends, stock_splits, source
- prices_3ans.parquet : les mêmes colonnes, depuis 3 ans (pour le scan quotidien)
- rapport.json        : nombre de titres, tickers sans cours, dernière date par marché
"""
import json
import os
import subprocess
import sys
import time

import pandas as pd
import yfinance as yf

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
OUT = os.path.join(RACINE, "out")
PREV = os.path.join(RACINE, "prev")
DEBUT = "2000-01-01"
LOT = 50
COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "adj_close", "dividends", "stock_splits", "source"]
NOMS = {"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
        "Volume": "volume", "Dividends": "dividends", "Stock Splits": "stock_splits"}


def telecharger(lot, **kw):
    """Un lot de tickers ; renvoie {ticker: DataFrame au bon format}."""
    for essai in range(5):
        try:
            d = yf.download(lot, group_by="ticker", auto_adjust=False, actions=True, threads=True,
                            progress=False, **kw)
            break
        except Exception as e:  # limite de débit, réseau
            print(f"  lot {lot[0]}… essai {essai + 1} : {e}", file=sys.stderr)
            time.sleep(30 * (essai + 1))
    else:
        return {}
    res = {}
    if d is None or d.empty:
        return res
    multi = isinstance(d.columns, pd.MultiIndex)
    for t in lot:
        try:
            x = d[t] if multi else d
        except KeyError:
            continue
        x = x.dropna(how="all")
        if x.empty or "Close" not in x:
            continue
        x = x[x["Close"].notna()].reset_index().rename(columns=NOMS)
        x["date"] = pd.to_datetime(x["date"]).dt.tz_localize(None).dt.normalize()
        for c in ["dividends", "stock_splits"]:
            if c not in x:
                x[c] = 0.0
        if "adj_close" not in x:
            x["adj_close"] = x["close"]
        x["ticker"] = t
        x["source"] = "yahoo"
        res[t] = x[COLS]
    return res


def par_lots(tickers, **kw):
    res = {}
    for i in range(0, len(tickers), LOT):
        lot = tickers[i:i + LOT]
        res.update(telecharger(lot, **kw))
        print(f"  {min(i + LOT, len(tickers))}/{len(tickers)} tickers, {len(res)} avec des cours")
        time.sleep(3)
    return res


def precedent():
    """La publication précédente (release « data »), si elle existe."""
    os.makedirs(PREV, exist_ok=True)
    p = os.path.join(PREV, "prices_full.parquet")
    r = subprocess.run(["gh", "release", "download", "data", "-p", "prices_full.parquet", "-D", PREV, "--clobber"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(p):
        print("pas de publication précédente :", r.stderr.strip()[:200])
        return None
    return pd.read_parquet(p)


def compacter(df):
    df = df.copy()
    for c in ["open", "high", "low", "close", "adj_close"]:
        df[c] = df[c].astype("float32")
    for c in ["volume", "dividends", "stock_splits"]:
        df[c] = df[c].astype("float64")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def marche_de(t):
    return "FR" if t.endswith((".PA", ".AS", ".BR")) else "US"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "jour"
    u = pd.read_csv(os.path.join(OUT, "univers.csv"))
    u["actuel"] = True
    tickers = list(dict.fromkeys(u["ticker"].astype(str)))
    prev = precedent()
    if mode == "jour" and prev is None:
        mode = "complet"
    # Un titre entré dans l'univers y reste (même passé sous 2 Md$ après une chute : c'est là que naissent les signaux).
    anciens = sorted(set(prev["ticker"]) - set(tickers)) if prev is not None else []
    if anciens:
        u = pd.concat([u, pd.DataFrame({"ticker": anciens, "nom": "", "marche": [marche_de(t) for t in anciens],
                                        "actuel": False})], ignore_index=True)
        tickers = tickers + anciens
    u.to_csv(os.path.join(OUT, "univers.csv"), index=False)
    print(f"mode {mode}, {len(tickers)} tickers dont {len(anciens)} sortis du filtre mais gardés")

    if mode == "complet":
        res = par_lots(tickers, start=DEBUT)
        full = pd.concat(res.values(), ignore_index=True) if res else pd.DataFrame(columns=COLS)
        if prev is not None:  # titres radiés : on garde leur historique
            full = pd.concat([full, prev[~prev["ticker"].isin(set(full["ticker"]))]], ignore_index=True)
    else:
        res = par_lots(tickers, period="15d")
        recents = pd.concat(res.values(), ignore_index=True) if res else pd.DataFrame(columns=COLS)
        # dividende ou division récente, ou ticker nouveau : on recharge tout son historique
        evt = recents[(recents["dividends"] > 0) | (recents["stock_splits"] > 0)]["ticker"].unique().tolist()
        nouveaux = sorted(set(recents["ticker"]) - set(prev["ticker"]))
        a_recharger = sorted(set(evt) | set(nouveaux))
        print(f"rechargement complet de {len(a_recharger)} tickers (dividende, division ou nouveau)")
        complet = par_lots(a_recharger, start=DEBUT) if a_recharger else {}
        garde = prev[~prev["ticker"].isin(a_recharger)]
        full = pd.concat([garde, recents[~recents["ticker"].isin(a_recharger)]] + list(complet.values()),
                         ignore_index=True)
        full = full.drop_duplicates(["ticker", "date"], keep="last")

    full = compacter(full)
    os.makedirs(OUT, exist_ok=True)
    full.to_parquet(os.path.join(OUT, "prices_full.parquet"), compression="zstd", index=False)
    depuis = full["date"].max() - pd.DateOffset(years=3)
    full[full["date"] >= depuis].to_parquet(os.path.join(OUT, "prices_3ans.parquet"), compression="zstd", index=False)

    sans = sorted(set(tickers) - set(full["ticker"]))
    marche = u.set_index("ticker")["marche"]
    derniere = full.groupby(full["ticker"].map(marche))["date"].max().astype(str).to_dict()
    rapport = {"mode": mode, "genere_utc": pd.Timestamp.now("UTC").isoformat(), "tickers_univers": len(tickers),
               "tickers_avec_cours": int(full["ticker"].nunique()), "lignes": int(len(full)),
               "derniere_date_par_marche": derniere, "sans_cours": sans}
    json.dump(rapport, open(os.path.join(OUT, "rapport.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in rapport.items() if k != "sans_cours"}, ensure_ascii=False))
    print(f"sans cours ({len(sans)}) : {sans[:60]}")


if __name__ == "__main__":
    main()
