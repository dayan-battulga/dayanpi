"""Draws the focus tracker's LED sign: two 64x32 HUB75 panels side by side, 128x32 pixels.

Every page renders to a plain numpy frame, (32, 128, 3) uint8 RGB, so the sign can be
tested and previewed in the browser before the panels arrive:
- render_page() turns a NowPage, TodayPage, CalloutPage or SummaryPage into a frame.
- PreviewOutput keeps the last frame as a PNG that looks like the real panels.
- PanelOutput sends frames to the panels through Adafruit's Piomatter library.
"""

import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np

import sign_glyphs

SIGN_WIDTH = 128
SIGN_HEIGHT = 32
# Full white is blinding up close, and both panels on full white would pull about 8A from one 4A supply.
CHANNEL_CAP = 200

AMBER = (200, 120, 0)
RED = (200, 30, 20)
DIM_BLUE = (40, 70, 150)
GRAY = (110, 110, 110)
GREEN = (40, 190, 50)

LETTER_GAP = 1
BIG_SCALE = 2
BIG_ICON_SCALE = 2
EDGE_MARGIN = 1
BADGE_GAP = 2
BADGE_COLOR = GRAY
FALLBACK_CHAR = "?"
FALLBACK_ICON = "question"
COUNT_MAX = 9999
DURATION_MAX_S = 999 * 3600 + 59 * 60

NOW_TEXT_LEFT = 36
NOW_LABEL_TOP = 3
NOW_DURATION_TOP = 15

TODAY_LABEL_LEFT = 1
TODAY_VALUE_LEFT = 34
TODAY_FOCUS_TOP = 1
TODAY_PHONE_TOP = 17
TODAY_LABEL_DROP = 4

CALLOUT_TEXT_LEFT = 36
CALLOUT_TEXT_SCALE = 2
CALLOUT_TEXT_TOP = 9

SUMMARY_LABEL_LEFT = 36
SUMMARY_VALUE_LEFT = 72
SUMMARY_LINE_PITCH = 8

PREVIEW_SCALE = 6
PREVIEW_MAX_SCALE = 16
PREVIEW_BOARD = (10, 10, 12)
PREVIEW_UNLIT_DOT = (34, 34, 38)
PREVIEW_DOT_FILL = 0.78
PREVIEW_PNG_COMPRESSION = 3

PANEL_ADDRESS_LINES = 4
PANEL_PINOUT = "AdafruitMatrixBonnet"
PANEL_ORIENTATION = "Normal"


@dataclass
class NowPage:
    state: str
    seconds_in_state: float
    pickups_today: int


@dataclass
class TodayPage:
    working_seconds: float
    phone_seconds: float
    pickups: int
    snacks: int


@dataclass
class CalloutPage:
    text: str
    icon: str
    color: tuple[int, int, int]
    scroll_px: int = 0


@dataclass
class SummaryPage:
    working_seconds: float
    phone_seconds: float
    pickups: int
    longest_streak_seconds: float


@dataclass
class Region:
    """A rectangle of frame pixels; right and bottom are exclusive."""

    left: int
    top: int
    right: int
    bottom: int


@dataclass
class Bitmap:
    """pixels is (height, width, 3) uint8 RGB; mask is True where a pixel is lit."""

    pixels: np.ndarray
    mask: np.ndarray


@dataclass
class StateStyle:
    icon: str
    label: str
    color: tuple[int, int, int]


FULL_FRAME = Region(left=0, top=0, right=SIGN_WIDTH, bottom=SIGN_HEIGHT)

STATE_STYLES = {
    "working": StateStyle(icon="fire", label="FOCUSED", color=AMBER),
    "phone": StateStyle(icon="phone", label="PHONE", color=RED),
    "away": StateStyle(icon="zzz", label="AWAY", color=DIM_BLUE),
    "unknown": StateStyle(icon="question", label="?", color=GRAY),
}


def build_glyph_mask(rows: tuple[str, ...]) -> np.ndarray:
    mask = np.array([[cell == sign_glyphs.LIT for cell in row] for row in rows], dtype=bool)
    return mask


def build_bitmap(rows: tuple[str, ...]) -> Bitmap:
    """rows is palette art: one sign_glyphs.PALETTE key per pixel, '.' for dark."""
    height = len(rows)
    width = len(rows[0])
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=bool)
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell != sign_glyphs.DARK:
                pixels[y, x] = sign_glyphs.PALETTE[cell]
                mask[y, x] = True
    bitmap = Bitmap(pixels=pixels, mask=mask)
    return bitmap


GLYPH_MASKS = {char: build_glyph_mask(rows) for char, rows in sign_glyphs.FONT.items()}
ICON_BITMAPS = {name: build_bitmap(rows) for name, rows in sign_glyphs.ICONS.items()}
MINI_ICON_BITMAPS = {name: build_bitmap(rows) for name, rows in sign_glyphs.MINI_ICONS.items()}


def sanitize_scale(scale: int) -> int:
    whole_scale = max(1, int(scale))
    return whole_scale


def scale_up(pixels: np.ndarray, scale: int) -> np.ndarray:
    """Blows each pixel up into a scale x scale block; works on masks and RGB arrays."""
    scaled = np.repeat(np.repeat(pixels, scale, axis=0), scale, axis=1)
    return scaled


def scale_bitmap(bitmap: Bitmap, scale: int) -> Bitmap:
    scaled = Bitmap(pixels=scale_up(bitmap.pixels, scale), mask=scale_up(bitmap.mask, scale))
    return scaled


def find_glyph(char: str) -> np.ndarray:
    """Tabs and newlines draw as spaces; any other character the font lacks draws as '?'."""
    fallback = " " if char.isspace() else FALLBACK_CHAR
    mask = GLYPH_MASKS.get(char, GLYPH_MASKS[fallback])
    return mask


def find_icon(name: str) -> Bitmap:
    bitmap = ICON_BITMAPS.get(name, ICON_BITMAPS[FALLBACK_ICON])
    return bitmap


def build_text_mask(text: str) -> np.ndarray:
    """The text as one (7, width) bool array, with LETTER_GAP dark columns between letters."""
    gap = np.zeros((sign_glyphs.GLYPH_HEIGHT, LETTER_GAP), dtype=bool)
    pieces = []
    for char in text:
        pieces.extend([find_glyph(char), gap])
    mask = np.zeros((sign_glyphs.GLYPH_HEIGHT, 0), dtype=bool)
    if pieces:
        mask = np.hstack(pieces[:-1])
    return mask


def measure_text(text: str, scale: int = 1) -> int:
    """Pixel width of text drawn at this scale, with no gap after the last letter."""
    advance = sign_glyphs.GLYPH_WIDTH + LETTER_GAP
    width = max(0, len(text) * advance - LETTER_GAP) * sanitize_scale(scale)
    return width


def paste_bitmap(frame: np.ndarray, bitmap: Bitmap, left: int, top: int, clip: Region) -> None:
    """Copies the bitmap's lit pixels with its top-left corner at (left, top).

    Anything outside clip or the frame is cut off, so this never writes out of bounds.
    """
    height, width = bitmap.mask.shape
    frame_height, frame_width = frame.shape[:2]
    x1 = max(left, clip.left, 0)
    y1 = max(top, clip.top, 0)
    x2 = min(left + width, clip.right, frame_width)
    y2 = min(top + height, clip.bottom, frame_height)
    if x1 < x2 and y1 < y2:
        rows = slice(y1 - top, y2 - top)
        columns = slice(x1 - left, x2 - left)
        lit = bitmap.mask[rows, columns]
        frame[y1:y2, x1:x2][lit] = bitmap.pixels[rows, columns][lit]


def draw_text(
    frame: np.ndarray,
    text: str,
    left: int,
    top: int,
    color: tuple[int, int, int] | np.ndarray,
    scale: int = 1,
    clip: Region = FULL_FRAME,
) -> None:
    """Draws text with its top-left corner at (left, top); anything outside clip or the frame is cut off."""
    safe_scale = sanitize_scale(scale)
    advance = (sign_glyphs.GLYPH_WIDTH + LETTER_GAP) * safe_scale
    # Only letters that can land inside clip get built, so long scrolling text stays cheap.
    first = max(0, (clip.left - left) // advance)
    last = min(len(text), max(0, -(-(clip.right - left) // advance)))
    if first < last:
        mask = scale_up(build_text_mask(text[first:last]), safe_scale)
        pixels = np.broadcast_to(np.asarray(color, dtype=np.uint8), mask.shape + (3,))
        paste_bitmap(frame, Bitmap(pixels=pixels, mask=mask), left + first * advance, top, clip)


def draw_icon(
    frame: np.ndarray,
    name: str,
    left: int,
    top: int,
    scale: int = 1,
    clip: Region = FULL_FRAME,
) -> None:
    paste_bitmap(frame, scale_bitmap(find_icon(name), sanitize_scale(scale)), left, top, clip)


def find_badge_left(icon_name: str, text: str) -> int:
    """Left edge of a badge (mini icon plus small text) that ends EDGE_MARGIN from the right edge."""
    badge_width = MINI_ICON_BITMAPS[icon_name].mask.shape[1] + BADGE_GAP + measure_text(text)
    left = SIGN_WIDTH - EDGE_MARGIN - badge_width
    return left


def draw_badge(frame: np.ndarray, icon_name: str, text: str, top: int) -> None:
    """A mini icon plus small text, pushed up against the right edge."""
    icon = MINI_ICON_BITMAPS[icon_name]
    left = find_badge_left(icon_name, text)
    paste_bitmap(frame, icon, left, top, FULL_FRAME)
    draw_text(frame, text, left + icon.mask.shape[1] + BADGE_GAP, top, BADGE_COLOR)


def clamp(value: float, low: float, high: float) -> float:
    """value squeezed into low..high, with NaN as low."""
    # Clamp before isnan: isnan converts to float, which overflows on huge ints.
    clamped = min(max(value, low), high)
    safe_value = low if math.isnan(clamped) else clamped
    return safe_value


def limit_color(color: tuple[int, int, int]) -> np.ndarray:
    """Scales a caller's colour down so no channel passes CHANNEL_CAP, keeping its hue."""
    channels = np.clip(np.asarray(color[:3], dtype=np.float64), 0, 255)
    peak = channels.max()
    factor = CHANNEL_CAP / peak if peak > CHANNEL_CAP else 1.0
    limited = np.rint(channels * factor).astype(np.uint8)
    return limited


def format_duration(seconds: float) -> str:
    """Short and glanceable: "45s", "12m", "1h05", "10h30". Negative or NaN shows as "0s"."""
    whole_seconds = int(clamp(seconds, 0, DURATION_MAX_S))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes = remainder // 60
    duration = f"{hours}h{minutes:02d}"
    if whole_seconds < 60:
        duration = f"{whole_seconds}s"
    elif whole_seconds < 3600:
        duration = f"{minutes}m"
    return duration


def format_count(count: float) -> str:
    """Whole number from 0 to COUNT_MAX, so a runaway counter can't push the layout around."""
    text = str(int(clamp(count, 0, COUNT_MAX)))
    return text


def draw_now_page(frame: np.ndarray, page: NowPage) -> None:
    """Big state icon, state label, time in this state, and today's pickups top right."""
    style = STATE_STYLES.get(page.state, STATE_STYLES["unknown"])
    draw_icon(frame, style.icon, 0, 0, scale=BIG_ICON_SCALE)
    draw_text(frame, style.label, NOW_TEXT_LEFT, NOW_LABEL_TOP, style.color)
    draw_text(
        frame,
        format_duration(page.seconds_in_state),
        NOW_TEXT_LEFT,
        NOW_DURATION_TOP,
        style.color,
        scale=BIG_SCALE,
    )
    draw_badge(frame, "phone", format_count(page.pickups_today), NOW_LABEL_TOP)


def draw_stat_row(
    frame: np.ndarray,
    label: str,
    value: str,
    color: tuple[int, int, int],
    badge_icon: str,
    badge_text: str,
    top: int,
) -> None:
    """One TodayPage row: small label level with the big value's middle, and a badge on the right
    that a huge value gets clipped short of."""
    value_area = Region(
        left=0,
        top=0,
        right=find_badge_left(badge_icon, badge_text) - BADGE_GAP,
        bottom=SIGN_HEIGHT,
    )
    draw_text(frame, label, TODAY_LABEL_LEFT, top + TODAY_LABEL_DROP, color)
    draw_text(frame, value, TODAY_VALUE_LEFT, top, color, scale=BIG_SCALE, clip=value_area)
    draw_badge(frame, badge_icon, badge_text, top + TODAY_LABEL_DROP)


def draw_today_page(frame: np.ndarray, page: TodayPage) -> None:
    """FOCUS and PHONE totals, with snacks and pickups as badges."""
    draw_stat_row(
        frame,
        "FOCUS",
        format_duration(page.working_seconds),
        AMBER,
        "food",
        format_count(page.snacks),
        TODAY_FOCUS_TOP,
    )
    draw_stat_row(
        frame,
        "PHONE",
        format_duration(page.phone_seconds),
        RED,
        "phone",
        format_count(page.pickups),
        TODAY_PHONE_TOP,
    )


def measure_callout(text: str) -> int:
    """How far scroll_px has to go before a CalloutPage's text has fully scrolled out of view."""
    width = measure_text(text, CALLOUT_TEXT_SCALE)
    return width


def draw_callout_page(frame: np.ndarray, page: CalloutPage) -> None:
    """Icon fixed on the left; the text slides through the area right of it and is clipped there."""
    text_area = Region(left=CALLOUT_TEXT_LEFT, top=0, right=SIGN_WIDTH, bottom=SIGN_HEIGHT)
    # Past either end nothing shows, so clamping changes no pixels but keeps inf and NaN out of int().
    scroll = int(clamp(page.scroll_px, -SIGN_WIDTH, measure_callout(page.text)))
    draw_icon(frame, page.icon, 0, 0, scale=BIG_ICON_SCALE)
    draw_text(
        frame,
        page.text,
        CALLOUT_TEXT_LEFT - scroll,
        CALLOUT_TEXT_TOP,
        limit_color(page.color),
        scale=CALLOUT_TEXT_SCALE,
        clip=text_area,
    )


def draw_summary_page(frame: np.ndarray, page: SummaryPage) -> None:
    """End of day: a big check, DAY DONE with the day's pickups, then three totals."""
    draw_icon(frame, "check", 0, 0, scale=BIG_ICON_SCALE)
    draw_text(frame, "DAY DONE", SUMMARY_LABEL_LEFT, 0, GREEN)
    draw_badge(frame, "phone", format_count(page.pickups), 0)
    lines = [
        ("FOCUS", page.working_seconds, AMBER),
        ("PHONE", page.phone_seconds, RED),
        ("BEST", page.longest_streak_seconds, GRAY),
    ]
    for line_number, (label, seconds, color) in enumerate(lines, start=1):
        top = line_number * SUMMARY_LINE_PITCH
        draw_text(frame, label, SUMMARY_LABEL_LEFT, top, color)
        draw_text(frame, format_duration(seconds), SUMMARY_VALUE_LEFT, top, color)


PAGE_DRAWERS = {
    NowPage: draw_now_page,
    TodayPage: draw_today_page,
    CalloutPage: draw_callout_page,
    SummaryPage: draw_summary_page,
}


def render_page(page: NowPage | TodayPage | CalloutPage | SummaryPage, brightness: float = 1.0) -> np.ndarray:
    """The page as a (32, 128, 3) uint8 RGB frame; brightness (0 to 1) scales every pixel."""
    draw_page = PAGE_DRAWERS.get(type(page))
    if draw_page is None:
        raise TypeError(f"not a sign page: {type(page).__name__}")
    frame = np.zeros((SIGN_HEIGHT, SIGN_WIDTH, 3), dtype=np.uint8)
    draw_page(frame, page)
    dimmed = np.rint(frame * clamp(brightness, 0.0, 1.0)).astype(np.uint8)
    return dimmed


def build_dot_alpha(scale: int) -> np.ndarray:
    """How much of each preview pixel one round LED covers (0 to 1), for one scale x scale cell."""
    offsets = np.arange(scale, dtype=np.float32) - (scale - 1) / 2
    distance = np.hypot(offsets[:, None], offsets[None, :])
    alpha = np.clip(PREVIEW_DOT_FILL * scale / 2 - distance + 0.5, 0.0, 1.0).astype(np.float32)
    return alpha


def render_preview_png(frame: np.ndarray, scale: int = PREVIEW_SCALE) -> bytes:
    """A PNG that looks like the panels: round dots on a dark board, unlit dots faintly visible.

    scale is pixels per LED, kept between 1 and PREVIEW_MAX_SCALE.
    """
    safe_scale = min(sanitize_scale(scale), PREVIEW_MAX_SCALE)
    height, width = frame.shape[:2]
    lit = frame.astype(np.float32)
    # A lit LED shows its own colour; the faint unlit gray fades out as it brightens.
    unlit_share = 1.0 - lit.max(axis=2, keepdims=True) / 255.0
    dots = lit + np.asarray(PREVIEW_UNLIT_DOT, dtype=np.float32) * unlit_share
    alpha = np.tile(build_dot_alpha(safe_scale), (height, width))[..., None]
    board = np.asarray(PREVIEW_BOARD, dtype=np.float32)
    image = board + (scale_up(dots, safe_scale) - board) * alpha
    rgb = np.clip(np.rint(image), 0, 255).astype(np.uint8)
    # Without an explicit level OpenCV uses its RLE strategy, which makes these dotted PNGs ~20x bigger.
    encoded = cv2.imencode(
        ".png",
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_PNG_COMPRESSION, PREVIEW_PNG_COMPRESSION],
    )[1]
    png = encoded.tobytes()
    return png


class PreviewOutput:
    """Holds the last frame for the dashboard; the PNG is only encoded when someone asks."""

    def __init__(self, scale: int = PREVIEW_SCALE) -> None:
        self._scale = scale
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._png: bytes | None = None
        self._version = 0

    @property
    def version(self) -> int:
        """Goes up only when the picture actually changes, so callers can skip re-sending it."""
        with self._lock:
            version = self._version
        return version

    def show(self, frame: np.ndarray) -> None:
        frame_copy = np.array(frame, dtype=np.uint8, copy=True)
        with self._lock:
            unchanged = self._frame is not None and np.array_equal(self._frame, frame_copy)
            if not unchanged:
                self._frame = frame_copy
                self._png = None
                self._version += 1

    def latest_png(self) -> bytes | None:
        with self._lock:
            frame = self._frame
            png = self._png
            version = self._version
        if png is None and frame is not None:
            png = render_preview_png(frame, self._scale)
            with self._lock:
                if self._version == version:
                    self._png = png
        return png


class PanelOutput:
    """The real panels; call show() from one thread. Untested on hardware until they arrive."""

    def __init__(self) -> None:
        # Imported here so the app and the tests run on machines without Piomatter.
        import adafruit_blinka_raspberry_pi5_piomatter as piomatter

        geometry = piomatter.Geometry(
            width=SIGN_WIDTH,
            height=SIGN_HEIGHT,
            n_addr_lines=PANEL_ADDRESS_LINES,
            rotation=getattr(piomatter.Orientation, PANEL_ORIENTATION),
        )
        self._framebuffer = np.zeros((SIGN_HEIGHT, SIGN_WIDTH, 3), dtype=np.uint8)
        self._matrix = piomatter.PioMatter(
            colorspace=piomatter.Colorspace.RGB888Packed,
            pinout=getattr(piomatter.Pinout, PANEL_PINOUT),
            framebuffer=self._framebuffer,
            geometry=geometry,
        )

    def show(self, frame: np.ndarray) -> None:
        self._framebuffer[:] = frame
        self._matrix.show()
