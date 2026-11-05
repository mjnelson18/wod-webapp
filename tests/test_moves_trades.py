"""
Trades on an inline payload shaped like reference/raw_2526/league/*_trades.json.

Every state the API serves is kept — offered, rejected, withdrawn as well as
processed — because the frontend (not the pipeline) decides what to show, and
an entry missing from the standings table keeps its id as a string label rather
than being dropped (that is how the organiser's excluded entry stays visible).
"""

import pandas as pd

from pipeline.transforms.moves import TRADE_COLUMNS, finalise_trades, trades_table

TRADES = {
    "trades": [
        # accepted and executed: AA receives 11, gives up 22, from GW3
        {"event": 3, "id": 1, "offered_entry": 100, "received_entry": 200, "state": "p",
         "offer_time": "2025-09-01T07:00:00Z", "response_time": "2025-09-01T21:00:00Z",
         "tradeitem_set": [{"element_in": 11, "element_out": 22}]},
        # an offer from an entry outside the table that never went through
        {"event": 5, "id": 2, "offered_entry": 999, "received_entry": 100, "state": "o",
         "offer_time": "2025-09-15T07:00:00Z", "response_time": None,
         "tradeitem_set": [{"element_in": 33, "element_out": 11}]},
    ]
}

TABLE = pd.DataFrame({"entry_id": [100, 200], "short_name": ["AA", "BB"]})
PLAYERS = pd.DataFrame({"id": [11, 22, 33], "web_name": ["Eleven", "TwentyTwo", "ThirtyThree"]})


def _weekly_points() -> pd.DataFrame:
    """11 scores 2 a week, 22 scores 1 a week, 33 scored 10 in GW1 and nothing since."""
    rows = []
    for gw in range(1, 7):
        rows.append({"league_code": "Prem", "id": 11, "gameweek": gw, "total_points": 2})
        rows.append({"league_code": "Prem", "id": 22, "gameweek": gw, "total_points": 1})
        rows.append({"league_code": "Prem", "id": 33, "gameweek": gw,
                     "total_points": 10 if gw == 1 else 0})
    return pd.DataFrame(rows)


def test_trades_table_keeps_every_state_and_labels_missing_entries():
    frame = trades_table(TRADES, TABLE, league_code="Prem")

    assert list(frame.columns) == TRADE_COLUMNS
    assert len(frame) == 2                              # one row per trade item
    assert frame["state"].tolist() == ["p", "o"]        # nothing filtered here
    assert frame["gameweek"].tolist() == [3, 5]
    assert frame["offered_by"].tolist() == ["AA", "999"]   # unknown entry -> its id, as text
    assert frame["received_by"].tolist() == ["BB", "AA"]
    assert frame["league_code"].eq("Prem").all()


def test_finalise_trades_sums_points_from_the_trade_gameweek_to_season_end():
    frame = finalise_trades(trades_table(TRADES, TABLE, league_code="Prem"),
                            _weekly_points(), PLAYERS)

    assert frame["player_in"].tolist() == ["Eleven", "ThirtyThree"]
    assert frame["player_out"].tolist() == ["TwentyTwo", "Eleven"]
    # GW3..GW6 inclusive: 11 banks 4 x 2, 22 banks 4 x 1
    assert frame["player_in_total_points"].tolist() == [8, 0]
    # GW5..GW6: 33 scored nothing after GW1, 11 banks 2 x 2
    assert frame["player_out_total_points"].tolist() == [4, 4]
    assert frame["net_points_from_trade"].tolist() == [4, -4]
    assert frame["state"].tolist() == ["p", "o"]        # still carried through


def test_missing_trades_payload_is_an_empty_table():
    """A 404 from the trades endpoint reaches the transform as None, not {}."""
    for payload in (None, {}, {"trades": []}):
        frame = trades_table(payload, TABLE, league_code="Prem")
        assert frame.empty
        assert list(frame.columns) == TRADE_COLUMNS
