import json

import numpy as np

from dayanpi.vision import export_fixture


def read_pixels(fixture: dict) -> list[list[int]]:
    pixels = [fixture["resize"]["source"]["data"], fixture["warp"]["result"]["data"]] + [result["data"] for result in fixture["resize"]["results"]]
    return pixels


def test_the_browser_fixture_is_up_to_date():
    """web/src/lib/vision/ is checked against this file, so a change in vision/ has to land in it too:
    .venv/bin/python -m dayanpi.vision.export_fixture"""
    fresh = export_fixture.build_fixture()
    saved = json.loads(export_fixture.FIXTURE_PATH.read_text(encoding="utf-8"))
    pixels = export_fixture.PIXEL_SECTIONS
    assert {name: value for name, value in fresh.items() if name not in pixels} == {name: value for name, value in saved.items() if name not in pixels}
    for fresh_data, saved_data in zip(read_pixels(fresh), read_pixels(saved), strict=True):
        assert np.abs(np.array(fresh_data) - np.array(saved_data)).max() <= 2
