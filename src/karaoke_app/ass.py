import unicodedata
from typing import Any

MAX_LYRIC_LINES_PER_PAGE = 3
PAGE_BREAK_SILENCE_SECONDS = 1.5
MAX_PAGE_DURATION_SECONDS = 15.0
PAGE_LEAD_SECONDS = 0.35
PAGE_TAIL_SECONDS = 0.35
PAGE_FADE_MILLISECONDS = 150


def generate_ass(
    transcript: dict[str, Any], video: dict[str, int], *, scroll_long_lines: bool = False
) -> str:
    """Generate ASS subtitles from the canonical transcript."""
    width = video["width"]
    height = video["height"]
    font_size = 64 if height >= 1080 else 46
    margin = 70 if height >= 1080 else 48
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 1",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,DejaVu Sans,{font_size},&H0000D7FF,&H00FFFFFF,&H00000000,&H70000000,-1,0,0,0,"
        f"100,100,0,0,1,4,1,5,{margin},{margin},{margin},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for page in _build_pages(transcript["segments"]):
        for channel, lane_page in _page_lanes(page):
            agent, is_background = channel
            name = f"{agent}-bg" if is_background and agent else "background" if is_background else agent
            lane_lines = lane_page["lines"] if scroll_long_lines else [None]
            for line_index, line in enumerate(lane_lines):
                event_page = {**lane_page, "lines": [line]} if line is not None else lane_page
                text, scheduled_end = _render_page_text(event_page)
                if line is not None:
                    text = _position_karaoke_line(
                        event_page,
                        text,
                        line_index=line_index,
                        line_count=len(lane_lines),
                        width=width,
                        height=height,
                        font_size=font_size,
                        margin=margin,
                    )
                end = max(page["display_end_cs"], scheduled_end)
                lines.append(
                    f"Dialogue: 0,{_ass_timestamp(page['display_start_cs'])},{_ass_timestamp(end)},"
                    f"Default,{_escape_ass_field(name)},0,0,0,,{text}"
                )
    return "\n".join(lines) + "\n"


def _position_karaoke_line(
    page: dict[str, Any],
    text: str,
    *,
    line_index: int,
    line_count: int,
    width: int,
    height: int,
    font_size: int,
    margin: int,
) -> str:
    line_gap = round(font_size * 1.35)
    y = round(height / 2 + (line_index - (line_count - 1) / 2) * line_gap)
    line_text = str(page["lines"][0]["text"])
    text_width = _estimated_text_width(line_text, font_size)
    available_width = width - 2 * margin
    if text_width <= available_width:
        return f"{{\\an5\\pos({width // 2},{y})}}{text}"

    words = _page_words(page)
    starts, durations, _ = _schedule_words(words, page["display_start_cs"])
    move_start_cs = max(0, starts[0] - page["display_start_cs"])
    move_end_cs = max(move_start_cs + 1, starts[-1] + durations[-1] - page["display_start_cs"])
    move_start_ms = move_start_cs * 10
    move_end_ms = move_end_cs * 10
    end_x = width - margin - text_width
    return (
        f"{{\\an4\\q2\\clip({margin},0,{width - margin},{height})"
        f"\\move({margin},{y},{end_x},{y},{move_start_ms},{move_end_ms})}}{text}"
    )


def _estimated_text_width(value: str, font_size: int) -> int:
    units = 0.0
    for character in value:
        if character.isspace():
            units += 0.35
        elif unicodedata.east_asian_width(character) in {"F", "W"}:
            units += 1.0
        elif character in "MW@#%&":
            units += 0.9
        elif character.isupper():
            units += 0.7
        elif character in "ilI.,'`:;!|":
            units += 0.3
        else:
            units += 0.58
    return round(units * font_size * 1.08)


def _build_pages(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        if not segment.get("words"):
            continue
        gap = segment["start"] - current[-1]["end"] if current else 0
        duration = segment["end"] - current[0]["start"] if current else 0
        if current and (
            len(current) >= MAX_LYRIC_LINES_PER_PAGE
            or gap >= PAGE_BREAK_SILENCE_SECONDS
            or duration > MAX_PAGE_DURATION_SECONDS
        ):
            grouped.append(current)
            current = []
        current.append(segment)
    if current:
        grouped.append(current)

    lead = _to_centiseconds(PAGE_LEAD_SECONDS)
    tail = _to_centiseconds(PAGE_TAIL_SECONDS)
    pages: list[dict[str, Any]] = []
    for page_lines in grouped:
        words = [word for line in page_lines for word in line["words"]]
        source_start = min(_to_centiseconds(word["start"]) for word in words)
        source_end = max(_to_centiseconds(word["end"]) for word in words)
        display_start = max(0, source_start - lead)
        scheduled_end = _scheduled_end(words, display_start)
        pages.append(
            {
                "lines": page_lines,
                "source_start_cs": source_start,
                "display_start_cs": display_start,
                "karaoke_end_cs": scheduled_end,
                "desired_end_cs": max(scheduled_end, source_end + tail),
            }
        )

    next_start: int | None = None
    for index, page in enumerate(pages):
        if next_start is not None:
            page["display_start_cs"] = next_start
            page["karaoke_end_cs"] = _scheduled_end(
                [word for line in page["lines"] for word in line["words"]], next_start
            )
            page["desired_end_cs"] = max(page["desired_end_cs"], page["karaoke_end_cs"])
        if index + 1 == len(pages):
            page["display_end_cs"] = page["desired_end_cs"]
            continue
        following = pages[index + 1]
        following_start = following["display_start_cs"]
        if page["desired_end_cs"] <= following_start:
            page["display_end_cs"] = page["desired_end_cs"]
            next_start = following_start
        elif page["karaoke_end_cs"] <= following["source_start_cs"]:
            boundary = (page["karaoke_end_cs"] + following["source_start_cs"]) // 2
            page["display_end_cs"] = boundary
            next_start = boundary
        else:
            page["display_end_cs"] = page["karaoke_end_cs"]
            next_start = page["karaoke_end_cs"]
    return pages


def _scheduled_end(words: list[dict[str, Any]], event_start: int) -> int:
    lanes: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for word in words:
        lanes.setdefault(_word_channel(word), []).append(word)
    return max(_schedule_words(lane_words, event_start)[2] for lane_words in lanes.values())


def _render_page_text(page: dict[str, Any]) -> tuple[str, int]:
    parts = [f"{{\\fad({PAGE_FADE_MILLISECONDS},{PAGE_FADE_MILLISECONDS})}}"]
    cursor = page["display_start_cs"]
    words = _page_words(page)
    word_starts, word_durations, scheduled_end = _schedule_words(words, cursor)
    word_index = 0
    first_word = True
    for line_index, line in enumerate(page["lines"]):
        preserve_spacing = "".join(str(word["text"]) for word in line["words"]).strip() == str(line["text"]).strip()
        for word in line["words"]:
            if not first_word and not preserve_spacing:
                parts.append(" ")
            first_word = False
            start = word_starts[word_index]
            if start > cursor:
                parts.append(f"{{\\k{start - cursor}}}")
            for text, duration in _word_fragments(word, word_durations[word_index]):
                parts.append(f"{{\\kf{duration}}}{_escape_ass_text(text)}")
                start += duration
            cursor = start
            word_index += 1
        if line_index + 1 < len(page["lines"]):
            parts.append(r"\N")
            first_word = True
    return "".join(parts), max(cursor, scheduled_end)


def _page_words(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [word for line in page["lines"] for word in line["words"]]


def _page_lanes(page: dict[str, Any]) -> list[tuple[tuple[str, bool], dict[str, Any]]]:
    lane_lines: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for line in page["lines"]:
        words_by_lane: dict[tuple[str, bool], list[dict[str, Any]]] = {}
        for word in line["words"]:
            words_by_lane.setdefault(_word_channel(word), []).append(word)
        for channel, source_words in words_by_lane.items():
            words = [dict(word) for word in source_words]
            if channel[1]:
                if not str(words[0]["text"]).lstrip().startswith("("):
                    words[0]["text"] = f"({words[0]['text']}"
                if not str(words[-1]["text"]).rstrip().endswith(")"):
                    words[-1]["text"] = f"{words[-1]['text'].rstrip()})"
            lane_lines.setdefault(channel, []).append(
                {**line, "text": "".join(word["text"] for word in words).strip(), "words": words}
            )
    return [(channel, {**page, "lines": lines}) for channel, lines in lane_lines.items()]


def _word_channel(word: dict[str, Any]) -> tuple[str, bool]:
    return str(word.get("agent") or ""), bool(word.get("isBackground", False))


def _schedule_words(words: list[dict[str, Any]], event_start: int) -> tuple[list[int], list[int], int]:
    starts: list[int] = []
    durations: list[int] = []
    cursor = event_start
    for word in words:
        start = max(cursor, _to_centiseconds(word["start"]))
        end = max(start + _minimum_word_duration(word), _to_centiseconds(word["end"]))
        starts.append(start)
        durations.append(end - start)
        cursor = end
    return starts, durations, cursor


def _minimum_word_duration(word: dict[str, Any]) -> int:
    timing = word.get("timing")
    return len(timing) if isinstance(timing, list) and timing else 1


def _word_fragments(word: dict[str, Any], total_duration: int) -> list[tuple[str, int]]:
    timing = word.get("timing")
    source = timing if isinstance(timing, list) and timing else [word]
    if len(source) == 1:
        return [(str(source[0]["text"]), total_duration)]

    source_durations = [max(1, _to_centiseconds(fragment["end"] - fragment["start"])) for fragment in source]
    source_total = sum(source_durations)
    durations = [max(1, int(source_duration * total_duration / source_total)) for source_duration in source_durations]
    while sum(durations) > total_duration:
        index = max(
            (index for index, duration in enumerate(durations) if duration > 1),
            key=durations.__getitem__,
            default=-1,
        )
        if index < 0:
            break
        durations[index] -= 1
    while sum(durations) < total_duration:
        index = max(range(len(durations)), key=lambda item: source_durations[item])
        durations[index] += 1
    return [(str(fragment["text"]), duration) for fragment, duration in zip(source, durations, strict=True)]


def _to_centiseconds(seconds: float) -> int:
    return max(0, round(float(seconds) * 100))


def _ass_timestamp(centiseconds: int) -> str:
    hours, remainder = divmod(max(0, centiseconds), 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _escape_ass_text(value: str) -> str:
    return value.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _escape_ass_field(value: str) -> str:
    return value.replace(",", " ").replace("\r", " ").replace("\n", " ")
