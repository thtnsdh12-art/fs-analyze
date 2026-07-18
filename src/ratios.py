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

# DART fnlttSinglAcntAll 응답은 재무상태표/손익계산서/현금흐름표/자본변동표를 구분 없이
# 한 테이블에 섞어서 준다. 특히 자본변동표는 구조상 "자본총계"/"당기순이익" 같은
# account_id가 한 기간 안에 8~9번 반복된다(기초자본/배당/당기순이익반영/기타포괄손익/
# 기말자본 등 각 행이 같은 태그를 재사용) — 이는 값이 서로 다른 게 정상이며 오류가 아니다.
# 그래서 매칭 대상을 애초에 계정이 실제로 속한 재무제표 구분(sj_nm)으로 좁혀야 한다.
_BS_STATEMENTS = frozenset({"재무상태표"})
# 회사에 따라 손익계산서/포괄손익계산서를 하나로 합쳐 내거나(포괄손익계산서만 존재)
# 둘로 나눠 내므로(손익계산서 + 포괄손익계산서) 둘 다 허용한다.
_IS_STATEMENTS = frozenset({"손익계산서", "포괄손익계산서"})

# 표준 계정명 -> {account_id 후보 집합, account_nm 완전일치 후보 집합, 유효 sj_nm 집합}
ACCOUNT_ALIASES: dict[str, dict[str, frozenset[str]]] = {
    "유동자산": {
        "account_id": {"ifrs-full_CurrentAssets"},
        "account_nm": {"유동자산"},
        "sj_nm": _BS_STATEMENTS,
    },
    "유동부채": {
        "account_id": {"ifrs-full_CurrentLiabilities"},
        "account_nm": {"유동부채"},
        "sj_nm": _BS_STATEMENTS,
    },
    "비유동자산": {
        "account_id": {"ifrs-full_NoncurrentAssets"},
        "account_nm": {"비유동자산"},
        "sj_nm": _BS_STATEMENTS,
    },
    "비유동부채": {
        "account_id": {"ifrs-full_NoncurrentLiabilities"},
        "account_nm": {"비유동부채"},
        "sj_nm": _BS_STATEMENTS,
    },
    "자산총계": {
        "account_id": {"ifrs-full_Assets"},
        "account_nm": {"자산총계"},
        "sj_nm": _BS_STATEMENTS,
    },
    "부채총계": {
        "account_id": {"ifrs-full_Liabilities"},
        "account_nm": {"부채총계"},
        "sj_nm": _BS_STATEMENTS,
    },
    "자본총계": {
        "account_id": {"ifrs-full_Equity"},
        "account_nm": {"자본총계"},
        "sj_nm": _BS_STATEMENTS,
    },
    "매출액": {
        "account_id": {
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
        },
        "account_nm": {"매출액", "영업수익"},
        "sj_nm": _IS_STATEMENTS,
    },
    "매출원가": {
        "account_id": {"ifrs-full_CostOfSales"},
        "account_nm": {"매출원가"},
        "sj_nm": _IS_STATEMENTS,
    },
    "매출총이익": {
        "account_id": {"ifrs-full_GrossProfit"},
        "account_nm": {"매출총이익", "매출총이익(손실)"},
        "sj_nm": _IS_STATEMENTS,
    },
    "영업이익": {
        "account_id": {
            "dart_OperatingIncomeLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
        },
        "account_nm": {"영업이익", "영업이익(손실)"},
        "sj_nm": _IS_STATEMENTS,
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
        "sj_nm": _IS_STATEMENTS,
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

# 비율이 공란일 때 "왜" 공란인지 설명하기 위한, 비율별 원천 계정 의존관계.
# 매출총이익률은 매출총이익(직접 태깅 또는 매출액-매출원가 파생)에 의존하는 특수
# 케이스라 아래 딕셔너리가 아니라 _blank_reason()에서 별도로 처리한다.
_RATIO_DEPENDENCIES: dict[str, list[str]] = {
    "유동비율": ["유동자산", "유동부채"],
    "부채비율": ["부채총계", "자본총계"],
    "자기자본비율": ["자본총계", "자산총계"],
    "ROA": ["당기순이익", "자산총계"],
    "ROE": ["당기순이익", "자본총계"],
    "영업이익률": ["영업이익", "매출액"],
    "순이익률": ["당기순이익", "매출액"],
}


def _match_amount(period_df: pd.DataFrame, aliases: dict[str, set[str]]) -> tuple[float, bool]:
    """한 기간·한 재무제표(sj_nm) 내에서 account_id 우선, account_nm 폴백으로 금액을 찾는다.

    먼저 aliases["sj_nm"](예: 재무상태표)으로 대상을 좁힌 뒤 매칭한다 — DART 응답은
    재무상태표/손익계산서/현금흐름표/자본변동표가 한 테이블에 섞여 있고, 특히 자본변동표는
    같은 account_id를 여러 행(기초자본/배당/당기순이익반영 등)에서 재사용하므로 sj_nm으로
    먼저 좁히지 않으면 전혀 무관한 값과 충돌하는 것처럼 보일 수 있다.

    반환: (금액 또는 NaN, ambiguous 여부)
    sj_nm으로 좁힌 뒤에도 동일 account_id(또는 account_nm)를 가진 행이 여러 개 있을 수
    있다. 값이 전부 같으면 단순 중복 행이라 문제없이 그 값을 쓰지만, 값이 서로 다르면
    어느 쪽이 맞는지 판단할 근거가 없으므로 임의로 첫 번째 값을 택하지 않고
    NaN + ambiguous=True를 반환한다("매핑 실패 시 공란+경고, 임의 추정 금지" 원칙과 동일).
    """
    sj_nm_filter = aliases.get("sj_nm")
    if sj_nm_filter:
        period_df = period_df[period_df["sj_nm"].isin(sj_nm_filter)]

    id_hits = period_df[period_df["account_id"].isin(aliases["account_id"])]
    if not id_hits.empty:
        amounts = id_hits["amount"]
        if amounts.nunique(dropna=False) > 1:
            return math.nan, True
        return amounts.iloc[0], False

    nm_hits = period_df[period_df["account_nm"].isin(aliases["account_nm"])]
    if not nm_hits.empty:
        amounts = nm_hits["amount"]
        if amounts.nunique(dropna=False) > 1:
            return math.nan, True
        return amounts.iloc[0], False

    return math.nan, False


def standardize_accounts(
    long_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    """계정과목을 표준명으로 매핑해 (표준계정명 x 기간) 와이드 테이블을 만든다.

    반환:
        accounts_wide: 표준계정명(행) x 기간(열) 금액 테이블
        missing: 하나 이상의 기간에서 매핑에 실패한 필수 표준계정명 목록 (경고용)
        derived_notes: 직접 매핑되지 않고 다른 계정으로부터 계산된 항목 설명 목록
        ambiguous_matches: 동일 계정코드/계정명으로 매칭된 값이 서로 달라 공란 처리된
            항목 설명 목록 (경고용, 어느 값이 맞는지 판단 근거가 없어 임의 선택하지 않음)
    """
    periods_present = [p for p in PERIODS if p in set(long_df.get("period", []))]

    data: dict[str, dict[str, float]] = {name: {} for name in ACCOUNT_ALIASES}
    missing: list[str] = []
    derived_notes: list[str] = []
    ambiguous_matches: list[str] = []

    for period in periods_present:
        period_df = long_df[long_df["period"] == period]
        for name, aliases in ACCOUNT_ALIASES.items():
            amount, ambiguous = _match_amount(period_df, aliases)
            data[name][period] = amount
            if ambiguous:
                ambiguous_matches.append(
                    f"[{period}] {name}: 동일 계정코드(account_id) 또는 계정과목명(account_nm)으로 "
                    "매칭된 금액이 서로 달라 공란 처리됨 (임의로 값을 선택하지 않음)"
                )

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
    return accounts_wide, missing, derived_notes, ambiguous_matches


def _subject_particle(word: str) -> str:
    """단어 마지막 글자의 받침 유무로 주격조사(이/가)를 고른다.

    예: "매출원가"(받침 없음) -> "가", "매출액"(받침 있음) -> "이".
    """
    if not word:
        return "가"
    code = ord(word[-1]) - 0xAC00
    if 0 <= code <= 11171:  # 완성형 한글 음절 범위(가~힣)
        return "이" if code % 28 != 0 else "가"
    return "가"


def _missing_reason_text(missing_names: list[str]) -> str:
    joined = ", ".join(missing_names)
    return f"{joined}{_subject_particle(missing_names[-1])} 없어 산출되지 않습니다."


def _account_missing(accounts_wide: pd.DataFrame, name: str, period: str) -> bool:
    if name not in accounts_wide.index or period not in accounts_wide.columns:
        return True
    return math.isnan(accounts_wide.loc[name, period])


def _blank_reason(name: str, period: str, accounts_wide: pd.DataFrame) -> str | None:
    """비율 한 칸(비율명 x 기간)이 공란인 이유를, 실제로 없는 원천 계정명으로 설명한다."""
    if name == "매출총이익률":
        missing_names = []
        if _account_missing(accounts_wide, "매출액", period):
            missing_names.append("매출액")
        if _account_missing(accounts_wide, "매출총이익", period):
            # 매출총이익 자체가 없다는 건 직접 태깅도, 매출액-매출원가 파생도 실패했다는
            # 뜻이다. 매출액은 위에서 이미 확인했으니, 매출원가 유무로 원인을 좁힌다.
            if "매출액" not in missing_names and _account_missing(accounts_wide, "매출원가", period):
                missing_names.append("매출원가")
            elif not missing_names:
                missing_names.append("매출총이익")
        if not missing_names:
            return None
        return _missing_reason_text(missing_names)

    deps = _RATIO_DEPENDENCIES.get(name)
    if not deps:
        return None
    missing_names = [d for d in deps if _account_missing(accounts_wide, d, period)]
    if not missing_names:
        return None
    return _missing_reason_text(missing_names)


def format_blank_reason_notes(
    blank_reasons: dict[str, dict[str, str]], periods: list[str]
) -> list[str]:
    """blank_reasons를 "[기간] 비율명: 사유" 형태의 출력용 문자열 목록으로 펼친다."""
    notes: list[str] = []
    for name in RATIO_NAMES:
        period_reasons = blank_reasons.get(name)
        if not period_reasons:
            continue
        for period in periods:
            if period in period_reasons:
                notes.append(f"[{period}] {name}: {period_reasons[period]}")
    return notes


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


def compute_ratios(
    long_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], list[str], list[str], dict[str, dict[str, str]]]:
    """3개년 재무비율(단위: %)을 계산한다.

    반환: (비율 x 기간 데이터프레임, 매핑 실패 표준계정 목록, 파생 계산 안내 목록,
           동일 계정코드 중복 매칭으로 공란 처리된 항목 안내 목록,
           공란 처리된 비율 칸의 사유 {비율명: {기간: 사유}})
    """
    accounts_wide, missing, derived_notes, ambiguous_matches = standardize_accounts(long_df)
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

    blank_reasons: dict[str, dict[str, str]] = {}
    for name in RATIO_NAMES:
        for period in periods_present:
            if math.isnan(ratio_df.loc[name, period]):
                reason = _blank_reason(name, period, accounts_wide)
                if reason:
                    blank_reasons.setdefault(name, {})[period] = reason

    return ratio_df, missing, derived_notes, ambiguous_matches, blank_reasons


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
