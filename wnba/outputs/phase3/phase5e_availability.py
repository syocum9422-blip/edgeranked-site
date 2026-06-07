"""Phase 5E: shadow availability integration (ESPN UA fix).

Shadow-only: fetches the ESPN WNBA injuries page with a corrected User-Agent, parses status,
and measures detection rate, OUT players that would be removed, and which currently-projected
players would be corrected. Does NOT modify production files; writes a shadow status CSV.
"""
from __future__ import annotations

import sys
import urllib.request
import ssl
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

WNBA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WNBA))
import fetch_wnba_data as fwd

HERE = Path(__file__).resolve().parent
OUT = HERE / "reports"
SHADOW_STATUS = HERE / "shadow" / "wnba_player_status_shadow.csv"
EXCLUDE = {"out", "doubtful", "inactive", "suspended"}
FIXED_UA = "Mozilla/5.0"  # generic UA bypasses the stub that the detailed Chrome UA triggers


def fetch_fixed():
    headers = {"User-Agent": FIXED_UA,
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    req = urllib.request.Request(fwd.ESPN_INJURIES_URL, headers=headers)
    html = urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()).read().decode("utf-8", "ignore")
    if len(html) < 5000:
        raise RuntimeError(f"stub response ({len(html)} bytes) — UA still blocked")
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for section in soup.find_all("div", class_="Table__league-injuries"):
        tname = section.find("span", class_="injuries__teamName")
        team = tname.get_text(strip=True) if tname else "?"
        for tr in section.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) >= 4:
                name = cells[0].get_text(" ", strip=True)
                status = cells[3].get_text(" ", strip=True)
                if name:
                    rows.append({"team": team, "player_name": name, "status_text": status})
    return pd.DataFrame(rows), len(html)


def main():
    df, nbytes = fetch_fixed()
    df["player_key"] = df["player_name"].astype(str).str.lower().str.strip()
    df["status_norm"] = df["status_text"].astype(str).str.lower().str.split().str[0]
    df.to_csv(SHADOW_STATUS, index=False)

    # currently-projected players (production today_features) that would be corrected
    tf = pd.read_csv(WNBA / "data" / "processed" / "wnba_today_features.csv")
    tf["player_key"] = tf["player_name"].astype(str).str.lower().str.strip()
    proj_keys = set(tf["player_key"])
    flagged = df[df["player_key"].isin(proj_keys)]
    would_remove = flagged[flagged["status_norm"].isin(EXCLUDE)]
    questionable = flagged[~flagged["status_norm"].isin(EXCLUDE)]

    summary = {
        "page_bytes": nbytes,
        "injury_entries_detected": len(df),
        "teams_with_injuries": int(df["team"].nunique()),
        "status_breakdown": df["status_norm"].value_counts().to_dict(),
        "currently_projected_players": len(proj_keys),
        "projected_players_on_injury_report": len(flagged),
        "projected_players_would_be_removed_OUT": len(would_remove),
        "projected_players_confidence_capped_GTD": len(questionable),
    }
    import json
    json.dump(summary, open(OUT / "phase5e_availability_summary.json", "w"), indent=2)
    flagged.to_csv(OUT / "phase5e_projected_player_corrections.csv", index=False)

    print("=== Phase 5E: shadow availability (UA fix) ===")
    print(f"page bytes: {nbytes} (was 1987 stub) | injury entries: {len(df)} across {df['team'].nunique()} teams")
    print(f"status breakdown: {summary['status_breakdown']}")
    print(f"currently-projected players: {len(proj_keys)}")
    print(f"  on injury report: {len(flagged)} | would REMOVE (OUT/Doubtful): {len(would_remove)} | "
          f"confidence-cap (GTD/Quest): {len(questionable)}")
    if len(flagged):
        print("\nprojected players on injury report:")
        print(flagged[["player_name", "team", "status_text"]].to_string(index=False))


if __name__ == "__main__":
    main()
