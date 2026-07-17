import pandas as pd

from src import dart_client


def test_fetch_financial_statements_auto_prefers_cfs(monkeypatch):
    """연결재무제표(CFS)가 존재하면 그대로 사용하고 OFS는 조회하지 않는다."""
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div="OFS"):
        calls.append(fs_div)
        return pd.DataFrame([{"account_nm": "유동자산"}])

    monkeypatch.setattr(dart_client, "fetch_financial_statements", fake_fetch)

    df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
        "00164779", "2025", "11011"
    )

    assert calls == ["CFS"]
    assert fs_div_used == "CFS"
    assert fell_back is False
    assert not df.empty


def test_fetch_financial_statements_auto_falls_back_to_ofs_when_cfs_empty(monkeypatch):
    """연결 대상 종속기업이 없어 CFS 응답이 비어 있으면 OFS로 자동 전환한다.

    계정과목 내용(예: 비지배지분 유무)으로 추론하지 않고, API 응답이 비어 있는지
    여부만으로 판별한다는 점이 이 테스트의 핵심.
    """
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div="OFS"):
        calls.append(fs_div)
        if fs_div == "CFS":
            return pd.DataFrame()
        return pd.DataFrame([{"account_nm": "유동자산"}])

    monkeypatch.setattr(dart_client, "fetch_financial_statements", fake_fetch)

    df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
        "00526599", "2025", "11011"
    )

    assert calls == ["CFS", "OFS"]
    assert fs_div_used == "OFS"
    assert fell_back is True
    assert not df.empty


def test_fetch_financial_statements_auto_respects_explicit_override(monkeypatch):
    """사용자가 --fs-div를 명시하면 폴백 없이 그 값만 조회한다."""
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div="OFS"):
        calls.append(fs_div)
        return pd.DataFrame()  # 빈 응답이어도 폴백하지 않아야 함

    monkeypatch.setattr(dart_client, "fetch_financial_statements", fake_fetch)

    df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
        "00164779", "2025", "11011", fs_div_override="OFS"
    )

    assert calls == ["OFS"]
    assert fs_div_used == "OFS"
    assert fell_back is False


def test_fetch_financial_statements_auto_uses_hint_over_cfs_default(monkeypatch):
    """링크의 dcmNo로 추정된 힌트(예: 별도)가 있으면 CFS 기본값보다 우선한다."""
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div="OFS"):
        calls.append(fs_div)
        return pd.DataFrame([{"account_nm": "유동자산"}])  # 어느 쪽이든 데이터 있음

    monkeypatch.setattr(dart_client, "fetch_financial_statements", fake_fetch)

    df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
        "00537221", "2025", "11011", fs_div_hint="OFS"
    )

    assert calls == ["OFS"]
    assert fs_div_used == "OFS"
    assert fell_back is False


def test_fetch_financial_statements_auto_falls_back_when_hinted_fs_div_empty(monkeypatch):
    """힌트가 가리키는 기준의 데이터가 실제로는 없으면 반대쪽으로 폴백한다."""
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div="OFS"):
        calls.append(fs_div)
        if fs_div == "OFS":
            return pd.DataFrame()
        return pd.DataFrame([{"account_nm": "유동자산"}])

    monkeypatch.setattr(dart_client, "fetch_financial_statements", fake_fetch)

    df, fs_div_used, fell_back = dart_client.fetch_financial_statements_auto(
        "00537221", "2025", "11011", fs_div_hint="OFS"
    )

    assert calls == ["OFS", "CFS"]
    assert fs_div_used == "CFS"
    assert fell_back is True
