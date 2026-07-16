import pandas as pd
import pytest

from src import dart_client, resolver


def test_resolve_disclosure_matches_rcept_no(monkeypatch):
    fake_list = pd.DataFrame(
        [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "report_nm": "감사보고서 (2022.12)",
                "rcept_no": "20230330001234",
            },
            {
                "corp_code": "00164742",
                "corp_name": "다른회사",
                "report_nm": "감사보고서 (2022.12)",
                "rcept_no": "20230330009999",
            },
        ]
    )

    monkeypatch.setattr(dart_client, "search_disclosures", lambda **kwargs: fake_list)

    info = resolver.resolve_disclosure("20230330001234")

    assert info["corp_code"] == "00126380"
    assert info["corp_name"] == "삼성전자"
    assert info["bsns_year"] == "2022"
    assert info["reprt_code"] == "11011"


def test_resolve_disclosure_not_found_raises(monkeypatch):
    monkeypatch.setattr(
        dart_client, "search_disclosures", lambda **kwargs: pd.DataFrame()
    )

    with pytest.raises(resolver.ResolveError):
        resolver.resolve_disclosure("20230330001234")


def test_resolve_disclosure_invalid_format_raises():
    with pytest.raises(resolver.ResolveError):
        resolver.resolve_disclosure("not-a-valid-no")


@pytest.mark.parametrize(
    "report_nm,filing_date,expected",
    [
        ("감사보고서 (2022.12)", "20230330", "2022"),
        ("사업보고서 (2023.12) (첨부:감사보고서)", "20240320", "2023"),
        ("감사보고서", "20230215", "2022"),  # 연도 미표기 -> 접수월 기준 추정
        ("감사보고서", "20230815", "2023"),
    ],
)
def test_infer_bsns_year(report_nm, filing_date, expected):
    assert resolver._infer_bsns_year(report_nm, filing_date) == expected
