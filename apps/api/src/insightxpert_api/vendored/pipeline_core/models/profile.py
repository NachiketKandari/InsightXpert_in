from pydantic import BaseModel


class ColumnStats(BaseModel):
    count: int
    null_count: int
    distinct_count: int
    min_value: str | None = None
    max_value: str | None = None
    sample_values: list[str] = []


class ColumnQuirks(BaseModel):
    """Structured quirks detected during profiling to help schema linking.

    All fields are optional — populated only when the relevant pattern is detected.
    """
    # Rule-based quirks
    has_special_chars: bool = False  # Spaces, parens, slashes in name
    numbered_group: str | None = None  # e.g. "A" for A1-A16, "q" for q1/q2/q3
    fk_alias: str | None = None  # e.g. "link_to_event" → "event_id"
    type_mismatch: str | None = None  # e.g. "declared DATE stores TEXT YYYYMM"
    symbolic_values: bool = False  # e.g. "+/-", "=/-/#"
    # LLM-enriched quirks
    enum_labels: dict[str, str] = {}  # e.g. {"PRIJEM": "credit", "VYBER": "withdrawal"}
    semantic_hint: str = ""  # e.g. "A11 is average salary by district"
    aliases: list[str] = []  # e.g. ["completion time", "DNF indicator"]


class ColumnProfile(BaseModel):
    name: str
    type: str
    stats: ColumnStats
    mechanical_description: str = ""
    short_summary: str = ""
    long_summary: str = ""
    # LLM synthesis of profiling + quirks + BIRD metadata into one coherent
    # description. Empty when the bird-enriched pass hasn't been run or when
    # no BIRD metadata was available for this column.
    bird_enriched_summary: str = ""
    quirks: ColumnQuirks = ColumnQuirks()


class TableProfile(BaseModel):
    name: str
    row_count: int
    columns: list[ColumnProfile]
    description: str = ""


class DatabaseProfile(BaseModel):
    db_id: str
    tables: list[TableProfile]
