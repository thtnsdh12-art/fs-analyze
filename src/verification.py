"""엑셀을 만들 때마다 자동으로 도는 독립 검증(대사) 절차.

지금까지 대사 검증(비율을 별도 코드로 재계산해서 비교, 재무상태표 등식 확인)을
회계사가 요청할 때마다 임시 스크립트로 수작업 실행해왔는데, 이걸 매 실행마다
자동으로 돌아가도록 파이프라인에 내장한다.

핵심 원칙: 여기서 쓰는 계산식은 ratios.py의 compute_ratios와 "완전히 독립된" 코드로
다시 짜다. 같은 함수를 두 번 호출해 비교하면 그 함수 자체에 버그가 있을 때 못 잡기
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
# 표와 별개로 여기서 다시 정의한다(같은 딜셔너리를 재사용하면 그 딜셔너리 자체가
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
