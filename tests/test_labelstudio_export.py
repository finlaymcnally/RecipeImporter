from cookimport.labelstudio.export import _extract_labels, _map_to_tip_label, _select_annotation


def test_extract_labels_and_mapping() -> None:
    annotation = {
        "result": [
            {"from_name": "content_type", "value": {"choices": ["tip"]}},
            {"from_name": "value_usefulness", "value": {"choices": ["useful"]}},
            {"from_name": "tags", "value": {"choices": ["timing", "storage"]}},
        ]
    }
    labels = _extract_labels(annotation)
    assert labels["content_type"] == "tip"
    assert labels["value_usefulness"] == "useful"
    assert labels["tags"] == ["timing", "storage"]
    assert _map_to_tip_label(labels) == "tip"

    labels["content_type"] = "mixed"
    assert _map_to_tip_label(labels) is None


def test_select_annotation_latest() -> None:
    task = {
        "annotations": [
            {"id": 1, "result": [{"from_name": "content_type", "value": {"choices": ["tip"]}}]},
            {"id": 2, "result": [{"from_name": "content_type", "value": {"choices": ["fluff"]}}]},
        ]
    }
    selected = _select_annotation(task)
    assert selected is not None
    labels = _extract_labels(selected)
    assert labels["content_type"] == "fluff"
