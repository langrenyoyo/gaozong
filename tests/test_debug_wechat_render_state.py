"""P0-3A Render Ready 诊断脚本测试"""

from PIL import Image


def test_gray_low_edge_image_is_render_suspect():
    from scripts.debug_wechat_render_state import calculate_pixel_metrics, is_render_suspect

    img = Image.new("RGB", (20, 20), (150, 150, 150))

    metrics = calculate_pixel_metrics(img)
    suspect = is_render_suspect(visible=True, iconic=False, metrics=metrics)

    assert metrics["gray_ratio"] == 1.0
    assert metrics["edge_score"] == 0
    assert suspect is True


def test_high_detail_normal_image_is_not_render_suspect():
    from scripts.debug_wechat_render_state import calculate_pixel_metrics, is_render_suspect

    img = Image.new("RGB", (20, 20), (255, 255, 255))
    pixels = img.load()
    for y in range(20):
        for x in range(20):
            pixels[x, y] = (255, 255, 255) if (x + y) % 2 == 0 else (20, 80, 180)

    metrics = calculate_pixel_metrics(img)
    suspect = is_render_suspect(visible=True, iconic=False, metrics=metrics)

    assert metrics["edge_score"] > 0
    assert suspect is False


def test_manual_observation_mapping():
    from scripts.debug_wechat_render_state import parse_manual_observation

    assert parse_manual_observation("y") == "normal"
    assert parse_manual_observation("g") == "gray"
    assert parse_manual_observation("h") == "hidden"
    assert parse_manual_observation("n") == "other"
    assert parse_manual_observation("") is None


def test_first_step_helpers():
    from scripts.debug_wechat_render_state import (
        first_manual_abnormal_step,
        first_render_suspect_step,
    )

    records = [
        {"step": "step_01_initial_state", "render_suspect": False, "manual_observation": None},
        {"step": "step_02_activate", "render_suspect": True, "manual_observation": "normal"},
        {"step": "step_03_click_search_box", "render_suspect": False, "manual_observation": "gray"},
    ]

    assert first_render_suspect_step(records) == "step_02_activate"
    assert first_manual_abnormal_step(records) == "step_03_click_search_box"
