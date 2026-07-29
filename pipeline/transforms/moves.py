"""Transfers and trades. Ported from notebook cells 23 and 25. Pure."""

import numpy as np
import pandas as pd

KIND_LABELS = {"w": "waiver", "f": "free agent"}
RESULT_LABELS = {
    "a": "successful",
    "do": "unsuccessful - player out already gone",
    "di": "unsuccessful - player in already been picked up",
}

TRANSFER_COLUMNS = [
    "league_code", "date_added", "gameweek", "short_name", "kind", "result", "index",
    "priority", "position", "element_in", "player_in", "element_out", "player_out",
    "player_in_points_scored_in_week", "player_out_points_scored_in_week",
    "net_points_of_transfer_in_week", "abs_net_trade",
]


def transfers_table(transactions: dict, players: pd.DataFrame, table: pd.DataFrame,
                    *, league_code) -> pd.DataFrame:
    """
    Waiver and free-agent moves, including failed attempts — the point of the table.

    `result` distinguishes them, and unrecognised codes become NaN as in the
    notebook.
    """
    frame = pd.json_normalize(transactions["transactions"])
    lookup = players[["id", "web_name", "position"]]

    frame = frame.merge(lookup, left_on="element_in", right_on="id", how="inner")
    frame = frame.rename(columns={"web_name": "player_in"})
    frame = frame.merge(players[["id", "web_name"]], left_on="element_out", right_on="id",
                        how="inner", suffixes=("", "_out"))
    frame = frame.rename(columns={"web_name": "player_out"})
    frame = frame.merge(table[["entry_id", "short_name"]], left_on="entry",
                        right_on="entry_id", how="inner")

    frame = frame[[
        "added", "event", "index", "kind", "priority", "result", "position",
        "element_in", "player_in", "element_out", "player_out", "short_name",
    ]].copy()
    frame["league_code"] = league_code
    return frame


def finalise_transfers(frame: pd.DataFrame, weekly_points: pd.DataFrame) -> pd.DataFrame:
    """Attach in-week points for both players and label kind/result."""
    points = weekly_points[["league_code", "gameweek", "id", "total_points"]]

    frame = frame.merge(
        points, left_on=["league_code", "event", "element_in"],
        right_on=["league_code", "gameweek", "id"], how="inner",
    ).rename(columns={"total_points": "player_in_points_scored_in_week"})
    frame = frame.drop(columns=["id", "gameweek"])

    frame = frame.merge(
        points, left_on=["league_code", "event", "element_out"],
        right_on=["league_code", "gameweek", "id"], how="inner",
    ).rename(columns={"total_points": "player_out_points_scored_in_week"})
    frame = frame.drop(columns=["id", "gameweek"])

    frame["kind"] = frame["kind"].map(KIND_LABELS)
    frame["result"] = frame["result"].map(RESULT_LABELS)
    frame["added"] = pd.to_datetime(frame["added"], errors="coerce")
    frame = frame.rename(columns={"added": "date_added", "event": "gameweek"})

    frame["net_points_of_transfer_in_week"] = (
        frame["player_in_points_scored_in_week"] - frame["player_out_points_scored_in_week"]
    )
    frame["abs_net_trade"] = frame["net_points_of_transfer_in_week"].abs()
    frame["transfer_category"] = frame["kind"] + " - " + frame["result"]
    return frame[TRANSFER_COLUMNS + ["transfer_category"]]


TRADE_COLUMNS = [
    "league_code", "gameweek", "state", "offer_time", "response_time",
    "offered_by", "received_by", "element_in", "element_out",
]


def trades_table(trades: dict, table: pd.DataFrame, *, league_code) -> pd.DataFrame:
    """
    Drafter-to-drafter swaps, one row per trade item.

    Deliberately does NOT filter on `exclude_entries`: the notebook's inner join
    against the league table silently dropped 9 of 2526's 13 Premiership trades,
    because they involved the organiser's excluded entry. `state='p'` means
    processed, and `event` is the gameweek the swap takes effect in, so squads
    change between GW event-1 and GW event.

    Entries missing from `table` (i.e. excluded ones) keep their entry id as a
    label rather than being dropped.
    """
    rows = trades.get("trades") or []
    if not rows:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    names = dict(zip(table["entry_id"], table["short_name"]))
    records = []
    for trade in rows:
        for item in trade.get("tradeitem_set", []):
            records.append({
                "league_code": league_code,
                "gameweek": trade["event"],
                "state": trade.get("state"),
                "offer_time": trade.get("offer_time"),
                "response_time": trade.get("response_time"),
                "offered_by": names.get(trade["offered_entry"], str(trade["offered_entry"])),
                "received_by": names.get(trade["received_entry"], str(trade["received_entry"])),
                "element_in": item["element_in"],
                "element_out": item["element_out"],
            })
    return pd.DataFrame(records, columns=TRADE_COLUMNS)


def finalise_trades(frame: pd.DataFrame, weekly_points: pd.DataFrame,
                    players: pd.DataFrame) -> pd.DataFrame:
    """
    Attach names and points-since-trade.

    Each player's points are summed from the trade gameweek to the end of the
    season, reproducing the notebook's merge-then-filter (`event <= gameweek`).
    Verified against trade_history_2526.csv: 112/86, 117/88 and 32/38 all match.
    """
    if frame.empty:
        return frame.assign(player_in=None, player_out=None, player_in_total_points=0,
                            player_out_total_points=0, net_points_from_trade=0)

    names = players.set_index("id")["web_name"]
    frame = frame.copy()
    frame["player_in"] = frame["element_in"].map(names)
    frame["player_out"] = frame["element_out"].map(names)

    points = weekly_points[["league_code", "id", "gameweek", "total_points"]]

    def since(element_column: str, label: str) -> pd.Series:
        """Sum a traded player's points from the trade gameweek to season end."""
        base = frame[["league_code", "gameweek", element_column]].reset_index(names="_row")
        merged = base.merge(
            points, left_on=["league_code", element_column],
            right_on=["league_code", "id"], how="left", suffixes=("_trade", "_row"),
        )
        merged = merged[merged["gameweek_trade"] <= merged["gameweek_row"]]
        return merged.groupby("_row")["total_points"].sum().rename(label)

    frame = frame.join(since("element_in", "player_in_total_points"))
    frame = frame.join(since("element_out", "player_out_total_points"))
    for column in ("player_in_total_points", "player_out_total_points"):
        frame[column] = pd.to_numeric(frame[column]).fillna(0).astype(int)

    frame["net_points_from_trade"] = (
        frame["player_in_total_points"] - frame["player_out_total_points"]
    )
    return frame
