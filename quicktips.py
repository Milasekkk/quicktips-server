# -*- coding: utf-8 -*-
"""
QuickTips → konzolový „tiket“ + CSV + TXT export
------------------------------------------------
Stáhne fotbalové QuickTips z Vitisportu, vypíše do konzole
a uloží CSV i TXT do stejné složky, kde je tento skript.

📦 Vytvoří:
  - tiket_quicktips_YYYY-MM-DD.csv
  - tiket_telegram_YYYY-MM-DD.txt

Závislosti:
  pip install requests beautifulsoup4
"""

import csv
import datetime as dt
import itertools
import os
import re
import sys
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup

URL_QUICKTIPS = "https://www.vitisport.cz/index.php?clanek=quicktips&sekce=fotbal&lang=cs"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# ---------- Regexy a pomocné funkce ----------

PERC_RE = re.compile(r"(\d{1,3})\s*%")
DATE_TOKEN_RE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\s*$")
TIME_TOKEN_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
DATE_PREFIX_RE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\s+")
DASH_FIX_RE = re.compile(r"\s*[-–]\s*")  # sjednocení pomlček

def normspace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def parse_percent(cell_text: str) -> Optional[int]:
    m = PERC_RE.search(cell_text)
    if not m:
        return None
    v = int(m.group(1))
    if 0 <= v <= 100:
        return v
    return None

def is_quicktips_table(table: BeautifulSoup) -> bool:
    """Heuristika: tabulka QuickTips má v řádku tři sousední buňky s procenty (1/X/2)."""
    rows = table.find_all("tr")
    if not rows:
        return False
    for tr in rows[:6]:
        cells = [normspace(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cells) < 5:
            continue
        streak = 0
        for c in cells:
            if parse_percent(c) is not None:
                streak += 1
                if streak >= 3:
                    return True
            else:
                streak = 0
    return False

def is_noise_cell(c: str) -> bool:
    if not c or len(c) <= 1:
        return True
    if DATE_TOKEN_RE.match(c):
        return True
    if TIME_TOKEN_RE.match(c):
        return True
    if re.fullmatch(r"[0-9%:|\-–.]+", c):
        return True
    return False

def plausible_team_text(c: str) -> bool:
    if is_noise_cell(c):
        return False
    if not re.search(r"[A-Za-zÁ-Žá-ž]", c):
        return False
    return len(c.strip()) >= 3

def clean_match_name(s: str) -> str:
    """Odstraní datový prefix 'DD.MM ' a sjednotí pomlčky na ' – '."""
    s = DATE_PREFIX_RE.sub("", s)
    s = DASH_FIX_RE.sub(" – ", s)
    s = normspace(s)
    return s

def extract_teams_from_cells(cells: List[str], perc_indices: List[int]) -> str:
    """Z celé sady buněk: odstraní % buňky, šum a vytvoří název zápasu."""
    perc_set = set(perc_indices)
    candidates: List[str] = []
    for i, c in enumerate(cells):
        if i in perc_set:
            continue
        c = normspace(c)
        if plausible_team_text(c):
            candidates.append(c)

    dedup: List[str] = []
    for c in candidates:
        if not dedup or dedup[-1].lower() != c.lower():
            dedup.append(c)

    if not dedup:
        return "?"

    home = dedup[0]
    away = None
    for c in reversed(dedup):
        if c.lower() != home.lower():
            away = c
            break
    if not away:
        away = dedup[1] if len(dedup) >= 2 else dedup[0]

    return clean_match_name(f"{home} – {away}")

# ---------- Parsování QuickTips ----------

def parse_quicktips(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows_out: List[Dict[str, Any]] = []

    for table in soup.find_all("table"):
        if not is_quicktips_table(table):
            continue

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            cells = [normspace(td.get_text(" ", strip=True)) for td in tds]

            perc_idx = [i for i, c in enumerate(cells) if parse_percent(c) is not None]
            best_run: List[int] = []
            for _, g in itertools.groupby(enumerate(perc_idx), key=lambda x: x[0] - x[1]):
                run = [v for _, v in g]
                if len(run) >= 3 and len(run) > len(best_run):
                    best_run = run
            if len(best_run) < 3:
                continue

            i1, iX, i2 = best_run[0], best_run[1], best_run[2]
            p1 = parse_percent(cells[i1]) or 0
            pX = parse_percent(cells[iX]) or 0
            p2 = parse_percent(cells[i2]) or 0

            match_str = extract_teams_from_cells(cells, best_run)

            probs = {"1": p1, "X": pX, "2": p2}
            tip = max(probs, key=probs.get)

            rows_out.append({
                "match": match_str,
                "tip": tip,
                "p1": p1,
                "pX": pX,
                "p2": p2,
            })

    seen = set()
    uniq: List[Dict[str, Any]] = []
    for r in rows_out:
        key = (r["match"], r["tip"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq

# ---------- Výpis ----------

def print_ticket(rows: List[Dict[str, Any]]) -> None:
    today = dt.date.today().strftime("%d.%m.%Y")
    print(f"🧾 ELEKTRONICKÝ TIKET — QuickTips (Fotbal) [{today}]")
    print("──────────────────────────────────────────────────────────────")
    print(" #  ZÁPAS                                           TIP   p1   pX   p2")
    print("──────────────────────────────────────────────────────────────")
    for idx, r in enumerate(rows, start=1):
        match = r["match"]
        if len(match) > 44:
            match = match[:41] + "..."
        print(f"{idx:>2}  {match:<44}  {r['tip']:<1}  {r['p1']:>3}  {r['pX']:>3}  {r['p2']:>3}")
    print("──────────────────────────────────────────────────────────────")
    print(f"💰 Počet zápasů: {len(rows)}")
    print("──────────────────────────────────────────────────────────────")

# ---------- CSV export ----------

def save_csv(rows: List[Dict[str, Any]]) -> str:
    script_dir = os.path.abspath(os.path.dirname(__file__)) if "__file__" in globals() else os.getcwd()
    fname = f"tiket_quicktips_{dt.date.today().isoformat()}.csv"
    fpath = os.path.join(script_dir, fname)
    with open(fpath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["match", "tip", "p1", "pX", "p2"])
        for r in rows:
            writer.writerow([r["match"], r["tip"], r["p1"], r["pX"], r["p2"]])
    return fpath

# ---------- TXT export (pro Telegram) ----------

def save_txt(rows: List[Dict[str, Any]]) -> str:
    today = dt.date.today().strftime("%Y-%m-%d")
    fname = f"tiket_telegram_{today}.txt"
    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    lines = [f"TIKET {dt.date.today().strftime('%d.%m.%Y')}",
             "────────────────────────────────",
             "ZÁPAS | TIP | p1/pX/p2",
             "────────────────────────────────"]
    for r in rows:
        lines.append(f"{r['match']} | {r['tip']} | {r['p1']}/{r['pX']}/{r['p2']}")
    lines.append("────────────────────────────────")
    lines.append(f"Počet zápasů: {len(rows)}")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] TXT tiket uložen: {fpath}")
    return fpath

# ---------- Main ----------

def main() -> int:
    try:
        resp = requests.get(URL_QUICKTIPS, headers={"User-Agent": UA}, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[HTTP] Nelze načíst QuickTips: {e}", file=sys.stderr)
        return 1

    rows = parse_quicktips(resp.text)
    if not rows:
        print("[INFO] Nenašel jsem žádné parsovatelné řádky QuickTips (fotbal).")
        return 0

    print_ticket(rows)

    try:
        csv_path = save_csv(rows)
        print(f"[OK] CSV uloženo: {csv_path}")
    except Exception as e:
        print(f"[WARN] CSV se nepodařilo uložit: {e}", file=sys.stderr)

    try:
        txt_path = save_txt(rows)
    except Exception as e:
        print(f"[WARN] TXT se nepodařilo uložit: {e}", file=sys.stderr)

    return 0

if __name__ == "__main__":
    sys.exit(main())
