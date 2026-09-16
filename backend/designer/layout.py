"""Shared geometry model for editing, audit and native export. Units: points."""

import copy
import math

from .parsing import best_text_color

DEFAULT_SAFE_AREA = {"x": 0.055, "y": 0.055, "w": 0.89, "h": 0.825}
DEFAULT_MARGINS = {"x": 0.04, "y": 0.04, "w": 0.92, "h": 0.9}


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
    candidates = [
        p
        for p in template["patterns"]
        if p["text_slots"] >= 2
        and p.get("title_box")
        and p["title_box"]["y"] < 0.2
        and p["title_box"]["w"] > 0.65
    ] or template["patterns"]
    # Prefer reusable content pages over covers, speaker cards, and icon catalogues.
    candidates = sorted(
        candidates,
        key=lambda p: (p.get("decoration_area", 0), abs(p["text_slots"] - 4)),
    )
    for i, content in enumerate(outline["slides"]):
        best = [
            p
            for p in candidates
            if p.get("decoration_area", 0)
            <= candidates[0].get("decoration_area", 0) + 0.015
        ]
        pattern = best[i % len(best)]
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
            else:
                pivot = math.ceil(len(bullets) / 2)
                text_box("body_left", bullets[:pivot], [margin, top, bw, h])
                text_box("body_right", bullets[pivot:], [margin + bw + gap, top, bw, h])
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
                "layout_index": pattern["layout_index"],
                "content": copy.deepcopy(content),
                "elements": elements,
            }
        )
    return {"width": width, "height": height, "variant": variant, "slides": slides}
