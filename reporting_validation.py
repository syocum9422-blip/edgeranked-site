from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


Logger = Callable[[str], None]

FINAL_STRIKEOUT_COLUMNS = [
    "Final_Projected_Strikeouts",
    "Projected_Strikeouts",
    "predicted_strikeouts",
]
FINAL_OUTS_COLUMNS = [
    "Final_Projected_Outs",
    "Projected_Outs",
    "predicted_outs",
]

MARKET_TO_SOURCE = {
    "PITCHER_K": ("PITCHER", "K"),
    "PITCHER_OUTS": ("PITCHER", "OUTS"),
    "HITTER_K": ("HITTER", "K"),
    "HITTER_HIT": ("HITTER", "HIT"),
    "HITTER_TB": ("HITTER", "TB"),
    "HITTER_RBI": ("HITTER", "RBI"),
    "HITTER_RUNS": ("HITTER", "RUNS"),
    "HITTER_HR": ("HITTER", "HR"),
    "HITTER_HRRBI": ("HITTER", "H+R+RBI"),
}

CLEAN_STANDARD_HITTER_LINES = {
    "K": (0.5, 2.5),
    "HIT": (1.5, 1.5),
    "HITS": (1.5, 1.5),
    "TB": (1.5, 2.5),
    "RBI": (1.5, 1.5),
    "RUNS": (1.5, 1.5),
    "H+R+RBI": (1.5, 2.5),
}

CLEAN_STANDARD_PITCHER_LINES = {
    "K": (0.5, 12.5),
    "OUTS": (9.0, 24.5),
}


def normalize_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_key(value) -> str:
    return normalize_text(value).lower()


def parse_boolish(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on"}


def _is_blankish(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def _is_half_step_line(value: float) -> bool:
    return abs((value * 2.0) - round(value * 2.0)) < 1e-9


def clean_standard_line_reason(row) -> str:
    odds_type = str(row.get("ODDS_TYPE", row.get("odds_type", "")) or "").lower().strip()
    if odds_type != "standard":
        return "non_standard_odds_type"

    if parse_boolish(row.get("ADJUSTED_ODDS", row.get("adjusted_odds", False))):
        return "adjusted_or_boosted_line"

    if not _is_blankish(row.get("FLASH_SALE_LINE_SCORE", row.get("flash_sale_line_score", None))):
        return "flash_sale_line"

    if parse_boolish(row.get("IS_PROMO", row.get("is_promo", False))):
        return "promo_line"

    if parse_boolish(row.get("IN_GAME", row.get("in_game", False))):
        return "in_game_line"

    if parse_boolish(row.get("IS_LIVE", row.get("is_live", False))):
        return "live_line"

    status = str(row.get("STATUS", row.get("status", "")) or "").lower().strip()
    if status and status not in {"pre_game", "scheduled"}:
        return "non_pregame_status"

    player_type = str(row.get("PLAYER_TYPE", row.get("player_type", "")) or "").upper().strip()
    stat = str(row.get("STAT", row.get("stat", "")) or "").upper().strip()
    try:
        line = float(row.get("LINE", row.get("line", "")))
    except Exception:
        return "unparseable_line"

    if line <= 0:
        return "invalid_line"

    if player_type == "HITTER":
        allowed = CLEAN_STANDARD_HITTER_LINES.get(stat)
    elif player_type == "PITCHER":
        allowed = CLEAN_STANDARD_PITCHER_LINES.get(stat)
    else:
        return "unsupported_player_type"

    if allowed is None:
        return "unsupported_market"

    low, high = allowed
    if line < low or line > high:
        return "one_sided_or_alt_line"

    if not _is_half_step_line(line):
        return "non_half_step_line"

    return "clean_standard"


def is_clean_standard_line(row) -> bool:
    return clean_standard_line_reason(row) == "clean_standard"


def _first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


_ODDS_TYPE_CANDIDATES = ["ODDS_TYPE", "odds_type"]


def _normalize_sanitized_lines_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional line metadata without weakening row-level validation."""
    out = df.copy()

    col = _first_existing(df, _ODDS_TYPE_CANDIDATES)
    if col is None:
        raise ValueError(
            "Sanitized PrizePicks lines are missing ODDS_TYPE; refusing to infer standard lines."
        )
    elif col != "ODDS_TYPE":
        out["ODDS_TYPE"] = out[col]

    if out["ODDS_TYPE"].isna().any():
        raise ValueError(
            "Sanitized PrizePicks lines contain blank ODDS_TYPE values; refusing to infer standard lines."
        )
    out["ODDS_TYPE"] = out["ODDS_TYPE"].astype(str).str.lower().str.strip()

    if "SLATE_DATE" not in out.columns:
        raise ValueError(
            "Sanitized PrizePicks lines are missing SLATE_DATE; refusing to validate without slate isolation."
        )

    if "GAME_ID" not in out.columns:
        raise ValueError(
            "Sanitized PrizePicks lines are missing GAME_ID; refusing to validate without game isolation."
        )

    return out


def final_projection_column(df: pd.DataFrame) -> str:
    col = _first_existing(df, FINAL_STRIKEOUT_COLUMNS)
    if col is None:
        raise KeyError(
            f"Could not find a final strikeout projection column. Found columns: {list(df.columns)}"
        )
    return col


def final_outs_column(df: pd.DataFrame) -> str:
    col = _first_existing(df, FINAL_OUTS_COLUMNS)
    if col is None:
        raise KeyError(
            f"Could not find a final outs projection column. Found columns: {list(df.columns)}"
        )
    return col


def attach_final_projection_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    strikeout_source = _first_existing(out, FINAL_STRIKEOUT_COLUMNS[1:])
    if strikeout_source is None:
        raise KeyError(
            f"Could not derive Final_Projected_Strikeouts. Found columns: {list(out.columns)}"
        )
    out["Final_Projected_Strikeouts"] = pd.to_numeric(
        out[strikeout_source], errors="coerce"
    ).round(2)

    outs_source = _first_existing(out, FINAL_OUTS_COLUMNS[1:])
    if outs_source is not None:
        out["Final_Projected_Outs"] = pd.to_numeric(out[outs_source], errors="coerce").round(2)

    if "Projected_IP" in out.columns:
        out["Final_Projected_IP"] = pd.to_numeric(out["Projected_IP"], errors="coerce").round(2)
    elif "Final_Projected_Outs" in out.columns:
        out["Final_Projected_IP"] = (out["Final_Projected_Outs"] / 3.0).round(2)

    return out


def _print_df_sample(label: str, df: pd.DataFrame, columns: list[str], logger: Logger, limit: int = 8) -> None:
    logger(f"\n=== {label} ===")
    if df.empty:
        logger("(empty)")
        return
    keep = [col for col in columns if col in df.columns]
    logger(df[keep].head(limit).to_string(index=False))


def validate_mlb_best_bets_artifacts(
    *,
    raw_lines_path: Path,
    sanitized_lines_path: Path,
    final_board_path: Path,
    logger: Logger = print,
) -> dict:
    logger(f"[mlb_best_bets] raw PrizePicks source path: {raw_lines_path}")
    logger(f"[mlb_best_bets] sanitized PrizePicks source path: {sanitized_lines_path}")
    logger(f"[mlb_best_bets] final image source path: {final_board_path}")

    raw_df = pd.read_csv(raw_lines_path)
    sanitized_df = pd.read_csv(sanitized_lines_path)
    final_df = pd.read_csv(final_board_path)

    _print_df_sample(
        "SAMPLE RAW FETCHED PRIZEPICKS ROWS",
        raw_df,
        ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE", "RAW_STAT_TYPE"],
        logger,
    )
    _print_df_sample(
        "SAMPLE SANITIZED LINES ROWS",
        sanitized_df,
        ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE", "RAW_STAT_TYPE"],
        logger,
    )
    _print_df_sample(
        "SAMPLE FINAL MLB BEST BETS ROWS",
        final_df,
        ["market", "player_name", "play", "line", "confidence", "matchup", "opponent"],
        logger,
    )

    raw_odds_col = _first_existing(raw_df, _ODDS_TYPE_CANDIDATES)
    if raw_odds_col is None:
        raw_alt = raw_df.iloc[0:0].copy()
    else:
        raw_alt = raw_df[
            raw_df[raw_odds_col].astype(str).str.lower().isin({"goblin", "demon"})
        ]
    logger(f"[mlb_best_bets] raw alt-line rows detected: {len(raw_alt)}")

    sanitized_df = _normalize_sanitized_lines_schema(sanitized_df)
    sanitized_ot = sanitized_df["ODDS_TYPE"].astype(str).str.lower()
    sanitized_non_standard = sanitized_df[sanitized_ot != "standard"]
    logger(f"[mlb_best_bets] sanitized non-standard rows detected: {len(sanitized_non_standard)}")
    if not sanitized_non_standard.empty:
        raise ValueError(
            "Sanitized PrizePicks file still contains non-standard rows.\n"
            + sanitized_non_standard[
                ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE"]
            ].head(20).to_string(index=False)
        )

    sanitized_playable_mask = sanitized_df.apply(is_clean_standard_line, axis=1)
    sanitized_non_playable = sanitized_df[~sanitized_playable_mask].copy()
    logger(f"[mlb_best_bets] sanitized non-playable standard rows detected: {len(sanitized_non_playable)}")
    if not sanitized_non_playable.empty:
        sanitized_non_playable["_playability_reason"] = sanitized_non_playable.apply(
            clean_standard_line_reason, axis=1
        )
        raise ValueError(
            "Sanitized PrizePicks file still contains non-playable standard rows.\n"
            + sanitized_non_playable[
                ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "LINE", "ODDS_TYPE", "_playability_reason"]
            ].head(20).to_string(index=False)
        )

    sanitized_dupes = sanitized_df.duplicated(["PLAYER_NAME", "PLAYER_TYPE", "STAT", "GAME_ID"], keep=False)
    logger(f"[mlb_best_bets] sanitized duplicate player/stat/game rows: {int(sanitized_dupes.sum())}")
    if sanitized_dupes.any():
        dupes = sanitized_df.loc[sanitized_dupes, ["PLAYER_NAME", "PLAYER_TYPE", "STAT", "GAME_ID", "LINE", "ODDS_TYPE"]]
        raise ValueError("Sanitized PrizePicks file still contains duplicate rows.\n" + dupes.head(20).to_string(index=False))

    market_col = _first_existing(final_df, ["market", "MARKET"])
    player_col = _first_existing(final_df, ["player_name", "PLAYER_NAME"])
    line_col = _first_existing(final_df, ["line", "LINE"])
    matchup_col = _first_existing(final_df, ["matchup", "opponent", "OPPONENT", "matchup_pitcher"])
    if not market_col or not player_col or not line_col:
        raise ValueError(
            f"Final MLB best bets file is missing required columns. Found: {list(final_df.columns)}"
        )

    work = final_df.copy()
    work["_market"] = work[market_col].astype(str).str.upper().str.strip()
    work["_player_key"] = work[player_col].map(normalize_key)
    work["_line"] = pd.to_numeric(work[line_col], errors="coerce")
    work["_matchup_key"] = work[matchup_col].map(normalize_key) if matchup_col else ""
    work["_player_type"] = work["_market"].map(lambda m: MARKET_TO_SOURCE.get(m, ("", ""))[0])
    work["_stat"] = work["_market"].map(lambda m: MARKET_TO_SOURCE.get(m, ("", ""))[1])

    unsupported = work[work["_player_type"] == ""]
    if not unsupported.empty:
        raise ValueError(
            "Final MLB best bets file contains unsupported markets.\n"
            + unsupported[[market_col, player_col]].head(20).to_string(index=False)
        )

    dupes = work.duplicated(["_player_key", "_market", "_matchup_key"], keep=False)
    logger(f"[mlb_best_bets] final duplicate player/stat rows: {int(dupes.sum())}")
    if dupes.any():
        raise ValueError(
            "Final MLB best bets file contains duplicate player/stat rows.\n"
            + work.loc[dupes, [market_col, player_col, line_col, matchup_col if matchup_col else market_col]]
            .head(20)
            .to_string(index=False)
        )

    multi_lines = work.groupby(["_player_key", "_market", "_matchup_key"])["_line"].nunique(dropna=True)
    multi_lines = multi_lines[multi_lines > 1]
    logger(f"[mlb_best_bets] final groups with multiple line values: {len(multi_lines)}")
    if not multi_lines.empty:
        raise ValueError(
            "Final MLB best bets file contains multiple line values for the same player/stat/game.\n"
            + multi_lines.head(20).to_string()
        )

    sanitized_lookup = sanitized_df.copy()
    sanitized_lookup["_player_key"] = sanitized_lookup["PLAYER_NAME"].map(normalize_key)
    sanitized_lookup["_player_type"] = sanitized_lookup["PLAYER_TYPE"].astype(str).str.upper().str.strip()
    sanitized_lookup["_stat"] = sanitized_lookup["STAT"].astype(str).str.upper().str.strip()
    sanitized_lookup["_line"] = pd.to_numeric(sanitized_lookup["LINE"], errors="coerce")

    merged = work.merge(
        sanitized_lookup[["_player_key", "_player_type", "_stat", "_line", "GAME_ID", "ODDS_TYPE"]],
        on=["_player_key", "_player_type", "_stat", "_line"],
        how="left",
    )
    unmatched = merged[merged["GAME_ID"].isna()].copy()
    logger(f"[mlb_best_bets] final rows not backed by sanitized lines: {len(unmatched)}")
    if not unmatched.empty:
        raise ValueError(
            "Final MLB best bets file contains rows that do not map to the sanitized PrizePicks lines file.\n"
            + unmatched[[market_col, player_col, line_col, matchup_col if matchup_col else market_col]]
            .head(20)
            .to_string(index=False)
        )

    logger("[mlb_best_bets] final duplicate check passed")
    logger("[mlb_best_bets] final non-standard row check passed")
    return {
        "raw_path": str(raw_lines_path),
        "sanitized_path": str(sanitized_lines_path),
        "final_path": str(final_board_path),
        "raw_alt_rows": int(len(raw_alt)),
        "final_rows": int(len(final_df)),
    }


def validate_strikeout_projection_consistency(
    *,
    projection_source_path: Path,
    pitcher_props_path: Path,
    pitcher_card_path: Path | None = None,
    logger: Logger = print,
    sample_pitchers: list[str] | None = None,
) -> dict:
    logger(f"[strikeout] image source path: {projection_source_path}")
    logger(f"[strikeout] detail/card source path: {pitcher_props_path}")
    if pitcher_card_path:
        logger(f"[strikeout] best-bets card source path: {pitcher_card_path}")

    projection_df = attach_final_projection_columns(pd.read_csv(projection_source_path))
    props_df = pd.read_csv(pitcher_props_path)

    projection_col = final_projection_column(projection_df)
    props_col = _first_existing(props_df, ["projected_strikeouts", "predicted_strikeouts"])
    if props_col is None:
        raise ValueError(
            f"Pitcher props file is missing a strikeout projection column. Found: {list(props_df.columns)}"
        )

    logger(f"[strikeout] image projection column: {projection_col}")
    logger(f"[strikeout] detail/card projection column: {props_col}")

    merged = projection_df.assign(_pitcher_key=projection_df["Pitcher"].map(normalize_key)).merge(
        props_df.assign(_pitcher_key=props_df["pitcher_name"].map(normalize_key))[
            ["_pitcher_key", "pitcher_name", props_col]
        ],
        on="_pitcher_key",
        how="inner",
    )
    merged["_source_projection"] = pd.to_numeric(merged[projection_col], errors="coerce").round(2)
    merged["_detail_projection"] = pd.to_numeric(merged[props_col], errors="coerce").round(2)
    mismatches = merged[merged["_source_projection"] != merged["_detail_projection"]].copy()
    if not mismatches.empty:
        raise ValueError(
            "Strikeout projection mismatch detected between source and downstream props output.\n"
            + mismatches[
                ["Pitcher", projection_col, props_col]
            ].head(20).to_string(index=False)
        )

    card_col = None
    card_samples = pd.DataFrame()
    if pitcher_card_path and pitcher_card_path.exists():
        card_df = pd.read_csv(pitcher_card_path)
        if "market" in card_df.columns:
            card_df = card_df[card_df["market"].astype(str).str.upper().eq("PITCHER_K")].copy()
        if not card_df.empty and "player_name" in card_df.columns:
            card_col = _first_existing(card_df, ["predicted_strikeouts", "projected_strikeouts"])
            if card_col:
                card_merged = projection_df.assign(_pitcher_key=projection_df["Pitcher"].map(normalize_key)).merge(
                    card_df.assign(_pitcher_key=card_df["player_name"].map(normalize_key))[
                        ["_pitcher_key", "player_name", card_col]
                    ],
                    on="_pitcher_key",
                    how="inner",
                )
                card_merged["_source_projection"] = pd.to_numeric(card_merged[projection_col], errors="coerce").round(2)
                card_merged["_card_projection"] = pd.to_numeric(card_merged[card_col], errors="coerce").round(2)
                card_mismatches = card_merged[card_merged["_source_projection"] != card_merged["_card_projection"]].copy()
                if not card_mismatches.empty:
                    raise ValueError(
                        "Strikeout projection mismatch detected between source and downstream PITCHER_K cards.\n"
                        + card_mismatches[
                            ["Pitcher", projection_col, card_col]
                        ].head(20).to_string(index=False)
                    )
                card_samples = card_merged

    if not sample_pitchers:
        sample_pitchers = ["Garrett Crochet"]
        sample_pitchers.extend(
            merged.sort_values("_source_projection", ascending=False)["Pitcher"].head(3).tolist()
        )

    sample_keys = {normalize_key(name) for name in sample_pitchers}
    samples = merged[merged["_pitcher_key"].isin(sample_keys)].copy()
    _print_df_sample(
        "STRIKEOUT CONSISTENCY SAMPLES",
        samples,
        ["Pitcher", projection_col, props_col],
        logger,
        limit=12,
    )
    if card_col and not card_samples.empty:
        card_samples = card_samples[card_samples["_pitcher_key"].isin(sample_keys)].copy()
        _print_df_sample(
            "STRIKEOUT CARD CONSISTENCY SAMPLES",
            card_samples,
            ["Pitcher", projection_col, card_col],
            logger,
            limit=12,
        )
    return {
        "projection_source_path": str(projection_source_path),
        "projection_source_column": projection_col,
        "detail_source_path": str(pitcher_props_path),
        "detail_source_column": props_col,
        "card_source_path": str(pitcher_card_path) if pitcher_card_path else "",
        "card_source_column": card_col or "",
        "sample_pitchers": samples[["Pitcher", projection_col, props_col]].to_dict(orient="records"),
    }
