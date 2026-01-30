"""Generate a scanned (image-only) PDF fixture for OCR testing."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def generate_scanned_pdf():
    """Create a simple scanned PDF with recipe text rendered as an image."""
    output_path = Path(__file__).parent / "scanned_recipe.pdf"

    # Create image with recipe text
    width, height = 612, 792  # Letter size at 72 DPI
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Use default font (PIL has a built-in default)
    try:
        # Try to get a monospace font
        font = ImageFont.load_default(size=16)
        title_font = ImageFont.load_default(size=24)
    except Exception:
        font = ImageFont.load_default()
        title_font = font

    # Recipe content
    recipe_text = """
    Scanned Banana Bread

    Ingredients:
    3 ripe bananas
    1/3 cup melted butter
    3/4 cup sugar
    1 egg
    1 teaspoon vanilla
    1 teaspoon baking soda
    Pinch of salt
    1 1/2 cups flour

    Instructions:
    Preheat oven to 350 degrees F.
    Mash the bananas in a mixing bowl.
    Mix in the melted butter.
    Add sugar, egg, and vanilla.
    Stir in baking soda and salt.
    Add flour and mix until smooth.
    Pour into a greased loaf pan.
    Bake for 60 to 65 minutes.
    """

    # Draw title
    y_pos = 50
    draw.text((72, y_pos), "Scanned Banana Bread", fill="black", font=title_font)
    y_pos += 50

    # Draw content
    for line in recipe_text.strip().split("\n"):
        line = line.strip()
        if line and line != "Scanned Banana Bread":
            draw.text((72, y_pos), line, fill="black", font=font)
            y_pos += 25

    # Save as PDF
    img.save(str(output_path), "PDF", resolution=100.0)
    print(f"Generated scanned PDF: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_scanned_pdf()
