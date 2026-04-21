from pydantic import BaseModel


class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None


class ForeignKey(BaseModel):
    column: str
    ref_table: str
    ref_column: str
    on_delete: str | None = None
    on_update: str | None = None


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    foreign_keys: list[ForeignKey] = []

    @property
    def primary_keys(self) -> list[str]:
        """Return names of all primary key columns in this table."""
        return [c.name for c in self.columns if c.primary_key]


class DatabaseSchema(BaseModel):
    db_id: str
    tables: list[TableSchema]

    @property
    def table_names(self) -> list[str]:
        """Return a list of all table names in the database."""
        return [t.name for t in self.tables]

    def get_table(self, name: str) -> TableSchema | None:
        """Look up a table by name; returns None if not found."""
        for t in self.tables:
            if t.name == name:
                return t
        return None
