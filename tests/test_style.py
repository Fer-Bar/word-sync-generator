import unittest

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


if __name__ == "__main__":
    unittest.main()
