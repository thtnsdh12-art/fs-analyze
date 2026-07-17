import requests

from src import doc_tree


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


def _viewer_html(*node_texts: str) -> str:
    """실제 DART 뷰어 페이지에서 관찰되는 makeToc() 스니펫을 흥낸다.

    실제 페이지는 최상위 노드(node1, 첫 항목) 제목이 연결/별도 감사보고서 모두
    "감사보고서"로 동일하고, "(첨부)연결재무제표"처럼 하위 항목에서만 연결 여부가
    드러난다 — 그래서 테스트도 여러 노드를 함께 흥낸다.
    """
    nodes = "\n".join(f"node1['text'] = \"{t}\";" for t in node_texts)
    return f"function makeToc() {{\n{nodes}\n}}"


def test_guess_fs_div_detects_separate_audit_report(monkeypatch):
    # 최상위 제목은 "감사보고서"뿐이고, 하위 항목에 "연결"이 전혀 없는 실제 별도 케이스
    monkeypatch.setattr(
        doc_tree.requests,
        "get",
        lambda *a, **k: _FakeResponse(
            _viewer_html("감   사   보   고   서", "독립된감사인의감사보고서", "(첨부)재무제표", "주석")
        ),
    )
    fs_div, title = doc_tree.guess_fs_div("20260320001036", "11158217")
    assert fs_div == "OFS"
    assert title == "(첨부)재무제표"


def test_guess_fs_div_detects_consolidated_audit_report(monkeypatch):
    # 최상위 제목도 "감사보고서"로 동일하지만(실제 DART 동작), 하위 항목에 "연결"이 있는 케이스
    monkeypatch.setattr(
        doc_tree.requests,
        "get",
        lambda *a, **k: _FakeResponse(
            _viewer_html("감   사   보   고   서", "독립된감사인의감사보고서", "(첨부)연결재무제표", "주석")
        ),
    )
    fs_div, title = doc_tree.guess_fs_div("20260320001036", "11158218")
    assert fs_div == "CFS"
    assert title == "(첨부)연결재무제표"


def test_guess_fs_div_unrecognized_title_returns_none(monkeypatch):
    monkeypatch.setattr(
        doc_tree.requests, "get", lambda *a, **k: _FakeResponse(_viewer_html("정관"))
    )
    fs_div, title = doc_tree.guess_fs_div("20260320001036", "11158221")
    assert fs_div is None
    assert title == "정관"


def test_guess_fs_div_network_failure_returns_none_without_raising(monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr(doc_tree.requests, "get", _raise)
    fs_div, title = doc_tree.guess_fs_div("20260320001036", "11158217")
    assert fs_div is None
    assert title is None


def test_guess_fs_div_unparsable_page_returns_none(monkeypatch):
    monkeypatch.setattr(doc_tree.requests, "get", lambda *a, **k: _FakeResponse("<html>404</html>"))
    fs_div, title = doc_tree.guess_fs_div("20260320001036", "11158217")
    assert fs_div is None
    assert title is None
