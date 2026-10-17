import re

CONTEXT_BUDGET = 24000
CHUNK_SIZE = 1200
WORD = re.compile(r"\w{4,}", re.UNICODE)

def chunk_text(text, size=CHUNK_SIZE):
    """Bound chunks and retain source order, including text with no spaces."""
    if type(size) is not int or size < 1:
        raise ValueError("chunk size must be a positive integer")
    chunks, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current)
            current = ""
        while len(paragraph) > size:
            cut = paragraph.rfind(" ", 0, size + 1)
            if cut <= 0:
                cut = size
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if paragraph:
            current = (current + "\n\n" + paragraph).strip()
    if current:
        chunks.append(current)
    return chunks


def relevance(chunk, terms):
    """Share of the query vocabulary present in this chunk."""
    if not terms:
        return 0.0
    words = set(WORD.findall(chunk.lower()))
    return len(words & terms) / len(terms)

def select_context(sources, query, budget=CONTEXT_BUDGET):
    """Select relevant fragments within a strict total character budget.

    Reserve an opening fragment per source, account for separators, retain IDs
    even when the budget cannot fit every document. Never add unbudgeted tails.
    """
    # Full datasets/provenance stay in server storage; a text budget must never
    # accidentally forward their unbounded rows as extra JSON metadata.
    sources = [{k: v for k, v in source.items() if k not in {"datasets", "_analysis_results", "analysis_requests", "resolved_analysis_requests"}} for source in sources]
    if type(budget) is not int or budget < 0:
        raise ValueError("context budget must be a nonnegative integer")
    if budget == 0:
        return [{**source, "text": ""} for source in sources]
    if sum(len(source["text"]) for source in sources) <= budget:
        return [dict(source) for source in sources]
    count = max(1, sum(bool(source["text"].strip()) for source in sources))
    chunk_size = max(1, min(CHUNK_SIZE, budget // (count * 2)))
    terms = set(WORD.findall(query.lower()))
    separator = "\n\n[...]\n\n"
    kept = [dict() for _ in sources]
    candidates = []
    used = 0
    for index, source in enumerate(sources):
        chunks = chunk_text(source["text"], chunk_size)
        for position, text in enumerate(chunks):
            if position == 0 and used + len(text) <= budget:
                kept[index][position] = text
                used += len(text)
            else:
                candidates.append((relevance(text, terms), index, position, text))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for _, index, position, text in candidates:
        cost = len(text) + (len(separator) if kept[index] else 0)
        if used + cost <= budget:
            kept[index][position] = text
            used += cost
    return [{**source, "text": separator.join(text for _, text in sorted(parts.items()))}
            for source, parts in zip(sources, kept)]
