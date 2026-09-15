"""集中設定：地點、模型、門檻、路徑。其他模組只讀這裡，不互相依賴設定細節。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
EXCEL_NAME = "台灣北部_7天逐時降雨預測.xlsx"
HORIZON_H = 168


@dataclass(frozen=True)
class Location:
    key: str      # 內部代碼
    name: str     # 顯示名稱
    lat: float
    lon: float
    note: str = ""


# 代表點座標：市府／區公所附近（約略座標，可在 config/settings.json 的 "locations" 覆寫）
DEFAULT_LOCATIONS = [
    Location("taipei", "台北市", 25.0375, 121.5637, "臺北市政府附近"),
    Location("banqiao", "新北市板橋區", 25.0120, 121.4650, "新北市政府附近"),
    Location("zhonghe", "新北市中和區", 24.9994, 121.4990, "中和區公所附近"),
    Location("tucheng", "新北市土城區", 24.9722, 121.4445, "土城區公所附近"),
    Location("hsinchu_city", "新竹市", 24.8069, 120.9689, "新竹市政府附近"),
    Location("zhubei", "新竹縣竹北市", 24.8387, 121.0070, "竹北市公所附近"),
]

# 比較用數值模型（Open-Meteo API 名稱）。不支援的模型會在執行時自動略過並記錄。
COMPARE_MODELS = [
    "ecmwf_ifs025",
    "ecmwf_aifs025",
    "gfs_seamless",
    "icon_seamless",
    "jma_seamless",
    "kma_seamless",
    "cma_grapes_global",
    "ukmo_seamless",
]
BASE_MODEL = "best_match"

# 預報提前時間分組（依視窗結束時間相對發布時間，單位小時；左開右閉）
LEAD_BUCKETS = [
    ("0–6h", 0, 6),
    ("6–24h", 6, 24),
    ("第2天", 24, 48),
    ("第3天", 48, 72),
    ("第4–5天", 72, 120),
    ("第6–7天", 120, 168),
]

# 文字分析門檻（會寫入 Excel「來源」頁說明）
UMBRELLA_PROB = 40        # 逐時降雨機率 ≥ 40% 建議帶傘
UMBRELLA_MM = 0.3         # 或逐時雨量 ≥ 0.3 mm
NOTABLE_DAY_MM = 5.0      # 任一地點日雨量 ≥ 5 mm 視為雨勢較明顯
NOTABLE_DAY_PROB = 60     # 或任一小時機率 ≥ 60%
EVENT_MM = 0.5            # 驗證用降雨事件門檻（每個實測視窗）
STATION_MAX_KM = 8.0      # 配對雨量站最大距離

# 校正啟用閘門（必須全部成立才啟用）
CALIB_MIN_TRAIN = 60
CALIB_MIN_TEST = 30
CALIB_MIN_WET_TEST = 10
CALIB_MIN_TEST_DAYS = 7    # 獨立測試期至少涵蓋 7 個不同日期
VERIFY_DAYS = 90           # 驗證與校正使用最近 90 天配對（滾動）
CALIB_MIN_IMPROVE = 0.05   # 獨立測試期 MAE 至少改善 5%
CALIB_BOOT = 1000          # 依日區塊 bootstrap 次數，改善量 95% 信賴下界須 > 0

BACKUP_KEEP = 56           # 保留最近 56 份 Excel 版本（約 7 天 × 8 次）


@dataclass
class Settings:
    root: Path
    cwa_api_key: str | None = None
    locations: list[Location] = field(default_factory=lambda: list(DEFAULT_LOCATIONS))

    @property
    def excel_path(self) -> Path:
        return self.root / EXCEL_NAME

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rain.sqlite"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def backup_dir(self) -> Path:
        return self.root / "backup"

    @property
    def report_dir(self) -> Path:
        return self.root / "reports"

    @property
    def log_path(self) -> Path:
        return self.root / "logs" / "run_log.jsonl"


def load_settings(root: str | os.PathLike) -> Settings:
    root = Path(root)
    s = Settings(root=root)
    cfg = root / "config" / "settings.json"
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        s.cwa_api_key = (data.get("cwa_api_key") or "").strip() or None
        if data.get("locations"):
            s.locations = [Location(**d) for d in data["locations"]]
    s.cwa_api_key = os.environ.get("CWA_API_KEY", s.cwa_api_key)
    return s
