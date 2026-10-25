"""Generate the baseline PostgreSQL DDL from the versioned platform mappings."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import postgresql
from server.database import Base


def schema_sql():
    dialect = postgresql.dialect()
    statements = ["-- Generated baseline; apply once to an empty BTP2 database."]
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n\n".join(statements) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "migrations" / "001_platform.sql"
    target.parent.mkdir(exist_ok=True)
    target.write_text(schema_sql(), encoding="utf-8")
    print("Generated", target.name)
