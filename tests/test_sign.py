import math
import sys
import types
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest

import sign
import sign_glyphs
from sign import (
    CalloutPage,
    NowPage,
    PanelOutput,
    PreviewOutput,
    SummaryPage,
    TodayPage,
    measure_callout,
    format_duration,
    render_page,
    render_preview_png,
    measure_text,
)

PIOMATTER = "adafruit_blinka_raspberry_pi5_piomatter"
REQUIRED_ICONS = ["fire", "phone", "zzz", "question", "food", "cup", "check", "moon", "hand", "alert"]
STATES = ["working", "phone", "away", "unknown"]
HOURS_99 = 99 * 3600
PINK = (200, 80, 140)


def assert_is_frame(frame):
    assert frame.shape == (sign.SIGN_HEIGHT, sign.SIGN_WIDTH, 3) == (32, 128, 3)
    assert frame.dtype == np.uint8
    assert frame.any()
    assert frame.max() <= sign.CHANNEL_CAP


def decode_png(png):
    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    return image


def crop_icon_area(frame):
    icon_area = frame[:, : sign.CALLOUT_TEXT_LEFT]
    return icon_area


def crop_text_area(frame):
    text_area = frame[:, sign.CALLOUT_TEXT_LEFT :]
    return text_area


def test_font_covers_every_printable_ascii_character():
    assert set(sign_glyphs.FONT) == {chr(code) for code in range(32, 127)}
    assert len(sign_glyphs.FONT) == 95


def test_every_glyph_is_7_rows_of_5_pixels():
    misshapen = [
        char
        for char, rows in sign_glyphs.FONT.items()
        if len(rows) != 7 or any(len(row) != 5 or set(row) - {"#", "."} for row in rows)
    ]
    assert misshapen == []


def test_only_space_is_blank():
    blank = [char for char, rows in sign_glyphs.FONT.items() if "#" not in "".join(rows)]
    assert blank == [" "]


def test_required_icons_exist():
    assert set(REQUIRED_ICONS) <= set(sign_glyphs.ICONS)


def test_every_icon_is_16x16():
    misshapen = [
        name
        for name, rows in sign_glyphs.ICONS.items()
        if len(rows) != 16 or any(len(row) != 16 for row in rows)
    ]
    assert misshapen == []


def test_mini_icons_are_one_text_line_tall():
    misshapen = [
        name
        for name, rows in sign_glyphs.MINI_ICONS.items()
        if len(rows) != sign_glyphs.GLYPH_HEIGHT or len({len(row) for row in rows}) != 1
    ]
    assert misshapen == []


def test_icons_only_use_palette_colors():
    known = set(sign_glyphs.PALETTE) | {sign_glyphs.DARK}
    all_art = {**sign_glyphs.ICONS, **{f"mini {name}": rows for name, rows in sign_glyphs.MINI_ICONS.items()}}
    unknown = {name: set("".join(rows)) - known for name, rows in all_art.items() if set("".join(rows)) - known}
    assert unknown == {}


def test_palette_stays_under_the_channel_cap():
    assert max(max(color) for color in sign_glyphs.PALETTE.values()) <= sign.CHANNEL_CAP


@pytest.mark.parametrize(
    "text, scale, width",
    [("", 1, 0), ("", 2, 0), ("A", 1, 5), ("AB", 1, 11), ("1h05", 1, 23), ("AB", 2, 22), ("10h30", 2, 58)],
)
def test_text_width(text, scale, width):
    assert measure_text(text, scale) == width


@pytest.mark.parametrize("scale", [1, 2])
def test_text_width_matches_the_drawn_pixels(scale):
    canvas = np.zeros((20, 200, 3), np.uint8)
    sign.draw_text(canvas, "MWM", 0, 0, (200, 200, 200), scale=scale, clip=sign.Region(0, 0, 200, 20))
    lit_columns = np.flatnonzero(canvas.any(axis=(0, 2)))
    assert lit_columns[0] == 0
    assert lit_columns[-1] + 1 == measure_text("MWM", scale)


@pytest.mark.parametrize("clip", [sign.Region(0, 0, 20, 10), sign.Region(-100, -100, 100, 100)])
def test_text_hanging_off_any_edge_is_cut_off_without_wrapping_around(clip):
    canvas = np.zeros((10, 20, 3), np.uint8)
    sign.draw_text(canvas, "W", -3, -3, (200, 200, 200), clip=clip)
    sign.draw_text(canvas, "W", 18, 8, (200, 200, 200), clip=clip)
    glyph = sign.find_glyph("W")
    expected = np.zeros((10, 20), dtype=bool)
    expected[:4, :2] = glyph[3:, 3:]
    expected[8:, 18:] = glyph[:2, :2]
    assert np.array_equal(canvas.any(axis=2), expected)


def test_unknown_characters_draw_as_question_marks_and_whitespace_as_spaces():
    assert np.array_equal(sign.build_text_mask("é"), sign.build_text_mask("?"))
    assert np.array_equal(sign.build_text_mask("a\tb\nc"), sign.build_text_mask("a b c"))


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "0s"),
        (0.9, "0s"),
        (45, "45s"),
        (59.99, "59s"),
        (60, "1m"),
        (12 * 60 + 59, "12m"),
        (3599, "59m"),
        (3600, "1h00"),
        (3900, "1h05"),
        (10 * 3600 + 30 * 60, "10h30"),
        (HOURS_99, "99h00"),
        (-5, "0s"),
        (math.nan, "0s"),
        (math.inf, "999h59"),
        (10**400, "999h59"),
    ],
)
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


@pytest.mark.parametrize("state", STATES)
def test_now_page_renders_every_state(state):
    assert_is_frame(render_page(NowPage(state=state, seconds_in_state=3900, pickups_today=3)))


def test_now_page_states_look_different():
    frames = [render_page(NowPage(state, 3900, 3)).tobytes() for state in STATES]
    assert len(set(frames)) == len(STATES)


def test_now_page_unrecognised_state_shows_as_unknown():
    assert np.array_equal(render_page(NowPage("sleeping", 60, 1)), render_page(NowPage("unknown", 60, 1)))


@pytest.mark.parametrize("seconds", [0, HOURS_99, math.inf, math.nan, -1, 10**400])
@pytest.mark.parametrize("pickups", [0, 9999, 10**12, -3])
def test_now_page_survives_extremes(seconds, pickups):
    assert_is_frame(render_page(NowPage("working", seconds, pickups)))


@pytest.mark.parametrize(
    "page",
    [
        TodayPage(working_seconds=3 * 3600 + 12 * 60, phone_seconds=45 * 60, pickups=14, snacks=2),
        TodayPage(working_seconds=0, phone_seconds=0, pickups=0, snacks=0),
        TodayPage(working_seconds=HOURS_99, phone_seconds=HOURS_99, pickups=9999, snacks=9999),
        TodayPage(working_seconds=math.inf, phone_seconds=math.nan, pickups=10**12, snacks=10**12),
    ],
)
def test_today_page_renders(page):
    assert_is_frame(render_page(page))


@pytest.mark.parametrize(
    "page",
    [
        SummaryPage(working_seconds=6 * 3600, phone_seconds=52 * 60, pickups=14, longest_streak_seconds=80 * 60),
        SummaryPage(working_seconds=0, phone_seconds=0, pickups=0, longest_streak_seconds=0),
        SummaryPage(working_seconds=HOURS_99, phone_seconds=HOURS_99, pickups=9999, longest_streak_seconds=HOURS_99),
    ],
)
def test_summary_page_renders(page):
    assert_is_frame(render_page(page))


@pytest.mark.parametrize("icon", sorted(sign_glyphs.ICONS))
def test_callout_page_renders_every_icon(icon):
    assert_is_frame(render_page(CalloutPage(text="Snack time!", icon=icon, color=PINK)))


def test_callout_with_an_unknown_icon_shows_the_question_mark():
    unknown = render_page(CalloutPage(text="", icon="no-such-icon", color=PINK))
    question = render_page(CalloutPage(text="", icon="question", color=PINK))
    assert np.array_equal(unknown, question)


def test_callout_width_is_the_width_of_the_scrolling_text():
    assert measure_callout("") == 0
    assert measure_callout("Snack time") == measure_text("Snack time", sign.CALLOUT_TEXT_SCALE)


def test_callout_text_is_gone_once_scrolled_by_callout_width():
    text = "Snack time"
    almost_gone = render_page(CalloutPage(text, "food", PINK, scroll_px=measure_callout(text) - 1))
    gone = render_page(CalloutPage(text, "food", PINK, scroll_px=measure_callout(text)))
    assert crop_text_area(almost_gone).any()
    assert not crop_text_area(gone).any()


@pytest.mark.parametrize("scroll_px", [-10**12, -500, -40, 0, 7, 100, 10**12, math.inf, math.nan])
def test_callout_text_never_spills_into_the_icon_area(scroll_px):
    long_text = "W" * 10_000
    with_text = render_page(CalloutPage(long_text, "cup", (200, 200, 200), scroll_px=scroll_px))
    icon_only = render_page(CalloutPage("", "cup", (200, 200, 200)))
    assert_is_frame(with_text)
    assert np.array_equal(crop_icon_area(with_text), crop_icon_area(icon_only))


def test_callout_scrolled_past_the_end_shows_only_the_icon():
    text = "Put the phone down"
    frame = render_page(CalloutPage(text, "alert", (200, 170, 20), scroll_px=measure_callout(text) + 500))
    assert not crop_text_area(frame).any()
    assert crop_icon_area(frame).any()


def test_callout_too_bright_color_is_scaled_under_the_cap():
    frame = render_page(CalloutPage("HI", "check", (255, 255, 255)))
    assert crop_text_area(frame).max() == sign.CHANNEL_CAP


def test_brightness_scales_every_pixel():
    page = NowPage("working", 3900, 3)
    full = render_page(page).astype(float)
    half = render_page(page, brightness=0.5).astype(float)
    assert np.all(np.abs(half - full * 0.5) <= 0.5)


@pytest.mark.parametrize("brightness", [0, -1, math.nan])
def test_brightness_zero_or_bad_is_dark(brightness):
    assert not render_page(NowPage("working", 3900, 3), brightness=brightness).any()


def test_brightness_above_one_is_full():
    page = TodayPage(3600, 60, 2, 1)
    assert np.array_equal(render_page(page, brightness=7), render_page(page))


def test_render_page_rejects_things_that_are_not_pages():
    with pytest.raises(TypeError):
        render_page("hello")


@pytest.mark.parametrize("scale", [1, 3, 6])
def test_preview_png_decodes_to_the_scaled_size(scale):
    image = decode_png(render_preview_png(render_page(TodayPage(3600, 60, 2, 1)), scale))
    assert image.shape == (32 * scale, 128 * scale, 3)


def test_preview_png_stays_small_enough_to_poll():
    assert len(render_preview_png(render_page(NowPage("working", 3900, 3)))) < 30_000


def test_preview_lit_dot_keeps_its_color():
    frame = np.zeros((32, 128, 3), np.uint8)
    frame[0, 0] = (200, 0, 0)
    blue, green, red = decode_png(render_preview_png(frame, 6))[3, 3]
    assert red > 150
    assert blue < 50 and green < 50


def test_preview_unlit_dots_are_faint_but_visible():
    image = decode_png(render_preview_png(np.zeros((32, 128, 3), np.uint8), 6))
    dot_middle = image[3, 3].astype(int)
    board_between_dots = image[0, 0].astype(int)
    assert dot_middle.sum() > board_between_dots.sum()
    assert dot_middle.max() < 60


def test_preview_output_is_empty_before_the_first_frame():
    assert PreviewOutput().latest_png() is None


def test_preview_output_encodes_once_per_frame(monkeypatch):
    encoded = []
    real_render = sign.render_preview_png

    def count_render(frame, scale=sign.PREVIEW_SCALE):
        encoded.append(scale)
        png = real_render(frame, scale)
        return png

    monkeypatch.setattr(sign, "render_preview_png", count_render)
    output = PreviewOutput()
    output.show(render_page(NowPage("working", 60, 0)))
    first = output.latest_png()
    assert output.latest_png() is first
    assert len(encoded) == 1

    output.show(render_page(NowPage("phone", 60, 0)))
    second = output.latest_png()
    assert len(encoded) == 2
    assert second != first


def test_preview_output_keeps_its_own_copy_of_the_frame():
    frame = render_page(NowPage("working", 60, 0))
    expected = render_preview_png(frame)
    output = PreviewOutput()
    output.show(frame)
    frame[:] = 0
    assert output.latest_png() == expected


def test_preview_output_drops_a_png_that_finished_after_a_newer_frame(monkeypatch):
    output = PreviewOutput()
    old_frame = render_page(NowPage("working", 60, 0))
    new_frame = render_page(NowPage("away", 60, 0))
    real_render = sign.render_preview_png

    def render_while_a_new_frame_arrives(frame, scale=sign.PREVIEW_SCALE):
        png = real_render(frame, scale)
        output.show(new_frame)
        return png

    monkeypatch.setattr(sign, "render_preview_png", render_while_a_new_frame_arrives)
    output.show(old_frame)
    output.latest_png()
    monkeypatch.setattr(sign, "render_preview_png", real_render)
    assert output.latest_png() == real_render(new_frame)


def test_preview_output_handles_shows_and_reads_from_many_threads():
    output = PreviewOutput(scale=1)
    frames = [render_page(NowPage("working", seconds, 0)) for seconds in range(0, 3000, 100)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(output.show, frame) for frame in frames]
        jobs += [pool.submit(output.latest_png) for _ in frames]
        for job in jobs:
            job.result()
    output.show(frames[-1])
    assert output.latest_png() == render_preview_png(frames[-1], 1)


def build_fake_piomatter():
    """Stands in for Adafruit's module, with the same names and constructor arguments as its docs."""
    module = types.ModuleType(PIOMATTER)
    module.matrices = []
    module.Orientation = types.SimpleNamespace(Normal="Normal", R180="R180", CW="CW", CCW="CCW")
    module.Pinout = types.SimpleNamespace(
        AdafruitMatrixBonnet="AdafruitMatrixBonnet",
        AdafruitMatrixBonnetBGR="AdafruitMatrixBonnetBGR",
    )
    module.Colorspace = types.SimpleNamespace(RGB888Packed="RGB888Packed", RGB888="RGB888", RGB565="RGB565")

    class FakeGeometry:
        def __init__(self, width, height, n_addr_lines, serpentine=True, rotation="Normal", n_planes=10):
            self.width = width
            self.height = height
            self.n_addr_lines = n_addr_lines
            self.rotation = rotation

    class FakeMatrix:
        def __init__(self, colorspace, pinout, framebuffer, geometry):
            self.colorspace = colorspace
            self.pinout = pinout
            self.framebuffer = framebuffer
            self.geometry = geometry
            self.shown = []
            module.matrices.append(self)

        def show(self):
            self.shown.append(self.framebuffer.copy())

    module.Geometry = FakeGeometry
    module.PioMatter = FakeMatrix
    return module


@pytest.fixture
def fake_piomatter(monkeypatch):
    module = build_fake_piomatter()
    monkeypatch.setitem(sys.modules, PIOMATTER, module)
    return module


def test_importing_sign_does_not_need_piomatter():
    assert PIOMATTER not in sys.modules


def test_panel_output_without_piomatter_raises_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, PIOMATTER, None)
    with pytest.raises(ImportError):
        PanelOutput()


def test_panel_output_drives_two_chained_64x32_panels_through_the_bonnet(fake_piomatter):
    PanelOutput()
    matrix = fake_piomatter.matrices[0]
    assert (matrix.geometry.width, matrix.geometry.height) == (128, 32)
    assert matrix.geometry.n_addr_lines == 4
    assert matrix.geometry.rotation == "Normal"
    assert matrix.colorspace == "RGB888Packed"
    assert matrix.pinout == "AdafruitMatrixBonnet"
    assert matrix.framebuffer.shape == (32, 128, 3)
    assert matrix.framebuffer.dtype == np.uint8


def test_panel_output_copies_each_frame_in_then_shows_it(fake_piomatter):
    panel = PanelOutput()
    matrix = fake_piomatter.matrices[0]
    framebuffer = matrix.framebuffer
    first = render_page(NowPage("working", 60, 0))
    second = render_page(TodayPage(3600, 60, 2, 1))

    panel.show(first)
    panel.show(second)
    second[:] = 0

    assert len(matrix.shown) == 2
    assert np.array_equal(matrix.shown[0], first)
    assert np.array_equal(matrix.shown[1], render_page(TodayPage(3600, 60, 2, 1)))
    assert matrix.framebuffer is framebuffer
    assert framebuffer.any()
