"""Checksummed, forward-only migrations for the independent Growth database."""

from hashlib import sha256
from importlib.resources import files
import re


def migration_files():
    migrations = []
    for path in sorted(files("smartlect").joinpath("migrations").iterdir(), key=lambda p: p.name):
        if re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", path.name):
            source = path.read_bytes()
            migrations.append((path.name, sha256(source).hexdigest(), source.decode("utf-8")))
    if not migrations:
        raise RuntimeError("No packaged Growth migrations found")
    versions = [name[:4] for name, _, _ in migrations]
    if len(set(versions)) != len(versions):
        raise RuntimeError("Duplicate Growth migration versions")
    return migrations


def migrate(connect):
    migrations = migration_files()
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK('smartlect_growth_schema', 10) AS acquired")
        if cursor.fetchone()["acquired"] != 1:
            raise RuntimeError("Growth migration lock unavailable")
        try:
            cursor.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
                name VARCHAR(128) PRIMARY KEY, checksum CHAR(64) NOT NULL,
                applied_at DATETIME(6) NOT NULL
                ) ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin""")
            cursor.execute("SELECT name,checksum FROM schema_migration ORDER BY name")
            applied = {row["name"]: row["checksum"] for row in cursor.fetchall()}
            available = {name: checksum for name, checksum, _ in migrations}
            if any(available.get(name) != checksum for name, checksum in applied.items()):
                raise RuntimeError("Applied Growth migration missing or checksum changed")
            highest_applied = max((int(name[:4]) for name in applied), default=-1)
            if any(int(name[:4]) <= highest_applied for name in available if name not in applied):
                raise RuntimeError("Growth migrations are forward-only; unapplied older version found")
            for name, checksum, source in migrations:
                if name in applied:
                    continue
                # MySQL DDL commits implicitly, so a migration that dies halfway can leave the
                # schema ahead of the ledger. Replaying it is therefore the recovery path, and
                # the "object already exists/exists no more" errors below are how a replay
                # reports that a statement already reached its target state. The file checksum
                # stays the contract for what the statement was, so this cannot paper over a
                # changed migration.
                # A delimiter in owned SQL avoids writing a general SQL/string parser.
                for statement in source.split("\n-- statement-break\n"):
                    if statement.strip():
                        try:
                            cursor.execute(statement)
                        except Exception as error:
                            if not _already_applied(error):
                                raise
                cursor.execute("INSERT INTO schema_migration (name,checksum,applied_at) VALUES (%s,%s,UTC_TIMESTAMP(6))",
                               (name, checksum))
                connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            cursor.execute("SELECT RELEASE_LOCK('smartlect_growth_schema')")


# MySQL has no IF NOT EXISTS for columns and indexes: these codes are the DDL-level
# equivalent, i.e. "this statement's target state is already in place".
REPLAYABLE_DDL_ERRORS = {
    1050: "table already exists",
    1060: "duplicate column name",
    1061: "duplicate key name",
    1091: "can't drop; object does not exist",
}


def _already_applied(error):
    code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    return code in REPLAYABLE_DDL_ERRORS
