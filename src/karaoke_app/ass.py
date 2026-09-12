import math
import re
from pathlib import Path
from typing import Any

from karaoke_app.style import StyleConfig, hex_to_ass_color

MAX_LYRIC_LINES_PER_PAGE = 3
PAGE_BREAK_SILENCE_SECONDS = 1.5
MAX_PAGE_DURATION_SECONDS = 15.0
PAGE_LEAD_SECONDS = 0.35
PAGE_TAIL_SECONDS = 0.35
PAGE_FADE_MILLISECONDS = 150


def _ass_style_name(agent: str | None, is_background: bool) -> str:
    """Derive a valid ASS style name for a given agent and vocal channel."""
    clean_agent = re.sub(r"[,\r\n]", "", str(agent or "")).strip()
    if clean_agent and is_background:
        return f"Agent_{clean_agent}_bg"
    if clean_agent:
        return f"Agent_{clean_agent}"
    if is_background:
        return "Background"
    return "Default"


def generate_ass(
    transcript: dict[str, Any],
    video: dict[str, int],
    *,
    style: StyleConfig | None = None,
    mode: str = "karaoke",
) -> str:
    """Generate ASS subtitles from the canonical transcript."""
    width = video["width"]
    height = video["height"]
    active_style = style if isinstance(style, StyleConfig) else StyleConfig.from_dict(None, height=height)
    font_size = active_style.font_size

    unique_agents: list[str] = []
    known_channels: list[tuple[str, bool]] = []
    for segment in transcript.get("segments", []):
        for word in segment.get("words", []):
            ch = _word_channel(word)
            if ch not in known_channels:
                known_channels.append(ch)
            agent_name = ch[0]
            if agent_name and agent_name not in unique_agents:
                unique_agents.append(agent_name)
        if not segment.get("words"):
            ch = (str(segment.get("agent") or ""), bool(segment.get("isBackground", False)))
            if ch not in known_channels:
                known_channels.append(ch)
            agent_name = ch[0]
            if agent_name and agent_name not in unique_agents:
                unique_agents.append(agent_name)

    if not known_channels:
        known_channels = [("", False)]

    l_colors = active_style.lyrics_colors if mode == "lyrics" else None
    if l_colors:
        style_lines = [
            active_style.to_ass_style(
                "Default",
                primary_color=l_colors["active"],
                highlight_color=l_colors["inactive"],
            )
        ]
    else:
        style_lines = [active_style.to_ass_style("Default")]
    seen_styles = {"Default"}

    for agent, is_background in known_channels:
        style_name = _ass_style_name(agent, is_background)
        if style_name in seen_styles:
            continue
        seen_styles.add(style_name)
        agent_idx = unique_agents.index(agent) if agent in unique_agents else 0
        p_col, h_col = active_style.get_agent_colors(
            agent if agent else None,
            index=agent_idx,
            is_background=is_background,
        )
        if l_colors:
            if is_background:
                bg_font_size = max(12, round(font_size * 0.85))
                style_lines.append(
                    active_style.to_ass_style(
                        style_name,
                        primary_color=l_colors["active"],
                        highlight_color=l_colors["inactive"],
                        italic=True,
                        font_size=bg_font_size,
                    )
                )
            else:
                style_lines.append(
                    active_style.to_ass_style(
                        style_name,
                        primary_color=l_colors["active"],
                        highlight_color=l_colors["inactive"],
                    )
                )
        else:
            if is_background:
                bg_font_size = max(12, round(font_size * 0.85))
                style_lines.append(
                    active_style.to_ass_style(
                        style_name,
                        primary_color=p_col,
                        highlight_color=h_col,
                        italic=True,
                        font_size=bg_font_size,
                    )
                )
            else:
                style_lines.append(
                    active_style.to_ass_style(
                        style_name,
                        primary_color=p_col,
                        highlight_color=h_col,
                    )
                )

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
        *style_lines,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if active_style.lyrics_effect == "word-synced":
        from karaoke_app.word_synced import build_word_synced_dialogues

        dialogue_lines = build_word_synced_dialogues(
            transcript.get("segments", []), width, height, active_style, scroll=mode == "karaoke",
        )
    elif mode == "lyrics":
        dialogue_lines = _build_page_dialogues(
            transcript.get("segments", []),
            width=width,
            height=height,
            font_size=font_size,
            active_style=active_style,
            lyrics_colors=l_colors,
        )
    else:
        dialogue_lines = _build_teleprompter_dialogues(
            transcript.get("segments", []),
            width=width,
            height=height,
            font_size=font_size,
            line_gap_factor=active_style.line_gap_factor,
            active_style=active_style,
            unique_agents=unique_agents,
        )
    lines.extend(dialogue_lines)
    return "\n".join(lines) + "\n"


def _estimate_line_width(
    text: str,
    font_family: str,
    font_size: int,
    *,
    bold: bool = True,
) -> float:
    """Estimate or measure rendered text width in pixels."""
    if not text:
        return 0.0

    clean_family = font_family.lower().replace(" ", "").replace("-", "")

    try:
        from PIL import ImageFont

        font = None
        candidates: list[str] = []
        if "bebas" in clean_family:
            candidates = [
                "/usr/local/share/fonts/truetype/bebasneue/BebasNeue-Regular.ttf",
                str(Path.home() / ".local/share/fonts/BebasNeue-Regular.ttf"),
                "/tmp/BebasNeue-Regular.ttf",
            ]
        elif "dejavu" in clean_family:
            candidates = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            ]

        for cand in candidates:
            if Path(cand).is_file():
                try:
                    font = ImageFont.truetype(cand, font_size)
                    break
                except Exception:
                    continue

        if font is None:
            try:
                font = ImageFont.truetype(font_family, font_size)
            except Exception:
                pass

        if font is not None:
            bbox = font.getbbox(text)
            return float(bbox[2] - bbox[0])
    except Exception:
        pass

    if "bebas" in clean_family:
        char_ratio = 0.33
    elif "oswald" in clean_family:
        char_ratio = 0.38
    elif any(k in clean_family for k in ("montserrat", "inter", "roboto")):
        char_ratio = 0.52 if bold else 0.49
    else:
        char_ratio = 0.55 if bold else 0.52

    return float(len(text) * font_size * char_ratio)


def _build_page_dialogues(
    segments: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    font_size: int,
    active_style: StyleConfig,
    lyrics_colors: dict[str, str] | None = None,
) -> list[str]:
    pages = _build_pages(segments)
    dialogue_lines: list[str] = []
    center_x = width // 2
    max_line_width = max(200, width - (active_style.margin_h * 2) - 40)
    line_gap = round(font_size * active_style.line_gap_factor)
    inter_line_gap = max(10, line_gap - font_size)

    for page in pages:
        lanes = _page_lanes(page)
        sorted_lanes = sorted(lanes, key=lambda item: 1 if item[0][1] else 0)

        all_lane_lines: list[tuple[tuple[str, bool], dict[str, Any]]] = []
        for channel, lane_page in sorted_lanes:
            for line in lane_page["lines"]:
                all_lane_lines.append((channel, line))

        line_count = len(all_lane_lines)
        if line_count == 0:
            continue

        line_specs: list[dict[str, Any]] = []
        for channel, line in all_lane_lines:
            agent, is_bg = channel
            base_fs = max(12, round(font_size * 0.85)) if is_bg else font_size
            plain_text = _render_line_plain_text(line)
            raw_w = _estimate_line_width(
                plain_text,
                active_style.font_family,
                base_fs,
                bold=active_style.bold,
            )
            visual_lines = max(1, math.ceil(raw_w / max_line_width))
            visual_h = visual_lines * round(base_fs * 1.08)
            line_specs.append(
                {
                    "channel": channel,
                    "line": line,
                    "base_font_size": base_fs,
                    "visual_lines": visual_lines,
                    "visual_height": visual_h,
                }
            )

        all_single_standard = all(spec["visual_lines"] == 1 for spec in line_specs)
        if all_single_standard:
            y_coords = [round(height / 2 + (idx - (line_count - 1) / 2) * line_gap) for idx in range(line_count)]
        else:
            total_visual_h = sum(s["visual_height"] for s in line_specs) + (line_count - 1) * inter_line_gap
            cur_top = (height - total_visual_h) / 2
            y_coords = []
            for spec in line_specs:
                y_center = round(cur_top + spec["visual_height"] / 2)
                y_coords.append(y_center)
                cur_top += spec["visual_height"] + inter_line_gap

        for spec, y in zip(line_specs, y_coords, strict=True):
            channel = spec["channel"]
            line = spec["line"]

            agent, is_bg = channel
            style_name = _ass_style_name(agent, is_bg)
            actor_name = f"{agent}-bg" if is_bg and agent else "background" if is_bg else agent

            pos_tag = f"{{\\an5\\pos({center_x},{y})\\fad({PAGE_FADE_MILLISECONDS},{PAGE_FADE_MILLISECONDS})}}"

            karaoke_text, scheduled_end = _render_line_karaoke_text(
                line,
                page["display_start_cs"],
                lyrics_colors=lyrics_colors,
            )
            end = max(page["display_end_cs"], scheduled_end)

            dialogue_lines.append(
                f"Dialogue: 0,{_ass_timestamp(page['display_start_cs'])},{_ass_timestamp(end)},"
                f"{_escape_ass_field(style_name)},{_escape_ass_field(actor_name)},0,0,0,,{pos_tag}{karaoke_text}"
            )

    return dialogue_lines


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
                {
                    **line,
                    "agent": channel[0],
                    "isBackground": channel[1],
                    "text": "".join(word["text"] for word in words).strip(),
                    "words": words,
                }
            )
    return [(channel, {**page, "lines": lines}) for channel, lines in lane_lines.items()]


def _scheduled_end(words: list[dict[str, Any]], event_start: int) -> int:
    lanes: dict[tuple[str, bool], list[dict[str, Any]]] = {}
    for word in words:
        lanes.setdefault(_word_channel(word), []).append(word)
    return max(_schedule_words(lane_words, event_start)[2] for lane_words in lanes.values())


def _build_teleprompter_dialogues(
    segments: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    font_size: int,
    line_gap_factor: float = 1.35,
    active_style: StyleConfig | None = None,
    unique_agents: list[str] | None = None,
) -> list[str]:
    valid_segments = [s for s in segments if s.get("words")]
    if not valid_segments:
        return []

    style = active_style if isinstance(active_style, StyleConfig) else StyleConfig.from_dict(None, height=height)
    known_unique_agents = unique_agents or []

    center_x = width // 2
    center_y = height // 2
    slot_offset = max(round(font_size * line_gap_factor * 1.5), round(height * 0.14))
    top_y = center_y - slot_offset
    bottom_y = center_y + slot_offset
    nominal_slide_cs = 35
    max_gap_cs = 200

    num_segments = len(valid_segments)
    seg_timings: list[tuple[int, int]] = []
    for seg in valid_segments:
        words = seg["words"]
        start_cs = min(_to_centiseconds(w["start"]) for w in words)
        end_cs = max(_to_centiseconds(w["end"]) for w in words)
        seg_timings.append((start_cs, end_cs))

    # Precalculate synchronized transition windows between segment i and i+1
    # trans_info[i] = (has_conn, trans_start_cs, trans_end_cs, duration_cs)
    trans_info: list[tuple[bool, int, int, int]] = []
    for i in range(num_segments - 1):
        curr_start, curr_end = seg_timings[i]
        next_start, next_end = seg_timings[i + 1]
        gap_cs = next_start - curr_end

        if gap_cs >= max_gap_cs:
            # Long pause / silence: disconnected transition
            trans_info.append((False, 0, 0, nominal_slide_cs))
        else:
            if gap_cs >= nominal_slide_cs:
                t_end = next_start
                t_start = max(0, next_start - nominal_slide_cs)
                dur = nominal_slide_cs
            elif gap_cs >= 15:
                t_start = max(0, curr_end)
                t_end = next_start
                dur = t_end - t_start
            else:
                dur = max(15, min(nominal_slide_cs, 25))
                t_end = next_start
                t_start = max(0, next_start - dur)
                dur = max(1, t_end - t_start)
            trans_info.append((True, t_start, t_end, dur))

    dialogue_lines: list[str] = []

    for i, seg in enumerate(valid_segments):
        start_cs, end_cs = seg_timings[i]

        # Check incoming connection (from i-1 to i)
        if i > 0 and trans_info[i - 1][0]:
            has_prev_conn = True
            _, entry_start, _, entry_dur = trans_info[i - 1]
        else:
            has_prev_conn = False
            entry_dur = nominal_slide_cs
            entry_start = max(0, start_cs - nominal_slide_cs)

        # Check outgoing connection (from i to i+1)
        if i < num_segments - 1 and trans_info[i][0]:
            has_next_conn = True
            _, exit_start, _, exit_dur = trans_info[i]
        else:
            has_next_conn = False
            exit_dur = nominal_slide_cs
            exit_start = end_cs

        agent = str(seg.get("agent") or "")
        is_bg = bool(seg.get("isBackground", False))
        style_name = _ass_style_name(agent, is_bg)
        actor_name = f"{agent}-bg" if is_bg and agent else "background" if is_bg else agent
        plain_text = _render_line_plain_text(seg)

        # 1. Upcoming preview (Bottom Slot)
        if i > 0 and has_prev_conn:
            prev_start_cs, _ = seg_timings[i - 1]
            preview_start = max(0, prev_start_cs)
            preview_end = entry_start
            if preview_end > preview_start:
                agent_idx = known_unique_agents.index(agent) if agent in known_unique_agents else 0
                _, h_col = style.get_agent_colors(
                    agent if agent else None,
                    index=agent_idx,
                    is_background=is_bg,
                )
                unsung_bgr = hex_to_ass_color(h_col)[4:]
                preview_tag = f"{{\\an5\\pos({center_x},{bottom_y})\\alpha&H80&\\1c&H{unsung_bgr}&\\fad(150,0)}}"
                dialogue_lines.append(
                    f"Dialogue: 0,{_ass_timestamp(preview_start)},{_ass_timestamp(preview_end)},"
                    f"{_escape_ass_field(style_name)},{_escape_ass_field(actor_name)},0,0,0,,{preview_tag}{plain_text}"
                )

        # 2. Active singing event (Transition from Bottom to Center + Karaoke highlight)
        entry_ms = entry_dur * 10
        if has_prev_conn:
            move_tag = (
                f"{{\\an5\\move({center_x},{bottom_y},{center_x},{center_y},0,{entry_ms})"
                f"\\t(0,{entry_ms},\\alpha&H00&)}}"
            )
        else:
            move_tag = f"{{\\an5\\pos({center_x},{center_y})\\fad(150,0)}}"

        karaoke_text, scheduled_end = _render_line_karaoke_text(seg, entry_start)
        active_end = exit_start if has_next_conn else max(exit_start, scheduled_end)

        dialogue_lines.append(
            f"Dialogue: 1,{_ass_timestamp(entry_start)},{_ass_timestamp(active_end)},"
            f"{_escape_ass_field(style_name)},{_escape_ass_field(actor_name)},0,0,0,,{move_tag}{karaoke_text}"
        )

        # 3. Past history event (Transition from Center to Top Slot + Fade Out)
        past_start = active_end
        exit_ms = exit_dur * 10
        if has_next_conn:
            next_end_cs = seg_timings[i + 1][1]
            past_end = min(past_start + 120, max(past_start + exit_dur + 20, next_end_cs))
        else:
            past_end = past_start + exit_dur + 40

        if past_end > past_start:
            past_tag = (
                f"{{\\an5\\move({center_x},{center_y},{center_x},{top_y},0,{exit_ms})"
                f"\\t(0,{exit_ms},\\alpha&H80&)\\fad(0,150)}}"
            )
            dialogue_lines.append(
                f"Dialogue: 0,{_ass_timestamp(past_start)},{_ass_timestamp(past_end)},"
                f"{_escape_ass_field(style_name)},{_escape_ass_field(actor_name)},0,0,0,,{past_tag}{plain_text}"
            )

    return dialogue_lines


def _render_line_karaoke_text(
    line: dict[str, Any],
    event_start_cs: int,
    *,
    lyrics_colors: dict[str, str] | None = None,
) -> tuple[str, int]:
    words = line["words"]
    is_bg = bool(line.get("isBackground", False))
    starts, durations, scheduled_end = _schedule_words(words, event_start_cs)
    parts = []
    cursor = event_start_cs
    preserve_spacing = "".join(str(w["text"]) for w in words).strip() == str(line.get("text", "")).strip()
    first_word = True
    for idx, word in enumerate(words):
        if not first_word and not preserve_spacing:
            parts.append(" ")
        first_word = False
        start = starts[idx]
        if start > cursor:
            parts.append(f"{{\\k{start - cursor}}}")
        word_text = str(word["text"])
        if is_bg and idx == 0 and not word_text.lstrip().startswith("("):
            word_text = f"({word_text}"
        if is_bg and idx == len(words) - 1 and not word_text.rstrip().endswith(")"):
            word_text = f"{word_text.rstrip()})"
        for text, duration in _word_fragments({**word, "text": word_text}, durations[idx]):
            parts.append(f"{{\\kf{duration}}}{_escape_ass_text(text)}")
            start += duration
        cursor = start
    return "".join(parts), max(cursor, scheduled_end)


def _render_line_plain_text(line: dict[str, Any]) -> str:
    words = line.get("words", [])
    is_bg = bool(line.get("isBackground", False))
    if not words:
        raw = str(line.get("text") or "")
    else:
        preserve_spacing = "".join(str(w["text"]) for w in words).strip() == str(line.get("text", "")).strip()
        raw = "".join(str(w["text"]) for w in words) if preserve_spacing else " ".join(str(w["text"]) for w in words)
    raw = raw.strip()
    if is_bg:
        if not raw.startswith("("):
            raw = f"({raw}"
        if not raw.endswith(")"):
            raw = f"{raw})"
    return _escape_ass_text(raw)


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
