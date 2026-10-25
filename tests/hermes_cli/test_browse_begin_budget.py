"""Regression for browse DDL budget expiry during BEGIN IMMEDIATE.

The SQLite VM may interrupt BEGIN itself on a slow filesystem. The browse
path must roll back and map the timed-out SQLite operation to the typed
BrowseBudgetExceeded instead of a misleading generic schema-corrupt 503.
"""
from pathlib import Path
import sqlite3

import pytest

from hermes_state_reconcile import BrowseBudgetExceeded, _apply_additive_schema


@pytest.mark.parametrize("expired", [True, False])
def test_interrupted_begin_is_budget_error_only_after_deadline(monkeypatch, expired):
    class Budget:
        def __init__(self):
            self.expired = False

        def check(self):
            pass

        def busy_timeout(self):
            return 0.1

        def arm(self, conn):
            pass

    budget = Budget()

    class FakeConnection:
        def __init__(self):
            self.operations = []

        def execute(self, sql):
            self.operations.append(sql)
            if sql == "BEGIN IMMEDIATE":
                budget.expired = expired
                raise sqlite3.OperationalError("interrupted")
            raise sqlite3.OperationalError("cannot rollback: no transaction is active")

        def close(self):
            pass

    connection = FakeConnection()
    monkeypatch.setattr(
        "hermes_cli.sqlite_safe_read.connect_tracked", lambda *args, **kwargs: connection
    )
    monkeypatch.setattr(
        "hermes_state_repair._reapply_durability_barriers", lambda conn: None
    )
    exc_type = BrowseBudgetExceeded if expired else sqlite3.OperationalError
    with pytest.raises(exc_type):
        _apply_additive_schema(Path("synthetic-state.db"), budget)
    assert connection.operations == ["BEGIN IMMEDIATE", "ROLLBACK"]
