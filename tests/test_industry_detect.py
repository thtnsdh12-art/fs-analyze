import pandas as pd

from src.industry_detect import detect_financial_industry


def _long_df(account_names: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "period": "당기",
                "period_label": "당기",
                "sj_nm": "포괄손익계산서",
                "account_nm": name,
                "account_id": None,
                "amount": 1.0,
            }
            for name in account_names
        ]
    )


def test_detects_bank_marker():
    long_df = _long_df(["매출액", "영업이익", "이자수익", "예수부채"])
    assert detect_financial_industry(long_df) == ["예수부채", "이자수익"]


def test_detects_securities_firm_marker():
    # 삼성증권 실측 계정과목명 재현 — 보험 계열 마커 없이 예수부채/이자수익/이자비용
    # 3개만으로도 정상 감지되어야 한다 (실데이터로 확인됨, 2026-07-18)
    long_df = _long_df(["영업이익", "수수료수익", "예수부채", "이자수익", "이자비용", "자산총계"])
    assert detect_financial_industry(long_df) == ["예수부채", "이자비용", "이자수익"]


def test_detects_insurance_marker():
    long_df = _long_df(["보험수익", "재보험계약부채", "매출원가"])
    assert detect_financial_industry(long_df) == ["보험수익", "재보험계약부채"]


def test_no_false_positive_on_general_manufacturer():
    # SK지주/SK하이닉스/삼성전자 등 일반 기업 실측 계정과목명 — 마커와 겹치지 않아야 함
    long_df = _long_df(
        [
            "유동자산",
            "유동부채",
            "매출액",
            "매출원가",
            "영업이익",
            "당기순이익",
            "이자의 수취",
            "이자의 지급",
            "예수보증금의 증가",
        ]
    )
    assert detect_financial_industry(long_df) == []


def test_empty_long_df_returns_empty_list():
    assert detect_financial_industry(pd.DataFrame()) == []
