import pytest

from alphaforge.data import DataError, read_ohlcv

GOOD = b"""Date,Open,High,Low,Close,Volume
2024-01-02,10,11,9,10.5,100
2024-01-03,10.5,12,10,11,120
2024-01-04,11,11.5,10.2,10.4,90
"""


def test_yahoo_style():
    b, rep = read_ohlcv(GOOD)
    assert len(b) == 3 and rep.ok and b.close[-1] == 10.4


def test_tradestation_style_date_time_columns():
    text = b"Date,Time,Open,High,Low,Close,Up,Down\n01/02/2024,0935,10,11,9,10.5,5,6\n01/02/2024,0940,10.5,12,10,11,5,6\n01/02/2024,0945,11,11.5,10,10.2,1,1\n"
    b, rep = read_ohlcv(text, timezone="America/New_York")
    assert len(b) == 3 and b.timezone == "America/New_York"
    assert b.datetime_index()[0].hour == 9


def test_metatrader_semicolon_compact_dates():
    text = b"<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<TICKVOL>\n20240102;0000;1.1;1.2;1.0;1.15;10\n20240103;0000;1.15;1.25;1.1;1.2;12\n20240104;0000;1.2;1.3;1.1;1.25;8\n"
    b, _ = read_ohlcv(text)
    assert len(b) == 3


def test_unsorted_and_duplicates_are_fixed_and_reported():
    text = GOOD.splitlines()
    text = b"\n".join([text[0], text[2], text[1], text[1], text[3]])
    b, rep = read_ohlcv(text)
    assert len(b) == 3 and any("sorted" in f for f in rep.fixes) and any("duplicate" in f for f in rep.fixes)


def test_inconsistent_bar_is_an_error():
    with pytest.raises(DataError, match="violate"):
        read_ohlcv(b"Date,Open,High,Low,Close\n2024-01-02,10,9,8,10.5\n2024-01-03,10,11,9,10\n")


def test_missing_columns():
    with pytest.raises(DataError, match="missing"):
        read_ohlcv(b"Date,Price\n2024-01-02,10\n2024-01-03,11\n")
