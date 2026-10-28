"""Central configuration; secrets are read from environment variables."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("SUPPLYCHAINIQ_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
BACKEND = os.getenv("SUPPLYCHAINIQ_BACKEND", "local").lower()
RANDOM_SEED = int(os.getenv("SUPPLYCHAINIQ_SEED", "42"))
ORDERS_COUNT = int(os.getenv("SUPPLYCHAINIQ_ORDERS", "1000"))
