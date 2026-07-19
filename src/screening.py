"""전기 대비 당기 증감 스크리닝 — 감사 위험평가 관점의 분석적 절차(analytical procedures).

재무상태표/손익계산서/현금흐름표에 속하는 개별 계정과목(표준화 이전 원본,
long_df 기준) 중 전기 대비 당기 증감률이 큰 계정을 찾아낸다. ratios.py의
표준 8개 비율과 달리, 회사가 실제로 공시한 모든 개별 계정(수십~수백 개)을
대상으로 훑는다는 점이 다르다.

자본변동표는 제외한다 — 같은 계정(예: 자본총계)이 기초자본/배당/당기순이익
반영 등 여러 행에서 반복 등장하는 구조라(ratios.py의 sj_nm 스코핑과 동일한
이유), "전기 대비 당기 증감"이라는 단순 비교가 성립하지 않는다.
"""

from __future__ import annotations

import math

import pandas as pd

# 자본변동표는 제외 (모듈 docstring 참고)
SCREENING_STATEMENTS = frozenset({"재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표"})

# 정렬 1순위(재무제표구분): 재무상태표 -> 손익계산서/포괄손익계산서 -> 현금흐름표 순.
# 회사에 따라 손익계산서/포괄손익계산서 중 하나만 쓰므로 같은 순위로 묶는다.
_STATEMENT_ORDER = {"재무상태표": 0, "손익계산서": 1, "포괄손익계산서": 1, "현금흐름표": 2}

SCREENING_COLUMNS = [
    "재무제표구분",
    "계정명",
    "전기금액",
    "당기금액",
    "증감액",
    "증감률(%)",
    "구분",
]

STATUS_NORMAL = "증감률초과"
STATUS_NEW = "신규계정"
STATUS_SIGN_FLIP = "부호전환"


def _pivot_prior_current(long_df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """(sj_nm, account_nm)별 전기/당기 금액을 뽑는다.

    같은 (sj_nm, account_nm) 조합이 같은 기간에 서로 다른 금액으로 나타나면(내부
    충돌 — long_df에는 계정 위계 정보가 없어 이름만으로 구분하는 한계상 드물게
    발생 가능), 임의로 하나를 택하지 않고 그 계정을 제외한다(ratios.py의
    ambiguous-match 방어와 동일한 원칙: 판단 근거가 없으면 추정하지 않는다).

    반환: (계정 x [전기, 당기] 금액 데이터프레임(index=[sj_nm, account_nm]),
           충돌로 제외된 계정 설명 목록)
    """
    scoped = long_df[
        long_df["sj_nm"].isin(SCREENING_STATEMENTS) & long_df["period"].isin(["전기", "당기"])
    ]
    if scoped.empty:
        return pd.DataFrame(columns=["전기", "당기"]), []

    grouped = scoped.groupby(["sj_nm", "account_nm", "period"])["amount"]
    conflicts = grouped.nunique(dropna=False)
    conflict_keys = set(conflicts[conflicts > 1].index.droplevel("period"))

    excluded_notes = [
        f"[{sj_nm}] {account_nm}: 동일 계정명으로 매칭된 금액이 서로 달라 스크리닝에서 제외됨"
        for sj_nm, account_nm in sorted(conflict_keys)
    ]

    clean = scoped[
        ~scoped.set_index(["sj_nm", "account_nm"]).index.isin(conflict_keys)
    ]

    wide = clean.pivot_table(
        index=["sj_nm", "account_nm"], columns="period", values="amount", aggfunc="first"
    )
    for col in ("전기", "당기"):
        if col not in wide.columns:
            wide[col] = math.nan

    return wide[["전기", "당기"]], excluded_notes


def _classify(prior: float, current: float) -> tuple[float, str]:
    """(증감률 또는 NaN, 상태) 반환. 상태가 신규계정/부호전환이면 증감률은 NaN."""
    if math.isnan(prior) or math.isnan(current):
        return math.nan, STATUS_NORMAL  # 한쪽 기간에 계정 자체가 없음 -> 비교 불가, 뒤에서 걸러짐

    if prior == 0:
        if current == 0:
            return math.nan, STATUS_NORMAL
        return math.nan, STATUS_NEW

    if (prior > 0) != (current > 0):
        return math.nan, STATUS_SIGN_FLIP

    return (current - prior) / abs(prior) * 100, STATUS_NORMAL


def build_screening_df(
    long_df: pd.DataFrame,
    total_assets: float,
    threshold_pct: float = 10.0,
    strong_threshold_pct: float = 30.0,
    materiality_pct: float = 1.0,
) -> tuple[pd.DataFrame, list[str]]:
    """전기 대비 당기 증감 스크리닝 결과를 만든다.

    포함 조건:
      - 중요성 필터 통과: max(|전기|, |당기|) >= 자산총계 x materiality_pct% (소액 계정 노이즈 제외)
      - 그리고 (신규계정 또는 부호전환) 또는 |증감률| > threshold_pct

    반환: (SCREENING_COLUMNS 기준 데이터프레임 — 재무제표구분(재무상태표 ->
           손익계산서/포괄손익계산서 -> 현금흐름표) 순으로 먼저 묶고, 그 안에서
           증감액 절대값 내림차순 정렬, 내부 계정명 충돌로 제외된 항목 설명 목록)
    """
    wide, excluded_notes = _pivot_prior_current(long_df)
    if wide.empty or math.isnan(total_assets) or total_assets == 0:
        return pd.DataFrame(columns=SCREENING_COLUMNS), excluded_notes

    materiality_floor = abs(total_assets) * materiality_pct / 100

    rows = []
    for (sj_nm, account_nm), row in wide.iterrows():
        prior, current = row["전기"], row["당기"]
        if math.isnan(prior) or math.isnan(current):
            continue

        if max(abs(prior), abs(current)) < materiality_floor:
            continue

        change_pct, status = _classify(prior, current)

        if status == STATUS_NORMAL:
            if math.isnan(change_pct) or abs(change_pct) <= threshold_pct:
                continue

        rows.append(
            {
                "재무제표구분": sj_nm,
                "계정명": account_nm,
                "전기금액": prior,
                "당기금액": current,
                "증감액": current - prior,
                "증감률(%)": change_pct,
                "구분": status,
            }
        )

    result = pd.DataFrame(rows, columns=SCREENING_COLUMNS)
    if not result.empty:
        statement_rank = result["재무제표구분"].map(_STATEMENT_ORDER)
        sort_key = pd.DataFrame(
            {"statement_rank": statement_rank, "abs_change": result["증감액"].abs()}
        )
        order = sort_key.sort_values(
            ["statement_rank", "abs_change"], ascending=[True, False]
        ).index
        result = result.reindex(order).reset_index(drop=True)

    # strong_threshold_pct는 계산에는 안 쓰이고 엑셀 조건부 서식(노란색 강조)
    # 임계값으로 excel_export.py에서 참조한다. 함수 시그니처에 남겨 호출부가
    # 두 임계값을 한 곳(build_screening_df 호출)에서 관리할 수 있게 한다.
    del strong_threshold_pct

    return result, excluded_notes
