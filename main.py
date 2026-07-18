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

from src import config, dart_client, doc_tree, industry_detect, verification
from src.excel_export import build_workbook
from src.financials import pivot_wide, to_long_format
from src.link_parser import InvalidDartLinkError, extract_dcm_no, extract_rcept_no
from src.ratios import (
    compute_ratios,
    format_blank_reason_notes,
    get_bs_chart_items,
    standardize_accounts,
)
from src.resolver import ResolveError, resolve_disclosure

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(corp_name: str) -> str:
    return _INVALID_FILENAME_CHARS.sub("_", corp_name).strip()


def _fs_div_label(fs_div: str) -> str:
    return "연결" if fs_div == "CFS" else "별도"

# DART API 호출 과정(공시검색/재무제표 조회)에서 발생 가능한 오류를 한 곳에서
# 사용자 친화적으로 처리하기 위한 튜플. DartApiError=API 응답 오류,
# ConfigError=config.require_api_key()의 DART_API_KEY 미설정 오류,
# requests.RequestException=네트워크 연결 실패.
# 일반 RuntimeError는 일부러 잡지 않는다 — 여기서 잡으면 이 코드와 무관한 예상치
# 못한 런타임 오류까지 "API 호출 문제"로 오분류되어 원인 파악이 어려워지기 때문.
API_ERRORS = (dart_client.DartApiError, config.ConfigError, requests.RequestException)


def run(url: str, fs_div: str | None = None, output_dir: str = ".") -> None:
    try:
        rcept_no = extract_rcept_no(url)
    except InvalidDartLinkError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
    dcm_no = extract_dcm_no(url)

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

    # 사용자가 --fs-div를 명시하지 않았고 링크에 dcmNo가 있으면, 그 dcmNo가 가리키는
    # 첨부문서명("감사보고서" vs "연결감사보고서")으로 연결/별도를 추정한다. 이 추정은
    # DART 공식 API가 아니라 공개 뷰어 페이지를 읽는 방식이라 실패할 수 있는데, 실패해도
    # doc_tree.guess_fs_div가 (None, None)을 반환하므로 아래 CFS 우선 자동판별로 안전하게
    # 넘어간다.
    fs_div_hint, hint_title = (None, None)
    if fs_div is None and dcm_no:
        fs_div_hint, hint_title = doc_tree.guess_fs_div(rcept_no, dcm_no)
        if fs_div_hint:
            print(
                f"[안내] 링크가 가리키는 문서('{hint_title}')를 기준으로 "
                f"{_fs_div_label(fs_div_hint)}재무제표를 우선 조회합니다."
            )

    try:
        raw_df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
            corp_code=info["corp_code"],
            bsns_year=info["bsns_year"],
            reprt_code=info["reprt_code"],
            fs_div_override=fs_div,
            fs_div_hint=fs_div_hint,
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

    fs_note = ""
    if fell_back:
        requested = fs_div or fs_div_hint or "CFS"
        fs_note = (
            f"{_fs_div_label(requested)}재무제표가 공시되어 있지 않아 "
            f"{_fs_div_label(fs_div_used)}재무제표로 자동 전환됨"
        )
        print(f"\n[안내] {fs_note}.")
    elif fs_div_hint:
        fs_note = f"링크가 가리키는 문서('{hint_title}') 기준으로 자동 선택됨"
    print(f"재무제표 기준: {_fs_div_label(fs_div_used)}재무제표({fs_div_used})")

    long_df = to_long_format(raw_df)
    wide_df = pivot_wide(long_df)

    financial_markers = industry_detect.detect_financial_industry(long_df)
    if financial_markers:
        print("\n" + "=" * 70)
        print("⚠️  이 회사는 금융업(은행/보험/지주 등)으로 추정됩니다.")
        print(
            "본 도구의 표준 재무비율(유동비율 등)은 일반 기업 기준으로 설계되어 "
            "있어 다수 지표가 공란 처리될 수 있습니다."
        )
        print(
            "금융업종은 예대율/BIS비율 등 별도 지표가 필요하며, 본 도구는 "
            "현재 이를 지원하지 않습니다."
        )
        print(f"(감지된 금융업 특유 계정: {', '.join(financial_markers)})")
        print("=" * 70)

    missing = long_df[long_df["amount"].isna()]
    if not missing.empty:
        print(f"\n[경고] 금액 파싱 실패 계정 {len(missing)}건 (공란 처리됨):")
        print(missing[["period", "account_nm"]].drop_duplicates().to_string(index=False))

    print("\n=== 3개년 재무제표 (단위: 원) ===")
    print(wide_df.to_string())

    ratio_df, missing_accounts, derived_notes, ambiguous_matches, blank_reasons = compute_ratios(
        long_df
    )
    accounts_wide, _, _, _ = standardize_accounts(long_df)
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
    if ambiguous_matches:
        print(
            "\n[경고] 동일 계정코드/계정명으로 매칭된 금액이 서로 달라 공란 처리된 항목 "
            "(임의로 값을 선택하지 않음):"
        )
        for note in ambiguous_matches:
            print(f"  - {note}")
    if derived_notes:
        print("\n[안내] 파생 계산된 항목:")
        for note in derived_notes:
            print(f"  - {note}")

    print("\n=== 3개년 재무비율 (단위: %) ===")
    print(ratio_df.to_string(float_format=lambda v: f"{v:,.2f}"))

    ratio_periods = [c for c in ratio_df.columns if c != "전기대비증감률(%)"]
    blank_reason_notes = format_blank_reason_notes(blank_reasons, ratio_periods)
    if blank_reason_notes:
        print("\n[안내] 공란 처리된 비율의 사유:")
        for note in blank_reason_notes:
            print(f"  - {note}")

    print(
        "\n[면책] 본 결과는 참고용 사전분석 자료이며 감사의견 형성의 유일한 근거가 될 수 없습니다."
    )

    # ratios.py 계산 로직과 완전히 별개의 코드로 재계산해 대사하고, 재무상태표 등식
    # (자산=부채+자본 등)이 성립하는지 확인한다. 결과는 엑셀 "검증" 시트에도 동일하게 남는다.
    ratio_checks = verification.verify_ratios(accounts_wide, ratio_df)
    bs_checks = verification.verify_balance_sheet_identity(accounts_wide)
    all_checks = ratio_checks + bs_checks
    failed_checks = [c for c in all_checks if not c.ok]
    if failed_checks:
        print(
            f"\n[경고] 독립 검증 결과 불일치 {len(failed_checks)}건 발견 "
            f"(전체 {len(all_checks)}건 중) — 엑셀 '검증' 시트에서 상세 확인 필요:"
        )
        for c in failed_checks:
            print(f"  - [{c.period}] {c.label}: 보고값={c.expected:,.2f} 재계산값={c.actual:,.2f}")
    else:
        print(f"\n[검증] 독립 재계산 대사 + 재무상태표 등식 {len(all_checks)}건 모두 일치")

    wb = build_workbook(
        info,
        fs_div_used,
        wide_df,
        ratio_df,
        missing_accounts,
        derived_notes,
        bs_item_df,
        bs_missing_items,
        accounts_wide,
        fs_note=fs_note,
        financial_markers=financial_markers,
        blank_reasons=blank_reasons,
    )
    fs_label = _fs_div_label(fs_div_used)
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
        default=None,
        help=(
            "OFS=개별/별도재무제표, CFS=연결재무제표. "
            "생략 시 자동: 연결재무제표를 먼저 시도하고, 연결 대상 종속기업이 없어 "
            "연결재무제표가 없는 회사는 별도재무제표로 자동 전환됨"
        ),
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
