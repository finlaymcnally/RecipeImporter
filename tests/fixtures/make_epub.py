from __future__ import annotations

from pathlib import Path
import zipfile


def make_test_epub(path: Path, *, title: str = "Debug Cookbook") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zip_handle:
        zip_handle.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zip_handle.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zip_handle.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:test-book</dc:identifier>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
</package>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zip_handle.writestr(
            "OEBPS/nav.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Navigation</title></head>
  <body>
    <nav epub:type="toc" id="toc">
      <ol>
        <li><a href="chapter1.xhtml">Chapter 1</a></li>
        <li><a href="chapter2.xhtml">Chapter 2</a></li>
      </ol>
    </nav>
  </body>
</html>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zip_handle.writestr(
            "OEBPS/chapter1.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Pancakes</title></head>
  <body>
    <h1>Best Pancakes</h1>
    <h2>Ingredients</h2>
    <p>1 cup flour</p>
    <p>1 cup milk</p>
    <h2>Instructions</h2>
    <p>Whisk ingredients together.</p>
    <p>Cook on medium heat.</p>
    <p>Serves 2</p>
  </body>
</html>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zip_handle.writestr(
            "OEBPS/chapter2.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Notes</title></head>
  <body>
    <h1>Kitchen Notes</h1>
    <p>Keep dry ingredients in airtight containers.</p>
    <p>Label spice jars with purchase dates.</p>
  </body>
</html>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return path
