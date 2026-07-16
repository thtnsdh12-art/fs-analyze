import pytest

from src.link_parser import InvalidDartLinkError, extract_rcept_no


def test_extract_rcept_no_from_viewer_url():
    url = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230330001234&dcmNo=1234567"
    assert extract_rcept_no(url) == "20230330001234"


def test_extract_rcept_no_lowercase_param():
    url = "https://dart.fss.or.kr/report/viewer.do?rcpno=20230330001234"
    assert extract_rcept_no(url) == "20230330001234"


def test_extract_rcept_no_falls_back_to_bare_number_in_url():
    url = "https://dart.fss.or.kr/pdf/download/20230330001234.pdf"
    assert extract_rcept_no(url) == "20230330001234"


def test_extract_rcept_no_missing_raises():
    with pytest.raises(InvalidDartLinkError):
        extract_rcept_no("https://dart.fss.or.kr/dsaf001/main.do?foo=bar")


def test_extract_rcept_no_rejects_wrong_length():
    with pytest.raises(InvalidDartLinkError):
        extract_rcept_no("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=12345")
