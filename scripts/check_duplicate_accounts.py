"""여러 회사의 DART 재무제표에서 account_id 중복 매칭 케이스가 실제로 존재하는지 진단한다.

`src/ratios.py`의 `_match_amount()`는 같은 기간에 동일 account_id를 가진 행이 여러 개면,
값이 전부 같을 때만 안전하게 그 값을 쓰고 값이 다르면 공란+경고로 처리한다(임의로 첫
값을 택하지 않음). 이 스크립트는 그 방어 로직이 실제로 필요한 상황인지 — 즉 실제 DART
데이터에서 동일 account_id 중복이 얼마나 자주 나타나는지, 그중 값이 실제로 충돌하는
케이스가 있는지 — 여러 회사를 순회하며 확인하기 위한 진단용 스크립트다. 프로덕션 실행
경로(main.py)와는 무관하다.

사용법:
    python scripts/check_duplicate_accounts.py 00126380 00164779 00537221
    python scripts/check_duplicate_accounts.py 00126380 --year 2024 --fs-div OFS
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src import config, dart_client  # noqa: E402
from src.financials import to_long_format  # noqa: E402

_DUP_COLUMNS = [
    "corp_code",
    "fs_div",
    "period",
    "sj_nm",
    "account_id",
    "count",
    "n_unique_amounts",
    "conflicting",
    "account_nms",
    "amounts",
]
_DUP_RESULT_COLUMNS = _DUP_COLUMNS[2:]  # corp_code/fs_div는 check_corp에서 나중에 붙인다


def find_duplicate_account_ids(long_df: pd.DataFrame) -> pd.DataFrame:
    """한 기간·한 재무제표(sj_nm) 내에 동일 account_id가 2건 이상 나타나는 케이스를 찾는다.

    주의(실측으로 확인된 함정): DART 응답은 재무상태표/손익계산서/현금흐름표/자본변동표를
    구분 없이 한 테이블에 섞어서 주는데, 자본변동표는 구조상 "자본총계"/"당기순이익" 같은
    account_id를 기초자본/배당/당기순이익반영/기말자본 등 여러 행에서 재사용한다 — 이건
    정상이고 오류가 아니다. sj_nm으로 먼저 묶지 않고 (period, account_id)만으로 묶으면
    이런 자본변동표 재사용을 전부 "충돌"로 오판하는 대량의 가짜 양성이 나온다(실측 SK
    하이닉스 CFS에서 확인됨). 그래서 반드시 (period, sj_nm, account_id)로 묶는다 —
    ratios.py의 standardize_accounts()가 sj_nm으로 매칭 대상을 좋히는 것과 동일한 원리다.

    ratios.py는 표준화 대상 계정(ACCOUNT_ALIASES) 8~12개만 검사하지만, 이 함수는
    회사가 공시한 모든 계정(수십~수백 개)을 대상으로 훑어 표준화 범위 밖의 계정에서도
    같은 문제가 있는지 넓게 확인한다.
    """
    # DART는 표준 IFRS 코드가 없는 계정의 account_id에 "-표준계정코드 미사용-"라는 고정
    # 플레이스홀더 문자열을 그대로 넣는다. 이건 실제 계정코드가 아니라 "코드 없음"이라는
    # 표시라, 서로 무관한 계정 수십 개가 이 문자열을 동일하게 공유한다 — 진짜 중복
    # account_id가 아니므로 진단 대상에서 제외한다(ratios.py의 account_id 매칭도 실제
    # IFRS 코드만 검사하므로 이 플레이스홀더에는 애초에 영향받지 않음).
    _NO_STANDARD_CODE = "-표준계정코드 미사용-"

    df = long_df[
        long_df["account_id"].notna()
        & long_df["account_id"].ne("")
        & long_df["account_id"].ne(_NO_STANDARD_CODE)
    ].copy()
    if df.empty:
        return pd.DataFrame(columns=_DUP_RESULT_COLUMNS)

    rows = []
    for (period, sj_nm, account_id), group in df.groupby(["period", "sj_nm", "account_id"]):
        if len(group) <= 1:
            continue
        n_unique = group["amount"].nunique(dropna=False)
        rows.append(
            {
                "period": period,
                "sj_nm": sj_nm,
                "account_id": account_id,
                "count": len(group),
                "n_unique_amounts": n_unique,
                "conflicting": n_unique > 1,
                "account_nms": ", ".join(group["account_nm"].astype(str).tolist()),
                "amounts": ", ".join(str(v) for v in group["amount"].tolist()),
            }
        )
    return pd.DataFrame(rows, columns=_DUP_RESULT_COLUMNS)


def check_corp(corp_code: str, bsns_year: str, reprt_code: str, fs_div: str) -> pd.DataFrame:
    raw_df = dart_client.fetch_financial_statements(corp_code, bsns_year, reprt_code, fs_div=fs_div)
    if raw_df.empty:
        return pd.DataFrame(columns=_DUP_COLUMNS)

    long_df = to_long_format(raw_df)
    dup_df = find_duplicate_account_ids(long_df)
    if dup_df.empty:
        return pd.DataFrame(columns=_DUP_COLUMNS)

    dup_df.insert(0, "fs_div", fs_div)
    dup_df.insert(0, "corp_code", corp_code)
    return dup_df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="여러 회사의 DART 재무제표에서 account_id 중복 매칭 케이스를 진단한다."
    )
    parser.add_argument("corp_codes", nargs="+", help="점검할 DART corp_code 목록 (공백으로 구분)")
    parser.add_argument("--year", default="2025", help="사업연도 (기본값: 2025)")
    parser.add_argument(
        "--reprt-code", default="11011", help="보고서 코드 (기본값: 11011=사업보고서/연간)"
    )
    parser.add_argument(
        "--fs-div",
        choices=["OFS", "CFS", "BOTH"],
        default="BOTH",
        help="점검할 재무제표 기준 (기본값: BOTH=연결+별도 모두 점검)",
    )
    args = parser.parse_args()

    try:
        config.require_api_key()
    except config.ConfigError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)

    fs_divs = ["CFS", "OFS"] if args.fs_div == "BOTH" else [args.fs_div]

    results: list[pd.DataFrame] = []
    for corp_code in args.corp_codes:
        for fs_div in fs_divs:
            try:
                dup_df = check_corp(corp_code, args.year, args.reprt_code, fs_div)
            except (dart_client.DartApiError, config.ConfigError) as e:
                print(f"[오류] corp_code={corp_code} fs_div={fs_div}: {e}", file=sys.stderr)
                continue
            if not dup_df.empty:
                results.append(dup_df)

    if not results:
        print("중복 account_id 케이스가 발견되지 않았습니다 (점검한 모든 회사/기간).")
        return

    combined = pd.concat(results, ignore_index=True)
    conflicting = combined[combined["conflicting"]]

    print(f"=== 전체 중복 account_id 케이스 {len(combined)}건 (단순 중복 포함, 재무제표별로 구분됨) ===")
    print(
        combined[
            ["corp_code", "fs_div", "period", "sj_nm", "account_id", "count", "n_unique_amounts", "conflicting"]
        ].to_string(index=False)
    )

    print()
    if conflicting.empty:
        print("값이 실제로 충돌하는(conflicting) 케이스는 없습니다 — 전부 단순 중복 행입니다.")
    else:
        print(f"⚠ 값이 서로 다른(conflicting) 케이스 {len(conflicting)}건 발견 — ratios.py가 공란+경고로 처리해야 하는 대상:")
        print(conflicting.to_string(index=False))


if __name__ == "__main__":
    main()
