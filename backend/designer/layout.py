"""Shared geometry model for editing, audit and native export. Units: points."""

import copy
import math

from .parsing import best_text_color

DEFAULT_SAFE_AREA = {"x": 0.055, "y": 0.055, "w": 0.89, "h": 0.825}
DEFAULT_MARGINS = {"x": 0.04, "y": 0.04, "w": 0.92, "h": 0.9}
# Below this a two-column split leaves both columns nearly empty.
MIN_BULLETS_FOR_COLUMNS = 4


def content_demand(content):
    """How much room this slide needs and what kind of room."""
    bullets = content["bullets"]
    return {
        "lines": sum(1 + len(b) // 60 for b in bullets),
        "has_visual": content["visual"]["kind"] != "none",
        "title_length": len(content["title"]),
    }


# Band where composed content actually lands; branding here is what collides.
CONTENT_BAND = (0.05, 0.22, 0.95, 0.9)


def free_area(pattern):
    """Share of the slide left for content once template branding is placed."""
    used = sum(b["w"] * b["h"] for b in pattern.get("reserved", []))
    return max(0.0, 1.0 - min(1.0, used))


def branding_in_band(pattern):
    """Branding area that sits where the content will go, as a slide fraction.

    A logo in the corner costs nothing; a decorative panel across the middle of
    the page makes every block on that pattern collide with the template.
    """
    left, top, right, bottom = CONTENT_BAND
    total = 0.0
    for box in pattern.get("reserved", []):
        overlap_w = max(0.0, min(box["x"] + box["w"], right) - max(box["x"], left))
        overlap_h = max(0.0, min(box["y"] + box["h"], bottom) - max(box["y"], top))
        total += overlap_w * overlap_h
    return round(total, 5)


def candidate_patterns(patterns):
    """Content pages a new slide can be built on, best first.

    Strict picks are full-width title pages. Some templates carry only one such
    slide, so the pool is widened until there is something to choose from:
    repeating one pattern twelve times is a worse outcome than a looser match.
    """

    def usable(pattern, min_slots, max_title_y, min_title_w):
        box = pattern.get("title_box")
        return bool(
            pattern["text_slots"] >= min_slots
            and box
            and box["y"] < max_title_y
            and box["w"] > min_title_w
        )

    for rule in ((2, 0.2, 0.65), (2, 0.3, 0.45), (1, 0.45, 0.3)):
        found = [p for p in patterns if usable(p, *rule)]
        if len(found) >= 3:
            return found
    return [p for p in patterns if p.get("title_box")] or patterns


def score_pattern(pattern, demand, recent, uses=0):
    """Rank a template pattern for one slide.

    Selection must be explainable on stage: a busy pattern loses points when the
    slide is dense, a pattern with room wins when a chart has to fit, and repeating
    the neighbour's pattern is penalised so the deck does not look like one slide
    printed twelve times.
    """
    dense = demand["has_visual"] or demand["lines"] > 4
    score = 1.0
    score -= pattern.get("decoration_area", 0.0) * (2.4 if dense else 0.8)
    score -= branding_in_band(pattern) * 2.0
    score += free_area(pattern) * (0.5 if demand["has_visual"] else 0.2)
    score += 0.05 * min(pattern.get("text_slots", 0), 4)
    title_box = pattern.get("title_box")
    if title_box:
        score += 0.12 if title_box["w"] > 0.6 else 0.0
        # A shallow title band cannot hold a long conclusion-style headline.
        if demand["title_length"] > 60 and title_box["h"] < 0.1:
            score -= 0.15
    if recent and pattern["index"] == recent[-1]:
        score -= 0.6
    # Reuse is allowed, but every repeat costs more, so a deck spreads over the
    # patterns the template actually offers.
    score -= 0.22 * uses
    return round(score, 6)


def choose_pattern(candidates, content, recent, usage=None):
    demand = content_demand(content)
    usage = usage or {}
    scored = [
        (score_pattern(p, demand, recent, usage.get(p["index"], 0)), -p["index"], p)
        for p in candidates
    ]
    # Deterministic: equal scores resolve by the lowest pattern index.
    best = max(scored, key=lambda item: (item[0], item[1]))
    return best[2], best[0]


def compose(outline, template, variant):
    width, height = template["width"] / 12700, template["height"] / 12700
    tokens = template["tokens"]
    geometry = template.get("geometry", {})
    safe = geometry.get("safe_area") or DEFAULT_SAFE_AREA
    margins = geometry.get("margins") or DEFAULT_MARGINS
    font = next(
        (f for f in tokens["fonts"] if f not in ("Wingdings", "Symbol")), "Arial"
    )
    palette = tokens["colors"] or ["000000", "FFFFFF"]
    # Use the template's type scale, bounded by physical slide height.
    scale = [s for s in tokens["font_sizes"] if 10 <= s <= 60]
    title_size = min(scale, key=lambda s: abs(s - height * 0.075)) if scale else 28
    body_size = min(scale, key=lambda s: abs(s - height * 0.045)) if scale else 18
    accent = tokens["theme"].get("accent1", palette[0])
    slides = []
    candidates = candidate_patterns(template["patterns"])
    # Prefer reusable content pages over covers, speaker cards, and icon catalogues.
    candidates = sorted(
        candidates,
        key=lambda p: (p.get("decoration_area", 0), abs(p["text_slots"] - 4)),
    )
    recent: list[int] = []
    usage: dict[int, int] = {}
    for i, content in enumerate(outline["slides"]):
        pattern, pattern_score = choose_pattern(candidates, content, recent, usage)
        recent = [*recent, pattern["index"]][-3:]
        usage[pattern["index"]] = usage.get(pattern["index"], 0) + 1
        # Margins come from the template's own safe area, not from constants, so an
        # unseen template keeps its own rhythm.
        right = width * min(1.0, safe["x"] + safe["w"])
        title_box = pattern.get("title_box")
        if title_box and title_box["y"] < 0.25 and title_box["w"] > 0.35:
            # Honour the template's title indent, but apply it to every block on the
            # slide: mismatched left edges are the misalignment the audit looks for.
            margin = min(max(width * safe["x"], width * title_box["x"]), width * 0.25)
            ty = max(height * margins["y"], height * title_box["y"])
            tw = min(right - margin, width * title_box["w"])
        else:
            margin = width * safe["x"]
            ty, tw = height * safe["y"], right - margin
        tx = margin
        # Compose around branding the template keeps on every slide: narrow the
        # title away from a corner logo, and drop below a full-width wordmark.
        reserved = [
            (width * b["x"], height * b["y"], width * b["w"], height * b["h"])
            for b in pattern.get("reserved", [])
        ]
        for bx, by, _, bh in reserved:
            if by < height * 0.3 and tx + tw * 0.35 < bx < tx + tw:
                tw = max(width * 0.3, bx - width * 0.012 - tx)
        current_title_size = title_size

        def title_height(size, title_width=tw, title_text=content["title"]):
            chars = max(1, (title_width - 12) / (size * 0.60))
            return math.ceil(len(title_text) / chars) * size * 1.3 + 10

        for size in sorted({s for s in scale if s <= title_size}, reverse=True):
            current_title_size = size
            if title_height(size) <= height * 0.21:
                break
        th = max(height * 0.12, title_height(current_title_size))
        for bx, by, bw, bh in reserved:
            if by < ty + th and by + bh > ty and bx < tx + tw and bx + bw > tx:
                ty = min(height * 0.35, max(ty, by + bh + height * 0.02))
        top = max(height * 0.26, ty + th + height * 0.035)
        bottom = height * min(1.0, safe["y"] + safe["h"])
        w, h, gap = right - margin, bottom - top, width * 0.03
        elements = [
            {
                "id": "title",
                "kind": "text",
                "role": "title",
                "text": content["title"],
                "box": [tx, ty, tw, th],
                "font_size": current_title_size,
            }
        ]
        bullets = content["bullets"]
        visual = content["visual"]
        has_visual = visual["kind"] != "none"

        def text_box(identifier, items, box, elements=elements):
            if items:
                elements.append(
                    {
                        "id": identifier,
                        "kind": "text",
                        "role": "body",
                        "text": "\n".join("• " + s for s in items),
                        "box": box,
                        "font_size": body_size,
                    }
                )

        if variant == "split":
            bw = (w - gap) / 2
            if has_visual:
                text_box("body", bullets, [margin, top, bw, h])
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin + bw + gap, top, bw, h],
                        "data": visual,
                    }
                )
            elif len(bullets) >= MIN_BULLETS_FOR_COLUMNS:
                pivot = math.ceil(len(bullets) / 2)
                text_box("body_left", bullets[:pivot], [margin, top, bw, h])
                text_box("body_right", bullets[pivot:], [margin + bw + gap, top, bw, h])
            else:
                # Two thin columns holding one line each read as an empty slide and
                # the audit flags them. Few bullets stay in one full-width block.
                text_box("body", bullets, [margin, top, w, h])
        elif has_visual:
            text_h = (
                min(
                    h * 0.4,
                    sum(
                        max(1, math.ceil(len(b) / (w / (body_size * 0.55))))
                        for b in bullets
                    )
                    * body_size
                    * 1.3
                    + 12,
                )
                if bullets
                else 0
            )
            visual_h = h - text_h - (height * 0.025 if bullets else 0)
            if variant == "focus":
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin, top, w, visual_h],
                        "data": visual,
                    }
                )
                text_box("body", bullets, [margin, bottom - text_h, w, text_h])
            else:
                text_box("body", bullets, [margin, top, w, text_h])
                elements.append(
                    {
                        "id": "visual",
                        "kind": visual["kind"],
                        "box": [margin, bottom - visual_h, w, visual_h],
                        "data": visual,
                    }
                )
        elif variant == "focus" and bullets:
            text_box("lead", bullets[:1], [margin + w * 0.1, top, w * 0.8, h * 0.3])
            text_box(
                "body",
                bullets[1:],
                [margin + w * 0.1, top + h * 0.36, w * 0.8, h * 0.64],
            )
        else:
            text_box("body", bullets, [margin, top, w, h])
        # Resolve the text color once, against this slide's real background, so
        # layout, export and the contrast audit all agree on what will be rendered.
        background = pattern.get("background") or tokens["theme"].get("lt1", "FFFFFF")
        text_color = best_text_color(background, palette)
        for element in elements:
            element.update(font=font, color=text_color, accent=accent)
        slides.append(
            {
                "background": background,
                "index": i,
                "pattern_index": pattern["index"],
                # Kept so the UI and the pitch can answer "why this layout?".
                "pattern_choice": {
                    "score": pattern_score,
                    "decoration_area": pattern.get("decoration_area", 0.0),
                    "free_area": round(free_area(pattern), 5),
                    "branding_in_band": branding_in_band(pattern),
                    "text_slots": pattern.get("text_slots", 0),
                },
                "layout_index": pattern["layout_index"],
                "content": copy.deepcopy(content),
                "elements": elements,
            }
        )
    return {"width": width, "height": height, "variant": variant, "slides": slides}
