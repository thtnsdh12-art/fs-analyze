# fs-analyze

DART(전자공시시스템) 감사보고서/사업보고서 뷰어 링크 하나만으로 최근 3개년(전전기/전기/당기) 재무제표를 자동으로 가져와 핵심 재무비율을 계산하고, 그래프가 포함된 엑셀 보고서를 생성하는 CLI 도구입니다.

회계법인의 감사 착수 전(pre-audit) 단계에서, 감사인이 링크 하나만 넣으면 재무상태표/손익계산서 주요 항목과 유동비율·부채비율·ROA·ROE 등 8개 재무비율을 자동 산출해 이상 변동(전기 대비 ±20% 이상)을 빠르게 스크리닝할 수 있도록 만들었습니다.

## 주요 기능

- DART 뷰어 링크(`rcpNo`)만으로 회사명/사업연도를 자동 역산 (`src/resolver.py`)
- 3개년 재무제표 전체 계정 조회 (`src/dart_client.py`, `src/financials.py`)
- IFRS 표준계정코드(`account_id`) 우선 + 계정과목명 폴백 매칭으로 회사마다 다른 계정명(예: "매출액"/"영업수익")을 표준화 (`src/ratios.py`)
  - 표준계정 매핑에 실패하면 **임의로 추정하지 않고 공란 + 경고**만 표시합니다.
- 8개 재무비율(유동비율/부채비율/자기자본비율/ROA/ROE/매출총이익률/영업이익률/순이익률) 및 전기대비증감률 계산
- 결과를 그래프 포함 `.xlsx` 파일로 저장 (`src/excel_export.py`)
  - 재무비율 표에서 전기대비 ±20% 이상 급변동 항목 자동 강조(조건부 서식)
  - 유동자산/비유동자산/유동부채/비유동부채 3개년 추이 막대그래프 포함

## 프로젝트 상태

Phase 1(링크 파싱 + DART API 연동)~Phase 3(비율 계산 + 그래프 포함 엑셀 출력)까지 실제 DART 공시(삼성전자, 덴티움 사업보고서)로 검증 완료. 전체 로드맵과 진행 로그는 [`PRD.md`](./PRD.md) 참고.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## API 키 설정

DART Open API 키가 필요합니다 ([opendart.fss.or.kr](https://opendart.fss.or.kr)에서 무료 발급). 프로젝트 루트에 `.env` 파일을 만들고 `.env.example`을 참고해 아래와 같이 작성하세요.

```
DART_API_KEY=발급받은_키
```

`.env`는 `.gitignore`에 포함되어 있어 저장소에 올라가지 않습니다.

## 사용법

```bash
python main.py "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260323001196&dcmNo=11166205"

# 연결재무제표 기준으로 조회
python main.py "<DART 링크>" --fs-div CFS

# 결과 저장 위치 지정
python main.py "<DART 링크>" --output-dir ./output
```

실행하면 콘솔에 재무제표/재무비율 표가 출력되고, `{회사명}_{연결|별도}_결과.xlsx` 파일이 생성됩니다(안내/재무제표/재무비율 3개 시트 + 그래프 포함).

## API 키 없이 결과 미리 보기

DART API 키가 없어도 실행 결과물의 형태를 바로 확인할 수 있도록 샘플 출력 파일을 저장소에 첨부해 두었습니다: [`덴티움_별도_결과.xlsx`](./덴티움_별도_결과.xlsx) (덴티움 2025 사업보고서, 별도재무제표 기준).

## 테스트

```bash
pytest tests/
```

네트워크 호출 없이 오프라인으로 동작하는 단위 테스트 23건이 포함되어 있습니다.

## 면책 사항

본 도구의 산출물은 감사 착수 전 참고용 사전분석 자료이며, 감사의견 형성의 유일한 근거가 될 수 없습니다.
