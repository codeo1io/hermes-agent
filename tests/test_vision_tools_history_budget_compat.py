import json

import tools.vision_tools_history_budget as budget


def test_expected_history_budget_api_imports():
    assert callable(budget.native_turn_images)
    assert callable(budget.native_turn_duplicate)
    assert callable(budget.record_embed)
    assert callable(budget.release_embed)
    assert callable(budget.repeat_refusal)
    assert callable(budget.resolve_repeat_cap)
    assert callable(budget.resolve_embed_target_bytes)


def test_native_turn_duplicate_is_scoped_to_current_turn(tmp_path):
    image = str(tmp_path / "image.png")
    message = [
        {"type": "text", "text": f"[Image attached at: {image}]"},
        {"type": "image_url", "image_url": {"url": f"file://{image}"}},
    ]
    assert budget.native_turn_duplicate(image, None) is None
    with budget.native_turn_images(message):
        result = budget.native_turn_duplicate(image, None)
        assert json.loads(result)["already_in_context"] is True
        assert budget.native_turn_duplicate(image, [0, 0, 1, 1]) is None
    assert budget.native_turn_duplicate(image, None) is None


def test_repeat_budget_reservation_and_release(monkeypatch):
    budget._repeat_counts.clear()
    monkeypatch.setattr(budget, "resolve_repeat_cap", lambda: 2)
    monkeypatch.setattr(budget, "_count_key", lambda _url: ("session", "image"))
    assert budget.repeat_refusal("image") is None
    assert budget.repeat_refusal("image") is None
    refused = budget.repeat_refusal("image")
    assert refused is not None and "refused" in refused
    budget.release_embed("image")
    assert budget.repeat_refusal("image") is None
