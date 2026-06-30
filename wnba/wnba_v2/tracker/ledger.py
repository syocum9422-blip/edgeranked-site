"""Phase 6 — recommendation ledger (persist, line-track, grade).

One append-only row per V2 recommendation with everything promotion needs:
identity + projection/probability/conviction/side, version stamps, line tracking
(open/latest/close/move/CLV), and grading (actual/result/realized edge & CLV).
Production's stance on the same bet is stored in parallel for head-to-head.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from wnba_v2 import config as C
from wnba_v2.tracker import versions as V

LEDGER_PATH = C.OUTPUTS / "tracker" / "recommendations_ledger.csv"

COLUMNS = [
    # identity / recommendation
    "date", "market", "player", "line", "v2_projection", "p_over", "conviction", "side",
    "model_version", "calibration_version", "simulation_version", "timestamp",
    # line tracking
    "open_line", "latest_line", "close_line", "line_move", "clv",
    # grading
    "actual_value", "actual_over", "result", "realized_edge", "realized_clv",
    # parallel production reference (same bet)
    "prod_p_over", "prod_result",
]


def _blank(n, idx):
    return pd.Series([np.nan] * n, index=idx)


def append_recommendations(df: pd.DataFrame) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[COLUMNS]
    if LEDGER_PATH.exists():
        prev = pd.read_csv(LEDGER_PATH)
        df = pd.concat([prev, df], ignore_index=True)
        # V2 has one current stance per historical player/market/line. When the
        # simulator changes and the side flips, replace the stale stance instead
        # of carrying both old and new V2 records in the dashboard.
        df = df.drop_duplicates(["date", "market", "player", "line"], keep="last")
    df.to_csv(LEDGER_PATH, index=False)


def load_ledger() -> pd.DataFrame:
    return pd.read_csv(LEDGER_PATH) if LEDGER_PATH.exists() else pd.DataFrame(columns=COLUMNS)


def seed_from_backtest() -> pd.DataFrame:
    """Populate the ledger with V2's real historical (graded) track record from the
    Phase 5.1 backtest, so the dashboard has live evidence immediately. Idempotent."""
    src = C.OUTPUTS / "simulation" / "backtest_graded.csv"
    b = pd.read_csv(src)
    ver = V.current()
    now = datetime.now(timezone.utc).isoformat()
    out = pd.DataFrame({
        "date": b["date"], "market": b["stat"], "player": b["player"], "line": b["line"],
        "v2_projection": b["v2_proj"], "p_over": b["v2_p_over"],
        "conviction": b["conf"], "side": np.where(b["v2_p_over"] > 0.5, "over", "under"),
        "model_version": ver["model_version"], "calibration_version": ver["calibration_version"],
        "simulation_version": ver["simulation_version"], "timestamp": now,
        "open_line": np.nan, "latest_line": b["line"], "close_line": np.nan,
        "line_move": np.nan, "clv": b["clv"],
        "actual_value": b["actual_value"], "actual_over": b["actual_over"],
        "result": np.where(b["v2_correct"] == 1, "win", "loss"),
        "realized_edge": b["v2_p_over"] - 0.5,
        "realized_clv": b["clv"],
        "prod_p_over": b["prod_p_over"],
        "prod_result": np.where(b["prod_correct"] == 1, "win", "loss"),
    })
    append_recommendations(out)
    V.record_registry()
    return out


def grade_pending(actuals: pd.DataFrame | None = None) -> int:
    """Grade ledger rows that have a recommendation but no result yet, using actuals
    (date, player, market, actual_value). Returns number newly graded. For forward
    live use; the historical seed arrives already graded."""
    led = load_ledger()
    pending = led["result"].isna()
    if not pending.any() or actuals is None or actuals.empty:
        return 0
    a = actuals.rename(columns={"value": "actual_value"})
    led = led.merge(a[["date", "player", "market", "actual_value"]],
                    on=["date", "player", "market"], how="left", suffixes=("", "_new"))
    fill = led["actual_value"].isna() & led["actual_value_new"].notna()
    led.loc[fill, "actual_value"] = led.loc[fill, "actual_value_new"]
    graded = led["result"].isna() & led["actual_value"].notna()
    led.loc[graded, "actual_over"] = (led.loc[graded, "actual_value"] > led.loc[graded, "line"]).astype(int)
    over = led["side"] == "over"
    win = ((over & (led["actual_over"] == 1)) | (~over & (led["actual_over"] == 0)))
    push = np.isclose(led["actual_value"], led["line"])
    led.loc[graded, "result"] = np.where(push[graded], "push", np.where(win[graded], "win", "loss"))
    led.loc[graded, "realized_clv"] = led.loc[graded, "clv"]
    led = led.drop(columns=[c for c in led.columns if c.endswith("_new")])
    led.to_csv(LEDGER_PATH, index=False)
    return int(graded.sum())
