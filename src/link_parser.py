import re
from urllib.parse import parse_qs, urlparse

RCEPT_NO_PATTERN = re.compile(r"(?<!\d)(\d{14})(?!\d)")
RCEPT_NO_QUERY_KEYS = ("rcpNo", "rcpno", "rcept_no", "rceptNo")
DCM_NO_QUERY_KEYS = ("dcmNo", "dcmno", "dcm_no")


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


def extract_dcm_no(url: str) -> str | None:
    """DART 뷰어 URL에서 dcmNo(사용자가 실제로 보고 있던 첨부문서 식별자)를 추출한다.

    rcept_no와 달리 필수 값이 아니다(사업보고서 대표 링크는 dcmNo 없이도 유효함).
    없거나 형식이 이상하면 예외를 던지지 않고 None을 반환한다 — dcmNo는 연결/별도
    자동판별을 보강하는 힌트일 뿐, 없다고 링크 자체가 무효인 건 아니기 때문이다.
    """
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    for key in DCM_NO_QUERY_KEYS:
        values = query.get(key)
        if values and values[0].isdigit():
            return values[0]
    return None
