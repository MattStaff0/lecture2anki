"""Transcript and notes chunking for LLM card generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.models import Segment


@dataclass
class TranscriptChunk:
    """A group of segments or notes combined into a single text block for the LLM."""

    text: str
    start_time: float
    end_time: float
    segment_count: int
    source_type: str = "transcript"  # "transcript" or "notes"


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
                    source_type="transcript",
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
                    source_type="transcript",
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
                source_type="transcript",
            )
        )

    return chunks


_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def chunk_text(
    text: str,
    target_words: int = 800,
    max_words: int = 1200,
) -> list[TranscriptChunk]:
    """Split plain text into word-count-bounded chunks for LLM card generation.

    Splits on paragraph boundaries first, then accumulates paragraphs until
    the target word count is reached. Falls back to sentence splitting for
    very long paragraphs.
    """
    text = text.strip()
    if not text:
        return []

    # Split into paragraphs, filter empties
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text)]
    paragraphs = [p for p in paragraphs if p]

    # If no paragraph breaks, treat each line as a paragraph
    if len(paragraphs) == 1 and "\n" in text:
        paragraphs = [p.strip() for p in text.split("\n")]
        paragraphs = [p for p in paragraphs if p]

    chunks: list[TranscriptChunk] = []
    current_texts: list[str] = []
    current_word_count = 0

    for para in paragraphs:
        words_in_para = len(para.split())

        if current_word_count >= target_words and current_texts:
            chunks.append(
                TranscriptChunk(
                    text="\n\n".join(current_texts),
                    start_time=0.0,
                    end_time=0.0,
                    segment_count=0,
                    source_type="notes",
                )
            )
            current_texts = []
            current_word_count = 0

        if current_word_count + words_in_para > max_words and current_texts:
            chunks.append(
                TranscriptChunk(
                    text="\n\n".join(current_texts),
                    start_time=0.0,
                    end_time=0.0,
                    segment_count=0,
                    source_type="notes",
                )
            )
            current_texts = []
            current_word_count = 0

        current_texts.append(para)
        current_word_count += words_in_para

    if current_texts:
        chunks.append(
            TranscriptChunk(
                text="\n\n".join(current_texts),
                start_time=0.0,
                end_time=0.0,
                segment_count=0,
                source_type="notes",
            )
        )

    return chunks
