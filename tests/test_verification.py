import math

import pandas as pd
import pytest

from src import verification
from src.screening import build_screening_df


def _accounts_wide() -> pd.DataFrame:
    data = {
        "전기": {
            "유동자산": 100.0,
            "유동부채": 50.0,
            "비유동자산": 200.0,
            "자산총계": 300.0,
            "부채총계": 150.0,
            "자본총계": 150.0,
        },
        "당기": {
            "유동자산": 80.0,
            "유동부채": 40.0,
            "비유동자산": 220.0,
            "자산총계": 300.0,
            "부채총계": 180.0,
            "자본총계": 120.0,
        },
    }
    return pd.DataFrame(data)


def _ratio_df_matching(accounts_wide: pd.DataFrame) -> pd.DataFrame:
    ratios = {"유동비율": {}, "부채비율": {}, "자기자본비율": {}}
    for period in accounts_wide.columns:
        ratios["유동비율"][period] = (
            accounts_wide.loc["유동자산", period] / accounts_wide.loc["유동부채", period] * 100
        )
        ratios["부채비율"][period] = (
            accounts_wide.loc["부채총계", period] / accounts_wide.loc["자본총계", period] * 100
        )
        ratios["자기자본비율"][period] = (
            accounts_wide.loc["자본총계", period] / accounts_wide.loc["자산총계", period] * 100
        )
    return pd.DataFrame(ratios).T


def test_verify_ratios_all_pass_when_consistent():
    accounts_wide = _accounts_wide()
    ratio_df = _ratio_df_matching(accounts_wide)

    results = verification.verify_ratios(accounts_wide, ratio_df)

    assert len(results) == 6  # 3개 비율 x 2개 기간
    assert all(r.ok for r in results)


def test_verify_ratios_detects_mismatch():
    """ratio_df에 일부러 틀린 값을 넣으면 검증이 실패로 잡아내야 한다."""
    accounts_wide = _accounts_wide()
    ratio_df = _ratio_df_matching(accounts_wide)
    ratio_df.loc["부채비율", "당기"] = 999.0  # 의도적으로 틀린 값 주입

    results = verification.verify_ratios(accounts_wide, ratio_df)

    failed = [r for r in results if not r.ok]
    assert len(failed) == 1
    assert failed[0].label == "부채비율"
    assert failed[0].period == "당기"
    assert failed[0].expected == 999.0
    assert abs(failed[0].actual - 150.0) < 1e-9  # 180/120*100


def test_verify_ratios_skips_when_both_missing():
    """계정 매핑 실패로 양쪽 다 결측이면 검증 대상에서 제외한다(별도 경고로 이미 처리됨)."""
    accounts_wide = _accounts_wide()
    accounts_wide.loc["유동자산", "당기"] = math.nan
    ratio_df = _ratio_df_matching(accounts_wide)
    ratio_df.loc["유동비율", "당기"] = math.nan

    results = verification.verify_ratios(accounts_wide, ratio_df)

    labels_periods = [(r.label, r.period) for r in results]
    assert ("유동비율", "당기") not in labels_periods


def test_verify_balance_sheet_identity_passes_when_consistent():
    accounts_wide = _accounts_wide()

    results = verification.verify_balance_sheet_identity(accounts_wide)

    assert len(results) == 4  # 2개 항등식 x 2개 기간
    assert all(r.ok for r in results)


def test_verify_balance_sheet_identity_detects_broken_identity():
    accounts_wide = _accounts_wide()
    accounts_wide.loc["자산총계", "당기"] = 999.0  # 등식이 깨지도록 조작

    results = verification.verify_balance_sheet_identity(accounts_wide)

    failed = [r for r in results if not r.ok]
    assert any(r.label == "자산총계 = 부채총계 + 자본총계" and r.period == "당기" for r in failed)
    assert any(r.label == "자산총계 = 유동자산 + 비유동자산" and r.period == "당기" for r in failed)


def test_verify_balance_sheet_identity_skips_missing_parts():
    accounts_wide = _accounts_wide()
    accounts_wide.loc["비유동자산", "당기"] = math.nan

    results = verification.verify_balance_sheet_identity(accounts_wide)

    labels_periods = [(r.label, r.period) for r in results]
    assert ("자산총계 = 유동자산 + 비유동자산", "당기") not in labels_periods
    # 다른 항등식(자산=부채+자본)은 영향 없어야 함
    assert ("자산총계 = 부채총계 + 자본총계", "당기") in labels_periods


# --- verify_screening ---

_TOTAL_ASSETS = 100_000.0  # 중요성 기준(1%) = 1,000

_SCREENING_ROWS = [
    # (sj_nm, account_nm, period, amount)
    ("재무상태표", "정상초과계정", "전기", 10_000),
    ("재무상태표", "정상초과계정", "당기", 15_000),  # +50%, 포함 대상
    ("재무상태표", "정상미달계정", "전기", 10_000),
    ("재무상태표", "정상미달계정", "당기", 10_500),  # +5%, 제외 대상
    ("재무상태표", "신규계정", "전기", 0),
    ("재무상태표", "신규계정", "당기", 8_000),  # 신규계정, 포함 대상
    ("재무상태표", "부호전환계정", "전기", 3_000),
    ("재무상태표", "부호전환계정", "당기", -2_500),  # 부호전환, 포함 대상
    ("재무상태표", "소액계정", "전기", 10),
    ("재무상태표", "소액계정", "당기", 100),  # 중요성 미달, 제외 대상
]


def _screening_long_df() -> pd.DataFrame:
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
            for sj_nm, account_nm, period, amount in _SCREENING_ROWS
        ]
    )


def test_verify_screening_all_pass_when_screening_df_correct():
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)

    results = verification.verify_screening(long_df, screening_df, _TOTAL_ASSETS)

    assert results  # 뭔가는 검증됐어야 함
    assert all(r.ok for r in results)


def test_verify_screening_detects_wrong_reported_change_pct():
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)
    idx = screening_df.index[screening_df["계정명"] == "정상초과계정"][0]
    screening_df.loc[idx, "증감률(%)"] = 999.0  # 의도적으로 틀린 값 주입

    results = verification.verify_screening(long_df, screening_df, _TOTAL_ASSETS)

    failed = [r for r in results if not r.ok]
    assert any("정상초과계정" in r.label and "증감률" in r.label for r in failed)


def test_verify_screening_detects_wrong_original_amount():
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)
    idx = screening_df.index[screening_df["계정명"] == "신규계정"][0]
    screening_df.loc[idx, "당기금액"] = 12345.0  # long_df 원본과 불일치하도록 조작

    results = verification.verify_screening(long_df, screening_df, _TOTAL_ASSETS)

    failed = [r for r in results if not r.ok]
    assert any("신규계정" in r.label and "원본금액" in r.label for r in failed)


def test_verify_screening_detects_wrong_classification():
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)
    idx = screening_df.index[screening_df["계정명"] == "부호전환계정"][0]
    screening_df.loc[idx, "구분"] = "신규계정"  # 실제로는 부호전환인데 잘못 분류

    results = verification.verify_screening(long_df, screening_df, _TOTAL_ASSETS)

    failed = [r for r in results if not r.ok]
    assert any("부호전환계정" in r.label and "분류" in r.label for r in failed)


def test_verify_screening_detects_missing_account():
    """마땅히 포함됐어야 할 계정이 스크리닝 결과에서 빠지면 완전성 검증이 잡아내야 한다."""
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)
    dropped = screening_df[screening_df["계정명"] != "정상초과계정"].reset_index(drop=True)

    results = verification.verify_screening(long_df, dropped, _TOTAL_ASSETS)

    completeness = [r for r in results if "완전성" in r.label][0]
    assert not completeness.ok
    assert completeness.actual == pytest.approx(1.0)


def test_verify_screening_detects_false_positive():
    """중요성 기준 미달인데 잘못 포함된 계정이 있으면 정확성 검증이 잡아내야 한다."""
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)
    extra_row = pd.DataFrame(
        [
            {
                "재무제표구분": "재무상태표",
                "계정명": "소액계정",
                "전기금액": 10.0,
                "당기금액": 100.0,
                "증감액": 90.0,
                "증감률(%)": 900.0,
                "구분": "정상",
            }
        ]
    )
    polluted = pd.concat([screening_df, extra_row], ignore_index=True)

    results = verification.verify_screening(long_df, polluted, _TOTAL_ASSETS)

    accuracy = [r for r in results if "정확성" in r.label][0]
    assert not accuracy.ok
    assert accuracy.actual == pytest.approx(1.0)


def test_verify_screening_empty_when_total_assets_missing():
    long_df = _screening_long_df()
    screening_df, _ = build_screening_df(long_df, _TOTAL_ASSETS)

    assert verification.verify_screening(long_df, screening_df, math.nan) == []
