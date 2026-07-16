"""3개년 재무제표/재무비율을 그래프 포함 엑셀(.xlsx)로 출력한다.

VBA 매크로 방식(.xlsm) 대신 openpyxl로 네이티브 엑셀 차트를 직접 삽입한다.
매크로가 없으므로 감사법인 보안정책상 매크로 파일이 차단되는 문제가 없고,
받는 사람이 "매크로 사용" 설정 없이 파일을 열자마자 표/그래프를 볼 수 있다.
"""

from __future__ import annotations

import math

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.chart.text import RichText, Text
from openpyxl.chart.title import Title
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties, RegularTextRun
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
WARN_FILL = PatternFill("solid", fgColor="FFC7CE")
TITLE_FONT = Font(bold=True, size=14)


def _style_header_row(ws: Worksheet, row: int, n_cols: int) -> None:
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _autofit(ws: Worksheet, n_cols: int, min_width: int = 12) -> None:
    for col in range(1, n_cols + 1):
        letter = get_column_letter(col)
        width = max(
            (len(str(ws.cell(row=r, column=col).value or "")) for r in range(1, ws.max_row + 1)),
            default=min_width,
        )
        ws.column_dimensions[letter].width = max(min_width, width + 2)


def _write_df(ws: Worksheet, df: pd.DataFrame, start_row: int, index_title: str) -> int:
    """DataFrame을 (index_title 포함) 표로 쓰고, 헤더 스타일 적용 후 마지막 행 번호 반환."""
    ws.cell(row=start_row, column=1, value=index_title)
    for j, col in enumerate(df.columns, start=2):
        ws.cell(row=start_row, column=j, value=str(col))
    _style_header_row(ws, start_row, len(df.columns) + 1)

    for i, (idx, row) in enumerate(df.iterrows(), start=start_row + 1):
        ws.cell(row=i, column=1, value=str(idx))
        for j, col in enumerate(df.columns, start=2):
            value = row[col]
            cell = ws.cell(row=i, column=j)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                cell.value = None
            else:
                cell.value = round(float(value), 2)
                cell.number_format = "#,##0.00"

    return start_row + len(df.index)


def _add_ratio_sheet(wb: Workbook, ratio_df: pd.DataFrame) -> tuple[Worksheet, int]:
    ws = wb.create_sheet("재무비율")
    ws.cell(row=1, column=1, value="3개년 재무비율 (단위: %)").font = TITLE_FONT

    table_start = 3
    last_row = _write_df(ws, ratio_df, table_start, "비율명")
    n_cols = len(ratio_df.columns) + 1

    # 전기대비증감률(%) 컬럼에서 급변동(|증감률|>=20%)을 감사 위험평가 관점에서 강조 표시
    if "전기대비증감률(%)" in ratio_df.columns:
        change_col = ratio_df.columns.get_loc("전기대비증감률(%)") + 2
        col_letter = get_column_letter(change_col)
        cell_range = f"{col_letter}{table_start + 1}:{col_letter}{last_row}"
        ws.conditional_formatting.add(
            cell_range, CellIsRule(operator="greaterThanOrEqual", formula=["20"], fill=WARN_FILL)
        )
        ws.conditional_formatting.add(
            cell_range, CellIsRule(operator="lessThanOrEqual", formula=["-20"], fill=WARN_FILL)
        )

    _autofit(ws, n_cols)
    ws.freeze_panes = ws.cell(row=table_start + 1, column=2)
    return ws, last_row


def _add_bs_item_table(ws: Worksheet, item_df: pd.DataFrame, title_row: int) -> int:
    """재무상태표 주요 항목(유동/비유동 자산·부채, 억원) 표를 쓰고 마지막 행 번호를 반환."""
    ws.cell(row=title_row, column=1, value="주요 재무상태표 항목 (단위: 억원)").font = TITLE_FONT
    table_start = title_row + 2
    last_row = _write_df(ws, item_df, table_start, "항목")
    _autofit(ws, len(item_df.columns) + 1)
    return last_row


def _chart_title_with_unit(main_text: str, unit_text: str) -> Title:
    """차트 제목 아래에 단위 표기를 오른쪽 정렬로 붙인 2줄짜리 제목을 만든다.

    세로축 제목으로 단위를 표시하면 눈금 숫자와 겹쳐 보이는 문제가 있어(사용자 피드백),
    플롯 영역 바깥(차트 제목 영역)의 오른쪽 구석에 단위만 별도 줄로 배치한다.
    """
    main_run = RegularTextRun(t=main_text, rPr=CharacterProperties(b=True, sz=1400))
    main_para = Paragraph(pPr=ParagraphProperties(algn="ctr"), r=[main_run])

    unit_run = RegularTextRun(t=unit_text, rPr=CharacterProperties(b=False, sz=1000))
    unit_para = Paragraph(pPr=ParagraphProperties(algn="r"), r=[unit_run])

    return Title(tx=Text(rich=RichText(p=[main_para, unit_para])))


def _add_bs_item_chart(
    ws: Worksheet, item_df: pd.DataFrame, table_start: int, anchor_cell: str
) -> None:
    """유동자산/비유동자산/유동부채/비유동부채를 기간별로 비교하는 막대 그래프를 삽입한다.

    openpyxl의 LineChart/BarChart는 x_axis.axPos 기본값이 "l"(왼쪽)이라 카테고리축과
    값축이 같은 위치에 겹쳐 엑셀에서 차트가 깨져 보인다(빈 플레이스홀더처럼 렌더링됨).
    반드시 axPos를 명시적으로 지정해야 한다.
    """
    period_cols = list(item_df.columns)
    if not period_cols:
        return

    min_col, max_col = 2, 1 + len(period_cols)

    chart = BarChart()
    chart.type = "col"
    chart.grouping = "clustered"
    # 가로축 제목("기간")은 가운데 카테고리 라벨과 겹쳐 보여 삭제하고, 세로축 제목
    # ("금액(억원)")은 눈금 숫자와 겹쳐 보여 축 제목 대신 차트 제목 우측에 단위로 표기한다.
    chart.title = _chart_title_with_unit("재무상태표 주요 항목 3개년 추이", "(단위: 억원)")
    chart.style = 10
    chart.x_axis.axPos = "b"
    chart.y_axis.axPos = "l"
    chart.y_axis.numFmt = "#,##0"
    # openpyxl은 axId만 만들고 delete/tickLblPos를 비워두는데, 그러면 엑셀이
    # 눈금 라벨(가로축 전전기/전기/당기, 세로축 금액 눈금)을 표시하지 않고 숨겨버린다.
    # 두 축 모두 명시적으로 "삭제 안 함" + "축 옆에 라벨 표시"로 지정해야 눈금이 보인다.
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.x_axis.tickLblPos = "nextTo"
    chart.y_axis.tickLblPos = "nextTo"
    chart.x_axis.majorTickMark = "out"
    chart.y_axis.majorTickMark = "out"
    # 차트가 작으면 세로축 제목(금액(억원))이 눈금 숫자와, 가로축 제목(기간)이 가운데
    # 카테고리 라벨(전기)과 겹쳐 보인다. 차트 자체를 넉넉하게 키워 여백을 확보한다.
    chart.height, chart.width = 14, 26
    chart.legend.position = "r"
    chart.legend.overlay = False

    # from_rows=True 방식은 행이 1개뿐일 때 엑셀에서 계열/카테고리가 뒤바뀌어 보이는
    # 문제가 있어(실측: 유동비율 1개 지표 그래프에서 계열명이 "전전기/전기/당기"로
    # 잘못 표시됨), 항목마다 Series를 명시적으로 구성하는 방식으로 대체한다.
    for i, name in enumerate(item_df.index):
        row = table_start + 1 + i
        values = Reference(ws, min_col=min_col, max_col=max_col, min_row=row, max_row=row)
        chart.series.append(Series(values, title=name))

    cats = Reference(ws, min_col=min_col, max_col=max_col, min_row=table_start, max_row=table_start)
    chart.set_categories(cats)

    ws.add_chart(chart, anchor_cell)


def _add_financials_sheet(wb: Workbook, wide_df: pd.DataFrame) -> None:
    ws = wb.create_sheet("재무제표")
    ws.cell(row=1, column=1, value="3개년 재무제표 (단위: 원)").font = TITLE_FONT
    _write_df(ws, wide_df, 3, "계정과목")
    _autofit(ws, len(wide_df.columns) + 1)
    ws.freeze_panes = ws.cell(row=4, column=2)


def _add_info_sheet(
    wb: Workbook,
    info: dict,
    fs_div: str,
    missing_accounts: list[str],
    derived_notes: list[str],
) -> None:
    ws = wb.create_sheet("안내", 0)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90

    rows = [
        ("회사명", f"{info['corp_name']} (corp_code={info['corp_code']})"),
        ("공시서류명", info.get("report_nm", "")),
        ("사업연도(추정)", info.get("bsns_year", "")),
        ("재무제표 기준", "연결재무제표(CFS)" if fs_div == "CFS" else "개별/별도재무제표(OFS)"),
    ]
    r = 1
    for label, value in rows:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=2, value=value)
        r += 1

    r += 1
    if missing_accounts:
        ws.cell(
            row=r,
            column=1,
            value=(
                "[경고] 다음 표준계정을 하나 이상의 기간에서 찾지 못해 관련 비율이 "
                "공란 처리되었습니다 (임의 추정하지 않음)"
            ),
        ).font = Font(bold=True, color="C00000")
        r += 1
        ws.cell(row=r, column=1, value=", ".join(missing_accounts))
        r += 1

    if derived_notes:
        r += 1
        ws.cell(row=r, column=1, value="[안내] 파생 계산된 항목").font = Font(bold=True)
        r += 1
        for note in derived_notes:
            ws.cell(row=r, column=1, value=note)
            r += 1

    r += 1
    ws.cell(
        row=r,
        column=1,
        value="[면책] 본 결과는 참고용 사전분석 자료이며 감사의견 형성의 유일한 근거가 될 수 없습니다.",
    ).font = Font(italic=True)


def build_workbook(
    info: dict,
    fs_div: str,
    wide_df: pd.DataFrame,
    ratio_df: pd.DataFrame,
    missing_accounts: list[str],
    derived_notes: list[str],
    bs_item_df: pd.DataFrame,
    bs_missing_items: list[str],
) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)

    combined_missing = missing_accounts + [
        name for name in bs_missing_items if name not in missing_accounts
    ]
    _add_info_sheet(wb, info, fs_div, combined_missing, derived_notes)
    _add_financials_sheet(wb, wide_df)

    ratio_table_start = 3
    ratio_ws, ratio_last_row = _add_ratio_sheet(wb, ratio_df)

    # 요청사항: 그래프는 비율표 "아래"가 아니라 "옆"에 배치 -> 비율표와 같은 시작 행,
    # 표 오른쪽에 빈 열 하나를 띄우고 앵커링한다.
    ratio_n_cols = len(ratio_df.columns) + 1
    chart_anchor_col = get_column_letter(ratio_n_cols + 2)
    item_title_row = ratio_last_row + 3
    item_table_start = item_title_row + 2
    _add_bs_item_table(ratio_ws, bs_item_df, item_title_row)
    _add_bs_item_chart(
        ratio_ws, bs_item_df, item_table_start, f"{chart_anchor_col}{ratio_table_start}"
    )

    wb.active = 0
    return wb
