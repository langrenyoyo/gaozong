import importlib
import os
import sqlite3
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _reload_seed_module(monkeypatch, *, app_env: str = "development", extra_env: dict[str, str] | None = None):
    monkeypatch.setenv("APP_ENV", app_env)
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
    sys.modules.pop("scripts.seed_dev_data", None)
    return importlib.import_module("scripts.seed_dev_data")


def test_seed_dev_data_is_idempotent(monkeypatch):
    module = _reload_seed_module(monkeypatch)
    session = _make_session()

    first_summary = module.seed_dev_data(session)
    first_counts = {
        "staff": session.query(app.models.SalesStaff).count(),
        "lead": session.query(app.models.DouyinLead).count(),
        "check": session.query(app.models.ReplyCheck).count(),
        "authorized_account": session.query(app.models.DouyinAuthorizedAccount).count(),
        "binding": session.query(app.models.DouyinAccountAgentBinding).count(),
        "compute_account": session.query(app.models.ComputeAccount).count(),
        "compute_transaction": session.query(app.models.ComputeTransaction).count(),
        "compute_package": session.query(app.models.ComputePackage).count(),
        "ai_agent": session.query(app.models.AiAgent).count(),
    }

    second_summary = module.seed_dev_data(session)
    second_counts = {
        "staff": session.query(app.models.SalesStaff).count(),
        "lead": session.query(app.models.DouyinLead).count(),
        "check": session.query(app.models.ReplyCheck).count(),
        "authorized_account": session.query(app.models.DouyinAuthorizedAccount).count(),
        "binding": session.query(app.models.DouyinAccountAgentBinding).count(),
        "compute_account": session.query(app.models.ComputeAccount).count(),
        "compute_transaction": session.query(app.models.ComputeTransaction).count(),
        "compute_package": session.query(app.models.ComputePackage).count(),
        "ai_agent": session.query(app.models.AiAgent).count(),
    }

    assert first_summary["staff"]["created"] >= 3
    assert first_summary["leads"]["created"] >= 8
    assert first_counts == second_counts
    assert second_summary["staff"]["created"] == 0
    assert second_summary["leads"]["created"] == 0


def test_seed_dev_data_rejects_production_env(monkeypatch):
    module = _reload_seed_module(monkeypatch, app_env="production")
    session = _make_session()

    with pytest.raises(RuntimeError, match="生产环境"):
        module.seed_dev_data(session)


def test_seed_dev_data_does_not_autorun_on_import(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    sys.modules.pop("scripts.seed_dev_data", None)
    module = importlib.import_module("scripts.seed_dev_data")

    assert hasattr(module, "seed_dev_data")
    assert callable(module.seed_dev_data)
