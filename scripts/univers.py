#!/usr/bin/env python3
"""Univers du scan RSI 30 élargi (décision de Dylan du 6 nov. 2026).

- États-Unis : actions de sociétés américaines de plus de 2 Md$ de capitalisation (screener du Nasdaq,
  NYSE + Nasdaq + NYSE American), plus tous les membres du S&P 500 (même s'ils sont domiciliés ailleurs).
- France : le SBF 120, d'après data/sbf120.csv (tickers Yahoo ; liste à revoir à chaque révision d'Euronext).

Sortie : out/univers.csv (ticker, nom, marche, pays, secteur, industrie, capitalisation, devise, sp500).
"""
import io
import json
import os
import sys
import time
import urllib.request

import pandas as pd

SEUIL = 2e9
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
# Titres qui ne sont pas des actions ordinaires (dette, actions de préférence, bons de souscription...) : exclus.
NON_ACTIONS = (r"\d+(?:\.\d+)?\s?%|Preferred|\bNotes?\b|Debentures?|\bBonds?\b|Warrants?|\bRights\b"
               r"|Tangible Equity Unit|Units?,? each consisting|Subordinated")
# Références (pas des signaux) : marché américain, secteurs (SPDR et logiciel), marché français.
REFERENCES = {"SPY": "S&P 500 (ETF)", "XLK": "Technologie (ETF)", "XLF": "Finance (ETF)", "XLV": "Santé (ETF)",
              "XLY": "Consommation discrétionnaire (ETF)", "XLP": "Consommation de base (ETF)", "XLE": "Énergie (ETF)",
              "XLI": "Industrie (ETF)", "XLB": "Matériaux (ETF)", "XLU": "Services publics (ETF)",
              "XLRE": "Immobilier (ETF)", "XLC": "Communication (ETF)", "IGV": "Logiciel (ETF)",
              "CAC.PA": "CAC 40 (ETF Amundi)"}
SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"
ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
OUT = os.path.join(RACINE, "out")


def get(url, headers=UA, essais=5):
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # réseau, 403, 5xx
            print(f"essai {i + 1} : {url} : {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"échec du téléchargement : {url}")


def capitalisation(x):
    try:
        return float(str(x).replace(",", "").replace("$", "").strip())
    except ValueError:
        return float("nan")


def yahoo(sym):
    # BRK/B ou BRK.B -> BRK-B (convention Yahoo)
    return sym.strip().replace("/", "-").replace(".", "-")


def univers_us():
    sp = pd.read_csv(io.BytesIO(get(SP500_URL, headers={"User-Agent": "marche-data"})))
    sp["ticker"] = sp["Symbol"].map(yahoo)
    sp_set = set(sp["ticker"])

    rows = json.loads(get(SCREENER_URL))["data"]["rows"]
    df = pd.DataFrame(rows)
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df = df[~df["symbol"].str.contains(r"[\^ ]", regex=True)]          # actions de préférence, lignes vides
    exclus = df["name"].astype(str).str.contains(NON_ACTIONS, regex=True, case=False)
    print(f"{int(exclus.sum())} titres qui ne sont pas des actions ordinaires exclus (dette, préférence, bons...)")
    df = df[~exclus]
    df["ticker"] = df["symbol"].map(yahoo)
    df["capitalisation"] = df["marketCap"].map(capitalisation)
    df["pays"] = df["country"].fillna("")
    garde = ((df["capitalisation"] >= SEUIL) & (df["pays"] == "United States")) | df["ticker"].isin(sp_set)
    us = df[garde].drop_duplicates("ticker")
    out = pd.DataFrame({
        "ticker": us["ticker"], "nom": us["name"], "marche": "US", "pays": us["pays"],
        "secteur": us["sector"], "industrie": us["industry"], "capitalisation": us["capitalisation"],
        "devise": "USD", "sp500": us["ticker"].isin(sp_set),
    })
    manquants = sorted(sp_set - set(out["ticker"]))
    if manquants:  # membres du S&P 500 absents du screener : on les garde quand même
        extra = sp[sp["ticker"].isin(manquants)]
        out = pd.concat([out, pd.DataFrame({
            "ticker": extra["ticker"], "nom": extra["Security"], "marche": "US", "pays": "",
            "secteur": extra.get("GICS Sector", ""), "industrie": extra.get("GICS Sub-Industry", ""),
            "capitalisation": float("nan"), "devise": "USD", "sp500": True,
        })])
    print(f"US : {len(out)} titres ({int(out['sp500'].sum())} du S&P 500) ; "
          f"{len(manquants)} membres du S&P 500 absents du screener, ajoutés : {manquants[:20]}")
    return out


def univers_fr():
    fr = pd.read_csv(os.path.join(RACINE, "data", "sbf120.csv"))
    out = pd.DataFrame({
        "ticker": fr["ticker"], "nom": fr["nom"], "marche": "FR", "pays": "France", "secteur": "", "industrie": "",
        "capitalisation": float("nan"), "devise": "EUR", "sp500": False,
    })
    print(f"France : {len(out)} titres (SBF 120)")
    return out


def references():
    return pd.DataFrame({"ticker": list(REFERENCES), "nom": list(REFERENCES.values()), "marche": "REF",
                         "pays": "", "secteur": "", "industrie": "", "capitalisation": float("nan"),
                         "devise": ["EUR" if t.endswith(".PA") else "USD" for t in REFERENCES], "sp500": False})


def main():
    os.makedirs(OUT, exist_ok=True)
    u = pd.concat([univers_us(), univers_fr(), references()], ignore_index=True).drop_duplicates("ticker")
    u.to_csv(os.path.join(OUT, "univers.csv"), index=False)
    print(f"univers : {len(u)} titres -> out/univers.csv")


if __name__ == "__main__":
    main()
