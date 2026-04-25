import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime

import pandas as pd

from nba_model.settings import (
    BEST_BETS_OUTPUT_PATH,
    CALIBRATION_REPORT_PATH,
    GRADED_OUTPUT_PATH,
    PROJECT_ROOT,
    RECORD_SUMMARY_PATH,
    RESULTS_PAGE_PATH,
)

BASE_DIR = str(PROJECT_ROOT)
EMAIL_CONFIG_PATH = os.path.join(BASE_DIR, "email_config.json")


def load_config():
    recipients = []
    subject_prefix = "EdgeRanked SportsAI"

    if os.path.exists(EMAIL_CONFIG_PATH):
        try:
            with open(EMAIL_CONFIG_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            recipients = [str(x).strip() for x in data.get("to", []) if str(x).strip()]
            subject_prefix = str(data.get("subject_prefix", subject_prefix)).strip() or subject_prefix
        except Exception as exc:
            print(f"WARNING: Could not read email config: {exc}")

    env_to = os.environ.get("RESULTS_EMAIL_TO", "").strip()
    if env_to:
        recipients = [item.strip() for item in env_to.split(",") if item.strip()]

    return {
        "to": recipients,
        "subject_prefix": subject_prefix,
    }


def read_csv(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def summarize_graded_bets(df):
    if df.empty:
        return ["No graded bets were found."]

    wins = int((df.get("result", pd.Series(dtype=str)) == "WIN").sum())
    losses = int((df.get("result", pd.Series(dtype=str)) == "LOSS").sum())
    pending = int((df.get("result", pd.Series(dtype=str)) == "PENDING").sum())
    target_date = str(df["date"].astype(str).iloc[0]) if "date" in df.columns and not df.empty else "n/a"

    lines = [
        f"Yesterday's graded bets ({target_date})",
        f"Record: {wins}-{losses}",
        f"Pending: {pending}",
        "",
    ]

    preview = df.copy()
    keep_cols = [c for c in ["player", "team", "stat", "bet", "line", "actual", "result"] if c in preview.columns]
    for _, row in preview[keep_cols].head(12).iterrows():
        parts = [str(row.get("player", "")), str(row.get("team", "")), str(row.get("bet", ""))]
        if "line" in row.index:
            parts.append(f"line {row.get('line')}")
        if "actual" in row.index and pd.notna(row.get("actual")):
            parts.append(f"actual {row.get('actual')}")
        if "result" in row.index:
            parts.append(str(row.get("result", "")))
        lines.append(" - " + " | ".join([p for p in parts if p and p != "nan"]))
    return lines


def summarize_best_bets(df):
    if df.empty:
        return ["Today's best bets", "No bets found.", ""]

    lines = ["Today's best bets", ""]
    keep_cols = [c for c in ["PLAYER", "TEAM", "MATCHUP", "BET", "LINE", "PROJECTION", "CONFIDENCE_LABEL"] if c in df.columns]
    for _, row in df[keep_cols].head(10).iterrows():
        parts = [str(row.get("PLAYER", "")), str(row.get("TEAM", "")), str(row.get("MATCHUP", "")), str(row.get("BET", ""))]
        if "LINE" in row.index:
            parts.append(f"line {row.get('LINE')}")
        if "PROJECTION" in row.index:
            parts.append(f"proj {row.get('PROJECTION')}")
        if "CONFIDENCE_LABEL" in row.index:
            parts.append(str(row.get("CONFIDENCE_LABEL", "")))
        lines.append(" - " + " | ".join([p for p in parts if p and p != "nan"]))
    lines.append("")
    return lines


def summarize_record(df):
    if df.empty:
        return ["Updated results", "No record summary available.", ""]

    latest = df.iloc[-1]
    lines = [
        "Updated results",
        f"Latest day: {latest.get('date', 'n/a')}",
        f"Latest record: {latest.get('wins', 0)}-{latest.get('losses', 0)}",
        f"Win rate: {latest.get('win_pct', 'n/a')}",
        "",
    ]
    return lines


def build_email_body():
    graded = read_csv(GRADED_OUTPUT_PATH)
    best_bets = read_csv(BEST_BETS_OUTPUT_PATH)
    record = read_csv(RECORD_SUMMARY_PATH)
    calibration_report = ""
    if os.path.exists(CALIBRATION_REPORT_PATH):
        try:
            with open(CALIBRATION_REPORT_PATH, "r", encoding="utf-8") as handle:
                calibration_report = handle.read().strip()
        except Exception:
            calibration_report = ""

    sections = [
        f"EdgeRanked SportsAI morning update",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    sections.extend(summarize_graded_bets(graded))
    sections.extend(summarize_best_bets(best_bets))
    sections.extend(summarize_record(record))

    if calibration_report:
        sections.extend([
            "Calibration snapshot",
            calibration_report,
            "",
        ])

    sections.extend([
        f"Attached file: {RESULTS_PAGE_PATH}",
    ])
    return "\n".join(sections).strip() + "\n"


def applescript_string(value):
    text = str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return json.dumps(text)


def send_via_mail_app(recipients, subject, body, attachment_path=None):
    recipients_block = "\n".join(
        f'make new to recipient at end of to recipients with properties {{address:{applescript_string(address)}}}'
        for address in recipients
    )
    attachment_block = ""
    if attachment_path and os.path.exists(attachment_path):
        attachment_block = (
            "tell content of newMessage\n"
            f'    make new attachment with properties {{file name:((POSIX file {applescript_string(attachment_path)}) as alias)}} at after the last paragraph\n'
            "end tell\n"
        )

    script = f'''
tell application "Mail"
    set newMessage to make new outgoing message with properties {{subject:{applescript_string(subject)}, content:{applescript_string(body)}, visible:false}}
    tell newMessage
        {recipients_block}
    end tell
    {attachment_block}
    send newMessage
end tell
'''
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = handle.name
    try:
        subprocess.run(["osascript", script_path], check=True)
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass


def main():
    config = load_config()
    recipients = config["to"]
    if not recipients:
        print("No email recipients configured. Skipping email send.")
        print(f"Set RESULTS_EMAIL_TO or create {EMAIL_CONFIG_PATH}.")
        return

    subject = f"{config['subject_prefix']} morning update"
    body = build_email_body()
    send_via_mail_app(recipients, subject, body, RESULTS_PAGE_PATH)
    print(f"Sent results email to: {', '.join(recipients)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Email send failed: {exc}")
        sys.exit(exc.returncode or 1)
