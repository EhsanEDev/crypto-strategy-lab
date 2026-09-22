"""ADX tests: TA-Lib reference vectors, warm-up, bounds and DM rules.

The frozen vectors below were generated once with the official TA-Lib
library (version 0.8.0, ``talib.ADX/PLUS_DI/MINUS_DI``) on a fixed
deterministic dataset - they are external ground truth, not a copy of the
implementation under test. When TA-Lib happens to be installed, an
additional live cross-check runs; otherwise the frozen vectors guarantee
the declared TA-Lib-compatible convention.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_lab.indicators.adx import adx, directional_movement

try:  # optional live cross-check against the real TA-Lib
    import talib as _talib
except Exception:  # pragma: no cover - talib is optional
    _talib = None

# ------------------------------------------------------------------ #
# Frozen reference vectors generated with official TA-Lib 0.8.0
# (talib.ADX / PLUS_DI / MINUS_DI, timeperiod=14, fixed dataset below).
# First valid ADX at index 27 (= 2*period-1), first DI at index 14.
# ------------------------------------------------------------------ #

_TALIB_HIGH = [
    100.983027499, 100.5615476546, 97.3949182717, 96.7603057671, 95.4667191419,
    95.7009260527, 96.4448944499, 98.0990283963, 98.6158837148, 99.067383674,
    98.5514262147, 98.5369021728, 97.6604971952, 97.4394660652, 97.9177529969,
    98.4948136264, 99.1525173407, 100.5076680443, 102.3885097491, 102.8397917898,
    101.8423896319, 99.8795911677, 99.3554183032, 99.0776592235, 98.4155418055,
    97.3062658174, 97.8966180699, 98.8533434857, 99.0224747739, 98.7459721908,
    98.2967394527, 97.0603576528, 97.5598545518, 98.1875101735, 97.8837087818,
    98.7417003795, 98.1681969931, 96.9543368934, 97.8040521985, 96.6684551169,
    96.2703021858, 95.866232826, 97.0074707598, 97.8646139055, 99.8542154583,
    98.5037313356, 97.0551350202, 98.2256554637, 96.863463814, 97.9445921448,
    99.5140994777, 99.7709265046, 99.2787895759, 99.3612011558, 96.8448192837,
    97.2422965967, 97.8880843226, 97.3969933119, 98.0458716352, 98.3313524378,
]

_TALIB_LOW = [
    99.9515910421, 100.1593369168, 96.8389129493, 95.7822867241, 95.0116703864,
    95.3097945374, 95.8158942089, 97.3156862775, 98.295039228, 98.6600697628,
    97.8232860017, 97.6525222627, 96.6187279289, 97.1962030361, 96.9225296626,
    98.2341335423, 98.8537761913, 99.5214621169, 101.6226772493, 102.0223233673,
    101.1956617318, 99.0458177752, 98.9001490479, 98.7002136869, 98.1292748751,
    96.7739477864, 97.4405663902, 98.1018190952, 98.247885888, 98.1701345019,
    97.9585331631, 96.440608934, 97.1710194364, 97.5702173777, 97.7231287163,
    97.6970279181, 97.3872286401, 96.1226142255, 96.6839724969, 96.3997821751,
    95.3474414814, 95.7357522759, 96.1043050524, 97.490832414, 99.4969067601,
    98.0564425514, 96.7951171992, 97.1907928614, 95.7239067357, 97.7367997497,
    99.0558287848, 99.1483568331, 98.3075136515, 98.5841947888, 96.2845847586,
    96.9055970411, 97.2375705649, 96.734333694, 97.2148440123, 97.37206028,
]

_TALIB_CLOSE = [
    100.5423178789, 100.0467322456, 97.2046431492, 96.3565599237, 95.574620739,
    95.6282151444, 96.0508819241, 97.7229695596, 98.1002252846, 98.8151144927,
    98.3483764065, 98.0546755267, 97.5332545388, 97.309169294, 97.487974345,
    98.8979605141, 98.9152042531, 100.2256793758, 102.0037595736, 102.4077276242,
    101.7709782889, 99.670141124, 99.0801900856, 98.4361216442, 98.1742182306,
    97.2634839322, 97.5569500976, 98.179360288, 98.3323766923, 98.2533747743,
    98.2063238084, 96.7616488049, 97.4127528194, 97.9252035509, 97.6419288304,
    98.1110613304, 97.3433549637, 96.3353658553, 97.4888135351, 96.4698583508,
    95.8384993584, 95.7952056117, 96.37180814, 97.7846354924, 99.7430426004,
    98.182501771, 97.0115328252, 97.7160138185, 96.3846167595, 97.6854260467,
    99.0518219506, 99.5820835119, 98.9100951423, 99.259096437, 96.5328526153,
    97.2743325698, 97.345460606, 97.1834022819, 97.6094967114, 97.8429918474,
]

# ADX values start at index 27 (2*period-1); the list below holds exactly
# the values from index 14 onward for +DI/-DI and from index 27 for ADX.
_TALIB_PDI_FROM14 = [
    25.38342523540734, 27.528477362781235, 31.576561334246982, 37.33818935222112,
    44.08880673194629, 44.61886248193671, 41.173599328775, 34.688206439529694,
    33.10168337896681, 32.31619491246338, 31.662780958713, 28.800913602685867,
    31.5175533668201, 35.11368428586596, 34.267383039333275, 32.90665069590482,
    32.1004029207486, 28.213801276163597, 30.12658116102888, 32.92455428510908,
    32.423788074291, 36.15534632849853, 34.02560709225943, 30.956060185911348,
    33.77115421861861, 31.16658737048907, 28.709014669130777, 28.428377318875064,
    34.28283594916219, 36.727429330599705, 44.82249459289865, 40.0347947592099,
    36.57402225876877, 41.08141658358471, 36.25548884314638, 39.23438765355574,
    43.99457611500214, 43.65120528311444, 40.449261594975724, 39.07813180433839,
    32.854941975330306, 33.765510644512155, 36.21254040816642, 34.786996277789925,
    36.90209483003738, 36.48108154012534,]

_TALIB_MDI_FROM14 = [
    44.337478481120904, 41.35895469013017, 40.489803494982304, 36.13102085665598,
    31.215911929093465, 29.542928298327876, 32.52805771066462, 39.83048075103868,
    38.874023174469755, 39.200157857513155, 42.16970511348473, 47.106641246563676,
    45.120794741820056, 41.28317137685403, 38.96223165974605, 37.95123704394924,
    38.55431893612981, 44.294822281594065, 41.82924547882227, 39.5292865127007,
    38.928065586461464, 35.74190446345434, 35.973207891007654, 42.073473981661216,
    37.670373288432515, 36.77768781918637, 41.270640237595636, 40.86721005188155,
    37.226272271455116, 33.29277680392326, 28.756236779524162, 34.807303987182195,
    39.65738872661338, 36.669968218400754, 41.01232349405228, 37.31561072550962,
    33.503270671985916, 32.11384919067419, 34.59735131527244, 33.0077822163217,
    40.06298796550844, 38.488646243328745, 37.05091513977991, 38.58190237355509,
    36.56438274204842, 34.40912288795356,]

_TALIB_ADX_FROM27 = [
    14.224665613622019, 13.666556202345916, 13.198895120254562, 12.908577184509754,
    13.570684574368586, 13.763041284441211, 13.431094000438643, 13.122857236721972,
    12.226584965813638, 11.551995608038295, 11.814222708220724, 11.36020085141765,
    11.138642641293421, 11.625196492771275, 12.076996497714998, 11.508366019852824,
    11.036713484679398, 11.808052847284959, 11.463527138165407, 10.933614154868167,
    10.55791225216277, 10.243511036817745, 9.690872170529788, 9.96563447495595,
    10.341503924412127, 10.159803695950544, 10.035602913558455, 10.024856202293945,
    9.775711888277772, 9.159184516045324, 8.87441158258653, 8.273359461237254,]


def _reference_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": np.asarray(_TALIB_CLOSE) * 0.999,
            "high": np.asarray(_TALIB_HIGH),
            "low": np.asarray(_TALIB_LOW),
            "close": np.asarray(_TALIB_CLOSE),
        }
    )


def test_frozen_talib_reference_vectors() -> None:
    """First 14 ADX values and every +DI/−DI against frozen TA-Lib output."""
    result = adx(_reference_frame(), period=14)

    assert result["plus_di"].iloc[:14].isna().all()
    assert result["minus_di"].iloc[:14].isna().all()
    assert np.allclose(
        result["plus_di"].iloc[14:60].to_numpy(), _TALIB_PDI_FROM14, atol=1e-9
    )
    assert np.allclose(
        result["minus_di"].iloc[14:60].to_numpy(), _TALIB_MDI_FROM14, atol=1e-9
    )
    assert result["adx"].iloc[:27].isna().all()
    assert np.allclose(result["adx"].iloc[27:59].to_numpy(), _TALIB_ADX_FROM27, atol=1e-9)


def test_first_valid_positions_match_ta_lib_lookback() -> None:
    period = 14
    df = _reference_frame()
    result = adx(df, period=period)
    assert int(result["plus_di"].first_valid_index()) == period  # first DI at bar 14
    assert int(result["adx"].first_valid_index()) == 2 * period - 1  # ADX at bar 27


@pytest.mark.skipif(_talib is None, reason="talib optional live cross-check")
def test_live_talib_cross_check_multiple_periods() -> None:
    rng = np.random.default_rng(99)
    n = 200
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0.004, 0.002, n))
    high = base * (1 + spread)
    low = base * (1 - spread)
    close = base * (1 + rng.normal(0, 0.002, n))
    df = pd.DataFrame({"open": close * 0.99, "high": high, "low": low, "close": close})
    for period in (14, 7, 3, 20, 28):
        mine = adx(df, period=period)
        assert np.allclose(
            mine["adx"].to_numpy(), _talib.ADX(high, low, close, timeperiod=period),
            atol=1e-9, equal_nan=True,
        )
        assert np.allclose(
            mine["plus_di"].to_numpy(), _talib.PLUS_DI(high, low, close, timeperiod=period),
            atol=1e-9, equal_nan=True,
        )
        assert np.allclose(
            mine["minus_di"].to_numpy(), _talib.MINUS_DI(high, low, close, timeperiod=period),
            atol=1e-9, equal_nan=True,
        )


def test_directional_movement_standard_rules() -> None:
    df = pd.DataFrame(
        {
            "high": [10.0, 12.0, 13.0, 12.0],
            "low": [9.0, 10.0, 11.0, 10.5],
        }
    )
    plus_dm, minus_dm = directional_movement(df)
    assert plus_dm.tolist() == [0.0, 2.0, 1.0, 0.0]
    assert minus_dm.tolist() == [0.0, 0.0, 0.0, 0.5]


def test_adx_bounds_on_straight_trend() -> None:
    period = 14
    n = 300
    high = np.arange(10.0, 10.0 + n)  # straight staircase up
    low = high - 1.0
    close = (high + low) / 2
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close})

    result = adx(df, period=period)
    adx_col = result["adx"]
    assert adx_col.iloc[: 2 * period - 1].isna().all()
    assert adx_col.notna().iloc[2 * period - 1]
    valid = adx_col.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    # a perfectly one-sided trend converges to a high ADX
    assert valid.iloc[-1] == pytest.approx(100.0)
    assert (result["plus_di"].dropna() > result["minus_di"].dropna()).all()


def test_adx_low_in_tight_range() -> None:
    n = 400
    base = 100.0 + 0.5 * np.sin(np.arange(n) * 0.7)  # tight oscillation
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.05,
            "low": base - 0.05,
            "close": base,
        }
    )
    result = adx(df, period=14)
    valid = result["adx"].dropna()
    assert (valid < 20).all()
    assert result["plus_di"].dropna().min() > 0  # both sides active
    assert result["minus_di"].dropna().min() > 0


def test_adx_warmup_short_series() -> None:
    df = _reference_frame().iloc[:20]
    result = adx(df, period=14)
    assert result["adx"].isna().all()  # ADX needs 2*period-1 = 27 bars
    assert result["plus_di"].iloc[:14].isna().all()
    assert result["plus_di"].notna().iloc[14:].all()  # DI defined from bar 14


def test_adx_rejects_bad_period() -> None:
    with pytest.raises(ValueError, match="positive"):
        adx(_reference_frame(), period=0)
