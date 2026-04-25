import io
import re
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader

from nba_model.settings import (
    INJURY_CSV_PATH,
    INJURY_TXT_PATH,
)

EASTERN = ZoneInfo("America/New_York")
STATUS_PATTERN = r"(Available|Probable|Questionable|Doubtful|Out)"
ROW_WITHOUT_TEAM_RE = re.compile(
    rf"^(?P<player>[A-Za-z'. -]+,\s*[A-Za-z'. -]+)\s+(?P<status>{STATUS_PATTERN})\b(?P<reason>.*)$"
)
LEADING_GAME_RE = re.compile(
    r"^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\s+\(ET\)\s+[A-Z]{2,4}@[A-Z]{2,4}\s+"
)
TEAM_NAMES = sorted(
    [
        "Atlanta Hawks",
        "Boston Celtics",
        "Brooklyn Nets",
        "Charlotte Hornets",
        "Chicago Bulls",
        "Cleveland Cavaliers",
        "Dallas Mavericks",
        "Denver Nuggets",
        "Detroit Pistons",
        "Golden State Warriors",
        "Houston Rockets",
        "Indiana Pacers",
        "LA Clippers",
        "Los Angeles Lakers",
        "Memphis Grizzlies",
        "Miami Heat",
        "Milwaukee Bucks",
        "Minnesota Timberwolves",
        "New Orleans Pelicans",
        "New York Knicks",
        "Oklahoma City Thunder",
        "Orlando Magic",
        "Philadelphia 76ers",
        "Phoenix Suns",
        "Portland Trail Blazers",
        "Sacramento Kings",
        "San Antonio Spurs",
        "Toronto Raptors",
        "Utah Jazz",
        "Washington Wizards",
    ],
    key=len,
    reverse=True,
)


def normalize_player_name(raw_name):
    raw_name = " ".join(str(raw_name).strip().split())
    if "," not in raw_name:
        return raw_name
    last, first = [part.strip() for part in raw_name.split(",", 1)]
    return f"{first} {last}".strip()


def parse_report_timestamp(label):
    cleaned = str(label).replace("a.m", "AM").replace("p.m", "PM")
    cleaned = cleaned.replace("ET report", "ET").strip()
    try:
        return datetime.strptime(cleaned, "%I:%M %p ET").time()
    except ValueError:
        return None


def fetch_url_bytes(url, timeout=30):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def report_index_candidates():
    now = datetime.now(EASTERN)
    start_year = now.year if now.month >= 7 else now.year - 1
    current_slug = f"{start_year}-{str(start_year + 1)[-2:]}"
    previous_slug = f"{start_year - 1}-{str(start_year)[-2:]}"
    return [
        f"https://official.nba.com/nba-injury-report-{current_slug}-season/",
        f"https://official.nba.com/nba-injury-report-{previous_slug}-season/",
    ]


def extract_latest_report_url():
    today = datetime.now(EASTERN).date()
    today_slug = today.strftime("%Y-%m-%d")
    latest = None

    for report_index_url in report_index_candidates():
        try:
            html = fetch_url_bytes(report_index_url, timeout=30).decode("utf-8", errors="ignore")
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")

        for anchor in soup.find_all("a", href=True):
            label = " ".join(anchor.get_text(" ", strip=True).split())
            report_time = parse_report_timestamp(label)
            if report_time is None:
                continue
            url = anchor["href"].strip()
            if not url.lower().endswith(".pdf"):
                continue
            if today_slug not in url:
                continue
            candidate = {
                "label": label,
                "time": report_time,
                "url": url,
                "index_url": report_index_url,
            }
            if latest is None or candidate["time"] > latest["time"]:
                latest = candidate

        if latest is not None:
            break

    if latest is None:
        raise RuntimeError("Could not find a current-day official NBA injury report PDF from NBA Official.")

    return latest


def extract_pdf_text(pdf_url):
    pdf_bytes = fetch_url_bytes(pdf_url, timeout=60)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text(extraction_mode="layout") or "")
        except TypeError:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def parse_injury_rows(raw_text, source_url, report_label):
    rows = []
    current_team = None
    current_record = None

    for raw_line in raw_text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        if line.startswith("Injury Report:") or line.startswith("Page "):
            continue
        if line.startswith("Game Date Game Time Matchup Team Player Name Current Status Reason"):
            continue

        line = LEADING_GAME_RE.sub("", line)

        if "NOT YET SUBMITTED" in line:
            current_record = None
            continue

        matched_team = next((team for team in TEAM_NAMES if line.startswith(f"{team} ")), None)
        candidate_line = line
        if matched_team:
            current_team = matched_team
            candidate_line = line[len(matched_team) + 1 :].strip()

        match = ROW_WITHOUT_TEAM_RE.match(candidate_line)
        if match and matched_team:
            current_record = {
                "PLAYER_NAME": normalize_player_name(match.group("player")),
                "TEAM": current_team,
                "STATUS": match.group("status").upper(),
                "REASON": match.group("reason").strip(),
                "SOURCE_REPORT": report_label,
                "SOURCE_URL": source_url,
                "UPDATED_AT_ET": datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S"),
            }
            rows.append(current_record)
            continue

        match = ROW_WITHOUT_TEAM_RE.match(line)
        if match:
            current_record = {
                "PLAYER_NAME": normalize_player_name(match.group("player")),
                "TEAM": current_team or "",
                "STATUS": match.group("status").upper(),
                "REASON": match.group("reason").strip(),
                "SOURCE_REPORT": report_label,
                "SOURCE_URL": source_url,
                "UPDATED_AT_ET": datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S"),
            }
            rows.append(current_record)
            continue

        if current_record is not None:
            extra = line.strip()
            if extra:
                current_record["REASON"] = " ".join(
                    part for part in [current_record.get("REASON", ""), extra] if part
                ).strip()

    if not rows:
        raise RuntimeError("Official NBA injury report parsed zero rows.")

    df = pd.DataFrame(rows).drop_duplicates(subset=["PLAYER_NAME"], keep="last")
    return df.sort_values(["TEAM", "PLAYER_NAME"]).reset_index(drop=True)


def write_outputs(df):
    export_df = df[["PLAYER_NAME", "STATUS", "SOURCE_REPORT", "SOURCE_URL", "UPDATED_AT_ET"]].copy()
    export_df = export_df.sort_values(["STATUS", "PLAYER_NAME"]).reset_index(drop=True)
    export_df.to_csv(INJURY_CSV_PATH, index=False)
    with open(INJURY_TXT_PATH, "w", encoding="utf-8") as handle:
        for _, row in export_df.iterrows():
            handle.write(f"{row['PLAYER_NAME']}|{row['STATUS']}\n")


def main():
    latest = extract_latest_report_url()
    print(f"Using official NBA injury report: {latest['label']}")
    print(latest["url"])
    raw_text = extract_pdf_text(latest["url"])
    df = parse_injury_rows(raw_text, latest["url"], latest["label"])
    write_outputs(df)
    status_counts = df["STATUS"].value_counts().to_dict()
    print(f"Saved {len(df)} injury rows to {INJURY_CSV_PATH}")
    print("Status counts:", status_counts)


if __name__ == "__main__":
    main()
