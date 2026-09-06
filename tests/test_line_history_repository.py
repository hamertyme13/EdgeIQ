from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from repository.database import Base
from repository.models.prop_line_history_model import PropLineHistoryModel
from repository.repositories import line_history_repository as line_module
from repository.repositories.line_history_repository import LineHistoryRepository


def test_record_many_queries_exact_player_stat_platform_markets(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'lines.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(line_module, "SessionLocal", session_local)
    Base.metadata.create_all(engine)
    with session_local() as session:
        session.add_all([
            PropLineHistoryModel(player="Arch Manning", stat="Pass Yards", platform="PrizePicks", line=280.5),
            PropLineHistoryModel(player="Other Player", stat="Rush Yards", platform="PrizePicks", line=55.5),
        ])
        session.commit()

    statements = []
    event.listen(engine, "before_cursor_execute", lambda _conn, _cursor, statement, *_args: statements.append(statement))

    saved = LineHistoryRepository.record_many([
        {"player": "Arch Manning", "stat": "Pass Yards", "platform": "PrizePicks", "line": 281.5},
        {"player": "Other Player", "stat": "Rush Yards", "platform": "PrizePicks", "line": 56.5},
    ])

    assert saved == 2
    history_selects = [statement for statement in statements if "FROM prop_line_history" in statement]
    assert history_selects
    assert any("VALUES" in statement and "player" in statement for statement in history_selects)
