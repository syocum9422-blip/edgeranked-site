import os
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

from nba_model.settings import (
    CALIBRATION_REPORT_PATH,
    CALIBRATION_SUMMARY_PATH,
    RECORD_SUMMARY_PATH,
    RESULTS_PAGE_PATH,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPORTS_ROOT = PROJECT_ROOT.parent / "sports"
DEFAULT_PUBLIC_INDEX = Path.home() / "Public" / "index.html"


def resolve_mlb_base():
    env_base = os.environ.get("EDGERANKED_MLB_BASE_DIR")
    candidates = []
    if env_base:
        candidates.append(Path(env_base))
    candidates.extend(
        [
            SPORTS_ROOT / "mlb" / "mlb_model",
            PROJECT_ROOT / "mlb_model",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


DEFAULT_MLB_BASE = resolve_mlb_base()

PUBLIC_INDEX_PATH = os.environ.get("EDGERANKED_PUBLIC_INDEX_PATH", str(DEFAULT_PUBLIC_INDEX))
MLB_OUTPUT_DIR = os.path.join(
    os.environ.get("EDGERANKED_MLB_BASE_DIR", str(DEFAULT_MLB_BASE)),
    "mlb",
    "outputs",
)
MLB_HITTER_SUMMARY_PATH = os.path.join(MLB_OUTPUT_DIR, "hitter_summary_today.csv")
MLB_PITCHER_PROPS_PATH = os.path.join(MLB_OUTPUT_DIR, "pitcher_props_today.csv")
MLB_BETTING_SHEET_PATH = os.path.join(MLB_OUTPUT_DIR, "betting_sheet_today.csv")


def read_csv_or_empty(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def df_to_html(df, title):
    if df.empty:
        return f"<h2>{escape(title)}</h2><p>No data available.</p>"
    return f"<h2>{escape(title)}</h2>{df.to_html(index=False, border=0, classes='table')}"


def mlb_table_html(df, title):
    if df.empty:
        return f'<div class="section"><h2>{escape(title)}</h2><p>No MLB data available.</p></div>'
    return f'<div class="section"><h2>{escape(title)}</h2>{df.to_html(index=False, border=0, classes="table")}</div>'


def build_mlb_section():
    hitter_df = read_csv_or_empty(MLB_HITTER_SUMMARY_PATH)
    pitcher_df = read_csv_or_empty(MLB_PITCHER_PROPS_PATH)
    betting_df = read_csv_or_empty(MLB_BETTING_SHEET_PATH)

    if not hitter_df.empty:
        hitter_df = hitter_df.head(20)
    if not pitcher_df.empty:
        keep_cols = [
            c for c in [
                "pitcher_name",
                "opponent",
                "projected_strikeouts",
                "sim_mean",
                "recommended_play",
                "recommendation_confidence",
            ]
            if c in pitcher_df.columns
        ]
        pitcher_df = pitcher_df[keep_cols].head(20)
    if not betting_df.empty:
        keep_cols = [c for c in ["market", "player_name", "play", "line", "confidence", "edge"] if c in betting_df.columns]
        betting_df = betting_df[keep_cols].head(20)

    record_df = read_csv_or_empty(os.path.join(MLB_OUTPUT_DIR, "daily_betting_summary.csv"))
    history_df = read_csv_or_empty(os.path.join(MLB_OUTPUT_DIR, "bet_history.csv"))

    if not record_df.empty:
        record_df = record_df.head(20)
    if not history_df.empty:
        keep_cols = [c for c in ["date", "market", "player_name", "play", "line", "result"] if c in history_df.columns]
        if keep_cols:
            history_df = history_df[keep_cols]
        history_df = history_df.head(20)

    pieces = [
        '<div class="hero"><h1>MLB Model Results</h1><div class="meta">Live from the MLB model workspace</div></div>',
        mlb_table_html(betting_df, "MLB Best Values"),
        mlb_table_html(record_df, "MLB Record Summary"),
        mlb_table_html(hitter_df, "MLB Hitter Summary"),
        mlb_table_html(pitcher_df, "MLB Pitcher Props"),
        mlb_table_html(history_df, "MLB Recent Bet History"),
    ]
    return "".join(pieces)


def sync_public_copy(source_path):
    try:
        os.makedirs(os.path.dirname(PUBLIC_INDEX_PATH), exist_ok=True)
        with open(source_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        with open(PUBLIC_INDEX_PATH, "w", encoding="utf-8") as handle:
            handle.write(html)
        print(f"Synced public page: {PUBLIC_INDEX_PATH}")
    except Exception as exc:
        print(f"WARNING: Could not sync public page: {exc}")


def main():
    record_df = read_csv_or_empty(RECORD_SUMMARY_PATH)
    calibration_df = read_csv_or_empty(CALIBRATION_SUMMARY_PATH)

    calibration_report = ""
    if os.path.exists(CALIBRATION_REPORT_PATH):
        with open(CALIBRATION_REPORT_PATH, "r", encoding="utf-8") as handle:
            calibration_report = handle.read().strip()

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mlb_section = build_mlb_section()

    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>EdgeRanked Results</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffaf0;
      --ink: #1f1f1f;
      --accent: #b5522d;
      --grid: #d8cfc0;
      --bg-dark: #0d1117;
      --panel-dark: #151b23;
      --ink-dark: #f3f6fb;
      --grid-dark: #283344;
      --accent-dark: #77b2ff;
    }}
    body {{
      margin: 0;
      padding: 32px;
      background: linear-gradient(180deg, #f5f1e8 0%, #efe7db 100%);
      color: var(--ink);
      font-family: Georgia, 'Times New Roman', serif;
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .tabs {{
      display: flex;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .tab-btn {{
      appearance: none;
      border: 1px solid var(--grid);
      background: var(--panel);
      color: var(--ink);
      padding: 10px 16px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 14px;
    }}
    .tab-btn.active {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--grid);
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    }}
    .mlb-theme .hero, .mlb-theme .section {{
      background: var(--panel-dark);
      color: var(--ink-dark);
      border-color: var(--grid-dark);
      box-shadow: 0 14px 32px rgba(0,0,0,0.28);
    }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    .meta {{ color: #5b564f; font-size: 14px; }}
    .mlb-theme .meta {{ color: #9ba9ba; }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--grid);
      padding: 20px 24px;
      margin-bottom: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.05);
    }}
    .table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    .table th, .table td {{ border-bottom: 1px solid var(--grid); padding: 8px 10px; text-align: left; }}
    .table th {{ color: var(--accent); }}
    .mlb-theme .table th, .mlb-theme .table td {{ border-bottom-color: var(--grid-dark); }}
    .mlb-theme .table th {{ color: var(--accent-dark); }}
    pre {{ white-space: pre-wrap; background: #f7efe3; padding: 16px; border: 1px solid var(--grid); overflow-x: auto; }}
    .snapshot {{ width: 100%; border-radius: 12px; border: 1px solid var(--grid-dark); display: block; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"tabs\">
      <button class=\"tab-btn active\" onclick=\"showTab('nba', this)\">NBA</button>
      <button class=\"tab-btn\" onclick=\"showTab('mlb', this)\">MLB</button>
    </div>

    <div id=\"nba\" class=\"tab-panel active\">
      <div class=\"hero\">
        <h1>NBA Model Results</h1>
        <div class=\"meta\">Updated {updated_at}</div>
      </div>
      <div class=\"section\">
        {df_to_html(record_df, 'Record Summary')}
      </div>
      <div class=\"section\">
        {df_to_html(calibration_df, 'Calibration Summary')}
      </div>
      <div class=\"section\">
        <h2>Calibration Report</h2>
        <pre>{escape(calibration_report or 'No calibration report available.')}</pre>
      </div>
    </div>

    <div id=\"mlb\" class=\"tab-panel mlb-theme\">
      {mlb_section}
    </div>
  </div>
  <script>
    function showTab(tabId, btn) {{
      document.querySelectorAll('.tab-panel').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      btn.classList.add('active');
    }}
  </script>
</body>
</html>
"""

    with open(RESULTS_PAGE_PATH, "w", encoding="utf-8") as handle:
        handle.write(html)
    sync_public_copy(RESULTS_PAGE_PATH)

    print(f"Saved results page: {RESULTS_PAGE_PATH}")


if __name__ == "__main__":
    main()
