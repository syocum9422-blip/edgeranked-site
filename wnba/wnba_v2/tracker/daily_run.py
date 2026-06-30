"""Phase 6 — daily parallel-tracker run.

Operational loop that keeps V2's shadow-production evidence current:
  1. refit engines + recalibrate on all available history (leak-free, season-cut)
  2. score the slate with the full correlated MC -> V2 picks vs the offered lines
  3. append recommendations to the ledger (with version stamps)
  4. grade newly-completed games + attach CLV from the line-capture history
  5. refresh the dashboard + promotion/rollback gate

As the season's games flow in nightly (Phase-2 box-score refresh), the ledger
grows until the gate's sample/significance thresholds are met. Fail-soft: any
stage that errors is logged and the others still run.

Run:  .venv/bin/python -m wnba_v2.tracker.daily_run
"""
from __future__ import annotations

import json
import traceback

import pandas as pd

from wnba_v2 import config as C
from wnba_v2.tracker import dashboard, versions
from wnba_v2.tracker.ledger import grade_pending, seed_from_backtest


def _attach_clv(ledger_path) -> int:
    """Fill open/close/CLV on graded ledger rows from the prop open/close history."""
    hist = C.V2_ROOT / "data" / "line_history" / "prop_open_close.csv"
    if not hist.exists() or not ledger_path.exists():
        return 0
    oc = pd.read_csv(hist)
    if oc.empty:
        return 0
    led = pd.read_csv(ledger_path)
    # normalize join keys (player_name + stat + date)
    import re
    def nk(s): return re.sub(r"[^a-z]", "", str(s).lower())
    led["_k"] = led["player"].map(nk) + "|" + led["market"].astype(str) + "|" + led["date"].astype(str)
    oc["date2"] = pd.to_datetime(oc["date"], format="%Y%m%d", errors="coerce").dt.date.astype(str)
    oc["_k"] = oc["player_name"].map(nk) + "|" + oc["stat"].astype(str) + "|" + oc["date2"]
    oc = oc.drop_duplicates("_k", keep="last")
    m = oc.set_index("_k")[["open_line", "close_line", "line_move"]].to_dict("index")
    filled = 0
    for i, r in led.iterrows():
        rec = m.get(r["_k"])
        if rec and pd.isna(r.get("open_line")):
            led.at[i, "open_line"] = rec["open_line"]
            led.at[i, "close_line"] = rec["close_line"]
            led.at[i, "line_move"] = rec["line_move"]
            # CLV for V2's side: favorable if close moved away from our entry
            over = r["side"] == "over"
            led.at[i, "clv"] = (rec["close_line"] - r["line"]) if over else (r["line"] - rec["close_line"])
            led.at[i, "realized_clv"] = led.at[i, "clv"]
            filled += 1
    led.drop(columns=["_k"], inplace=True)
    led.to_csv(ledger_path, index=False)
    return filled


def run() -> dict:
    from wnba_v2.tracker.ledger import LEDGER_PATH
    status = {"stages": {}}
    versions.record_registry()

    # Phase 5.4. Fail closed for V2 scoring if the learned conserved simulator or
    # its realism gates are unavailable. This does not alter serving/promotion logic.
    v2_ready = False
    try:
        from wnba_v2.engines.simulation.phase54_daily import run as phase54_run
        phase54_status = phase54_run()
        status["stages"]["phase54_conserved_daily"] = "ok"
        status["phase54"] = phase54_status
        v2_ready = True
    except Exception:
        status["stages"]["phase54_conserved_daily"] = "FAIL_CLOSED\n" + traceback.format_exc()

    # 1+2+3. score slate -> recommendations ledger (re-derives V2 picks OOS on the
    # graded history; new completed slates extend it as box scores refresh nightly)
    if v2_ready:
        try:
            from wnba_v2.engines.simulation.backtest import run as bt_run
            bt_run()
            seeded = seed_from_backtest()
            status["stages"]["score_and_record"] = f"ok ({len(seeded)} recs)"
        except Exception:
            status["stages"]["score_and_record"] = "FAIL\n" + traceback.format_exc()
    else:
        status["stages"]["score_and_record"] = "SKIPPED_FAIL_CLOSED_PHASE54"

    # 4. CLV from line history + grade any pending
    try:
        n_clv = _attach_clv(LEDGER_PATH)
        n_graded = grade_pending()
        status["stages"]["clv_and_grade"] = f"ok (clv filled {n_clv}, graded {n_graded})"
    except Exception:
        status["stages"]["clv_and_grade"] = "FAIL\n" + traceback.format_exc()

    # 5. dashboard + gate
    try:
        d = dashboard.run()
        status["stages"]["dashboard"] = "ok"
        status["gate_decision"] = d["gate"]["decision"]
        status["graded_recommendations"] = d["graded_recommendations"]
    except Exception:
        status["stages"]["dashboard"] = "FAIL\n" + traceback.format_exc()

    (C.OUTPUTS / "tracker" / "daily_run_status.json").write_text(json.dumps(status, indent=2))
    return status


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
