from __future__ import annotations

import gzip
import json
import zipfile

from cookimport.plugins.paprika import PaprikaImporter


def test_merge_paprika(tmp_path):
    importer = PaprikaImporter()

    zip_path = tmp_path / "test.paprikarecipes"
    recipe_data = {
        "name": "Merged Recipe",
        "ingredients": "Zip Ingredient 1\nZip Ingredient 2",
        "directions": "Zip Direction 1",
        "notes": "Zip Notes",
        "uid": "123",
    }
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("recipe.json", gzip.compress(json.dumps(recipe_data).encode("utf-8")))

    (tmp_path / "index.html").touch()
    (tmp_path / "images").mkdir()
    html_content = """
    <html>
    <body>
        <h1>Merged Recipe</h1>
        <div class="ingredients">
            <ul>
                <li>HTML Ingredient 1</li>
                <li>HTML Ingredient 2</li>
                <li>HTML Ingredient 3</li>
            </ul>
        </div>
        <div class="directions">
            <ul>
                <li>HTML Direction 1</li>
            </ul>
        </div>
        <script type="application/ld+json">
            {
                "@context": "http://schema.org",
                "@type": "Recipe",
                "name": "Merged Recipe",
                "prepTime": "PT10M",
                "recipeIngredient": ["HTML Ingredient 1", "HTML Ingredient 2", "HTML Ingredient 3"]
            }
        </script>
    </body>
    </html>
    """
    (tmp_path / "recipe.html").write_text(html_content)

    result = importer.convert(tmp_path, None)
    joined_text = "\n".join(block.text for block in result.source_blocks)

    assert result.recipes == []
    assert len(result.source_blocks) == 2
    assert "Merged Recipe" in joined_text
    assert "HTML Ingredient 1" in joined_text
    assert "Zip Notes" in joined_text
    assert "PT10M" in joined_text
