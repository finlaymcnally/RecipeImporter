from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact, RecipeCandidate
from cookimport.labelstudio.chunking import build_extracted_archive, chunk_atomic, chunk_structural


def _make_result() -> ConversionResult:
    recipe = RecipeCandidate(
        name="Toast",
        recipeIngredient=["1 slice bread"],
        recipeInstructions=["Toast the bread."],
    )
    recipe.provenance = {"location": {"chunk_index": 0}}
    report = ConversionReport()
    return ConversionResult(
        recipes=[recipe],
        tips=[],
        tipCandidates=[],
        topicCandidates=[],
        rawArtifacts=[],
        report=report,
        workbook="toast",
        workbookPath="toast.txt",
    )


def test_chunk_ids_stable() -> None:
    result = _make_result()
    raw_artifacts = [
        RawArtifact(
            importer="text",
            sourceHash="hash",
            locationId="full_text",
            extension="json",
            content={
                "lines": [
                    {"index": 0, "text": "Intro"},
                    {"index": 1, "text": "More text"},
                ],
                "text": "Intro\nMore text",
            },
            metadata={"artifact_type": "extracted_text"},
        )
    ]
    result.raw_artifacts = raw_artifacts
    archive = build_extracted_archive(result, raw_artifacts)
    assert len(archive) == 2

    chunks_a = chunk_structural(
        result,
        archive,
        source_file="toast.txt",
        book_id="toast",
        pipeline_used="text",
        file_hash="deadbeef",
    )
    chunks_b = chunk_structural(
        result,
        archive,
        source_file="toast.txt",
        book_id="toast",
        pipeline_used="text",
        file_hash="deadbeef",
    )
    assert [chunk.chunk_id for chunk in chunks_a] == [chunk.chunk_id for chunk in chunks_b]

    atomic_a = chunk_atomic(
        result,
        archive,
        source_file="toast.txt",
        book_id="toast",
        pipeline_used="text",
        file_hash="deadbeef",
    )
    atomic_b = chunk_atomic(
        result,
        archive,
        source_file="toast.txt",
        book_id="toast",
        pipeline_used="text",
        file_hash="deadbeef",
    )
    assert [chunk.chunk_id for chunk in atomic_a] == [chunk.chunk_id for chunk in atomic_b]
    assert any(chunk.chunk_type == "ingredient_line" for chunk in atomic_a)
    assert any(chunk.chunk_type == "step_line" for chunk in atomic_a)
