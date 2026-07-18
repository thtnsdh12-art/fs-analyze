import math

import pandas as pd
import pytest

from src.ratios import (
    compute_ratios,
    format_blank_reason_notes,
    get_bs_chart_items,
    standardize_accounts,
)

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


_BS_ACCOUNT_NAMES = {"유동자산", "유동부채", "비유동자산", "비유동부채", "자산총계", "부채총계", "자본총계"}


def _sj_nm_for(account_nm: str) -> str:
    """standardize_accounts가 이제 sj_nm으로 매칭 대상을 좁히므로, 표본 데이터도
    실제 DART 응답처럼 계정이 재무상태표/손익계산서 중 어디 속하는지 태깅해야 한다.
    """
    base_name = account_nm.split("(")[0]
    return "재무상태표" if base_name in _BS_ACCOUNT_NAMES else "포괄손익계산서"


def _sample_long_df(rows=None) -> pd.DataFrame:
    rows = _ROWS if rows is None else rows
    return pd.DataFrame(
        [
            {
                "period": period,
                "period_label": period,
                "sj_nm": _sj_nm_for(account_nm),
                "account_nm": account_nm,
                "account_id": account_id,
                "amount": float(amount),
            }
            for period, account_nm, account_id, amount in rows
        ]
    )


def test_standardize_accounts_matches_by_id_and_name_fallback_and_derives_gross_profit():
    long_df = _sample_long_df()
    accounts_wide, missing, derived_notes, ambiguous = standardize_accounts(long_df)
    assert ambiguous == []

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
    _, missing, _, _ = standardize_accounts(long_df)

    assert "당기순이익" in missing


def test_compute_ratios_current_period_values():
    long_df = _sample_long_df()
    ratio_df, missing, _, _, _ = compute_ratios(long_df)

    assert missing == []
    assert ratio_df.loc["유동비율", "당기"] == pytest.approx(220.0)
    assert ratio_df.loc["자기자본비율", "당기"] == pytest.approx(60.0)
    assert ratio_df.loc["영업이익률", "당기"] == pytest.approx(10.0)
    assert ratio_df.loc["순이익률", "당기"] == pytest.approx(8.0)
    # ROA는 자산총계 평균((1400+1200)/2=1300) 기준
    assert ratio_df.loc["ROA", "당기"] == pytest.approx(56 / 1300 * 100)


def test_compute_ratios_uses_period_end_value_when_no_prior_period_for_average():
    long_df = _sample_long_df()
    ratio_df, _, _, _, _ = compute_ratios(long_df)

    # 전전기는 그 이전 기간 데이터가 없으므로 평균이 아닌 기말값을 그대로 사용
    assert ratio_df.loc["ROA", "전전기"] == pytest.approx(40 / 1000 * 100)
    assert ratio_df.loc["ROE", "전전기"] == pytest.approx(40 / 600 * 100)


def test_compute_ratios_change_column_vs_prior_period():
    long_df = _sample_long_df()
    ratio_df, _, _, _, _ = compute_ratios(long_df)

    assert ratio_df.loc["유동비율", "전기대비증감률(%)"] == pytest.approx(10.0)


def test_compute_ratios_blank_when_denominator_missing_or_zero():
    rows = [r for r in _ROWS if not (r[1] == "자본총계")]
    long_df = _sample_long_df(rows)
    ratio_df, missing, _, _, _ = compute_ratios(long_df)

    assert "자본총계" in missing
    assert all(math.isnan(v) for v in ratio_df.loc["부채비율"])
    assert all(math.isnan(v) for v in ratio_df.loc["자기자본비율"])


def test_get_bs_chart_items_converts_to_eok_and_reports_missing():
    long_df = _sample_long_df()
    accounts_wide, _, _, _ = standardize_accounts(long_df)
    item_df, missing = get_bs_chart_items(accounts_wide)

    assert missing == []
    # 억원 단위(1e8원=1억) 환산: 표본 데이터의 원 단위(1,400 등)를 그대로 나눔
    assert item_df.loc["유동자산", "당기"] == pytest.approx(440 / 1e8)
    assert item_df.loc["비유동자산", "당기"] == pytest.approx((1400 - 440) / 1e8)


def test_get_bs_chart_items_reports_missing_when_derivation_impossible():
    # 유동자산이 아예 없으면 비유동자산도 파생 불가 -> 그래프에서 공란 처리 대상
    rows = [r for r in _ROWS if not (r[1] == "유동자산")]
    long_df = _sample_long_df(rows)
    accounts_wide, _, _, _ = standardize_accounts(long_df)
    _, missing = get_bs_chart_items(accounts_wide)

    assert "유동자산" in missing
    assert "비유동자산" in missing


def test_standardize_accounts_duplicate_account_id_same_value_is_fine():
    """같은 account_id를 가진 행이 여러 개여도 값이 전부 같으면 문제없이 그 값을 쓴다."""
    rows = _ROWS + [("당기", "유동자산(중복행)", "ifrs-full_CurrentAssets", 440)]
    long_df = _sample_long_df(rows)

    accounts_wide, missing, _, ambiguous = standardize_accounts(long_df)

    assert ambiguous == []
    assert "유동자산" not in missing
    assert accounts_wide.loc["유동자산", "당기"] == pytest.approx(440.0)


def test_standardize_accounts_duplicate_account_id_conflicting_value_is_blanked_with_warning():
    """같은 account_id인데 값이 다르면 임의로 첫 값을 택하지 않고 공란+경고 처리한다."""
    rows = _ROWS + [("당기", "유동자산(오류행)", "ifrs-full_CurrentAssets", 999)]
    long_df = _sample_long_df(rows)

    accounts_wide, missing, _, ambiguous = standardize_accounts(long_df)

    assert math.isnan(accounts_wide.loc["유동자산", "당기"])
    assert "유동자산" in missing  # 필수계정이라 매핑 실패 목록에도 포함됨
    assert any("유동자산" in note and "당기" in note for note in ambiguous)


def test_standardize_accounts_ignores_statement_of_changes_in_equity_duplicates():
    """자본변동표는 같은 account_id(예: 자본총계)를 기초자본/배당/당기순이익반영/기말자본
    등 여러 행에서 재사용하는데, 이는 실제 DART 응답에서 관찰된 정상적인 구조이지 오류가
    아니다. sj_nm으로 재무상태표만 보도록 좁혀서, 이런 자본변동표 행들이 재무상태표의
    진짜 자본총계 값과 충돌하는 것처럼 오판(false positive)하지 않아야 한다.
    """
    rows = _ROWS + [
        # 실측(SK하이닉스)에서 관찰된 패턴을 축소 재현: 같은 account_id, 다른 sj_nm/값
        ("당기", "자본총계", "ifrs-full_Equity", 999),  # 일단 재무상태표로 태깅되지만 아래서 sj_nm만 자본변동표로 덮어씀
    ]
    long_df = _sample_long_df(rows)
    # 방금 추가한 행만 자본변동표로 재태깅(자본변동표의 다른 소계 행을 흉내냄)
    long_df.loc[long_df.index[-1], "sj_nm"] = "자본변동표"

    accounts_wide, missing, _, ambiguous = standardize_accounts(long_df)

    assert ambiguous == []
    assert "자본총계" not in missing
    # 재무상태표의 원래 값(840)이 그대로 쓰여야 하고, 자본변동표의 999는 무시되어야 함
    assert accounts_wide.loc["자본총계", "당기"] == pytest.approx(840.0)


def test_compute_ratios_propagates_ambiguous_matches():
    rows = _ROWS + [("당기", "유동자산(오류행)", "ifrs-full_CurrentAssets", 999)]
    long_df = _sample_long_df(rows)

    ratio_df, _, _, ambiguous, _ = compute_ratios(long_df)

    assert ambiguous != []
    assert math.isnan(ratio_df.loc["유동비율", "당기"])


def test_blank_reason_pinpoints_missing_cogs_for_holding_company_style_data():
    """지주회사처럼 매출원가 자체가 없는 회사는 매출총이익률이 공란인데, 그 이유가
    "매출원가가 없어 산출되지 않습니다."로 정확히 안내되어야 한다 (매출총이익이 아니라
    실제 원인인 매출원가를 짚어야 함).
    """
    rows = [r for r in _ROWS if r[1] != "매출원가"]
    long_df = _sample_long_df(rows)

    ratio_df, _, _, _, blank_reasons = compute_ratios(long_df)

    assert all(math.isnan(v) for v in ratio_df.loc["매출총이익률"])
    for period in ("전전기", "전기", "당기"):
        assert blank_reasons["매출총이익률"][period] == "매출원가가 없어 산출되지 않습니다."
    # 매출원가와 무관한 다른 비율은 영향받지 않아야 함
    assert "영업이익률" not in blank_reasons
    assert "순이익률" not in blank_reasons


def test_blank_reason_lists_multiple_missing_accounts_for_current_ratio():
    """은행/보험처럼 유동자산·유동부채가 둘 다 없는 경우, 사유에 둘 다 나열되어야 한다."""
    rows = [r for r in _ROWS if r[1] not in ("유동자산", "유동부채")]
    long_df = _sample_long_df(rows)

    _, _, _, _, blank_reasons = compute_ratios(long_df)

    for period in ("전전기", "전기", "당기"):
        assert (
            blank_reasons["유동비율"][period] == "유동자산, 유동부채가 없어 산출되지 않습니다."
        )


def test_format_blank_reason_notes_orders_by_ratio_then_period():
    rows = [r for r in _ROWS if r[1] != "매출원가"]
    long_df = _sample_long_df(rows)
    _, _, _, _, blank_reasons = compute_ratios(long_df)

    notes = format_blank_reason_notes(blank_reasons, ["전전기", "전기", "당기"])

    assert notes == [
        "[전전기] 매출총이익률: 매출원가가 없어 산출되지 않습니다.",
        "[전기] 매출총이익률: 매출원가가 없어 산출되지 않습니다.",
        "[당기] 매출총이익률: 매출원가가 없어 산출되지 않습니다.",
    ]
