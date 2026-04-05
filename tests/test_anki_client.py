import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.anki_client import SyncResult, add_note, check_connection, ensure_deck, sync_lecture
from src.db import (
    approve_card,
    create_card,
    create_course,
    create_lecture,
    create_unit,
    get_card_by_id,
    init_db,
)
from src.models import Card


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()


class TestCheckConnection:
    @patch("src.anki_client._anki_request", return_value=6)
    def test_returns_true_when_reachable(self, mock_req):
        assert check_connection() is True

    @patch("src.anki_client._anki_request", side_effect=RuntimeError("unreachable"))
    def test_returns_false_when_unreachable(self, mock_req):
        assert check_connection() is False


class TestEnsureDeck:
    @patch("src.anki_client._anki_request")
    def test_calls_create_deck(self, mock_req):
        ensure_deck("AI::Midterm 1")
        mock_req.assert_called_once_with("createDeck", deck="AI::Midterm 1")


class TestSyncLecture:
    @patch("src.anki_client._anki_request")
    def test_syncs_approved_cards(self, mock_req, db):
        mock_req.return_value = 99999

        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        card1 = create_card(db, lecture.id, "Q1", "A1", ["t1"])
        card2 = create_card(db, lecture.id, "Q2", "A2", ["t2"])
        approve_card(db, card1.id)
        approve_card(db, card2.id)

        result = sync_lecture(db, lecture.id)

        assert result.synced == 2
        assert result.failed == 0

        synced_card = get_card_by_id(db, card1.id)
        assert synced_card.synced_to_anki is True
        assert synced_card.anki_note_id == 99999

    @patch("src.anki_client._anki_request")
    def test_handles_partial_failure(self, mock_req, db):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if args[0] == "addNote" and call_count > 2:
                raise RuntimeError("Anki error")
            return 88888

        mock_req.side_effect = side_effect

        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        card1 = create_card(db, lecture.id, "Q1", "A1", [])
        card2 = create_card(db, lecture.id, "Q2", "A2", [])
        approve_card(db, card1.id)
        approve_card(db, card2.id)

        result = sync_lecture(db, lecture.id)

        assert result.synced == 1
        assert result.failed == 1
        assert len(result.errors) == 1

    def test_raises_when_no_approved_cards(self, db):
        course = create_course(db, "AI")
        unit = create_unit(db, course.id, "Midterm 1")
        lecture = create_lecture(db, unit.id)
        create_card(db, lecture.id, "Q1", "A1", [])

        with pytest.raises(ValueError, match="No approved unsynced"):
            sync_lecture(db, lecture.id)
