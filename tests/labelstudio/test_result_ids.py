from cookimport.labelstudio.result_ids import (
    make_safe_label_studio_result_id,
    sanitize_label_studio_result_ids,
)


def test_make_safe_label_studio_result_id_preserves_css_safe_ids() -> None:
    assert (
        make_safe_label_studio_result_id("cookimport-prelabel-123")
        == "cookimport-prelabel-123"
    )


def test_make_safe_label_studio_result_id_rewrites_urn_ids() -> None:
    rendered = make_safe_label_studio_result_id(
        "seed-urn:cookimport:row:abc:12:0-KNOWLEDGE"
    )

    assert ":" not in rendered
    assert rendered.startswith("seed-urn-cookimport-row-")


def test_sanitize_label_studio_result_ids_rewrites_relation_references() -> None:
    sanitized = sanitize_label_studio_result_ids(
        [
            {
                "id": "seed-urn:cookimport:row:abc:12:0-KNOWLEDGE",
                "type": "labels",
            },
            {
                "id": "rel:1",
                "type": "relation",
                "from_id": "seed-urn:cookimport:row:abc:12:0-KNOWLEDGE",
                "to_id": "seed-urn:cookimport:row:abc:12:0-KNOWLEDGE",
            },
        ]
    )

    first_id = sanitized[0]["id"]
    assert ":" not in first_id
    assert sanitized[1]["from_id"] == first_id
    assert sanitized[1]["to_id"] == first_id
