import math

import pandas as pd
import pytest

from src.ratios import compute_ratios, get_bs_chart_items, standardize_accounts

# (period, account_nm, account_id, amount)
_ROWS = [
    # 전전기
    ("전전기", "유동자산", "ifrs-full_CurrentAssets", 200),
    ("전전기", "유동부채", "ifrs-full_CurrentLiabilities", 100),
    ("전전기", "자산총계", "ifrs-full_Assets", 1000),
    ("전전기", "부채총계", "ifrs-full_Liabilities", 400),
    ("전전기", "자본총계", "ifrs-full_Equity", 600),
    ("전전기", "매출액", None, 500),  # account_id 없음 -> account_nm 폴백 매칭
    ("전전기", "매출원가", "ifrs-full_CostOfSales", 300),
    ("전전기", "영업이익", "dart_OperatingIncomeLoss", 50),
    ("전전기", "당기순이익", "ifrs-full_ProfitLoss", 40),
    # 전기
    ("전기", "유동자산", "ifrs-full_CurrentAssets", 300),
    ("전기", "유동부채", "ifrs-full_CurrentLiabilities", 150),
    ("전기", "자산총계", "ifrs-full_Assets", 1200),
    ("전기", "부채총계", "ifrs-full_Liabilities", 480),
    ("전기", "자본총계", "ifrs-full_Equity", 720),
    ("전기", "영업수익", None, 600),  # 회사가 "영업수익"으로 기재 -> alias 매칭
    ("전기", "매출원가", "ifrs-full_CostOfSales", 350),
    ("전기", "영업이익", "dart_OperatingIncomeLoss", 60),
    ("전기", "당기순이익", "ifrs-full_ProfitLoss", 48),
    # 당기
    ("당기", "유동자산", "ifrs-full_CurrentAssets", 440),
    ("당기", "유동부채", "ifrs-full_CurrentLiabilities", 200),
    ("당기", "자산총계", "ifrs-full_Assets", 1400),
    ("당기", "부채총계", "ifrs-full_Liabilities", 560),
    ("당기", "자본총계", "ifrs-full_Equity", 840),
    ("당기", "매출액", "ifrs-full_Revenue", 700),
    ("당기", "매출원가", "ifrs-full_CostOfSales", 400),
    ("당기", "영업이익", "dart_OperatingIncomeLoss", 70),
    ("당기", "당기순이익", "ifrs-full_ProfitLoss", 56),
]


def _sample_long_df(rows=None) -> pd.DataFrame:
    rows = _ROWS if rows is None else rows
    return pd.DataFrame(
        [
            {
                "period": period,
                "period_label": period,
                "sj_nm": "재무상태표",
                "account_nm": account_nm,
                "account_id": account_id,
                "amount": float(amount),
            }
            for period, account_nm, account_id, amount in rows
        ]
    )


def test_standardize_accounts_matches_by_id_and_name_fallback_and_derives_gross_profit():
    long_df = _sample_long_df()
    accounts_wide, missing, derived_notes = standardize_accounts(long_df)

    assert missing == []
    # 매출총이익은 어느 기간에도 직접 태깅되지 않았으므로 매출액-매출원가로 파생되어야 함
    assert accounts_wide.loc["매출총이익", "당기"] == pytest.approx(300.0)
    assert accounts_wide.loc["매출총이익", "전기"] == pytest.approx(250.0)
    assert accounts_wide.loc["매출총이익", "전전기"] == pytest.approx(200.0)
    # 매출총이익 파생 3건(매 기간) + 비유동자산/비유동부채 파생 각 3건(자산총계-유동자산,
    # 부채총계-유동부채) = 9건. 표본 데이터에 비유동자산/부채가 직접 태깅되지 않았으므로
    # 세 항목 모두 매 기간 파생 계산된다.
    assert len(derived_notes) == 9

    # 비유동자산/비유동부채도 자산총계-유동자산, 부채총계-유동부채로 파생되어야 함
    assert accounts_wide.loc["비유동자산", "당기"] == pytest.approx(1400 - 440)
    assert accounts_wide.loc["비유동부채", "당기"] == pytest.approx(560 - 200)

    # account_id 없이 account_nm만으로 매칭된 케이스 (전전기 "매출액", 전기 "영업수익")
    assert accounts_wide.loc["매출액", "전전기"] == pytest.approx(500.0)
    assert accounts_wide.loc["매출액", "전기"] == pytest.approx(600.0)


def test_standardize_accounts_reports_missing_when_account_absent_in_any_period():
    rows = [r for r in _ROWS if not (r[0] == "당기" and r[1] == "당기순이익")]
    long_df = _sample_long_df(rows)
    _, missing, _ = standardize_accounts(long_df)

    assert "당기순이익" in missing


def test_compute_ratios_current_period_values():
    long_df = _sample_long_df()
    ratio_df, missing, _ = compute_ratios(long_df)

    assert missing == []
    assert ratio_df.loc["유동비율", "당기"] == pytest.approx(220.0)
    assert ratio_df.loc["자기자본비율", "당기"] == pytest.approx(60.0)
    assert ratio_df.loc["영업이익률", "당기"] == pytest.approx(10.0)
    assert ratio_df.loc["순이익률", "당기"] == pytest.approx(8.0)
    # ROA는 자산총계 평균((1400+1200)/2=1300) 기준
    assert ratio_df.loc["ROA", "당기"] == pytest.approx(56 / 1300 * 100)


def test_compute_ratios_uses_period_end_value_when_no_prior_period_for_average():
    long_df = _sample_long_df()
    ratio_df, _, _ = compute_ratios(long_df)

    # 전전기는 그 이전 기간 데이터가 없으므로 평균이 아닌 기말값을 그대로 사용
    assert ratio_df.loc["ROA", "전전기"] == pytest.approx(40 / 1000 * 100)
    assert ratio_df.loc["ROE", "전전기"] == pytest.approx(40 / 600 * 100)


def test_compute_ratios_change_column_vs_prior_period():
    long_df = _sample_long_df()
    ratio_df, _, _ = compute_ratios(long_df)

    assert ratio_df.loc["유동비율", "전기대비증감률(%)"] == pytest.approx(10.0)


def test_compute_ratios_blank_when_denominator_missing_or_zero():
    rows = [r for r in _ROWS if not (r[1] == "자본총계")]
    long_df = _sample_long_df(rows)
    ratio_df, missing, _ = compute_ratios(long_df)

    assert "자본총계" in missing
    assert all(math.isnan(v) for v in ratio_df.loc["부채비율"])
    assert all(math.isnan(v) for v in ratio_df.loc["자기자본비율"])


def test_get_bs_chart_items_converts_to_eok_and_reports_missing():
    long_df = _sample_long_df()
    accounts_wide, _, _ = standardize_accounts(long_df)
    item_df, missing = get_bs_chart_items(accounts_wide)

    assert missing == []
    # 억원 단위(1e8원=1억) 환산: 표본 데이터의 원 단위(1,400 등)를 그대로 나눔
    assert item_df.loc["유동자산", "당기"] == pytest.approx(440 / 1e8)
    assert item_df.loc["비유동자산", "당기"] == pytest.approx((1400 - 440) / 1e8)


def test_get_bs_chart_items_reports_missing_when_derivation_impossible():
    # 유동자산이 아예 없으면 비유동자산도 파생 불가 -> 그래프에서 공란 처리 대상
    rows = [r for r in _ROWS if not (r[1] == "유동자산")]
    long_df = _sample_long_df(rows)
    accounts_wide, _, _ = standardize_accounts(long_df)
    _, missing = get_bs_chart_items(accounts_wide)

    assert "유동자산" in missing
    assert "비유동자산" in missing
