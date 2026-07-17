import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY")
DART_BASE_URL = "https://opendart.fss.or.kr/api"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
CORP_CODE_CACHE_PATH = CACHE_DIR / "corp_code.csv"
CORP_CODE_CACHE_TTL_DAYS = 7


class ConfigError(RuntimeError):
    pass


def require_api_key() -> str:
    if not DART_API_KEY:
        raise ConfigError(
            "DART_API_KEY가 설정되어 있지 않습니다. 프로젝트 루트의 .env 파일에 "
            "DART_API_KEY=발급받은키 형태로 저장했는지 확인하세요."
        )
    return DART_API_KEY
