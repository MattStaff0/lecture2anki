import pytest

from src.chunker import chunk_segments
from src.models import Segment
from datetime import datetime


def _seg(start: float, end: float, text: str) -> Segment:
    return Segment(id=0, lecture_id=1, start_time=start, end_time=end, text=text)


class TestChunkSegments:
    def test_empty_segments(self):
        assert chunk_segments([]) == []

    def test_single_short_segment(self):
        segs = [_seg(0, 10, "Hello world")]
        chunks = chunk_segments(segs, target_words=100, max_words=200)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].segment_count == 1

    def test_chunks_split_at_target(self):
        words = " ".join(["word"] * 50)
        segs = [_seg(i * 10, (i + 1) * 10, words) for i in range(4)]
        chunks = chunk_segments(segs, target_words=100, max_words=200)
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.segment_count == 2

    def test_chunks_respect_max(self):
        words_90 = " ".join(["word"] * 90)
        words_60 = " ".join(["word"] * 60)
        segs = [
            _seg(0, 10, words_90),
            _seg(10, 20, words_60),
            _seg(20, 30, words_60),
        ]
        chunks = chunk_segments(segs, target_words=80, max_words=100)
        assert len(chunks) == 3

    def test_timestamps_preserved(self):
        segs = [
            _seg(5.0, 10.0, "first segment"),
            _seg(10.0, 20.0, "second segment"),
        ]
        chunks = chunk_segments(segs, target_words=1000, max_words=2000)
        assert len(chunks) == 1
        assert chunks[0].start_time == 5.0
        assert chunks[0].end_time == 20.0
