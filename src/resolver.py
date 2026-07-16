"""rcept_no -> corp_code / corp_name / bsns_year / reprt_code 역산 로직.

DART는 rcept_no를 corp_code로 직접 변환해주는 API를 제공하지 않는다.
대신 rcept_no의 앞 8자리가 접수일자(YYYYMMDD)라는 규약을 이용해,
공시검색(list.json)에서 해당 일자의 공시 목록을 조회한 뒤 rcept_no가
일치하는 항목의 corp_code/corp_name/report_nm을 가져온다.
"""

import re

from . import dart_client

DEFAULT_REPRT_CODE = "11011"  # 사업보고서(연간) - 당기/전기/전전기 동시 확보


class ResolveError(RuntimeError):
    pass


def resolve_disclosure(rcept_no: str) -> dict:
    if not re.fullmatch(r"\d{14}", rcept_no):
        raise ResolveError(f"올바르지 않은 rcept_no 형식입니다: {rcept_no}")

    filing_date = rcept_no[:8]
    disclosures = dart_client.search_disclosures(bgn_de=filing_date, end_de=filing_date)

    if disclosures.empty or "rcept_no" not in disclosures.columns:
        raise ResolveError(
            f"{filing_date}일자 공시 목록이 비어 있어 rcept_no={rcept_no}를 "
            "찾지 못했습니다. 접수일자 산정 로직을 확인하세요."
        )

    match = disclosures[disclosures["rcept_no"] == rcept_no]
    if match.empty:
        raise ResolveError(
            f"rcept_no={rcept_no}가 {filing_date}일자 공시 목록에 없습니다. "
            "링크가 올바른 DART 공시 뷰어 링크인지 확인하세요."
        )

    row = match.iloc[0]
    report_nm = row.get("report_nm", "") or ""
    bsns_year = _infer_bsns_year(report_nm, filing_date)

    return {
        "rcept_no": rcept_no,
        "corp_code": row["corp_code"],
        "corp_name": row["corp_name"],
        "report_nm": report_nm,
        "bsns_year": bsns_year,
        "reprt_code": DEFAULT_REPRT_CODE,
    }


def _infer_bsns_year(report_nm: str, filing_date: str) -> str:
    """공시서류명에서 사업연도를 추출한다.

    예: "감사보고서 (2023.12)" -> "2023", "사업보고서 (2022.12)" -> "2022"
    서류명에 연도가 없으면 접수월 기준으로 추정한다(12월 결산법인은 통상
    익년 1~3월에 감사보고서/사업보고서를 제출하므로 접수연도-1을 우선 시도).
    """
    year_month_match = re.search(r"(20\d{2})[.\-]\s*(?:12|1[0-2])", report_nm)
    if year_month_match:
        return year_month_match.group(1)

    any_year_match = re.search(r"(20\d{2})", report_nm)
    if any_year_match:
        return any_year_match.group(1)

    filing_year = int(filing_date[:4])
    filing_month = int(filing_date[4:6])
    return str(filing_year - 1) if filing_month <= 6 else str(filing_year)
