# Copyright Thales 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
import pandas as pd
import logging
from typing import Optional
from app.core.processors.input.common.base_input_processor import BaseTabularProcessor

logger = logging.getLogger(__name__)


class CsvTabularProcessor(BaseTabularProcessor):
    """
    An example tabular processor for CSV files.
    Extracts header and rows from a simple CSV file.
    """

    def check_file_validity(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv" and file_path.is_file()

    def read_csv_flexible(self, path: Path, delimiters: Optional[list[str]] = None, encodings: Optional[list[str]] = None) -> pd.DataFrame:
        if delimiters is None:
            delimiters = [",", ";", "\t", "|"]
        if encodings is None:
            encodings = ["utf-8", "latin1", "iso-8859-1"]

        if not self.check_file_validity(path):
            logger.error(f"File invalid or not found: {path}")
            return pd.DataFrame()

        errors = []
        for enc in encodings:
            for delim in delimiters:
                try:
                    df = pd.read_csv(path, delimiter=delim, encoding=enc)
                    logger.info(f"CSV loaded successfully with delimiter '{delim}' and encoding '{enc}'")
                    return df
                except Exception as e:
                    errors.append(f"delimiter='{delim}', encoding='{enc}': {e}")
        logger.error(f"[ERROR] Failed to read CSV file '{path}'. Tried combinations:\n" + "\n".join(errors))
        return pd.DataFrame()

    def extract_file_metadata(self, file_path: Path) -> dict:
        df = self.read_csv_flexible(file_path)
        if df is not None:
            return {
                "suffix": "CSV",
                "row_count": len(df),
                "num_columns": len(df.columns),
                "sample_columns": df.columns.tolist(),
            }
        else:
            return {
                "suffix": "CSV",
                "row_count": 0,
                "num_columns": 0,
                "sample_columns": [],
            }

    def convert_file_to_table(self, file_path: Path) -> pd.DataFrame:
        return self.read_csv_flexible(file_path)
