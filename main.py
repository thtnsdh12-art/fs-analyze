"""Phase 1 CLI: DART 감사보고서 링크 -> 회사명/사업연도/3개년 재무제표 출력.

사용법:
    python main.py "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230330001234"
    python main.py "<링크>" --fs-div CFS   # 연결재무제표 기준
"""

import argparse
import re
import sys
from pathlib import Path

import requests

from src import dart_client
from src.excel_export import build_workbook
from src.financials import pivot_wide, to_long_format
from src.link_parser import InvalidDartLinkError, extract_rcept_no
from src.ratios import compute_ratios, get_bs_chart_items, standardize_accounts
from src.resolver import ResolveError, resolve_disclosure

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(corp_name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("_", corp_name).strip()


def _fs_div_label(fs_div: str) -> str:
    return "연결" if fs_div == "CFS" else "별도"

# DART API 호출 과정(공시검색/재무제표 조회)에서 발생 가능한 오류를 한 곳에서
# 사용자 친화적으로 처리하기 위한 튜플. DartApiError=API 응답 오류,
# RuntimeError=config.require_api_key()의 DART_API_KEY 미설정 오류,
# requests.RequestException=네트워크 연결 실패.
API_ERRORS = (dart_client.DartApiError, RuntimeError, requests.RequestException)


def run(url: str, fs_div: str = "OFS", output_dir: str = ".") -> None:
    try:
        rcept_no = extract_rcept_no(url)
    except InvalidDartLinkError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"접수번호(rcept_no): {rcept_no}")

    try:
        info = resolve_disclosure(rcept_no)
    except ResolveError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
    except API_ERRORS as e:
        print(f"[오류] DART API 호출 중 문제가 발생했습니다: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"회사명: {info['corp_name']} (corp_code={info['corp_code']})")
    print(f"공시서류명: {info['report_nm']}")
    print(f"사업연도(추정): {info['bsns_year']}")

    try:
        raw_df = dart_client.fetch_financial_statements(
            corp_code=info["corp_code"],
            bsns_year=info["bsns_year"],
            reprt_code=info["reprt_code"],
            fs_div=fs_div,
        )
    except API_ERRORS as e:
        print(f"[오류] DART API 호출 중 문제가 발생했습니다: {e}", file=sys.stderr)
        sys.exit(1)

    if raw_df.empty:
        print(
            "[경고] 재무제표 데이터를 가져오지 못했습니다. "
            "사업연도 추정이 잘못되었거나 해당 연도 사업보고서가 없을 수 있습니다."
        )
        return

    long_df = to_long_format(raw_df)
    wide_df = pivot_wide(long_df)

    missing = long_df[long_df["amount"].isna()]
    if not missing.empty:
        print(f"\n[경고] 금액 파싱 실패 계정 {len(missing)}건 (공란 처리됨):")
        print(missing[["period", "account_nm"]].drop_duplicates().to_string(index=False))

    print("\n=== 3개년 재무제표 (단위: 원) ===")
    print(wide_df.to_string())

    ratio_df, missing_accounts, derived_notes = compute_ratios(long_df)
    accounts_wide, _, _ = standardize_accounts(long_df)
    bs_item_df, bs_missing_items = get_bs_chart_items(accounts_wide)

    if bs_missing_items:
        print(
            f"\n[경고] 다음 재무상태표 항목을 하나 이상의 기간에서 찾지 못해 "
            f"그래프에서 공란 처리되었습니다 (임의 추정하지 않음): {', '.join(bs_missing_items)}"
        )

    if missing_accounts:
        print(
            f"\n[경고] 다음 표준계정을 하나 이상의 기간에서 찾지 못해 "
            f"관련 비율이 공란 처리되었습니다 (임의 추정하지 않음): {', '.join(missing_accounts)}"
        )
    if derived_notes:
        print("\n[안내] 파생 계산된 항목:")
        for note in derived_notes:
            print(f"  - {note}")

    print("\n=== 3개년 재무비율 (단위: %) ===")
    print(ratio_df.to_string(float_format=lambda v: f"{v:,.2f}"))

    print(
        "\n[면책] 본 결과는 참고용 사전분석 자료이며 감사의견 형성의 유일한 근거가 될 수 없습니다."
    )

    wb = build_workbook(
        info,
        fs_div,
        wide_df,
        ratio_df,
        missing_accounts,
        derived_notes,
        bs_item_df,
        bs_missing_items,
    )
    fs_label = _fs_div_label(fs_div)
    excel_path = Path(output_dir) / f"{_safe_filename(info['corp_name'])}_{fs_label}_결과.xlsx"
    wb.save(excel_path)
    print(f"\n재무제표/재무비율/그래프를 엑셀로 저장했습니다: {excel_path}")


def main() -> None:
    # Windows 콘솔은 활성 코드페이지가 UTF-8(65001)이어도 Python이 로케일 기반으로
    # stdout/stderr 인코딩을 cp949 등으로 잡아 한글 출력이 깨지는 경우가 있다.
    # 명시적으로 UTF-8로 재설정해 에러 메시지가 사용자에게 올바르게 표시되도록 한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="DART 감사보고서 링크로 3개년 재무제표를 조회한다."
    )
    parser.add_argument("url", help="DART 감사보고서/사업보고서 뷰어 링크")
    parser.add_argument(
        "--fs-div",
        choices=["OFS", "CFS"],
        default="OFS",
        help="OFS=개별/별도재무제표(기본값), CFS=연결재무제표",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=".",
        help="'{회사명}_결과.xlsx' 파일을 저장할 디렉터리 (기본값: 현재 디렉터리)",
    )
    args = parser.parse_args()
    run(args.url, fs_div=args.fs_div, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
