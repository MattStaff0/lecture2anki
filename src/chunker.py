"""Transcript chunking for LLM card generation."""

from __future__ import annotations

from dataclasses import dataclass

from src.models import Segment


@dataclass
class TranscriptChunk:
    """A group of segments combined into a single text block for the LLM."""

    text: str
    start_time: float
    end_time: float
    segment_count: int


def chunk_segments(
    segments: list[Segment],
    target_words: int = 800,
    max_words: int = 1200,
) -> list[TranscriptChunk]:
    """Group transcript segments into word-count-bounded chunks.

    Segments are accumulated until the target word count is reached. A new
    chunk starts when adding another segment would exceed max_words, or when
    the current chunk already meets the target.
    """
    if not segments:
        return []

    chunks: list[TranscriptChunk] = []
    current_texts: list[str] = []
    current_word_count = 0
    chunk_start = segments[0].start_time
    chunk_end = segments[0].end_time
    seg_count = 0

    for segment in segments:
        words_in_segment = len(segment.text.split())

        if current_word_count >= target_words and current_texts:
            chunks.append(
                TranscriptChunk(
                    text=" ".join(current_texts),
                    start_time=chunk_start,
                    end_time=chunk_end,
                    segment_count=seg_count,
                )
            )
            current_texts = []
            current_word_count = 0
            seg_count = 0
            chunk_start = segment.start_time

        if (
            current_word_count + words_in_segment > max_words
            and current_texts
        ):
            chunks.append(
                TranscriptChunk(
                    text=" ".join(current_texts),
                    start_time=chunk_start,
                    end_time=chunk_end,
                    segment_count=seg_count,
                )
            )
            current_texts = []
            current_word_count = 0
            seg_count = 0
            chunk_start = segment.start_time

        current_texts.append(segment.text)
        current_word_count += words_in_segment
        chunk_end = segment.end_time
        seg_count += 1

    if current_texts:
        chunks.append(
            TranscriptChunk(
                text=" ".join(current_texts),
                start_time=chunk_start,
                end_time=chunk_end,
                segment_count=seg_count,
            )
        )

    return chunks
