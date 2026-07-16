"""표준화된 계정과목으로부터 감사 위험평가용 핵심 재무비율을 계산한다.

계정과목 표준화는 account_id(IFRS 표준계정코드) 완전일치를 1순위로,
account_nm(회사가 실제 기재한 계정과목명) 완전일치를 폴백으로 사용한다.
회사마다 계정과목명이 다르더라도(예: "매출액"/"영업수익") account_id가
동일한 표준코드로 태깅되어 있으면 정확히 매칭할 수 있다.
두 방식 모두 실패하면 임의로 추정하지 않고 매핑 실패로 표시한다
(PRD 요구사항: 매핑 실패 시 공란 + 경고만, 값 추정 금지).
"""

from __future__ import annotations

import math

import pandas as pd

PERIODS = ["전전기", "전기", "당기"]
_PREV_PERIOD = {"전기": "전전기", "당기": "전기"}

# 표준 계정명 -> {account_id 후보 집합, account_nm 완전일치 후보 집합}
ACCOUNT_ALIASES: dict[str, dict[str, set[str]]] = {
    "유동자산": {
        "account_id": {"ifrs-full_CurrentAssets"},
        "account_nm": {"유동자산"},
    },
    "유동부채": {
        "account_id": {"ifrs-full_CurrentLiabilities"},
        "account_nm": {"유동부채"},
    },
    "비유동자산": {
        "account_id": {"ifrs-full_NoncurrentAssets"},
        "account_nm": {"비유동자산"},
    },
    "비유동부채": {
        "account_id": {"ifrs-full_NoncurrentLiabilities"},
        "account_nm": {"비유동부채"},
    },
    "자산총계": {
        "account_id": {"ifrs-full_Assets"},
        "account_nm": {"자산총계"},
    },
    "부채총계": {
        "account_id": {"ifrs-full_Liabilities"},
        "account_nm": {"부채총계"},
    },
    "자본총계": {
        "account_id": {"ifrs-full_Equity"},
        "account_nm": {"자본총계"},
    },
    "매출액": {
        "account_id": {
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
        },
        "account_nm": {"매출액", "영업수익"},
    },
    "매출원가": {
        "account_id": {"ifrs-full_CostOfSales"},
        "account_nm": {"매출원가"},
    },
    "매출총이익": {
        "account_id": {"ifrs-full_GrossProfit"},
        "account_nm": {"매출총이익", "매출총이익(손실)"},
    },
    "영업이익": {
        "account_id": {
            "dart_OperatingIncomeLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
        },
        "account_nm": {"영업이익", "영업이익(손실)"},
    },
    "당기순이익": {
        "account_id": {"ifrs-full_ProfitLoss"},
        "account_nm": {
            "당기순이익",
            "당기순이익(손실)",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
        },
    },
}

# 비율 계산에 최소한으로 필요한 표준 계정 (매출총이익은 매출액-매출원가로 대체 가능하므로 제외)
REQUIRED_ACCOUNTS = [
    "유동자산",
    "유동부채",
    "자산총계",
    "부채총계",
    "자본총계",
    "매출액",
    "영업이익",
    "당기순이익",
]

RATIO_NAMES = [
    "유동비율",
    "부채비율",
    "자기자본비율",
    "ROA",
    "ROE",
    "매출총이익률",
    "영업이익률",
    "순이익률",
]

# 엑셀 그래프용 재무상태표 항목 (비율이 아닌 실측 항목 자체를 보여달라는 요구사항)
BS_CHART_ITEMS = ["유동자산", "비유동자산", "유동부채", "비유동부채"]
_WON_PER_EOK = 1e8  # 억원 단위 환산


def _match_amount(period_df: pd.DataFrame, aliases: dict[str, set[str]]) -> float:
    """한 기간 내에서 account_id 우선, account_nm 폴백으로 금액을 찾는다. 못 찾으면 NaN."""
    id_hits = period_df[period_df["account_id"].isin(aliases["account_id"])]
    if not id_hits.empty:
        return id_hits.iloc[0]["amount"]

    nm_hits = period_df[period_df["account_nm"].isin(aliases["account_nm"])]
    if not nm_hits.empty:
        return nm_hits.iloc[0]["amount"]

    return math.nan


def standardize_accounts(long_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """계정과목을 표준명으로 매핑해 (표준계정명 x 기간) 와이드 테이블을 만든다.

    반환:
        accounts_wide: 표준계정명(행) x 기간(열) 금액 테이블
        missing: 하나 이상의 기간에서 매핑에 실패한 필수 표준계정명 목록 (경고용)
        derived_notes: 직접 매핑되지 않고 다른 계정으로부터 계산된 항목 설명 목록
    """
    periods_present = [p for p in PERIODS if p in set(long_df.get("period", []))]

    data: dict[str, dict[str, float]] = {name: {} for name in ACCOUNT_ALIASES}
    missing: list[str] = []
    derived_notes: list[str] = []

    for period in periods_present:
        period_df = long_df[long_df["period"] == period]
        for name, aliases in ACCOUNT_ALIASES.items():
            data[name][period] = _match_amount(period_df, aliases)

        # 매출총이익을 직접 공시하지 않는 회사가 많음 -> 매출액/매출원가가 모두
        # 확보된 경우에 한해 정확한 회계 등식(매출총이익 = 매출액 - 매출원가)으로
        # 산출한다. 이는 추정이 아니라 이미 확보된 두 실측치의 차감 계산이다.
        if math.isnan(data["매출총이익"][period]):
            revenue = data["매출액"][period]
            cogs = data["매출원가"][period]
            if not math.isnan(revenue) and not math.isnan(cogs):
                data["매출총이익"][period] = revenue - cogs
                derived_notes.append(
                    f"[{period}] 매출총이익 = 매출액 - 매출원가로 계산됨 (공시된 매출총이익 항목 없음)"
                )

        # 비유동자산/비유동부채도 별도로 공시하지 않는 회사가 있어, 자산총계/부채총계에서
        # 유동 항목을 차감해 산출한다(추정이 아니라 실측치의 차감 계산).
        if math.isnan(data["비유동자산"][period]):
            total_assets = data["자산총계"][period]
            current_assets = data["유동자산"][period]
            if not math.isnan(total_assets) and not math.isnan(current_assets):
                data["비유동자산"][period] = total_assets - current_assets
                derived_notes.append(
                    f"[{period}] 비유동자산 = 자산총계 - 유동자산으로 계산됨 (공시된 비유동자산 항목 없음)"
                )

        if math.isnan(data["비유동부채"][period]):
            total_liabilities = data["부채총계"][period]
            current_liabilities = data["유동부채"][period]
            if not math.isnan(total_liabilities) and not math.isnan(current_liabilities):
                data["비유동부채"][period] = total_liabilities - current_liabilities
                derived_notes.append(
                    f"[{period}] 비유동부채 = 부채총계 - 유동부채로 계산됨 (공시된 비유동부채 항목 없음)"
                )

    for name in REQUIRED_ACCOUNTS:
        if any(math.isnan(data[name].get(p, math.nan)) for p in periods_present):
            missing.append(name)

    accounts_wide = pd.DataFrame(data).T
    accounts_wide = accounts_wide.reindex(columns=periods_present)
    return accounts_wide, missing, derived_notes


def _safe_div(numerator: float, denominator: float) -> float:
    if numerator is None or denominator is None:
        return math.nan
    if isinstance(numerator, float) and math.isnan(numerator):
        return math.nan
    if isinstance(denominator, float) and (math.isnan(denominator) or denominator == 0):
        return math.nan
    if denominator == 0:
        return math.nan
    return numerator / denominator


def compute_ratios(long_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """3개년 재무비율(단위: %)을 계산한다.

    반환: (비율 x 기간 데이터프레임, 매핑 실패 표준계정 목록, 파생 계산 안내 목록)
    """
    accounts_wide, missing, derived_notes = standardize_accounts(long_df)
    periods_present = list(accounts_wide.columns)

    def get(name: str, period: str | None) -> float:
        if period is None or period not in accounts_wide.columns:
            return math.nan
        return accounts_wide.loc[name, period]

    def average_with_prior(name: str, period: str) -> float:
        current = get(name, period)
        prior = get(name, _PREV_PERIOD.get(period))
        if math.isnan(prior):
            return current
        if math.isnan(current):
            return math.nan
        return (current + prior) / 2

    ratios: dict[str, dict[str, float]] = {name: {} for name in RATIO_NAMES}

    for period in periods_present:
        유동자산 = get("유동자산", period)
        유동부채 = get("유동부채", period)
        자산총계 = get("자산총계", period)
        부채총계 = get("부채총계", period)
        자본총계 = get("자본총계", period)
        매출액 = get("매출액", period)
        매출총이익 = get("매출총이익", period)
        영업이익 = get("영업이익", period)
        당기순이익 = get("당기순이익", period)

        자산평균 = average_with_prior("자산총계", period)
        자본평균 = average_with_prior("자본총계", period)

        ratios["유동비율"][period] = _safe_div(유동자산, 유동부채) * 100
        ratios["부채비율"][period] = _safe_div(부채총계, 자본총계) * 100
        ratios["자기자본비율"][period] = _safe_div(자본총계, 자산총계) * 100
        ratios["ROA"][period] = _safe_div(당기순이익, 자산평균) * 100
        ratios["ROE"][period] = _safe_div(당기순이익, 자본평균) * 100
        ratios["매출총이익률"][period] = _safe_div(매출총이익, 매출액) * 100
        ratios["영업이익률"][period] = _safe_div(영업이익, 매출액) * 100
        ratios["순이익률"][period] = _safe_div(당기순이익, 매출액) * 100

    ratio_df = pd.DataFrame(ratios).T
    ratio_df = ratio_df.reindex(columns=periods_present)

    if "전기" in ratio_df.columns and "당기" in ratio_df.columns:
        prior = ratio_df["전기"]
        current = ratio_df["당기"]
        denom = prior.abs()
        change = (current - prior) / denom * 100
        change[denom == 0] = math.nan
        ratio_df["전기대비증감률(%)"] = change

    return ratio_df, missing, derived_notes


def get_bs_chart_items(accounts_wide: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """그래프용 재무상태표 항목(유동/비유동 자산·부채)을 억원 단위로 추출한다.

    반환: (항목 x 기간 데이터프레임(억원), 하나 이상의 기간에서 확보하지 못한 항목 목록)
    매핑/파생 모두 실패한 항목은 NaN으로 남겨 그래프에서 공란(끊긴 선/빈 막대)으로
    표시되며 임의로 추정하지 않는다.
    """
    missing = [
        name
        for name in BS_CHART_ITEMS
        if name not in accounts_wide.index or accounts_wide.loc[name].isna().any()
    ]
    item_df = accounts_wide.reindex(BS_CHART_ITEMS) / _WON_PER_EOK
    return item_df, missing
