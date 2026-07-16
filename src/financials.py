"""fnlttSinglAcntAll 원본 응답 -> 연도/계정과목/값 롱포맷/와이드 테이블 변환."""

import pandas as pd

# DART 응답 컬럼명: (기간 라벨 컬럼, 금액 컬럼)
PERIOD_COLUMNS = {
    "전전기": ("bfefrmtrm_nm", "bfefrmtrm_amount"),
    "전기": ("frmtrm_nm", "frmtrm_amount"),
    "당기": ("thstrm_nm", "thstrm_amount"),
}

LONG_COLUMNS = ["period", "period_label", "sj_nm", "account_nm", "account_id", "amount"]


def to_long_format(raw_df: pd.DataFrame) -> pd.DataFrame:
    """원본 응답을 (기간, 재무제표명, 계정과목, 금액) 롱포맷으로 변환한다.

    금액 파싱에 실패하는 계정은 amount=None으로 남겨 화면에서 경고 처리할 수 있게 한다
    (PRD 요구사항: 매핑/파싱 실패 시 임의 추정 금지, 공란 + 경고 표시).
    """
    if raw_df.empty:
        return pd.DataFrame(columns=LONG_COLUMNS)

    records = []
    for _, row in raw_df.iterrows():
        for period, (label_col, amount_col) in PERIOD_COLUMNS.items():
            label = row.get(label_col)
            amount_raw = row.get(amount_col)
            if not label:
                continue

            amount = None
            if amount_raw not in (None, ""):
                try:
                    amount = float(str(amount_raw).replace(",", ""))
                except ValueError:
                    amount = None

            records.append(
                {
                    "period": period,
                    "period_label": label,
                    "sj_nm": row.get("sj_nm"),
                    "account_nm": row.get("account_nm"),
                    "account_id": row.get("account_id"),
                    "amount": amount,
                }
            )

    return pd.DataFrame(records, columns=LONG_COLUMNS)


def pivot_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    """계정과목을 행, 기간(전전기/전기/당기)을 열로 배치한 와이드 테이블."""
    if long_df.empty:
        return pd.DataFrame()

    wide = long_df.pivot_table(
        index="account_nm", columns="period", values="amount", aggfunc="first"
    )
    ordered_cols = [c for c in ("전전기", "전기", "당기") if c in wide.columns]
    return wide[ordered_cols]
