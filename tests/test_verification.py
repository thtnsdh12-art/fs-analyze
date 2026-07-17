import math

import pandas as pd

from src import verification


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
