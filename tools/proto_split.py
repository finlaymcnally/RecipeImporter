import re

def split_text(text):
    # simple split by double newline
    parts = re.split(r'\n\s*\n', text)
    return [p.strip() for p in parts if p.strip()]

text = "Tip: Don't overmix.\n\nOtherwise it gets tough."
print(split_text(text))

text_list = """Here are some tips:
* Use cold butter.
* Don't overmix.
* Bake at 350.
"""

def split_text_advanced(text):
    # Split by double newline first
    blocks = re.split(r'\n\s*\n', text)
    atoms = []
    
    list_item_pattern = re.compile(r'^\s*[-*\u2022]+\s+(.+)$', re.MULTILINE)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
            
        # Check for list items
        list_items = list(list_item_pattern.finditer(block))
        if list_items:
            # If we have list items, we might need to handle introductory text
            last_end = 0
            for match in list_items:
                start, end = match.span()
                # Text before the list item (if any, and not just whitespace)
                pre_text = block[last_end:start].strip()
                if pre_text:
                    atoms.append(pre_text)
                
                # The list item itself
                atoms.append(match.group(0).strip())
                last_end = end
            
            # Text after the last list item
            post_text = block[last_end:].strip()
            if post_text:
                atoms.append(post_text)
        else:
            atoms.append(block)
            
    return atoms

print("\n--- List Test ---")
print(split_text_advanced(text_list))
