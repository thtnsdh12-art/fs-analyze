"""DART Open API 저수준 래퍼.

사용하는 엔드포인트:
  - corpCode.xml         : 전체 회사 고유번호 목록 (zip, 로컬 캐싱)
  - list.json            : 공시검색 (rcept_no -> corp_code/corp_name 역산에 사용)
  - fnlttSinglAcntAll.json: 단일회사 전체 재무제표 (사업보고서 기준 당기/전기/전전기 동시 반환)
"""

import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd
import requests

from . import config

STATUS_OK = "000"
STATUS_NO_DATA = "013"


class DartApiError(RuntimeError):
    pass


def _check_status(payload: dict, context: str) -> None:
    status = payload.get("status")
    if status not in (STATUS_OK, STATUS_NO_DATA):
        message = payload.get("message", "알 수 없는 오류")
        raise DartApiError(f"[{context}] DART API 오류 status={status}: {message}")


def fetch_corp_code_df(force_refresh: bool = False) -> pd.DataFrame:
    """전체 회사 고유번호 목록을 조회한다 (corp_code, corp_name, stock_code, modify_date).

    응답이 zip(CORPCODE.xml)이라 매 호출마다 받기엔 무거우므로 로컬에 CSV로 캐싱하고,
    CORP_CODE_CACHE_TTL_DAYS 이내면 캐시를 재사용한다.
    """
    cache_path = config.CORP_CODE_CACHE_PATH
    if not force_refresh and cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age < timedelta(days=config.CORP_CODE_CACHE_TTL_DAYS):
            return pd.read_csv(cache_path, dtype=str).fillna("")

    resp = requests.get(
        f"{config.DART_BASE_URL}/corpCode.xml",
        params={"crtfc_key": config.require_api_key()},
        timeout=30,
    )
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read("CORPCODE.xml")

    root = ET.fromstring(xml_bytes)
    rows = [
        {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        for item in root.iter("list")
    ]

    df = pd.DataFrame(rows)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    return df


def search_disclosures(
    bgn_de: str,
    end_de: str,
    pblntf_ty: str | None = None,
    corp_code: str | None = None,
    max_pages: int = 20,
) -> pd.DataFrame:
    """공시검색(list.json). 기간 내 공시 목록을 전량 페이징 조회한다.

    rcept_no의 앞 8자리(접수일자)로 bgn_de=end_de를 지정해 호출하면,
    해당일 공시 목록에서 rcept_no가 일치하는 항목을 찾아 corp_code/corp_name을
    역으로 알아낼 수 있다 (resolver.resolve_disclosure에서 사용).
    """
    all_rows: list[dict] = []
    page_no = 1

    while page_no <= max_pages:
        params = {
            "crtfc_key": config.require_api_key(),
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": page_no,
            "page_count": 100,
        }
        if pblntf_ty:
            params["pblntf_ty"] = pblntf_ty
        if corp_code:
            params["corp_code"] = corp_code

        resp = requests.get(f"{config.DART_BASE_URL}/list.json", params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("status") == STATUS_NO_DATA:
            break
        _check_status(payload, "list.json")

        rows = payload.get("list") or []
        all_rows.extend(rows)

        total_page = int(payload.get("total_page", 1) or 1)
        if page_no >= total_page:
            break
        page_no += 1

    return pd.DataFrame(all_rows)


def fetch_financial_statements(
    corp_code: str,
    bsns_year: str,
    reprt_code: str = "11011",
    fs_div: str = "OFS",
) -> pd.DataFrame:
    """단일회사 전체 재무제표(fnlttSinglAcntAll) 조회.

    reprt_code="11011"(사업보고서) 기준으로 호출하면 응답 각 행에 당기(thstrm)/
    전기(frmtrm)/전전기(bfefrmtrm) 금액이 함께 포함되어 3개년을 한 번에 확보할 수 있다.

    fs_div: "OFS"=개별/별도재무제표(기본값), "CFS"=연결재무제표
    해당 fs_div의 재무제표가 없는 회사(예: 연결 대상 종속기업이 없어 CFS 미공시)는
    status="013"(데이터없음)으로 응답하며, 이는 오류가 아니라 빈 DataFrame으로 정상 처리된다.
    """
    params = {
        "crtfc_key": config.require_api_key(),
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    resp = requests.get(
        f"{config.DART_BASE_URL}/fnlttSinglAcntAll.json", params=params, timeout=30
    )
    resp.raise_for_status()
    payload = resp.json()
    _check_status(payload, "fnlttSinglAcntAll.json")
    return pd.DataFrame(payload.get("list") or [])


def fetch_financial_statements_auto(
    corp_code: str,
    bsns_year: str,
    reprt_code: str = "11011",
    fs_div_override: str | None = None,
    fs_div_hint: str | None = None,
) -> tuple[pd.DataFrame, str, bool]:
    """연결/별도 여부를 계정과목 내용으로 추론하지 않고, DART API 응답 자체로 확정한다.

    우선순위:
      1. fs_div_override — 사용자가 --fs-div로 명시한 값. 폴백 없이 그 값만 조회한다.
      2. fs_div_hint — 사용자가 붙여넣은 링크의 dcmNo가 가리키는 첨부문서명(예: "감사보고서"
         vs "연결감사보고서")으로 추정된 값(src.doc_tree). 사용자가 실제로 클릭해서 가져온
         문서이므로 CFS 우선 기본값보다 우선한다. 다만 그 기준의 재무제표가 실제로 없으면
         (예: 링크는 별도였지만 그해 별도재무제표 미공시) 반대쪽으로 자동 폴백한다.
      3. 힌트도 없으면 연결재무제표(CFS)를 먼저 요청하고, 응답이 비어 있으면(연결 대상
         종속기업이 없어 CFS를 공시하지 않는 회사) 별도재무제표(OFS)로 자동 폴백한다.
         상장사 감사보고서의 주 재무제표는 연결이므로(K-IFRS), CFS 우선이 기본 동작에 맞다.

    반환: (재무제표 DataFrame, 실제 조회에 사용된 fs_div, 의도한 기준에서 폴백 발생 여부)
    """
    if fs_div_override:
        df = fetch_financial_statements(corp_code, bsns_year, reprt_code, fs_div=fs_div_override)
        return df, fs_div_override, False

    first_choice = fs_div_hint or "CFS"
    other_choice = "OFS" if first_choice == "CFS" else "CFS"

    df = fetch_financial_statements(corp_code, bsns_year, reprt_code, fs_div=first_choice)
    if not df.empty:
        return df, first_choice, False

    df = fetch_financial_statements(corp_code, bsns_year, reprt_code, fs_div=other_choice)
    return df, other_choice, True
