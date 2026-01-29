from __future__ import annotations

import json
import gzip
import zipfile
from pathlib import Path
from cookimport.plugins.paprika import PaprikaImporter

EXAMPLES_DIR = Path(__file__).parent.parent / "docs" / "template" / "examples"

def test_merge_paprika(tmp_path):
    importer = PaprikaImporter()
    
    # Create a mock .paprikarecipes file
    zip_path = tmp_path / "test.paprikarecipes"
    recipe_data = {
        "name": "Merged Recipe",
        "ingredients": "Zip Ingredient 1\nZip Ingredient 2",
        "directions": "Zip Direction 1",
        "notes": "Zip Notes",
        "uid": "123"
    }
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("recipe.json", gzip.compress(json.dumps(recipe_data).encode("utf-8")))
    
    # Create a mock HTML export
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
                    </script>    </body>
    </html>
    """
    (tmp_path / "recipe.html").write_text(html_content)
    
    # Convert the directory
    result = importer.convert(tmp_path, None)
    
    assert len(result.recipes) == 1
    recipe = result.recipes[0]
    assert recipe.name == "Merged Recipe"
    # Should prefer HTML ingredients because they are "more" (3 vs 2)
    assert len(recipe.ingredients) == 3
    assert "HTML Ingredient 1" in recipe.ingredients
    # Should have prepTime from HTML
    assert recipe.prep_time == "PT10M"
    # Should have notes from Zip (not in HTML)
    assert recipe.description == "Zip Notes"
