from src.chunker import chunk_segments
from src.models import Segment


class TestChunker:
    def test_chunk_segments_groups_ordered_text(self):
        segments = [
            Segment(id=1, lecture_id=1, start_time=0.0, end_time=5.0, text="one two"),
            Segment(id=2, lecture_id=1, start_time=5.0, end_time=10.0, text="three four"),
            Segment(id=3, lecture_id=1, start_time=10.0, end_time=15.0, text="five six seven"),
        ]

        chunks = chunk_segments(segments, target_words=4, max_words=5)

        assert len(chunks) == 2
        assert chunks[0].text == "one two three four"
        assert chunks[0].start_time == 0.0
        assert chunks[0].end_time == 10.0
        assert chunks[1].text == "five six seven"

    def test_chunk_segments_returns_empty_for_no_segments(self):
        assert chunk_segments([], target_words=10, max_words=20) == []

