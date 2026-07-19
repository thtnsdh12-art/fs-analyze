import math

import pandas as pd
import pytest

from src.screening import STATUS_NEW, STATUS_NORMAL, STATUS_SIGN_FLIP, build_screening_df

TOTAL_ASSETS = 100_000.0  # 중요성 기준(1%) = 1,000

# (sj_nm, account_nm, period, amount)
_ROWS = [
    # 정상, 30% 초과(진하게) -> 포함, 증감액 5,000
    ("재무상태표", "정상초과계정", "전기", 10_000),
    ("재무상태표", "정상초과계정", "당기", 15_000),
    # 정상, 10% 미달 -> 제외
    ("재무상태표", "정상미달계정", "전기", 10_000),
    ("재무상태표", "정상미달계정", "당기", 10_500),
    # 신규계정(전기=0) -> 포함, 증감액 8,000 (제일 큼)
    ("재무상태표", "신규계정", "전기", 0),
    ("재무상태표", "신규계정", "당기", 8_000),
    # 부호전환(흑자->적자) -> 포함, 증감액 -5,500
    ("재무상태표", "부호전환계정", "전기", 3_000),
    ("재무상태표", "부호전환계정", "당기", -2_500),
    # 중요성 미달 소액계정(900% 급증이어도 절대금액이 작아 제외)
    ("재무상태표", "소액계정", "전기", 10),
    ("재무상태표", "소액계정", "당기", 100),
    # 내부 충돌: 같은 (sj_nm, account_nm)인데 당기 금액이 서로 다름 -> 제외 + 경고
    ("재무상태표", "충돌계정", "전기", 1_000),
    ("재무상태표", "충돌계정", "당기", 1_500),
    ("재무상태표", "충돌계정", "당기", 9_999),
    # 손익계산서, 30% 초과(진하게) -> 포함, 증감액 400
    ("손익계산서", "손익정상계정", "전기", 1_000),
    ("손익계산서", "손익정상계정", "당기", 1_400),
    # 현금흐름표, 10~30%(연하게) -> 포함, 증감액 240
    ("현금흐름표", "현금흐름정상계정", "전기", 2_000),
    ("현금흐름표", "현금흐름정상계정", "당기", 2_240),
    # 현금흐름표, 증감액 자체는 재무상태표 항목들보다 훨씬 크지만(50,000) 재무제표구분
    # 정렬이 우선이므로 재무상태표 항목들보다 뒤에 와야 한다 (그룹 우선 정렬 검증용)
    ("현금흐름표", "현금흐름거액계정", "전기", 1_000),
    ("현금흐름표", "현금흐름거액계정", "당기", 51_000),
    # 자본변동표는 범위 밖 -> 증감률이 아무리 커도 항상 제외
    ("자본변동표", "자본변동표계정", "전기", 100),
    ("자본변동표", "자본변동표계정", "당기", 1_000_000),
]


def _long_df(rows=None) -> pd.DataFrame:
    rows = _ROWS if rows is None else rows
    return pd.DataFrame(
        [
            {
                "period": period,
                "period_label": period,
                "sj_nm": sj_nm,
                "account_nm": account_nm,
                "account_id": None,
                "amount": float(amount),
            }
            for sj_nm, account_nm, period, amount in rows
        ]
    )


def test_excludes_capital_change_statement_regardless_of_magnitude():
    long_df = _long_df()
    result, _ = build_screening_df(long_df, TOTAL_ASSETS)

    assert "자본변동표계정" not in result["계정명"].values


def test_excludes_below_threshold_and_below_materiality():
    long_df = _long_df()
    result, _ = build_screening_df(long_df, TOTAL_ASSETS)

    names = set(result["계정명"])
    assert "정상미달계정" not in names  # |5%| <= 10%
    assert "소액계정" not in names  # 절대금액이 중요성 기준 미만


def test_new_account_and_sign_flip_bypass_percentage_and_are_flagged():
    long_df = _long_df()
    result, _ = build_screening_df(long_df, TOTAL_ASSETS)
    by_name = result.set_index("계정명")

    assert by_name.loc["신규계정", "구분"] == STATUS_NEW
    assert math.isnan(by_name.loc["신규계정", "증감률(%)"])
    assert by_name.loc["신규계정", "증감액"] == pytest.approx(8_000)

    assert by_name.loc["부호전환계정", "구분"] == STATUS_SIGN_FLIP
    assert math.isnan(by_name.loc["부호전환계정", "증감률(%)"])
    assert by_name.loc["부호전환계정", "증감액"] == pytest.approx(-5_500)


def test_normal_account_change_pct_formula():
    long_df = _long_df()
    result, _ = build_screening_df(long_df, TOTAL_ASSETS)
    by_name = result.set_index("계정명")

    row = by_name.loc["정상초과계정"]
    assert row["구분"] == STATUS_NORMAL
    assert row["증감률(%)"] == pytest.approx((15_000 - 10_000) / 10_000 * 100)
    assert row["증감액"] == pytest.approx(5_000)


def test_internal_conflict_excluded_with_note():
    long_df = _long_df()
    result, excluded_notes = build_screening_df(long_df, TOTAL_ASSETS)

    assert "충돌계정" not in result["계정명"].values
    assert any("충돌계정" in note for note in excluded_notes)


def test_sorted_by_statement_group_then_absolute_change_amount_descending():
    """재무제표구분(재무상태표 -> 손익계산서/포괄손익계산서 -> 현금흐름표)을 먼저 묶고,
    그 안에서 증감액 절대값 내림차순으로 정렬해야 한다. 현금흐름거액계정은 증감액이
    재무상태표 항목들보다 훨씬 크지만(50,000) 그룹 정렬이 우선이므로 맨 뒤에 와야 한다.
    """
    long_df = _long_df()
    result, _ = build_screening_df(long_df, TOTAL_ASSETS)

    assert list(result["계정명"]) == [
        "신규계정",  # 재무상태표, 8,000
        "부호전환계정",  # 재무상태표, abs 5,500
        "정상초과계정",  # 재무상태표, 5,000
        "손익정상계정",  # 손익계산서, 400
        "현금흐름거액계정",  # 현금흐름표, 50,000 (그룹 정렬이 우선이라 위 항목들 뒤에 옴)
        "현금흐름정상계정",  # 현금흐름표, 240
    ]


def test_empty_when_total_assets_missing_or_zero():
    long_df = _long_df()
    result, notes = build_screening_df(long_df, math.nan)
    assert result.empty

    result_zero, _ = build_screening_df(long_df, 0.0)
    assert result_zero.empty
