# -*- coding: utf-8 -*-
"""
evaluate_quicktips.py — automat najde nejnovější tiket, vyhodnotí ho a uloží report
-----------------------------------------------------------------------------------
- Najde nejnovější tiket_quicktips_*.csv vedle skriptu
- Datum zkusí vyčíst z názvu souboru (YYYY-MM-DD), jinak použije dnešek
- Stáhne výsledky z Football-Data.org (token natvrdo)
- Spáruje zápasy fuzzy matchingem a vyhodnotí tip (✓/✗/•)
- Vypíše do konzole a uloží evaluated_quicktips_YYYY-MM-DD.csv
- Navíc vytvoří TXT „tiket pro Telegram“ ve formátu: ZÁPAS TIP p1 pX p2

Závislosti:
  pip install requests pandas fuzzywuzzy python-Levenshtein
"""

import os
import re
import glob
import sys
import datetime as dt
import requests
import pandas as pd
from fuzzywuzzy import fuzz

# ==== KONFIG ====
FD_TOKEN = "45f4946ab7654fac8d7a91f303227761"  # Football-Data.org token NATVRDO
FD_URL = "https://api.football-data.org/v4/matches"
HEADERS = {"X-Auth-Token": FD_TOKEN, "User-Agent": "QuickTips-Evaluator/1.0"}
FUZZY_THRESHOLD = 70  # minimální skóre shody (0–100)

# ==== Pomocné funkce ====

def find_latest_csv() -> str:
    """Najde nejnovější CSV soubor začínající 'tiket_quicktips_' v aktuálním adresáři."""
    files = glob.glob("tiket_quicktips_*.csv")
    if not files:
        print("[ERROR] Nebyl nalezen žádný CSV soubor 'tiket_quicktips_*.csv'")
        sys.exit(1)
    latest = max(files, key=os.path.getmtime)
    print(f"[INFO] Nalezen nejnovější CSV: {latest}")
    return latest

def extract_date_from_filename(fname: str) -> str:
    """
    Z názvu souboru vytáhne YYYY-MM-DD, např. 'tiket_quicktips_2025-10-25.csv'.
    Pokud se nepodaří, vrátí dnešní datum.
    """
    m = re.search(r"(\d{4}-\d{2}-\d{2})", fname)
    if m:
        return m.group(1)
    return dt.date.today().strftime("%Y-%m-%d")

def normalize_team_name(name: str) -> str:
    """Zjednoduší názvy pro porovnání (lowercase, bez zvláštních znaků apod.)."""
    if not isinstance(name, str):
        return ""
    name = name.lower()
    # běžné zkratky pryč
    name = name.replace(" fc", "").replace("cf ", "").replace(" sc", "").replace(" afc", "")
    # pomlčky a diakritika -> odstranit speciální znaky
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def split_match(match: str):
    """Rozdělí 'Home – Away' (různé pomlčky) na tuple (home, away)."""
    if "–" in match:
        parts = match.split("–")
    elif "-" in match:
        parts = match.split("-")
    else:
        parts = [match, ""]
    home = parts[0].strip()
    away = parts[1].strip() if len(parts) > 1 else ""
    return home, away

def fetch_results_from_fd(date: str) -> list:
    """Stáhne všechny zápasy z Football-Data pro dané datum."""
    print(f"[INFO] Stahuji výsledky z Football-Data.org pro {date} ...")
    params = {"dateFrom": date, "dateTo": date}
    resp = requests.get(FD_URL, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("matches", [])

def find_best_match(match_name: str, results: list):
    """
    Najde nejlepší shodu mezi názvem zápasu z CSV a zápasy z Football-Data.
    Vrací dict zápasu nebo None, pokud shoda < prahu.
    """
    home_csv, away_csv = split_match(match_name)
    h_norm = normalize_team_name(home_csv)
    a_norm = normalize_team_name(away_csv)

    best = None
    best_score = -1
    for m in results:
        h_api = normalize_team_name(m.get("homeTeam", {}).get("name", ""))
        a_api = normalize_team_name(m.get("awayTeam", {}).get("name", ""))
        # průměr dvou podobností
        score = (fuzz.token_sort_ratio(h_norm, h_api) + fuzz.token_sort_ratio(a_norm, a_api)) / 2
        if score > best_score:
            best = m
            best_score = score
    return (best if best_score >= FUZZY_THRESHOLD else None), int(best_score if best_score >= 0 else 0)

def decide_outcome_1x2(m: dict) -> str:
    """Vrátí '1'/'X'/'2' podle fullTime skóre — pokud není k dispozici, '?'."""
    score = (m.get("score") or {}).get("fullTime") or {}
    hg, ag = score.get("home"), score.get("away")
    if hg is None or ag is None:
        return "?"
    if hg > ag:
        return "1"
    if hg < ag:
        return "2"
    return "X"

def pretty_score(m: dict) -> str:
    score = (m.get("score") or {}).get("fullTime") or {}
    hg, ag = score.get("home"), score.get("away")
    if hg is None or ag is None:
        return "N/A"
    return f"{hg}:{ag}"

def status_done(m: dict) -> bool:
    return (m.get("status") in {"FINISHED", "AWARDED"}) and \
           ((m.get("score") or {}).get("fullTime") or {}).get("home") is not None

def save_telegram_txt(df: pd.DataFrame, date_iso: str) -> str:
    """
    Uloží TXT pro Telegram ve formátu:
    ZÁPAS TIP p1 pX p2
    """
    lines = []
    lines.append(f"TIKET {dt.datetime.strptime(date_iso, '%Y-%m-%d').strftime('%d.%m.%Y')}")
    lines.append("────────────────────────────────")
    # bezpečné čtení číselných sloupců
    for r in df.itertuples(index=False):
        match = str(getattr(r, "match"))
        tip = str(getattr(r, "tip")).strip().upper()
        p1  = str(getattr(r, "p1", "") if "p1" in df.columns else "")
        pX  = str(getattr(r, "pX", "") if "pX" in df.columns else "")
        p2  = str(getattr(r, "p2", "") if "p2" in df.columns else "")
        # přesně: "zapas tip p1 pX p2"
        lines.append(f"{match} {tip} {p1} {pX} {p2}")
    lines.append("────────────────────────────────")
    lines.append(f"Počet zápasů: {len(df)}")

    txt_name = f"tiket_telegram_{date_iso}.txt"
    txt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), txt_name)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Uložen Telegram TXT tiket: {txt_path}")
    return txt_path

# ==== Hlavní běh ====

def main():
    csv_path = find_latest_csv()
    target_date = extract_date_from_filename(os.path.basename(csv_path))

    # načti tiket
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    # ošetři očekávané sloupce
    for col in ["match", "tip"]:
        if col not in df.columns:
            print(f"[ERROR] CSV neobsahuje sloupec '{col}'.", file=sys.stderr)
            sys.exit(1)

    # 1) uložit TXT pro Telegram (přesný formát „zapas tip p1 pX p2“)
    save_telegram_txt(df, target_date)

    # 2) stáhni výsledky a vyhodnoť
    try:
        fd_matches = fetch_results_from_fd(target_date)
    except requests.RequestException as e:
        print(f"[ERROR] Nelze stáhnout výsledky z Football-Data.org: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n🧾 VYHODNOCENÍ TIKETU — QuickTips (Fotbal)")
    print("──────────────────────────────────────────────────────────────────────────")
    print(f"📅 Datum: {dt.datetime.strptime(target_date, '%Y-%m-%d').strftime('%d.%m.%Y')}")
    print(f"📁 Soubor: {csv_path}")
    print("──────────────────────────────────────────────────────────────────────────")
    print(" #  ZÁPAS                                           TIP  SKÓRE   OUT  ✓/✗ ")
    print("──────────────────────────────────────────────────────────────────────────")

    out_rows = []
    ok = bad = pend = 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        match = str(row.match)
        tip = str(row.tip).strip().upper()

        mdata, score_match = find_best_match(match, fd_matches)

        if not mdata:
            symbol = "•"  # nespárováno
            score_txt = "—"
            outc = "?"
            pend += 1
        else:
            if status_done(mdata):
                outc = decide_outcome_1x2(mdata)
                score_txt = pretty_score(mdata)
                if outc == tip:
                    symbol = "✅"
                    ok += 1
                else:
                    symbol = "❌"
                    bad += 1
            else:
                # nenahrano nebo bez FT score
                symbol = "•"
                score_txt = mdata.get("status", "N/A")
                outc = "?"

        match_disp = match[:44] + "..." if len(match) > 44 else match
        print(f"{i:>2}  {match_disp:<44}  {tip:<1}  {score_txt:<6}  {outc:^3}  {symbol}")

        # připrav řádek do uloženého CSV
        out_rows.append({
            "match": match,
            "tip": tip,
            "p1": row.p1 if "p1" in df.columns else "",
            "pX": row.pX if "pX" in df.columns else "",
            "p2": row.p2 if "p2" in df.columns else "",
            "fd_status": (mdata.get("status") if mdata else ""),
            "score": score_txt,
            "outcome": outc,
            "correct": 1 if symbol == "✅" else (0 if symbol == "❌" else ""),
            "symbol": symbol,
            "fuzzy_score": score_match,
            "fd_home": (mdata.get("homeTeam", {}).get("name") if mdata else ""),
            "fd_away": (mdata.get("awayTeam", {}).get("name") if mdata else ""),
            "fd_competition": (mdata.get("competition", {}).get("name") if mdata else ""),
            "fd_utcDate": (mdata.get("utcDate") if mdata else ""),
        })

    total = ok + bad + pend
    acc = (ok / (ok + bad) * 100.0) if (ok + bad) else 0.0

    print("──────────────────────────────────────────────────────────────────────────")
    print(f"✅ Správně: {ok}   ❌ Špatně: {bad}   ⏳ Bez výsledku/nenalezeno: {pend}   |  Celkem: {total}")
    print(f"🎯 Úspěšnost (z vyhodnocených): {acc:.1f} %")
    print("──────────────────────────────────────────────────────────────────────────")

    # Ulož vyhodnocený CSV report vedle skriptu
    eval_name = f"evaluated_quicktips_{target_date}.csv"
    eval_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), eval_name)
    pd.DataFrame(out_rows).to_csv(eval_path, sep=";", index=False, encoding="utf-8-sig")
    print(f"[OK] Uložen vyhodnocený report: {eval_path}")

if __name__ == "__main__":
    main()
