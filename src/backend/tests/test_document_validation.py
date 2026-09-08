from typing import Any

import pytest

from app.content import DocumentValidationError, extract_search_text, validate_document
from app.content.validation import MAX_DEPTH, MAX_NODES


def _doc(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "content": list(blocks)}


def _para(text: str = "Hello", marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks is not None:
        node["marks"] = marks
    return {"type": "paragraph", "content": [node]}


# --- The documents an author actually writes ---


def test_the_full_release_1_node_set_is_accepted() -> None:
    document = _doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Title"}]},
        _para("Plain text"),
        _para("Bold", [{"type": "bold"}]),
        _para("Italic", [{"type": "italic"}]),
        _para("Inline code", [{"type": "code"}]),
        _para("A link", [{"type": "link", "attrs": {"href": "https://example.com/policy"}}]),
        {
            "type": "bulletList",
            "content": [{"type": "listItem", "content": [_para("First")]}],
        },
        {
            "type": "orderedList",
            "attrs": {"start": 1},
            "content": [{"type": "listItem", "content": [_para("Step one")]}],
        },
        {"type": "blockquote", "content": [_para("Quoted")]},
        {
            "type": "codeBlock",
            "attrs": {"language": "python"},
            "content": [{"type": "text", "text": "print('hi')"}],
        },
        {"type": "horizontalRule"},
        {"type": "paragraph", "content": [{"type": "text", "text": "a"}, {"type": "hardBreak"}]},
    )

    validated = validate_document(document)

    assert validated["type"] == "doc"
    assert [block["type"] for block in validated["content"]] == [
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
        "bulletList",
        "orderedList",
        "blockquote",
        "codeBlock",
        "horizontalRule",
        "paragraph",
    ]


@pytest.mark.parametrize("href", ["https://example.com", "mailto:safety@example.com", "/modules/3"])
def test_permitted_link_targets_are_accepted(href: str) -> None:
    validate_document(_doc(_para("Link", [{"type": "link", "attrs": {"href": href}}])))


def test_heading_levels_two_to_four_are_accepted() -> None:
    for level in (2, 3, 4):
        validate_document(
            _doc({"type": "heading", "attrs": {"level": level}, "content": []})
        )


# --- Rejection, never a silent strip ---


def test_an_unknown_node_type_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "script", "content": []}))

    assert error.value.code == "unknown_node_type"


def test_an_unknown_mark_type_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc(_para("x", [{"type": "onmouseover"}])))

    assert error.value.code == "unknown_mark_type"


def test_an_unknown_node_attribute_is_rejected_rather_than_stripped() -> None:
    # prosemirror-py on its own drops an attribute it doesn't know and accepts
    # the document. That is the behaviour this platform refuses.
    with pytest.raises(DocumentValidationError) as error:
        validate_document(
            _doc({"type": "heading", "attrs": {"level": 2, "onclick": "steal()"}, "content": []})
        )

    assert error.value.code == "unknown_attribute"


def test_an_unknown_mark_attribute_is_rejected_rather_than_stripped() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(
            _doc(
                _para(
                    "x",
                    [
                        {
                            "type": "link",
                            "attrs": {"href": "https://example.com", "onclick": "steal()"},
                        }
                    ],
                )
            )
        )

    assert error.value.code == "unknown_attribute"


def test_an_unknown_key_on_a_node_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "paragraph", "content": [], "nodeSize": 99}))

    assert error.value.code == "unknown_node_key"


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)",
        "java\tscript:alert(1)",
        "\x01javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "http://example.com",
        "//evil.example.com/x",
        "/\\evil.example.com/x",
        "file:///etc/passwd",
        "",
    ],
)
def test_a_disallowed_link_href_is_rejected(href: str) -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc(_para("x", [{"type": "link", "attrs": {"href": href}}])))

    assert error.value.code == "bad_href"


@pytest.mark.parametrize(
    "src",
    [
        "javascript:alert(1)",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "vbscript:msgbox(1)",
        "https://evil.example.com/tracker.gif",
        "//evil.example.com/tracker.gif",
        "/api/modules/../../etc/passwd",
        "",
    ],
)
def test_a_disallowed_image_src_is_rejected(src: str) -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "image", "attrs": {"src": src}}))

    assert error.value.code == "bad_src"


def test_an_image_pointing_at_a_platform_asset_path_is_accepted() -> None:
    src = (
        "/api/modules/3f1a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8"
        "/assets/1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809"
    )

    validate_document(_doc({"type": "image", "attrs": {"src": src}}))


def test_a_heading_outside_levels_two_to_four_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "heading", "attrs": {"level": 1}, "content": []}))

    assert error.value.code == "bad_attribute"


def test_invalid_nesting_is_rejected_by_the_schema() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "paragraph", "content": [_para("nested")]}))

    assert error.value.code == "schema_violation"


def test_a_listitem_at_the_top_level_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "listItem", "content": [_para("x")]}))

    assert error.value.code == "schema_violation"


def test_a_marked_code_block_is_rejected() -> None:
    # `codeBlock` allows no marks at all — a link inside one would render as a
    # link in a place the author cannot see it in the editor.
    with pytest.raises(DocumentValidationError) as error:
        validate_document(
            _doc(
                {
                    "type": "codeBlock",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [{"type": "link", "attrs": {"href": "https://evil.example"}}],
                        }
                    ],
                }
            )
        )

    assert error.value.code == "schema_violation"


def test_an_over_deep_document_is_rejected() -> None:
    node: dict[str, Any] = _para("deep")
    for _ in range(MAX_DEPTH + 2):
        node = {"type": "blockquote", "content": [node]}

    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc(node))

    assert error.value.code == "too_deep"


def test_a_document_with_too_many_nodes_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc(*[_para("x") for _ in range(MAX_NODES)]))

    assert error.value.code == "too_many_nodes"


def test_an_over_large_document_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc(_para("x" * 300_000)))

    assert error.value.code == "document_too_large"


@pytest.mark.parametrize("body", ["a string", 42, None, [], True])
def test_a_body_that_is_not_a_document_object_is_rejected(body: Any) -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(body)

    assert error.value.code == "not_a_document"


def test_a_non_doc_root_node_is_rejected() -> None:
    with pytest.raises(DocumentValidationError):
        validate_document(_para("Not wrapped in a doc"))


def test_a_text_node_without_text_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "paragraph", "content": [{"type": "text"}]}))

    assert error.value.code == "malformed_text"


def test_a_non_text_node_carrying_text_is_rejected() -> None:
    with pytest.raises(DocumentValidationError) as error:
        validate_document(_doc({"type": "paragraph", "text": "smuggled", "content": []}))

    assert error.value.code == "malformed_text"


# --- Search text extraction ---


def test_search_text_is_the_documents_prose_and_nothing_else() -> None:
    document = validate_document(
        _doc(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Fire safety"}],
            },
            _para("Read the rules", [{"type": "link", "attrs": {"href": "https://evil.example/x"}}]),
        )
    )

    text = extract_search_text(document)

    assert text == "Fire safety Read the rules"
    # Neither node type names nor URL fragments — the whole reason the index is
    # built from a tree walk rather than jsonb_to_tsvector over the raw tree.
    assert "paragraph" not in text
    assert "evil.example" not in text
    assert "link" not in text


def test_search_text_of_an_empty_document_is_empty() -> None:
    assert extract_search_text({"type": "doc", "content": []}) == ""
