# marche-data

Ce dépôt contient les cours journaliers utilisés par le « comité RSI 30 » de Dylan pour son scan élargi, décidé le 6 nov. 2026.

## L'univers
- **États-Unis :** les actions de sociétés américaines de plus de 2 Md$ de capitalisation (NYSE, Nasdaq, NYSE American), d'après le screener du Nasdaq, plus tous les membres du S&P 500.
- **France :** le SBF 120, d'après `data/sbf120.csv`. La liste est à revoir à chaque révision d'Euronext (mars, juin, septembre, décembre).
- **Un titre entré dans l'univers y reste**, même s'il passe ensuite sous 2 Md$. C'est souvent après une forte chute que naissent les signaux.

## Les fichiers (release « data »)

| Fichier | Contenu |
|---|---|
| `prices_full.parquet` | Cours depuis 2000. Colonnes : date, ticker, open, high, low, close, volume, adj_close, dividends, stock_splits, source. Même format que la base S&P 500 du comité. |
| `prices_3ans.parquet` | Les mêmes colonnes, sur les 3 dernières années, pour le scan quotidien. |
| `univers.csv` | ticker, nom, marche (US ou FR), pays, secteur, industrie, capitalisation, devise, sp500, actuel. |
| `rapport.json` | Nombre de titres, tickers sans cours, dernière date par marché. |
| `scan_elargi.json` | Scan RSI 30 de la nuit : signaux, titres proches du seuil (30 à 34), fenêtre de 12 semaines (cours du signal, plafond, rattrapage, entrée de la voie pari). Les titres hors S&P 500 sont « hors méthode ». |

Adresse de téléchargement : `https://github.com/dylanlefauw-cell/marche-data/releases/download/data/<fichier>`

## La mise à jour
Elle passe par le workflow « Cours de la nuit » (`.github/workflows/nuit.yml`) :
- du mardi au samedi à 1 h 20 UTC : les dernières séances, fusionnées avec la publication précédente ;
- le dimanche à 6 h UTC : un rechargement complet.

## Les limites
- **La source** est Yahoo Finance (via yfinance), sans garantie. Les cours ajustés tiennent compte des dividendes et des divisions.
- **Le biais des survivants :** l'univers est celui d'aujourd'hui. Les sociétés disparues avant 2026 n'y sont pas. Tout test historique sur cette base est donc flatté ; la base S&P 500 du comité, elle, garde ses anciens membres.
- **Usage :** ce dépôt ne contient que des cours de marché publics, aucune donnée personnelle.
