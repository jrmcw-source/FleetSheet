"""Guardrails for the schema/migration split."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def test_engine_has_no_legacy_alter_table():
    text = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert "ALTER TABLE" not in text
    assert "CREATE TABLE" not in text


def test_migrations_contain_only_compatibility_ddl():
    text = (ROOT / "engine_migrations.py").read_text(encoding="utf-8")
    assert "ALTER TABLE" in text
    assert not re.search(r'con\.execute\(\s*["\']CREATE\s+TABLE', text, re.I)
    assert "migrate_legacy_schema" in text


def test_current_schema_owns_table_creation():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert len(re.findall(r"\bCREATE\s+TABLE\b", schema, re.I)) >= 20
    assert len(re.findall(r"\bCREATE\s+TABLE\b", schema, re.I)) > len(
        re.findall(r"\bCREATE\s+TABLE\b", (ROOT / "engine_migrations.py").read_text(encoding="utf-8"), re.I)
    )


if __name__ == "__main__":
    tests = [
        test_engine_has_no_legacy_alter_table,
        test_migrations_contain_only_compatibility_ddl,
        test_current_schema_owns_table_creation,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"{len(tests)}/{len(tests)} migration-ledger checks passed")
