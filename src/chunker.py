"""Transcript chunking helpers."""

from __future__ import annotations

from dataclasses import dataclass

from src.models import Segment


@dataclass
class TranscriptChunk:
    """A chunk of transcript text passed to the card generator."""

    start_time: float
    end_time: float
    text: str
    word_count: int


def chunk_segments(
    segments: list[Segment],
    target_words: int,
    max_words: int,
) -> list[TranscriptChunk]:
    """Group ordered transcript segments into LLM-sized text chunks."""
    if not segments:
        return []

    chunks: list[TranscriptChunk] = []
    current_segments: list[Segment] = []
    current_word_count = 0

    for segment in segments:
        segment_word_count = len(segment.text.split())
        exceeds_limit = current_segments and current_word_count + segment_word_count > max_words

        if exceeds_limit:
            chunks.append(_build_chunk(current_segments))
            current_segments = []
            current_word_count = 0

        current_segments.append(segment)
        current_word_count += segment_word_count

        if current_word_count >= target_words:
            chunks.append(_build_chunk(current_segments))
            current_segments = []
            current_word_count = 0

    if current_segments:
        chunks.append(_build_chunk(current_segments))

    return chunks


def _build_chunk(segments: list[Segment]) -> TranscriptChunk:
    """Convert a set of segments into a chunk object."""
    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    return TranscriptChunk(
        start_time=segments[0].start_time,
        end_time=segments[-1].end_time,
        text=text,
        word_count=len(text.split()),
    )
