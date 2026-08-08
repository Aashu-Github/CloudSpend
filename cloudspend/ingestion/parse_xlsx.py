from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_xlsx(path: Path) -> pd.DataFrame:
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Only .xlsx workbooks are supported; macro-enabled workbooks are rejected.")
    return pd.read_excel(path, engine="openpyxl")
