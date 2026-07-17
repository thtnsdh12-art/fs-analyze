"""DART 뷰어 페이지(dsaf001/main.do)에서 dcmNo가 가리키는 첨부문서명을 읽어온다.

공식 DART Open API(document.xml 등)에는 이 매핑이 없다. 대신 사용자가 붙여넣는
링크가 실제로 가리키는 공개 웹페이지(dart.fss.or.kr/dsaf001/main.do) 자체에 문서
트리(makeToc() 자바스크립트 변수)가 그대로 내려오는데, 여기서 현재 dcmNo에 해당하는
문서명(node1['text'])을 읽으면 "감사보고서"(별도) vs "연결감사보고서"(연결)를 구분할 수 있다.

이건 공식 API가 아니라 공개 페이지를 그대로 읽는 방식이라 DART가 페이지 구조를 바꾸면
깨질 수 있다. 그래서 실패해도 절대 예외를 던지지 않고 None을 반환해, 호출부가 기존
CFS 우선 자동판별로 안전하게 폴백하도록 한다(임의 추정 금지 원칙과 동일하게, 신뢰할 수
없는 신호는 아예 안 쓰는 쪽을 택함).
"""

from __future__ import annotations

import re

import requests

_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do"
_NODE_TEXT_PATTERN = re.compile(r"node\d+\['text'\]\s*=\s*\"(.*?)\";")


def fetch_document_titles(rcept_no: str, dcm_no: str) -> list[str] | None:
    """rcept_no/dcm_no가 가리키는 문서의 목차(TOC) 항목명 전체를 DART 뷰어 페이지에서 읽어온다.

    주의: 최상위 항목(첫 번째 TOC 노드)의 제목은 연결/별도 감사보고서 모두 "감사보고서"로
    동일하게 표시된다(DART가 그렇게 렌더링함) — 실제 구분은 "(첨부)연결재무제표" 처럼
    하위 항목에서만 드러난다. 그래서 첫 노드만 보지 않고 전체 목차를 반환한다.

    네트워크 오류, 페이지 구조 변경 등 어떤 이유로든 실패하면 None을 반환한다
    (호출부는 반드시 이 경우를 "판별 불가"로 취급하고 기존 로직으로 폴백해야 한다).
    """
    try:
        resp = requests.get(
            _VIEWER_URL,
            params={"rcpNo": rcept_no, "dcmNo": dcm_no},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    matches = _NODE_TEXT_PATTERN.findall(resp.text)
    if not matches:
        return None
    return [re.sub(r"\s+", "", t) for t in matches]


def _pick_display_title(titles: list[str]) -> str:
    """사용자에게 보여줄 대표 제목을 고른다.

    최상위 노드는 연결/별도 모두 "감사보고서"로 동일해 표시용으로는 부적합하므로,
    실제로 연결/별도가 드러나는 "...재무제표" 항목이 있으면 그걸 우선 사용한다.
    """
    for title in titles:
        if "재무제표" in title:
            return title
    return titles[0]


def guess_fs_div(rcept_no: str, dcm_no: str) -> tuple[str | None, str | None]:
    """문서 목차 전체 텍스트로부터 fs_div를 추정한다.

    반환: (fs_div 추정값("CFS"/"OFS"/None), 표시용 문서명(조회 실패 시 None))
    목차 어디든 "연결"이 포함되면 연결감사보고서(CFS), "감사보고서"/"재무제표"는 있지만
    "연결"이 없으면 별도(OFS)로 판단한다. 그 외 문서(정관, 영업보고서 등)를 가리키는
    링크는 판별 대상이 아니므로 None을 반환해 기존 CFS 우선 자동판별에 맡긴다.
    """
    titles = fetch_document_titles(rcept_no, dcm_no)
    if not titles:
        return None, None

    display_title = _pick_display_title(titles)
    combined = "".join(titles)
    if "연결" in combined:
        return "CFS", display_title
    if "감사보고서" in combined or "재무제표" in combined:
        return "OFS", display_title
    return None, display_title
