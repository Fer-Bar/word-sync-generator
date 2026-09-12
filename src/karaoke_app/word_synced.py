"""Measured, independently animated words for the Plus lyrics video preset."""

from typing import Any

from PIL import ImageFont

from karaoke_app.lyrics_plus import switzer_font
from karaoke_app.style import StyleConfig


def _wrap_words(words: list[dict[str, Any]], font: ImageFont.FreeTypeFont, width: float):
    rows: list[list[tuple[dict[str, Any], float, float]]] = [[]]
    cursor = 0.0
    space = font.getlength(" ")
    for word in words:
        text = str(word["text"]).strip()
        length = font.getlength(text)
        if cursor and cursor + length > width:
            rows.append([])
            cursor = 0.0
        rows[-1].append(({**word, "text": text}, cursor, length))
        cursor += length + space
    return rows


def _groups(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from karaoke_app.ass import _page_lanes, _to_centiseconds

    lines = [line for _, lane in _page_lanes({"lines": segments}) for line in lane["lines"]]
    lines.sort(key=lambda line: min(word["start"] for word in line["words"]))
    groups: list[dict[str, Any]] = []
    for line in lines:
        start = _to_centiseconds(min(word["start"] for word in line["words"]))
        end = _to_centiseconds(max(word["end"] for word in line["words"]))
        if groups and start < groups[-1]["end"]:
            groups[-1]["lines"].append(line)
            groups[-1]["end"] = max(end, groups[-1]["end"])
        else:
            groups.append({"lines": [line], "start": start, "end": max(start + 1, end)})
    for index, group in enumerate(groups):
        group["display_start"] = max(0, group["start"] - 35)
        group["display_end"] = group["end"] + 35
        if index and groups[index - 1]["display_end"] > group["display_start"]:
            boundary = (groups[index - 1]["end"] + group["start"]) // 2
            groups[index - 1]["display_end"] = boundary
            group["display_start"] = boundary
    return groups


def _layout(group, font_path, size, available, height, line_gap):
    while True:
        font = ImageFont.truetype(str(font_path), size)
        layouts = [(line, _wrap_words(line["words"], font, available)) for line in group["lines"]]
        row_count = sum(len(rows) for _, rows in layouts)
        gap = size * line_gap
        longest = max((length for _, rows in layouts for row in rows for _, _, length in row), default=0)
        if size <= 8 or (row_count * gap < height * 0.48 and longest <= available):
            return layouts, size, gap, row_count
        size -= 1


def _fixed_pages(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from karaoke_app.ass import _build_pages, _page_lanes

    return [{"lines": [line for _, lane in _page_lanes(page) for line in lane["lines"]],
             "start": page["source_start_cs"], "end": page["karaoke_end_cs"],
             "display_start": page["display_start_cs"], "display_end": page["display_end_cs"]}
            for page in _build_pages(segments)]


def _row_line(row) -> dict[str, Any]:
    words = []
    for original, _, _ in row:
        word = dict(original)
        if word.get("timing"):
            fragments = [dict(fragment) for fragment in word["timing"]]
            fragments[0]["text"] = fragments[0]["text"].lstrip()
            fragments[-1]["text"] = fragments[-1]["text"].rstrip()
            word["timing"] = fragments
        words.append(word)
    return {"words": words}


def _animated_row_text(line: dict[str, Any], start_cs: int) -> tuple[str, int]:
    """Pulse each word vertically around the fixed row baseline, keeping its advance width."""
    from karaoke_app.ass import _escape_ass_text, _schedule_words, _word_fragments

    words = line["words"]
    starts, durations, scheduled_end = _schedule_words(words, start_cs)
    cursor = start_cs
    parts = []
    for index, (word, start, duration) in enumerate(zip(words, starts, durations, strict=True)):
        if index:
            parts.append(r"{\fscy100} ")
        onset = (start - start_cs) * 10
        peak = onset + min(200, duration * 10)
        settle = (start + duration - start_cs) * 10 + 180
        parts.append(f"{{\\fscy100\\t({onset},{peak},\\fscy109)\\t({peak},{settle},\\fscy100)}}")
        if start > cursor:
            parts.append(f"{{\\k{start - cursor}}}")
        for text, fragment_duration in _word_fragments(word, duration):
            parts.append(f"{{\\kf{fragment_duration}}}{_escape_ass_text(text)}")
        cursor = start + duration
    return "".join(parts), scheduled_end


def build_word_synced_dialogues(
    segments: list[dict[str, Any]], width: int, height: int, style: StyleConfig, *, scroll: bool = True,
) -> list[str]:
    """Use identical shaped rows for active/context text, with optional scrolling."""
    from karaoke_app.ass import _ass_timestamp, _escape_ass_text, _to_centiseconds

    font_path = switzer_font()
    events = []
    margin = min(style.margin_h, width * 0.2)
    groups = _groups(segments) if scroll else _fixed_pages(segments)

    def event(start, end, tags, text, layer=1):
        if end > start:
            events.append(f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},"
                          f"Default,,0,0,0,,{{{tags}}}{text}")

    for index, group in enumerate(groups):
        layouts, size, gap, row_count = _layout(
            group, font_path, style.font_size, width - 2 * margin, height, style.line_gap_factor,
        )
        y = (height - row_count * gap) / 2 + size
        start_cs, end_cs = group["display_start"], group["display_end"]
        previous = groups[index - 1] if index else None
        following = groups[index + 1] if index + 1 < len(groups) else None
        connected_before = scroll and previous is not None and group["start"] - previous["end"] < 150
        connected_after = scroll and following is not None and following["start"] - group["end"] < 150
        entry_ms = min(300, (group["start"] - start_cs) * 10)
        base = f"\\an1\\fnSwitzer Semibold\\b0\\i0\\fs{size}\\bord0\\shad1\\q2"
        row_index = 0
        for line, rows in layouts:
            line_end = max(1, (_to_centiseconds(max(w["end"] for w in line["words"])) - start_cs) * 10)
            for row in rows:
                normalized = _row_line(row)
                plain = _escape_ass_text(" ".join(word["text"] for word in normalized["words"]))
                if row_index < 2:
                    context = plain + (" …" if row_index == 1 and row_count > 2 else "")
                    preview_y = height * 0.79 + row_index * gap + size
                    if connected_before:
                        event(max(previous["display_start"], start_cs - 300), start_cs,
                              f"{base}\\pos({margin:.2f},{preview_y:.2f})\\1c&HFFFFFF&"
                              "\\alpha&H57&\\fad(150,0)", context, 0)
                    if connected_after:
                        history_y = height * 0.10 + row_index * gap + size
                        event(end_cs, min(following["display_end"], end_cs + 250),
                              f"{base}\\move({margin:.2f},{y:.2f},{margin:.2f},{history_y:.2f},0,300)"
                              f"\\1c&HFFFFFF&\\alpha&HAA&\\blur{size * 2.5 / 48:.2f}\\fad(0,200)", context, 0)
                position = f"\\pos({margin:.2f},{y:.2f})"
                if connected_before:
                    start_y = height * 0.79 + row_index * gap + size
                    position = (f"\\move({margin:.2f},{start_y:.2f},{margin:.2f},{y:.2f},"
                                f"0,{max(1, entry_ms)})")
                tags = (f"{base}{position}\\1c&HFFFFFF&\\2c&HA8A8A8&\\alpha&H00&\\fad(150,150)"
                        f"\\t({line_end},{line_end + 500},\\alpha&HAA&\\blur{size * 2.5 / 48:.2f})")
                # A bottom anchor keeps neighboring words still while the sung word grows upward.
                text, scheduled_end = _animated_row_text(normalized, start_cs)
                event(start_cs, max(end_cs, scheduled_end), tags, text)
                y += gap
                row_index += 1
    return events
