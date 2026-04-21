"""BIRD benchmark CSV metadata reader.

Each database in the BIRD/mini_dev download ships a database_description/
folder containing one CSV per table with human-curated column descriptions:

    original_column_name, column_name, column_description, data_format, value_description

BirdMetadata loads these CSVs and exposes per-column descriptions for use
in the "bird" and "fused" metadata modes (see models/evaluation.py).
"""
import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BirdMetadata:
    """Cached BIRD CSV descriptions for a single database.

    Looks up descriptions in the mini_dev database_description/ folders.
    Falls back to empty string when no description is available.
    """

    def __init__(self, db_id: str, mini_dev_dir: Path) -> None:
        # (table_name, original_column_name) -> combined description
        self._descriptions: dict[tuple[str, str], str] = {}
        self._load(db_id, mini_dev_dir)

    def _load(self, db_id: str, mini_dev_dir: Path) -> None:
        desc_dir = mini_dev_dir / "dev_databases" / db_id / "database_description"
        if not desc_dir.exists():
            logger.debug("No database_description dir for '%s' at %s", db_id, desc_dir)
            return

        for csv_path in sorted(desc_dir.glob("*.csv")):
            table_name = csv_path.stem
            try:
                # utf-8-sig handles the optional BOM present in some BIRD CSVs
                with csv_path.open(encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        col = (row.get("original_column_name") or "").strip()
                        col_desc = (row.get("column_description") or "").strip()
                        val_desc = (row.get("value_description") or "").strip()

                        if not col:
                            continue

                        # Combine column_description and value_description into one string.
                        # Preserve both: col_desc gives meaning, val_desc gives value examples.
                        if col_desc and val_desc:
                            combined = f"{col_desc}. Values: {val_desc}"
                        else:
                            combined = col_desc or val_desc

                        if combined:
                            self._descriptions[(table_name, col)] = combined

            except Exception as e:
                logger.warning("Failed to read CSV %s: %s", csv_path, e)

        logger.debug(
            "Loaded Bird metadata for '%s': %d column descriptions across %d tables",
            db_id,
            len(self._descriptions),
            len({t for t, _ in self._descriptions}),
        )

    def get(self, table: str, column: str) -> str:
        """Return the Bird CSV description for (table, column), or empty string."""
        return self._descriptions.get((table, column), "")

    def __bool__(self) -> bool:
        return bool(self._descriptions)
