from __future__ import annotations

from cookimport.parsing.atoms import contextualize_atoms, split_text_to_atoms


def test_split_paragraphs_into_atoms():
    atoms = split_text_to_atoms("Tip one.\n\nTip two.", block_index=3)
    assert [atom.text for atom in atoms] == ["Tip one.", "Tip two."]
    assert all(atom.kind == "paragraph" for atom in atoms)


def test_split_list_items_into_atoms():
    text = "Intro:\n- Use cold butter.\n- Don't overmix."
    atoms = split_text_to_atoms(text, block_index=5)
    assert atoms[0].kind == "paragraph"
    assert atoms[0].text.startswith("Intro")
    assert atoms[1].kind == "list_item"
    assert atoms[1].text.startswith("-")
    assert atoms[2].kind == "list_item"


def test_split_numbered_list_items_into_atoms():
    text = "1. First tip\n2) Second tip"
    atoms = split_text_to_atoms(text, block_index=7)
    assert len(atoms) == 2
    assert all(atom.kind == "list_item" for atom in atoms)


def test_contextualize_atoms_sets_prev_next():
    atoms = split_text_to_atoms("One.\n\nTwo.\n\nThree.", block_index=1)
    contextualize_atoms(atoms)
    assert atoms[0].context_prev is None
    assert atoms[0].context_next == "Two."
    assert atoms[1].context_prev == "One."
    assert atoms[1].context_next == "Three."
    assert atoms[2].context_prev == "Two."
    assert atoms[2].context_next is None


def test_container_metadata_is_preserved():
    atoms = split_text_to_atoms(
        "Alpha\n\nBeta",
        block_index=2,
        container_start=10,
        container_end=12,
        container_header="Storage",
    )
    assert all(atom.container_start == 10 for atom in atoms)
    assert all(atom.container_end == 12 for atom in atoms)
    assert all(atom.container_header == "Storage" for atom in atoms)
