import pandas as pd

from src.financials import pivot_wide, to_long_format


def _sample_raw_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sj_nm": "재무상태표",
                "account_nm": "유동자산",
                "thstrm_nm": "제 55 기",
                "thstrm_amount": "100,000",
                "frmtrm_nm": "제 54 기",
                "frmtrm_amount": "90,000",
                "bfefrmtrm_nm": "제 53 기",
                "bfefrmtrm_amount": "80,000",
            },
            {
                "sj_nm": "재무상태표",
                "account_nm": "유동부채",
                "thstrm_nm": "제 55 기",
                "thstrm_amount": "50,000",
                "frmtrm_nm": "제 54 기",
                "frmtrm_amount": "N/A",  # 파싱 실패 케이스
                "bfefrmtrm_nm": "제 53 기",
                "bfefrmtrm_amount": "40,000",
            },
        ]
    )


def test_to_long_format_parses_amounts_and_marks_failures_as_none():
    long_df = to_long_format(_sample_raw_df())

    current = long_df[(long_df["account_nm"] == "유동자산") & (long_df["period"] == "당기")]
    assert current.iloc[0]["amount"] == 100000.0

    # DataFrame 생성 시 amount 컬럼이 float dtype으로 캐스팅되며 None -> NaN으로 변환된다.
    # (비율 계산 시 NaN이 예외 없이 전파되어 "공란 처리" 요구사항에 더 부합함)
    failed = long_df[(long_df["account_nm"] == "유동부채") & (long_df["period"] == "전기")]
    assert pd.isna(failed.iloc[0]["amount"])


def test_pivot_wide_orders_periods_and_computes_ratio_inputs():
    long_df = to_long_format(_sample_raw_df())
    wide = pivot_wide(long_df)

    assert list(wide.columns) == ["전전기", "전기", "당기"]

    current_ratio = wide.loc["유동자산", "당기"] / wide.loc["유동부채", "당기"]
    assert current_ratio == 2.0


def test_to_long_format_empty_input_returns_empty_df():
    long_df = to_long_format(pd.DataFrame())
    assert long_df.empty
    assert list(long_df.columns) == [
        "period",
        "period_label",
        "sj_nm",
        "account_nm",
        "account_id",
        "amount",
    ]
