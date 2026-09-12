import unittest

import pytest

from karaoke_app.style import (
    StyleConfig,
    ass_to_hex_color,
    hex_to_ass_color,
    normalize_hex_color,
)


class StyleTests(unittest.TestCase):
    def test_normalize_hex_color(self) -> None:
        self.assertEqual(normalize_hex_color("ffd700"), "#FFD700")
        self.assertEqual(normalize_hex_color("#112233"), "#112233")
        self.assertEqual(normalize_hex_color("invalid", default="#000000"), "#000000")

    def test_hex_to_ass_color(self) -> None:
        # Gold #FFD700: R=FF, G=D7, B=00 -> In ASS: &H0000D7FF (opaque: alpha=0)
        self.assertEqual(hex_to_ass_color("#FFD700", alpha=1.0), "&H0000D7FF")
        # White #FFFFFF: R=FF, G=FF, B=FF -> In ASS: &H00FFFFFF
        self.assertEqual(hex_to_ass_color("#FFFFFF", alpha=1.0), "&H00FFFFFF")
        # Black #000000: R=00, G=00, B=00 -> In ASS: &H00000000
        self.assertEqual(hex_to_ass_color("#000000", alpha=1.0), "&H00000000")
        # Black with ~44% opacity -> alpha float 0.44 -> ass_alpha = round(0.56 * 255) = 143 = 0x8F
        ass_shadow = hex_to_ass_color("#000000", alpha=0.56)
        self.assertTrue(ass_shadow.startswith("&H7"))

    def test_ass_to_hex_color(self) -> None:
        hex_val, opacity = ass_to_hex_color("&H0000D7FF")
        self.assertEqual(hex_val, "#FFD700")
        self.assertEqual(opacity, 1.0)

    def test_default_style_ass_output(self) -> None:
        config = StyleConfig.from_dict(None, height=1080)
        ass_line = config.to_ass_style()
        self.assertIn("Style: Default,DejaVu Sans,64,&H0000D7FF,&H00FFFFFF,&H00000000,", ass_line)
        self.assertIn(",-1,0,0,0,100,100,0,0,1,4,1,5,70,70,70,1", ass_line)

    def test_custom_style_ass_output(self) -> None:
        data = {
            "font_family": "Montserrat",
            "font_size": 72,
            "bold": False,
            "italic": True,
            "primary_color": "#00FFCC",
            "highlight_color": "#FF00AA",
            "outline_color": "#111111",
            "outline_width": 6,
            "shadow_depth": 2,
            "margin_v": 90,
            "margin_h": 80,
        }
        config = StyleConfig.from_dict(data, height=1080)
        ass_line = config.to_ass_style()
        self.assertIn("Style: Default,Montserrat,72,", ass_line)
        self.assertIn(",0,-1,0,0,100,100,0,0,1,6,2,5,80,80,90,1", ass_line)

    def test_agent_colors_parsing_and_fallback(self) -> None:
        data = {
            "primary_color": "#FFD700",
            "highlight_color": "#FFFFFF",
            "agent_colors": {
                "v1": {"primary_color": "#FF0000", "highlight_color": "#FFFF00"},
                "v2": {"primary_color": "#00FF00"},
            },
        }
        config = StyleConfig.from_dict(data, height=1080)
        self.assertEqual(config.get_agent_colors("v1"), ("#FF0000", "#FFFF00"))
        # v2 specified primary, highlight falls back to base
        self.assertEqual(config.get_agent_colors("v2"), ("#00FF00", "#FFFFFF"))
        # unconfigured agent falls back to DEFAULT_AGENT_PALETTE
        p, h = config.get_agent_colors("v3", index=1)
        self.assertEqual(p, "#00D7FF")
        self.assertEqual(h, "#FFFFFF")

    def test_parameterized_ass_style_generation(self) -> None:
        config = StyleConfig.from_dict(None, height=1080)
        style_agent_v2 = config.to_ass_style("Agent_v2", primary_color="#00D7FF", highlight_color="#FFFFFF")
        self.assertIn("Style: Agent_v2,DejaVu Sans,64,&H00FFD700,&H00FFFFFF,", style_agent_v2)

        style_bg = config.to_ass_style("Agent_v1_bg", primary_color="#FFD700", italic=True, font_size=54)
        self.assertIn("Style: Agent_v1_bg,DejaVu Sans,54,&H0000D7FF,&H00FFFFFF,", style_bg)
        self.assertIn(",-1,-1,0,0,100,100,0,0,1,", style_bg)  # bold=-1, italic=-1

    def test_coros_color_configuration_and_agent_bg_fallback(self) -> None:
        data = {
            "primary_color": "#FFD700",
            "coros_color": "#00E5FF",
            "agent_colors": {
                "v1": {"primary_color": "#FF0000", "coros_color": "#FF69B4"},
                "v2": {"primary_color": "#00FF00"},
            },
        }
        config = StyleConfig.from_dict(data, height=1080)
        self.assertEqual(config.coros_color, "#00E5FF")
        # Global coro channel
        self.assertEqual(config.get_agent_colors(None, is_background=True), ("#00E5FF", "#FFFFFF"))
        # v1 custom coros_color
        self.assertEqual(config.get_agent_colors("v1", is_background=True), ("#FF69B4", "#FFFFFF"))
        # v2 without custom coros_color falls back to global coros_color
        self.assertEqual(config.get_agent_colors("v2", is_background=True), ("#00E5FF", "#FFFFFF"))
        # Unconfigured agent background falls back to global coros_color
        self.assertEqual(config.get_agent_colors("v3", is_background=True), ("#00E5FF", "#FFFFFF"))

    def test_lyrics_colors_configuration_and_defaults(self) -> None:
        data = {
            "lyrics_colors": {
                "inactive": "#9A8F8B",
                "active": "#F4EEE6",
            }
        }
        config = StyleConfig.from_dict(data, height=1080)
        self.assertIsNotNone(config.lyrics_colors)
        self.assertEqual(config.lyrics_colors["inactive"], "#9A8F8B")
        self.assertEqual(config.lyrics_colors["active"], "#F4EEE6")
        self.assertEqual(config.get_lyrics_colors(), data["lyrics_colors"])
        self.assertIn("lyrics_colors", config.to_dict())

        # When omitted, lyrics_colors is None on config, but get_lyrics_colors() provides defaults
        default_config = StyleConfig.from_dict(None, height=1080)
        self.assertIsNone(default_config.lyrics_colors)
        self.assertNotIn("lyrics_colors", default_config.to_dict())
        self.assertEqual(default_config.get_lyrics_colors()["active"], "#F4EEE6")


@pytest.mark.parametrize("data", [
    [], False, "style", {"font_szie": 64}, {"bold": "false"}, {"italic": 0},
    {"font_family": 12}, {"font_family": " "}, {"font_size": 0}, {"font_size": 3.5},
    {"font_size": True}, {"alignment": 10}, {"margin_h": -1}, {"outline_width": "4"},
    {"shadow_depth": -1}, {"shadow_opacity": float("nan")}, {"shadow_opacity": float("inf")},
    {"shadow_opacity": 1.1}, {"line_gap_factor": 0.9}, {"primary_color": "invalid"},
    {"agent_colors": []}, {"agent_colors": {"": {}}}, {"agent_colors": {"v1": "red"}},
    {"agent_colors": {"v1": {"highlight_colour": "#FFFFFF"}}},
    {"agent_colors": {"v1": {"primary_color": False}}},
    {"lyrics_colors": None}, {"lyrics_colors": {"actve": "#FFFFFF"}},
    {"lyrics_colors": {"active": "bad"}},
])
def test_invalid_style_values_fail_without_coercion(data):
    with pytest.raises(ValueError):
        StyleConfig.from_dict(data)


def test_legacy_editor_opacity_input_is_accepted_but_not_stored():
    config = StyleConfig.from_dict({"overlay_opacity": 0.6})
    assert not hasattr(config, "overlay_opacity")
    assert "overlay_opacity" not in config.to_dict()
    assert StyleConfig.from_dict(config.to_dict()) == config


if __name__ == "__main__":
    unittest.main()
