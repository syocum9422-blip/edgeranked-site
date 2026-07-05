"""Phase 6.1 - minutes role-change diagnostics.

This is a diagnostic-only pass. It reads the Phase 6 out-of-sample minutes
predictions and finds where the remaining p50 errors cluster. It does not train
or promote a new minutes model.

Run:  python3 -m wnba_v2.engines.minutes.phase61_role_change_diagnostics
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from wnba_v2 import config as C

DATASET = C.PROD_ROOT / "data" / "processed" / "wnba_training_dataset.csv"
MINUTES_OUT = C.OUTPUTS / "minutes"
PREDICTIONS = MINUTES_OUT / "oos_predictions.csv"
OUT = MINUTES_OUT / "phase61"

ROLE_MINUTES = 24.0
JUMP_MINUTES = 8.0
KEY_TEAMMATE_MIN_MEAN = 18.0
KEY_TEAMMATE_LAST_GAME_MIN = 24.0


def _mae(s: pd.Series) -> float:
    if len(s) == 0:
        return float("nan")
    return float(s.abs().mean())


def _read_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    preds = pd.read_csv(PREDICTIONS, parse_dates=["game_date"])
    raw = pd.read_csv(DATASET, parse_dates=["game_date"])
    raw = raw.sort_values(["player_key", "game_date"]).copy()
    raw["min_lag1_raw"] = raw.groupby("player_key")["minutes"].shift(1)
    raw["min_lag2_raw"] = raw.groupby("player_key")["minutes"].shift(2)
    raw["prior_minutes_delta"] = raw["min_lag1_raw"] - raw["min_lag2_raw"]
    raw["prior_abs_minutes_delta"] = raw["prior_minutes_delta"].abs()
    return preds, raw


def _team_absence_proxy(raw: pd.DataFrame, team_dates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    raw_by_team = {team: grp.sort_values("game_date") for team, grp in raw.groupby("team")}
    active_lookup = {
        (date, team): set(group["player_key"].astype(str))
        for (date, team), group in raw.groupby(["game_date", "team"])
    }
    for row in team_dates.itertuples(index=False):
        team = row.team
        date = row.game_date
        season = row.season
        hist = raw_by_team.get(team, pd.DataFrame())
        if hist.empty:
            rows.append(_absence_row(date, team, 0, 0.0, ""))
            continue
        hist = hist[(hist["game_date"] < date) & (hist["season"] == season)]
        if hist.empty:
            rows.append(_absence_row(date, team, 0, 0.0, ""))
            continue
        active_today = active_lookup.get((date, team), set())
        key_players = []
        for player_key, ph in hist.groupby("player_key"):
            ph = ph.sort_values("game_date")
            recent = ph.tail(5)
            recent_mean = float(recent["minutes"].mean())
            last_minutes = float(recent["minutes"].iloc[-1])
            if recent_mean >= KEY_TEAMMATE_MIN_MEAN or last_minutes >= KEY_TEAMMATE_LAST_GAME_MIN:
                player_name = str(recent["player_name"].iloc[-1]) if "player_name" in recent else str(player_key)
                key_players.append((str(player_key), player_name, recent_mean))
        absent = [(key, name, mins) for key, name, mins in key_players if key not in active_today]
        absent_names = "; ".join(name for _, name, _ in sorted(absent, key=lambda x: -x[2])[:8])
        rows.append(_absence_row(date, team, len(absent), float(sum(x[2] for x in absent)), absent_names))
    return pd.DataFrame(rows)


def _absence_row(date, team: str, count: int, minutes: float, names: str) -> dict:
    return {
        "game_date": date,
        "team": team,
        "key_teammates_absent": int(count),
        "key_teammate_minutes_absent": round(minutes, 2),
        "key_teammates_absent_names": names,
    }


def _enrich(preds: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    lag_cols = raw[[
        "game_date", "player_key", "team", "min_lag1_raw", "min_lag2_raw",
        "prior_minutes_delta", "prior_abs_minutes_delta",
    ]].copy()
    df = preds.merge(lag_cols, on=["game_date", "player_key", "team"], how="left")

    team_dates = df[["game_date", "season", "team"]].drop_duplicates()
    absences = _team_absence_proxy(raw, team_dates)
    df = df.merge(absences, on=["game_date", "team"], how="left")
    for col in ["key_teammates_absent", "key_teammate_minutes_absent"]:
        df[col] = df[col].fillna(0)
    df["key_teammates_absent_names"] = df["key_teammates_absent_names"].fillna("")

    df["phase6_error"] = df["q50"] - df["minutes"]
    df["phase6_abs_error"] = df["phase6_error"].abs()
    df["naive_last5_error"] = df["naive_last5"] - df["minutes"]
    df["naive_last5_abs_error"] = df["naive_last5_error"].abs()
    df["base_gbm_abs_error"] = (df["q50_base_gbm"] - df["minutes"]).abs()

    prior_role = np.where(df["min_lag1_raw"].fillna(0) >= ROLE_MINUTES, "starter", "bench")
    actual_role = np.where(df["minutes"] >= ROLE_MINUTES, "starter", "bench")
    df["prior_role"] = prior_role
    df["actual_role"] = actual_role
    df["starter_to_bench"] = (df["prior_role"] == "starter") & (df["actual_role"] == "bench")
    df["bench_to_starter"] = (df["prior_role"] == "bench") & (df["actual_role"] == "starter")
    df["sudden_starter_bench_change"] = df["starter_to_bench"] | df["bench_to_starter"]

    df["after_prior_jump_up_8"] = df["prior_minutes_delta"] >= JUMP_MINUTES
    df["after_prior_drop_8"] = df["prior_minutes_delta"] <= -JUMP_MINUTES
    df["after_prior_jump_or_drop_8"] = df["prior_abs_minutes_delta"] >= JUMP_MINUTES
    df["current_jump_or_drop_8"] = (df["minutes"] - df["min_lag1_raw"]).abs() >= JUMP_MINUTES
    df["return_from_injury_proxy"] = (df["rest_days"].fillna(0) >= 7) & (df["games_played_season"].fillna(99) > 2)
    df["rookie_new_signing_proxy"] = (df["games_played_season"].fillna(0) <= 2) | df["min_lag1_raw"].isna()
    df["teammate_out_proxy"] = df["key_teammates_absent"] > 0
    df["blowout"] = df["abs_game_margin"].fillna(0) >= 15
    df["close_game"] = df["abs_game_margin"].fillna(99) <= 5
    return df


def _segment_table(df: pd.DataFrame) -> pd.DataFrame:
    segment_specs = {
        "overall": pd.Series("overall", index=df.index),
        "sudden_starter_bench_change": df["sudden_starter_bench_change"],
        "starter_to_bench": df["starter_to_bench"],
        "bench_to_starter": df["bench_to_starter"],
        "teammate_out_proxy": df["teammate_out_proxy"],
        "return_from_injury_proxy": df["return_from_injury_proxy"],
        "rookie_new_signing_proxy": df["rookie_new_signing_proxy"],
        "after_prior_jump_up_8": df["after_prior_jump_up_8"],
        "after_prior_drop_8": df["after_prior_drop_8"],
        "after_prior_jump_or_drop_8": df["after_prior_jump_or_drop_8"],
        "current_jump_or_drop_8": df["current_jump_or_drop_8"],
        "blowout": df["blowout"],
        "close_game": df["close_game"],
        "team": df["team"].astype(str),
        "player": df["player_key"].astype(str),
    }
    overall_mae = _mae(df["phase6_error"])
    rows = []
    for segment, labels in segment_specs.items():
        for value, idx in labels.groupby(labels).groups.items():
            sub = df.loc[idx]
            if segment in {"player", "team"} and len(sub) < (5 if segment == "player" else 20):
                continue
            phase6_mae = _mae(sub["phase6_error"])
            naive_mae = _mae(sub["naive_last5_error"])
            base_mae = _mae(sub["q50_base_gbm"] - sub["minutes"])
            rows.append({
                "segment": segment,
                "value": str(value),
                "n": int(len(sub)),
                "share_of_rows": round(len(sub) / len(df), 4),
                "phase6_mae": round(phase6_mae, 4),
                "naive_last5_mae": round(naive_mae, 4),
                "base_gbm_mae": round(base_mae, 4),
                "phase6_vs_naive_delta": round(phase6_mae - naive_mae, 4),
                "phase6_vs_overall_delta": round(phase6_mae - overall_mae, 4),
                "mean_signed_error": round(float(sub["phase6_error"].mean()), 4),
                "total_abs_error": round(float(sub["phase6_abs_error"].sum()), 4),
                "error_share": round(float(sub["phase6_abs_error"].sum() / df["phase6_abs_error"].sum()), 4),
            })
    return pd.DataFrame(rows).sort_values(
        ["phase6_vs_overall_delta", "total_abs_error"], ascending=[False, False]
    )


def _top_cases(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "game_date", "player_name", "player_key", "team", "opponent", "minutes",
        "q50", "naive_last5", "q50_base_gbm", "phase6_error", "phase6_abs_error",
        "min_lag1_raw", "prior_minutes_delta", "starter_to_bench", "bench_to_starter",
        "key_teammates_absent", "key_teammate_minutes_absent", "key_teammates_absent_names",
        "return_from_injury_proxy", "rookie_new_signing_proxy", "abs_game_margin",
    ]
    return df.sort_values("phase6_abs_error", ascending=False)[cols].head(50)


def _team_instability(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for team, sub in df.groupby("team"):
        if len(sub) < 20:
            continue
        rows.append({
            "team": team,
            "n": int(len(sub)),
            "phase6_mae": round(_mae(sub["phase6_error"]), 4),
            "naive_last5_mae": round(_mae(sub["naive_last5_error"]), 4),
            "role_change_rate": round(float(sub["sudden_starter_bench_change"].mean()), 4),
            "prior_jump_drop_rate": round(float(sub["after_prior_jump_or_drop_8"].mean()), 4),
            "teammate_out_rate": round(float(sub["teammate_out_proxy"].mean()), 4),
            "blowout_rate": round(float(sub["blowout"].mean()), 4),
            "avg_abs_margin": round(float(sub["abs_game_margin"].mean()), 4),
        })
    out = pd.DataFrame(rows)
    out["instability_score"] = (
        out["role_change_rate"] + out["prior_jump_drop_rate"] + out["teammate_out_rate"] + out["blowout_rate"]
    )
    return out.sort_values(["phase6_mae", "instability_score"], ascending=[False, False])


def _write_report(summary: dict, segments: pd.DataFrame, team_instability: pd.DataFrame, top_cases: pd.DataFrame) -> None:
    positive = segments[
        (segments["value"] == "True")
        & (~segments["segment"].isin(["current_jump_or_drop_8"]))
    ].copy()
    positive = positive.sort_values(["phase6_vs_overall_delta", "error_share"], ascending=[False, False])
    top_leak = positive.head(1)

    lines = [
        "# Phase 6.1 Minutes Role-Change Diagnostics",
        "",
        "Diagnostic-only pass. No new model was trained.",
        "",
        "## Baseline",
        f"Rows: {summary['rows']}",
        f"Overall Phase 6 p50 MAE: {summary['overall_phase6_mae']:.4f}",
        f"Naive last-5 MAE: {summary['overall_naive_last5_mae']:.4f}",
        "",
        "## Largest Quantified Leak",
    ]
    if not top_leak.empty:
        r = top_leak.iloc[0]
        lines.append(
            f"{r['segment']}={r['value']}: n={int(r['n'])}, MAE={r['phase6_mae']:.4f}, "
            f"overall_delta={r['phase6_vs_overall_delta']:.4f}, error_share={r['error_share']:.2%}."
        )
    else:
        lines.append("No positive diagnostic segment found.")
    lines.extend([
        "",
        "## Role/Availability Segments",
    ])
    keep = [
        "sudden_starter_bench_change", "starter_to_bench", "bench_to_starter",
        "teammate_out_proxy", "return_from_injury_proxy", "rookie_new_signing_proxy",
        "after_prior_jump_up_8", "after_prior_drop_8", "after_prior_jump_or_drop_8",
        "blowout", "close_game",
    ]
    for _, r in segments[(segments["segment"].isin(keep)) & (segments["value"] == "True")].iterrows():
        lines.append(
            f"- {r['segment']}: n={int(r['n'])}, MAE={r['phase6_mae']:.4f}, "
            f"vs overall={r['phase6_vs_overall_delta']:+.4f}, vs naive={r['phase6_vs_naive_delta']:+.4f}, "
            f"error_share={r['error_share']:.2%}, signed_error={r['mean_signed_error']:+.4f}"
        )
    lines.extend([
        "",
        "## Unstable Teams",
    ])
    for _, r in team_instability.head(8).iterrows():
        lines.append(
            f"- {r['team']}: n={int(r['n'])}, MAE={r['phase6_mae']:.4f}, "
            f"role_change_rate={r['role_change_rate']:.2%}, prior_jump_drop_rate={r['prior_jump_drop_rate']:.2%}, "
            f"teammate_out_rate={r['teammate_out_rate']:.2%}, blowout_rate={r['blowout_rate']:.2%}"
        )
    lines.extend([
        "",
        "## Top Error Examples",
    ])
    for _, r in top_cases.head(10).iterrows():
        lines.append(
            f"- {r['game_date'].date()} {r['player_name']} {r['team']} vs {r['opponent']}: "
            f"actual={r['minutes']:.1f}, phase6={r['q50']:.1f}, error={r['phase6_error']:+.1f}, "
            f"lag1={r['min_lag1_raw'] if pd.notna(r['min_lag1_raw']) else 'NA'}, "
            f"teammates_absent={int(r['key_teammates_absent'])}"
        )
    lines.extend([
        "",
        "## Data Limitation",
        "Historical injury statuses are not present in the training dataset, so teammates OUT and return-from-injury are inferred from box-score availability, rest, and prior rotation role.",
    ])
    (OUT / "phase61_role_change_report.md").write_text("\n".join(lines) + "\n")


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    preds, raw = _read_inputs()
    enriched = _enrich(preds, raw)
    segments = _segment_table(enriched)
    top_cases = _top_cases(enriched)
    team_instability = _team_instability(enriched)

    summary = {
        "phase": "6.1_minutes_role_change_diagnostics",
        "rows": int(len(enriched)),
        "overall_phase6_mae": round(_mae(enriched["phase6_error"]), 4),
        "overall_naive_last5_mae": round(_mae(enriched["naive_last5_error"]), 4),
        "overall_base_gbm_mae": round(_mae(enriched["q50_base_gbm"] - enriched["minutes"]), 4),
        "diagnostic_only": True,
        "specific_leak_to_fix": None,
    }
    positive = segments[(segments["value"] == "True") & (segments["segment"] != "current_jump_or_drop_8")]
    if not positive.empty:
        r = positive.sort_values(["phase6_vs_overall_delta", "error_share"], ascending=[False, False]).iloc[0]
        summary["specific_leak_to_fix"] = {
            "segment": r["segment"],
            "n": int(r["n"]),
            "phase6_mae": float(r["phase6_mae"]),
            "phase6_vs_overall_delta": float(r["phase6_vs_overall_delta"]),
            "error_share": float(r["error_share"]),
            "phase6_vs_naive_delta": float(r["phase6_vs_naive_delta"]),
        }

    enriched.to_csv(OUT / "phase61_enriched_oos_predictions.csv", index=False)
    segments.to_csv(OUT / "phase61_segment_diagnostics.csv", index=False)
    top_cases.to_csv(OUT / "phase61_top_error_cases.csv", index=False)
    team_instability.to_csv(OUT / "phase61_team_instability.csv", index=False)
    (OUT / "phase61_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_report(summary, segments, team_instability, top_cases)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
