"""Migration bookkeeping failures; no database or container is started here."""

from hashlib import sha256
import unittest
from unittest.mock import MagicMock, patch

from smartlect.migrate import migrate, migration_files


class MigrationTests(unittest.TestCase):
    def connection(self, applied=()):
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = {"acquired": 1}
        cursor.fetchall.return_value = list(applied)
        return connection, cursor

    def test_packaged_sql_and_checksum_mismatch_before_migration_execution(self):
        migrations = migration_files()
        self.assertEqual([row[0] for row in migrations][:4],
                         ["0001_ledger.sql", "0002_agent_state.sql", "0003_knowledge_memory.sql",
                          "0004_knowledge_index_attempt.sql"])
        for _, checksum, source in migrations:
            self.assertEqual(checksum, sha256(source.encode()).hexdigest())
        connection, cursor = self.connection([{"name": "0001_ledger.sql", "checksum": "0" * 64}])
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            migrate(lambda: connection)
        self.assertFalse(any("commerce_event" in call.args[0] for call in cursor.execute.call_args_list))
        connection.rollback.assert_called_once()
        self.assertIn("RELEASE_LOCK", cursor.execute.call_args.args[0])

    def test_failed_ddl_has_no_receipt_and_success_replays_owned_statements(self):
        source = "CREATE TABLE IF NOT EXISTS first_table (id INT);\n-- statement-break\nCREATE TABLE IF NOT EXISTS second_table (id INT);"
        migration = ("0001_probe.sql", sha256(source.encode()).hexdigest(), source)
        connection, cursor = self.connection()

        def fail_second(statement, *args):
            if "CREATE TABLE IF NOT EXISTS second_table" in statement:
                raise RuntimeError("injected DDL failure")

        cursor.execute.side_effect = fail_second
        with patch("smartlect.migrate.migration_files", return_value=[migration]):
            with self.assertRaisesRegex(RuntimeError, "injected DDL failure"):
                migrate(lambda: connection)
        self.assertFalse(any("INSERT INTO schema_migration" in call.args[0] for call in cursor.execute.call_args_list))
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        cursor.reset_mock()
        cursor.execute.side_effect = None
        with patch("smartlect.migrate.migration_files", return_value=[migration]):
            migrate(lambda: connection)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS first_table" in sql for sql in statements))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS second_table" in sql for sql in statements))
        self.assertEqual(sum("INSERT INTO schema_migration" in sql for sql in statements), 1)
        connection.commit.assert_called_once()

    def test_late_older_migration_is_rejected_but_newer_version_can_append(self):
        existing = migration_files()
        applied = [{"name": name, "checksum": checksum} for name, checksum, _ in existing]
        source = "CREATE TABLE IF NOT EXISTS forward_probe (id INT);"
        checksum = sha256(source.encode()).hexdigest()
        connection, cursor = self.connection(applied)
        with patch("smartlect.migrate.migration_files", return_value=[("0000_late.sql", checksum, source), *existing]):
            with self.assertRaisesRegex(RuntimeError, "forward-only"):
                migrate(lambda: connection)
        self.assertFalse(any("forward_probe" in call.args[0] or "INSERT INTO schema_migration" in call.args[0]
                             for call in cursor.execute.call_args_list))
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        self.assertIn("RELEASE_LOCK", cursor.execute.call_args.args[0])

        connection, cursor = self.connection(applied)
        next_name = f"{max(int(name[:4]) for name, _, _ in existing) + 1:04d}_next.sql"
        with patch("smartlect.migrate.migration_files", return_value=[*existing, (next_name, checksum, source)]):
            migrate(lambda: connection)
        self.assertEqual(sum("forward_probe" in call.args[0] for call in cursor.execute.call_args_list), 1)
        receipts = [call for call in cursor.execute.call_args_list if "INSERT INTO schema_migration" in call.args[0]]
        self.assertEqual([call.args[1] for call in receipts], [(next_name, checksum)])
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
