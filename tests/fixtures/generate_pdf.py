import fitz

def create_sample_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    
    # Title
    page.insert_text((50, 50), "PDF Pancakes", fontsize=24)
    
    # Description
    page.insert_text((50, 80), "Delicious pancakes from a PDF.", fontsize=12)
    
    # Ingredients Header
    page.insert_text((50, 110), "Ingredients", fontsize=14)
    
    # Ingredients List
    page.insert_text((50, 130), "- 1 cup flour", fontsize=12)
    page.insert_text((50, 150), "- 1 egg", fontsize=12)
    
    # Instructions Header
    page.insert_text((50, 180), "Instructions", fontsize=14)
    
    # Instructions List
    page.insert_text((50, 200), "1. Mix it all.", fontsize=12)
    page.insert_text((50, 220), "2. Cook it.", fontsize=12)
    
    doc.save(path)
    doc.close()

if __name__ == "__main__":
    create_sample_pdf("tests/fixtures/sample.pdf")
