from __future__ import annotations

from pytest import MonkeyPatch

from liveclip.db import session as db_session


def test_init_db_is_idempotent_for_same_url(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeEngine:
        pass

    class FakeSessionMaker:
        pass

    def fake_create_async_engine(url: str, **_: object) -> FakeEngine:
        calls.append(url)
        return FakeEngine()

    def fake_sessionmaker(engine: object, **_: object) -> FakeSessionMaker:
        assert isinstance(engine, FakeEngine)
        return FakeSessionMaker()

    monkeypatch.setattr(db_session, "engine", None)
    monkeypatch.setattr(db_session, "async_session_factory", None)
    monkeypatch.setattr(db_session, "_database_url", None)
    monkeypatch.setattr(db_session, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db_session, "async_sessionmaker", fake_sessionmaker)

    db_session.init_db("mysql+asyncmy://example")
    first_engine = db_session.engine
    db_session.init_db("mysql+asyncmy://example")

    assert calls == ["mysql+asyncmy://example"]
    assert db_session.engine is first_engine

