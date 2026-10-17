"""Compatibility imports. Implementations live in algorithms, ai and pipeline."""
from .workflow import PROMPTS, workflow, narrative, narrative_beats
from .ai import (InvalidCompletion, provider, message_text, parse_json, ask,
                 vision_provider, vision_available, ask_vision, image_provider,
                 image_available, draw_image, vision_completion, completion,
                 MAX_ATTEMPTS, RETRY_DELAY)
from .algorithms.content import (fit_schema_limits, beat_title, topic_title, strip_beat,
    numbers_in, known_numbers, tidy_label, tidy_visual, tidy_line, unsupported_numbers,
    number_label, fabricated_chart, same_text, repeated_items, drop_repeats)
from .algorithms.context import chunk_text, relevance, select_context
from .algorithms.balance import outline_overflow, trim_slide
from .sources import sources_for
from .pipeline import balance_outline, generate_outline
