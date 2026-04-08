from src.card_generator import RawCard
from src.deduplicator import deduplicate_cards, normalize_text, _extract_concept, _pick_winner


class TestNormalizeText:
    def test_lowercases(self):
        assert "hello world" == normalize_text("Hello WORLD")

    def test_strips_punctuation(self):
        assert "nfs" == normalize_text("What is NFS?")

    def test_removes_stopwords(self):
        result = normalize_text("What is the definition of NFS?")
        assert "what" not in result
        assert "nfs" in result
        assert "definition" in result

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_only_stopwords(self):
        assert normalize_text("the is a an") == ""


class TestDeduplicateCards:
    def test_empty_list(self):
        assert deduplicate_cards([]) == []

    def test_single_card(self):
        card = RawCard(front="What is NFS?", back="Network File System.", tags=["net"])
        assert deduplicate_cards([card]) == [card]

    def test_exact_duplicate_keeps_longer_answer(self):
        c1 = RawCard(front="What is NFS?", back="Network File System.", tags=[])
        c2 = RawCard(
            front="What is NFS?",
            back="Network File System developed by Sun Microsystems for sharing files.",
            tags=[],
        )
        result = deduplicate_cards([c1, c2])
        assert len(result) == 1
        assert result[0] is c2  # longer answer kept

    def test_near_duplicate_fronts_removed(self):
        c1 = RawCard(front="What is NFS used for?", back="Network File System.", tags=[])
        c2 = RawCard(
            front="What is NFS designed for?",
            back="NFS is the Network File System protocol.",
            tags=[],
        )
        result = deduplicate_cards([c1, c2], front_threshold=0.7)
        assert len(result) == 1

    def test_different_cards_both_kept(self):
        c1 = RawCard(front="What is NFS?", back="Network File System.", tags=[])
        c2 = RawCard(front="What is RPC?", back="Remote Procedure Call.", tags=[])
        result = deduplicate_cards([c1, c2])
        assert len(result) == 2

    def test_same_answer_different_question(self):
        c1 = RawCard(front="What is NFS?", back="Network File System for sharing files.", tags=[])
        c2 = RawCard(front="Define NFS protocol.", back="Network File System for sharing files.", tags=[])
        result = deduplicate_cards([c1, c2], back_threshold=0.85)
        assert len(result) == 1

    def test_three_cards_two_duplicates(self):
        c1 = RawCard(front="What is NFS?", back="Network File System.", tags=[])
        c2 = RawCard(front="What is RPC?", back="Remote Procedure Call.", tags=[])
        c3 = RawCard(front="What is NFS?", back="NFS stands for Network File System.", tags=[])
        result = deduplicate_cards([c1, c2, c3])
        assert len(result) == 2
        fronts = {c.front for c in result}
        assert "What is RPC?" in fronts


class TestExtractConcept:
    def test_strips_what_is(self):
        assert _extract_concept("What is NFS?") == "nfs"

    def test_strips_define(self):
        assert _extract_concept("Define NFS.") == "nfs"

    def test_preserves_remaining_words(self):
        result = _extract_concept("What does NFS stand for?")
        assert "nfs" in result
        assert "stand" in result

    def test_different_questions_different_concepts(self):
        c1 = _extract_concept("What is NFS?")
        c2 = _extract_concept("What is RPC?")
        assert c1 != c2


class TestPickWinner:
    def test_prefers_notes_over_transcript(self):
        notes_card = RawCard(front="What is NFS?", back="Short.", tags=[], source_type="notes")
        transcript_card = RawCard(front="What is NFS?", back="A much longer answer here.", tags=[], source_type="transcript")
        assert _pick_winner(notes_card, transcript_card) == 0
        assert _pick_winner(transcript_card, notes_card) == 1

    def test_prefers_longer_answer_same_source(self):
        short = RawCard(front="What is NFS?", back="NFS.", tags=[])
        long = RawCard(front="What is NFS?", back="Network File System for sharing.", tags=[])
        assert _pick_winner(short, long) == 1
        assert _pick_winner(long, short) == 0


class TestConceptAwareDedup:
    def test_same_concept_different_wording_deduped(self):
        c1 = RawCard(front="What is NFS?", back="Network File System for sharing files.", tags=[])
        c2 = RawCard(front="Define NFS.", back="Network File System for file sharing.", tags=[])
        result = deduplicate_cards([c1, c2])
        assert len(result) == 1

    def test_different_concepts_both_kept(self):
        c1 = RawCard(front="What is NFS?", back="Network File System.", tags=[])
        c2 = RawCard(front="How does NFS differ from SMB?", back="NFS is Unix, SMB is Windows.", tags=[])
        result = deduplicate_cards([c1, c2])
        assert len(result) == 2

    def test_cross_source_prefers_notes(self):
        transcript = RawCard(front="What is NFS?", back="Network File System.", tags=[], source_type="transcript")
        notes = RawCard(front="What is NFS?", back="Network File System.", tags=[], source_type="notes")
        result = deduplicate_cards([transcript, notes])
        assert len(result) == 1
        assert result[0].source_type == "notes"
