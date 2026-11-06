#!/usr/bin/env python3
"""Scan RSI 30 de l'univers élargi (US > 2 Md$ et SBF 120), avec les conventions du comité RSI 30.

Pour chaque titre :
- RSI hebdo 14 (Wilder) sur clôtures ajustées W-FRI ; la semaine en cours est une bougie provisoire si la dernière
  séance n'est pas un vendredi ;
- seuil du vendredi : la clôture qui mettrait (ou laisserait) le RSI hebdo à 30 ou moins ;
- fenêtre de 12 semaines : cours du signal (première clôture hebdo à RSI <= 30 des 12 dernières semaines), plafond
  (× 1,10), première séance de rattrapage (+5 % ou plus, volume >= 2 fois la moyenne des 50 séances précédentes),
  entrée de la voie pari (première semaine où l'histogramme du MACD hebdo 12-26-9 remonte) et statut ;
- RSI mensuel, perte sur 13 semaines, pire séance, nature de la chute (marché : SPY ou médiane du SBF 120 à −10 %).

Les titres hors S&P 500 sont « hors méthode » (règles testées sur le S&P 500 seulement) jusqu'à la décision de Dylan.

Usage : python scripts/scan_elargi.py --prix out/prices_full.parquet --univers out/univers.csv --out out/scan_elargi.json
"""
import argparse
import json

import numpy as np
import pandas as pd


def rsi_wilder(close, n=14):
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    d = np.diff(close); g = np.where(d > 0, d, 0.0); l = np.where(d < 0, -d, 0.0)
    ag, al = g[:n].mean(), l[:n].mean()
    val = lambda a, b: 50.0 if a == b == 0 else (100.0 if b == 0 else 100 - 100 / (1 + a / b))
    out[n] = val(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + g[i]) / n; al = (al * (n - 1) + l[i]) / n
        out[i + 1] = val(ag, al)
    return out


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def histogramme(close):
    macd = ema(close, 12) - ema(close, 26)
    return macd - ema(macd, 9)


def seuil(wk_adj, ratio, dernier, cible=30.0):
    """Clôture (non ajustée) du jour qui met le RSI hebdo de la bougie en cours à `cible` ou moins."""
    def rsi_avec(p):
        x = wk_adj.copy(); x[-1] = p * ratio
        return rsi_wilder(x)[-1]
    lo, hi = 0.3 * dernier, 3.0 * dernier
    if rsi_avec(lo) > cible:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if rsi_avec(mid) <= cible:
            lo = mid
        else:
            hi = mid
    return round(lo, 2)


def analyse(t, g, marche_13s):
    g = g.sort_values("date").set_index("date")
    adj, close, vol = g["adj_close"].astype(float), g["close"].astype(float), g["volume"].astype(float)
    if len(adj) < 60:
        return None
    dernier_jour = adj.index[-1]
    w_adj = adj.resample("W-FRI").last().dropna()
    w_last_day = adj.groupby(pd.Grouper(freq="W-FRI")).apply(lambda s: s.index[-1] if len(s) else pd.NaT).dropna()
    r = rsi_wilder(w_adj.to_numpy())
    h = histogramme(w_adj.to_numpy())
    semaine_close = dernier_jour.weekday() == 4
    ratio = float(adj.iloc[-1] / close.iloc[-1]) if close.iloc[-1] else 1.0
    m_adj = adj.resample("ME").last().dropna()
    rm = rsi_wilder(m_adj.to_numpy()) if len(m_adj) > 15 else np.full(len(m_adj), np.nan)
    passe = adj[adj.index <= dernier_jour - pd.Timedelta(weeks=13)]
    perf13 = float(adj.iloc[-1] / passe.iloc[-1] - 1) if len(passe) else None
    d13 = adj[adj.index > dernier_jour - pd.Timedelta(weeks=13)].pct_change()
    pire = float(d13.min()) if len(d13) > 2 else None

    res = {"ticker": t, "cours": round(float(close.iloc[-1]), 2), "cours_le": dernier_jour.date().isoformat(),
           "semaine_cloturee": bool(semaine_close), "semaines_historique": int(len(w_adj)),
           "rsi_hebdo": round(float(r[-1]), 1) if np.isfinite(r[-1]) else None,
           "rsi_hebdo_precedent": round(float(r[-2]), 1) if len(r) > 1 and np.isfinite(r[-2]) else None,
           "rsi_mois": round(float(rm[-1]), 1) if len(rm) and np.isfinite(rm[-1]) else None,
           "histogramme_en_hausse": bool(h[-1] > h[-2]) if len(h) > 2 else None,
           "perf_13s": perf13, "pire_seance_13s": pire, "choc": bool(pire is not None and pire <= -0.10),
           "nature": "marché" if (marche_13s is not None and marche_13s <= -0.10) else "action seule ou secteur"}
    if not semaine_close and len(w_adj) > 20:
        res["seuil_signal_vendredi"] = seuil(w_adj.to_numpy().copy(), ratio, float(close.iloc[-1]))

    # Fenêtre de 12 semaines (semaines closes ; la bougie en cours compte si elle est close)
    n_close = len(w_adj) if semaine_close else len(w_adj) - 1
    debut = max(0, n_close - 12)
    idx = [i for i in range(debut, n_close) if np.isfinite(r[i]) and r[i] <= 30]
    if idx:
        i0 = idx[0]
        jour_signal = w_last_day.iloc[i0]
        cours_signal = float(close.loc[jour_signal])
        plafond = cours_signal * 1.10
        apres = g[g.index > jour_signal]
        var = adj.pct_change()
        moy50 = vol.shift(1).rolling(50, min_periods=30).mean()
        rebond = None
        for d in apres.index:
            if var.loc[d] >= 0.05 and np.isfinite(moy50.loc[d]) and vol.loc[d] >= 2 * moy50.loc[d]:
                rebond = d
                break
        entree_pari = None
        for j in range(i0 + 1, len(w_adj)):
            if h[j] > h[j - 1]:
                entree_pari = {"semaine": w_adj.index[j].date().isoformat(),
                               "cours": round(float(close.loc[w_last_day.iloc[j]]), 2) if j < len(w_last_day) else None}
                break
        dernier = float(close.iloc[-1])
        if rebond is not None:
            delai = (rebond - jour_signal).days
            statut = "rattrapage possible" if dernier <= plafond else ("cher" if delai <= 14 else "trop tard")
        else:
            delai, statut = None, "pas de rebond"
        res["fenetre"] = {
            "date_signal": jour_signal.date().isoformat(), "cours_signal": round(cours_signal, 2),
            "rsi_signal": round(float(r[i0]), 1), "plafond": round(plafond, 2),
            "ecart_plafond": round(dernier / plafond - 1, 4),
            "rebond_le": rebond.date().isoformat() if rebond is not None else None,
            "rebond_var": round(float(var.loc[rebond]), 4) if rebond is not None else None,
            "rebond_volume_x": round(float(vol.loc[rebond] / moy50.loc[rebond]), 2) if rebond is not None else None,
            "delai_jours": delai, "entree_pari": entree_pari, "statut": statut}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prix", required=True); ap.add_argument("--univers", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--annees", type=int, default=8)
    a = ap.parse_args()
    u = pd.read_csv(a.univers)
    px = pd.read_parquet(a.prix, columns=["date", "ticker", "close", "adj_close", "volume"])
    px["date"] = pd.to_datetime(px["date"])
    px = px[px["date"] >= px["date"].max() - pd.DateOffset(years=a.annees)]
    groupes = dict(tuple(px.groupby("ticker")))

    def perf13(t):
        if t not in groupes:
            return None
        s = groupes[t].set_index("date")["adj_close"].sort_index()
        p = s[s.index <= s.index[-1] - pd.Timedelta(weeks=13)]
        return float(s.iloc[-1] / p.iloc[-1] - 1) if len(p) else None

    spy = perf13("SPY")
    fr = [perf13(t) for t in u.loc[u["marche"] == "FR", "ticker"]]
    fr = [x for x in fr if x is not None]
    sbf = float(np.median(fr)) if fr else None
    info = u.set_index("ticker").to_dict("index")
    lignes = []
    for t, g in groupes.items():
        if t not in info:
            continue
        m = info[t].get("marche", "US")
        try:
            x = analyse(t, g, spy if m == "US" else sbf)
        except Exception as e:  # données incomplètes
            print("erreur", t, e)
            continue
        if x is None:
            continue
        x.update({"nom": info[t].get("nom"), "marche": m, "devise": info[t].get("devise") or ("EUR" if m == "FR" else "USD"),
                  "sp500": bool(info[t].get("sp500")) if pd.notna(info[t].get("sp500")) else False,
                  "capitalisation": info[t].get("capitalisation"), "secteur": info[t].get("secteur")})
        x["hors_methode"] = not x["sp500"]
        lignes.append(x)
    df = pd.DataFrame(lignes)
    signaux = df[df["rsi_hebdo"] <= 30]
    proches = df[(df["rsi_hebdo"] > 30) & (df["rsi_hebdo"] <= 34)]
    fenetre = df[df["fenetre"].notna()] if "fenetre" in df else df.iloc[0:0]
    res = {"genere_le": pd.Timestamp.now("UTC").isoformat(), "spy_13s": spy, "sbf120_median_13s": sbf,
           "titres": int(len(df)), "signaux": json.loads(signaux.sort_values("rsi_hebdo").to_json(orient="records")),
           "proches_du_seuil": json.loads(proches.sort_values("rsi_hebdo").to_json(orient="records")),
           "fenetre_12_semaines": json.loads(fenetre.to_json(orient="records"))}
    json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1)
    hm = signaux[signaux["hors_methode"]]
    print(f"{len(df)} titres | {len(signaux)} à RSI hebdo <= 30 (dont {len(hm)} hors S&P 500) | "
          f"{len(proches)} entre 30 et 34 | {len(fenetre)} dans la fenêtre de 12 semaines | SPY 13 sem. {spy} | SBF 120 {sbf}")
    for _, s in hm.sort_values("rsi_hebdo").head(40).iterrows():
        print(f"  {s['ticker']:9s} {s['marche']} RSI {s['rsi_hebdo']:5.1f} cours {s['cours']} ({s['cours_le']}) "
              f"13 sem. {s['perf_13s']:+.1%} choc {s['choc']} {s['nom']}")


if __name__ == "__main__":
    main()
