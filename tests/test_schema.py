import pandas as pd
import pytest

from csanalysis import schema


def test_coerce_adds_missing_columns_and_orders():
    df = schema.coerce(pd.DataFrame({"round_num": [1], "match_id": ["m"], "extra": [1]}), "rounds")
    assert list(df.columns) == schema.columns("rounds")
    assert df["winner_side"].isna().all()


def test_steamids_stay_exact():
    big = 76561198012345679  # not representable exactly as float64
    df = schema.coerce(pd.DataFrame({"steamid": [big, "76561198000000001"]}), "economy")
    assert df["steamid"].tolist() == [str(big), "76561198000000001"]


def test_validate_rejects_bad_rows():
    base = {"match_id": "m", "round_num": 1, "start_tick": 0, "freeze_end_tick": 1, "end_tick": 2,
            "winner_side": "CT", "reason": "t_eliminated", "ct_team": "a", "t_team": "b", "ct_score": 0, "t_score": 0}
    schema.validate(schema.coerce(pd.DataFrame([base]), "rounds"), "rounds")
    with pytest.raises(schema.SchemaError, match="invalid sides"):
        schema.validate(schema.coerce(pd.DataFrame([{**base, "winner_side": "X"}]), "rounds"), "rounds")
    with pytest.raises(schema.SchemaError, match="duplicate"):
        schema.validate(schema.coerce(pd.DataFrame([base, base]), "rounds"), "rounds")
    with pytest.raises(schema.SchemaError, match="nulls"):
        schema.validate(schema.coerce(pd.DataFrame([{**base, "end_tick": None}]), "rounds"), "rounds")


def test_arrow_schema_covers_every_table():
    for name in schema.TABLES:
        assert schema.arrow_schema(name).names == schema.columns(name)


def test_schema_docs_are_up_to_date():
    from pathlib import Path

    doc = Path(__file__).parents[1] / "docs" / "data_schema.md"
    assert doc.read_text().strip() == schema.markdown().strip(), "regenerate docs/data_schema.md"
