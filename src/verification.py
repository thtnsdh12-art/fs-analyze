"""엑셀을 만들 때마다 자동으로 도는 독립 검증(대사) 절차.

지금까지 대사 검증(비율을 별도 코드로 재계산해서 비교, 재무상태표 등식 확인)을
회계사가 요청할 때마다 임시 스크립트로 수작업 실행해왔는데, 이걸 매 실행마다
자동으로 돌아가도록 파이프라인에 내장한다.

핵심 원칙: 여기서 쓰는 계산식은 ratios.py의 compute_ratios와 "완전히 독립된" 코드로
다시 짠다. 같은 함수를 두 번 호출해 비교하면 그 함수 자체에 버그가 있을 때 못 잡기
때문에, 일부러 로직을 중복 작성해 서로 다른 경로로 같은 결론에 도달하는지 확인한다.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pandas as pd

# 부동소수점 연산 오차만 허용하는 엄격한 허용오차(비율, %) — ratios.py와 계산식이
# 다르면 이 수준에서 이미 어긋난다.
RATIO_TOLERANCE = 1e-6
# 원 단위 항등식은 DART 원본 데이터 자체가 정수(원)이므로 1원 미만 오차만 허용한다.
AMOUNT_TOLERANCE = 1.0


class CheckResult(NamedTuple):
    label: str
    period: str
    expected: float
    actual: float
    ok: bool


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _independent_ratio_pct(numerator: float, denominator: float) -> float:
    """ratios.py의 _safe_div와 별개로 새로 짠 나눗셈(0/NaN 방어만 동일한 관례 적용)."""
    if _is_missing(numerator) or _is_missing(denominator) or denominator == 0:
        return math.nan
    return numerator / denominator * 100


# 비율명 -> (분자 표준계정명, 분모 표준계정명). ratios.compute_ratios가 참조하는
# 표와 별개로 여기서 다시 정의한다(같은 딕셔너리를 재사용하면 그 딕셔너리 자체가
# 잘못됐을 때 못 잡는다).
_RATIO_DEFINITIONS: dict[str, tuple[str, str]] = {
    "유동비율": ("유동자산", "유동부채"),
    "부채비율": ("부채총계", "자본총계"),
    "자기자본비율": ("자본총계", "자산총계"),
}


def verify_ratios(accounts_wide: pd.DataFrame, ratio_df: pd.DataFrame) -> list[CheckResult]:
    """유동비율/부채비율/자기자본비율을 독립 코드로 재계산해 ratio_df와 대사한다.

    ROA/ROE/수익성 비율은 평균 분모 로직(전기 평균) 자체가 재무비율 정의의 일부라
    "독립 재계산"이 사실상 같은 로직 중복이 되어 제외했다 — 대신 재무상태표 계정
    3종(유동비율/부채비율/자기자본비율)은 단순 나눗셈이라 완전히 독립적으로 검증 가능하다.
    """
    results: list[CheckResult] = []
    periods = [p for p in ratio_df.columns if p in accounts_wide.columns]

    for ratio_name, (num_name, den_name) in _RATIO_DEFINITIONS.items():
        if ratio_name not in ratio_df.index:
            continue
        for period in periods:
            numerator = (
                accounts_wide.loc[num_name, period] if num_name in accounts_wide.index else math.nan
            )
            denominator = (
                accounts_wide.loc[den_name, period] if den_name in accounts_wide.index else math.nan
            )
            recomputed = _independent_ratio_pct(numerator, denominator)
            reported = ratio_df.loc[ratio_name, period]

            if _is_missing(recomputed) and _is_missing(reported):
                continue  # 둘 다 결측 = 계정 매핑 실패로 이미 별도 경고가 뜨는 케이스

            ok = (
                not _is_missing(recomputed)
                and not _is_missing(reported)
                and abs(recomputed - reported) < RATIO_TOLERANCE
            )
            results.append(CheckResult(ratio_name, period, reported, recomputed, ok))

    return results


# 항등식명 -> (합계 표준계정명, [구성요소 표준계정명들])
_IDENTITIES: list[tuple[str, str, list[str]]] = [
    ("자산총계 = 부채총계 + 자본총계", "자산총계", ["부채총계", "자본총계"]),
    ("자산총계 = 유동자산 + 비유동자산", "자산총계", ["유동자산", "비유동자산"]),
]


def verify_balance_sheet_identity(accounts_wide: pd.DataFrame) -> list[CheckResult]:
    """재무상태표 항등식이 실제로 성립하는지 확인한다.

    이건 계산 로직 검증이라기보다 원천 데이터(및 standardize_accounts의 매핑/파생
    계산) 자체의 정합성 확인이다 — 만약 어긋난다면 표준화 로직이나 DART 원본
    데이터에 문제가 있다는 뜻이다.
    """
    results: list[CheckResult] = []
    for label, total_name, part_names in _IDENTITIES:
        if total_name not in accounts_wide.index:
            continue
        for period in accounts_wide.columns:
            total = accounts_wide.loc[total_name, period]
            if _is_missing(total):
                continue

            parts_available = all(
                name in accounts_wide.index and not _is_missing(accounts_wide.loc[name, period])
                for name in part_names
            )
            if not parts_available:
                continue

            part_sum = sum(accounts_wide.loc[name, period] for name in part_names)
            ok = abs(total - part_sum) < AMOUNT_TOLERANCE
            results.append(CheckResult(label, period, total, part_sum, ok))

    return results


# screening.py의 SCREENING_STATEMENTS와 같은 재무제표 범위를 가리키지만, 이 값을
# import해서 재사용하지 않고 독립적으로 다시 선언한다 — screening.py 쪽 상수 자체가
# 잘못됐을 경우(예: 실수로 자본변동표를 포함시킴)까지 잡아내기 위해서다.
_SCREENING_STATEMENTS_INDEPENDENT = frozenset(
    {"재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표"}
)
_SCREENING_STATUS_NEW = "신규계정"
_SCREENING_STATUS_SIGN_FLIP = "부호전환"
_SCREENING_STATUS_NORMAL = "정상"


def _extract_amount_independent(
    long_df: pd.DataFrame, sj_nm: str, account_nm: str, period: str
) -> float:
    """screening.py의 groupby/pivot_table과 다른 방식(불리언 마스크 + .loc)으로
    long_df 원본에서 금액을 직접 뽑는다. 같은 키에 서로 다른 값이 있으면(내부
    충돌) 판단 근거가 없으므로 NaN을 반환한다(임의 선택하지 않음).
    """
    hits = (
        long_df.loc[
            (long_df["sj_nm"] == sj_nm)
            & (long_df["account_nm"] == account_nm)
            & (long_df["period"] == period),
            "amount",
        ]
        .dropna()
        .unique()
    )
    if len(hits) != 1:
        return math.nan
    return float(hits[0])


def _independent_change_pct_and_status(prior: float, current: float) -> tuple[float, str | None]:
    """screening.py의 _classify()와 별개로 새로 짠 분류 로직.

    반환: (증감률 또는 NaN, 상태). 전기·당기가 둘 다 0이면(변동 없음) 상태는
    None(스크리닝 대상 자체가 아님)을 반환한다.
    """
    if prior == 0:
        if current == 0:
            return math.nan, None
        return math.nan, _SCREENING_STATUS_NEW
    if (prior > 0) != (current > 0):
        return math.nan, _SCREENING_STATUS_SIGN_FLIP
    return (current - prior) / abs(prior) * 100, _SCREENING_STATUS_NORMAL


def verify_screening(
    long_df: pd.DataFrame,
    screening_df: pd.DataFrame,
    total_assets: float,
    threshold_pct: float = 10.0,
    materiality_pct: float = 1.0,
) -> list[CheckResult]:
    """전기 대비 당기 증감 스크리닝(screening.build_screening_df) 결과를 독립 코드로 대사한다.

    네 가지를 확인한다:
      1) 스크리닝에 포함된 계정의 전기/당기 금액이 long_df 원본과 정확히 일치하는지
         (표준화·파생 계산을 거치지 않은 원본 그대로인지)
      2) 포함된 계정의 증감률이 (당기-전기)/|전기|*100 공식으로 재계산했을 때 일치하는지
      3) 신규계정/부호전환으로 분류된 계정이 실제로 그 조건을 만족하는지
      4) (전수 검사) long_df 전체를 훑어, 포함됐어야 할 계정이 빠지지 않았는지(누락)
         / 기준 미달인데 잘못 포함된 계정은 없는지(오탐) 확인
    """
    results: list[CheckResult] = []
    if _is_missing(total_assets) or total_assets == 0:
        return results
    materiality_floor = abs(total_assets) * materiality_pct / 100

    screening_index = {
        (row["재무제표구분"], row["계정명"]): row for _, row in screening_df.iterrows()
    }

    # 1)~3): 시트에 실제로 포함된 계정 각각에 대해 원본 금액/증감률/분류를 재확인
    for (sj_nm, account_nm), row in screening_index.items():
        prior_check = _extract_amount_independent(long_df, sj_nm, account_nm, "전기")
        current_check = _extract_amount_independent(long_df, sj_nm, account_nm, "당기")

        results.append(
            CheckResult(
                f"[스크리닝-원본금액] {sj_nm} {account_nm} (전기)",
                "전기",
                row["전기금액"],
                prior_check,
                not _is_missing(prior_check)
                and abs(prior_check - row["전기금액"]) < AMOUNT_TOLERANCE,
            )
        )
        results.append(
            CheckResult(
                f"[스크리닝-원본금액] {sj_nm} {account_nm} (당기)",
                "당기",
                row["당기금액"],
                current_check,
                not _is_missing(current_check)
                and abs(current_check - row["당기금액"]) < AMOUNT_TOLERANCE,
            )
        )

        pct, status = _independent_change_pct_and_status(prior_check, current_check)
        if row["구분"] == _SCREENING_STATUS_NORMAL:
            reported_pct = row["증감률(%)"]
            ok = (
                status == _SCREENING_STATUS_NORMAL
                and not _is_missing(pct)
                and not _is_missing(reported_pct)
                and abs(pct - reported_pct) < RATIO_TOLERANCE
            )
            results.append(
                CheckResult(
                    f"[스크리닝-증감률] {sj_nm} {account_nm}", "전기→당기", reported_pct, pct, ok
                )
            )
        else:
            ok = status == row["구분"]
            results.append(
                CheckResult(
                    f"[스크리닝-분류:{row['구분']}] {sj_nm} {account_nm}",
                    "전기→당기",
                    1.0,
                    1.0 if ok else 0.0,
                    ok,
                )
            )

    # 4) 전수 검사: long_df에 등장하는 모든 (sj_nm, account_nm) 조합을 독립적으로
    #    훑어, 스크리닝 결과와 어긋나는 누락/오탐이 있는지 집계한다.
    all_keys = set(
        map(
            tuple,
            long_df.loc[long_df["sj_nm"].isin(_SCREENING_STATEMENTS_INDEPENDENT), ["sj_nm", "account_nm"]]
            .drop_duplicates()
            .to_numpy(),
        )
    )

    missed = 0
    false_positive = 0
    for sj_nm, account_nm in all_keys:
        prior = _extract_amount_independent(long_df, sj_nm, account_nm, "전기")
        current = _extract_amount_independent(long_df, sj_nm, account_nm, "당기")
        in_screening = (sj_nm, account_nm) in screening_index

        if _is_missing(prior) or _is_missing(current):
            if in_screening:
                false_positive += 1
            continue

        if max(abs(prior), abs(current)) < materiality_floor:
            if in_screening:
                false_positive += 1
            continue

        pct, status = _independent_change_pct_and_status(prior, current)
        should_include = status in (_SCREENING_STATUS_NEW, _SCREENING_STATUS_SIGN_FLIP) or (
            status == _SCREENING_STATUS_NORMAL and not _is_missing(pct) and abs(pct) > threshold_pct
        )

        if should_include and not in_screening:
            missed += 1
        elif not should_include and in_screening:
            false_positive += 1

    results.append(
        CheckResult(
            "스크리닝 완전성(포함됐어야 할 계정 누락 없음)",
            "전기→당기",
            0.0,
            float(missed),
            missed == 0,
        )
    )
    results.append(
        CheckResult(
            "스크리닝 정확성(기준 미달 오탐 없음)", "전기→당기", 0.0, float(false_positive), false_positive == 0
        )
    )

    return results
