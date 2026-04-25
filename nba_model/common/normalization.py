import re
import unicodedata

import pandas as pd


def strip_accents(text):
    text = str(text)
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def base_clean_name(name):
    s = strip_accents(name).strip().lower()
    s = s.replace(".", "")
    s = s.replace("'", "")
    s = s.replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_name(name, alias_map=None):
    s = base_clean_name(name)

    replacements = {
        "nic claxton": "nicolas claxton",
        "alex sarr": "alexandre sarr",
        "cam thomas": "cameron thomas",
        "mike conley": "michael conley",
        "patty mills": "patrick mills",
        "pj washington": "p j washington",
        "cj mccollum": "c j mccollum",
        "og anunoby": "o g anunoby",
        "aj green": "a j green",
        "dj wagner": "d j wagner",
        "jt thor": "j t thor",
    }

    s = replacements.get(s, s)
    if alias_map and s in alias_map:
        s = alias_map[s]
    return s


def find_player_col(df):
    for col in ["PLAYER_NAME", "PLAYER", "NAME"]:
        if col in df.columns:
            return col
    raise ValueError(f"Could not find player column. Found: {list(df.columns)}")


def find_col(df, candidates, required=True):
    for col in candidates:
        if col in df.columns:
            return col
    if required:
        raise ValueError(f"Missing required column. Tried: {candidates}. Found: {list(df.columns)}")
    return None


def safe_num(value):
    return pd.to_numeric(value, errors="coerce")


def normalize_stat_name(stat):
    s = str(stat).strip().upper()
    s = s.replace("-", "")
    s = s.replace("_", "")
    s = re.sub(r"\s+", " ", s).strip()

    mapping = {
        "POINTS": "PTS",
        "POINT": "PTS",
        "PTS": "PTS",
        "REBOUNDS": "REB",
        "REBOUND": "REB",
        "REBS": "REB",
        "REB": "REB",
        "ASSISTS": "AST",
        "ASSIST": "AST",
        "ASTS": "AST",
        "AST": "AST",
        "STEALS": "STL",
        "STEAL": "STL",
        "STL": "STL",
        "BLOCKS": "BLK",
        "BLOCKED SHOTS": "BLK",
        "BLOCK": "BLK",
        "BLKS": "BLK",
        "BLK": "BLK",
        "3PM": "FG3M",
        "3PTM": "FG3M",
        "3PT MADE": "FG3M",
        "3PT MADES": "FG3M",
        "3 POINTERS MADE": "FG3M",
        "THREES": "FG3M",
        "FG3M": "FG3M",
        "3PT ATTEMPTED": "FG3A",
        "3PT ATTEMPTS": "FG3A",
        "3-PT ATTEMPTED": "FG3A",
        "3 POINTERS ATTEMPTED": "FG3A",
        "3 PT ATTEMPTED": "FG3A",
        "FG3A": "FG3A",
        "TURNOVERS": "TOV",
        "TURNOVER": "TOV",
        "TOV": "TOV",
        "FREE THROWS MADE": "FTM",
        "FT MADE": "FTM",
        "FTM": "FTM",
        "FREE THROWS ATTEMPTED": "FTA",
        "FT ATTEMPTED": "FTA",
        "FTA": "FTA",
        "FG MADE": "FGM",
        "FIELD GOALS MADE": "FGM",
        "FGM": "FGM",
        "FG ATTEMPTED": "FGA",
        "FIELD GOALS ATTEMPTED": "FGA",
        "FGA": "FGA",
        "TWO POINTERS MADE": "FG2M",
        "2PT MADE": "FG2M",
        "FG2M": "FG2M",
        "TWO POINTERS ATTEMPTED": "FG2A",
        "2PT ATTEMPTED": "FG2A",
        "FG2A": "FG2A",
        "OFFENSIVE REBOUNDS": "OREB",
        "OFFENSIVE REBOUND": "OREB",
        "OREB": "OREB",
        "DEFENSIVE REBOUNDS": "DREB",
        "DEFENSIVE REBOUND": "DREB",
        "DREB": "DREB",
        "PERSONAL FOULS": "PF",
        "FOULS": "PF",
        "PF": "PF",
        "DOUBLE-DOUBLE": "DD",
        "DOUBLE DOUBLE": "DD",
        "DOUBLEDOUBLE": "DD",
        "DOUBLE DOUBLE": "DD",
        "DD": "DD",
        "TRIPLE-DOUBLE": "TD",
        "TRIPLE DOUBLE": "TD",
        "TRIPLEDOUBLE": "TD",
        "TRIPLE DOUBLE": "TD",
        "TD": "TD",
        "POINTS 1ST 3 MINUTES": "PTS_3M",
        "POINTS FIRST 3 MINUTES": "PTS_3M",
        "PTS 1ST 3 MINUTES": "PTS_3M",
        "ASSISTS 1ST 3 MINUTES": "AST_3M",
        "ASSISTS FIRST 3 MINUTES": "AST_3M",
        "AST 1ST 3 MINUTES": "AST_3M",
        "REBOUNDS 1ST 3 MINUTES": "REB_3M",
        "REBOUNDS FIRST 3 MINUTES": "REB_3M",
        "REB 1ST 3 MINUTES": "REB_3M",
        "QUARTERS WITH 3+ POINTS": "Q3P",
        "QUARTERS WITH 5+ POINTS": "Q5P",
        "DUNKS": "DUNKS",
        "PTS REB": "PR",
        "POINTS REBOUNDS": "PR",
        "PTS REBS": "PR",
        "P R": "PR",
        "PR": "PR",
        "PTS AST": "PA",
        "POINTS ASSISTS": "PA",
        "PTS ASTS": "PA",
        "P A": "PA",
        "PA": "PA",
        "REB AST": "RA",
        "REBOUNDS ASSISTS": "RA",
        "REBS ASTS": "RA",
        "R A": "RA",
        "AR": "RA",
        "RA": "RA",
        "PTS REB AST": "PRA",
        "POINTS REBOUNDS ASSISTS": "PRA",
        "PTS REBS ASTS": "PRA",
        "P R A": "PRA",
        "PRA": "PRA",
        "STL BLK": "SB",
        "STEALS BLOCKS": "SB",
        "BLKS STLS": "SB",
        "BLOCKS STEALS": "SB",
        "S B": "SB",
        "SB": "SB",
        "FANTASY SCORE": "FANTASY",
        "FANTASY": "FANTASY",
    }

    if s in mapping:
        return mapping[s]

    compact = s.replace("+", " ").replace("/", " ").replace("&", " ")
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact in mapping:
        return mapping[compact]

    compact_no_space = compact.replace(" ", "")
    compact_map = {
        "PTSREB": "PR",
        "PTSREBS": "PR",
        "POINTSREBOUNDS": "PR",
        "PTSAST": "PA",
        "PTSASTS": "PA",
        "POINTSASSISTS": "PA",
        "REBAST": "RA",
        "REBSASTS": "RA",
        "REBOUNDSASSISTS": "RA",
        "PTSREBAST": "PRA",
        "PTSREBSASTS": "PRA",
        "POINTSREBOUNDSASSISTS": "PRA",
        "STLBLK": "SB",
        "BLKSSTLS": "SB",
        "STEALSBLOCKS": "SB",
        "POINTS1ST3MINUTES": "PTS_3M",
        "ASSISTS1ST3MINUTES": "AST_3M",
        "REBOUNDS1ST3MINUTES": "REB_3M",
        "QUARTERSWITH3+POINTS": "Q3P",
        "QUARTERSWITH5+POINTS": "Q5P",
    }
    return compact_map.get(compact_no_space, s)
