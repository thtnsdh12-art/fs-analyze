import re
from urllib.parse import parse_qs, urlparse

RCEPT_NO_PATTERN = re.compile(r"(?<!\d)(\d{14})(?!\d)")
RCEPT_NO_QUERY_KEYS = ("rcpNo", "rcpno", "rcept_no", "rceptNo")


class InvalidDartLinkError(ValueError):
    pass


def extract_rcept_no(url: str) -> str:
    """DART 뷰어 URL에서 접수번호(rcept_no, 14자리: YYYYMMDD + 일련번호 6자리)를 추출한다.

    지원 예시:
      https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230330001234
      https://dart.fss.or.kr/report/viewer.do?rcpNo=20230330001234&dcmNo=...
    """
    url = url.strip()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    for key in RCEPT_NO_QUERY_KEYS:
        values = query.get(key)
        if values and RCEPT_NO_PATTERN.fullmatch(values[0]):
            return values[0]

    match = RCEPT_NO_PATTERN.search(url)
    if match:
        return match.group(1)

    raise InvalidDartLinkError(
        f"URL에서 접수번호(rcept_no, 14자리 숫자)를 찾을 수 없습니다: {url}"
    )
