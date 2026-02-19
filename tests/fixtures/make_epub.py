from __future__ import annotations

from pathlib import Path
import zipfile


def make_synthetic_epub(
    path: Path,
    *,
    title: str = "Synthetic Cookbook",
    spine_documents: list[tuple[str, str]],
    nav_document: str | None = None,
    include_nav_in_spine: bool = False,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    opf_manifest: list[str] = []
    opf_spine: list[str] = []
    payload: dict[str, str] = {}

    if nav_document is not None:
        nav_filename = "nav.xhtml"
        opf_manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
        if include_nav_in_spine:
            opf_spine.append('<itemref idref="nav"/>')
        payload[nav_filename] = _ensure_xhtml_document(
            nav_document,
            title="Navigation",
        )

    for index, (filename, content) in enumerate(spine_documents):
        item_id = f"ch{index + 1}"
        opf_manifest.append(
            f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>'
        )
        opf_spine.append(f'<itemref idref="{item_id}"/>')
        payload[filename] = _ensure_xhtml_document(content, title=f"Chapter {index + 1}")

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
    {' '.join(opf_manifest)}
  </manifest>
  <spine>
    {' '.join(opf_spine)}
  </spine>
</package>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for filename, content in payload.items():
            zip_handle.writestr(
                f"OEBPS/{filename}",
                content,
                compress_type=zipfile.ZIP_DEFLATED,
            )

    return path


def make_test_epub(path: Path, *, title: str = "Debug Cookbook") -> Path:
    nav = """
<nav epub:type="toc" id="toc">
  <ol>
    <li><a href="chapter1.xhtml">Chapter 1</a></li>
    <li><a href="chapter2.xhtml">Chapter 2</a></li>
  </ol>
</nav>
"""
    chapter1 = """
<h1>Best Pancakes</h1>
<h2>Ingredients</h2>
<p>1 cup flour</p>
<p>1 cup milk</p>
<h2>Instructions</h2>
<p>Whisk ingredients together.</p>
<p>Cook on medium heat.</p>
<p>Serves 2</p>
"""
    chapter2 = """
<h1>Kitchen Notes</h1>
<p>Keep dry ingredients in airtight containers.</p>
<p>Label spice jars with purchase dates.</p>
"""
    return make_synthetic_epub(
        path,
        title=title,
        nav_document=nav,
        include_nav_in_spine=False,
        spine_documents=[
            ("chapter1.xhtml", chapter1),
            ("chapter2.xhtml", chapter2),
        ],
    )


def _ensure_xhtml_document(content: str, *, title: str) -> str:
    body = content.strip()
    if "<html" in body.lower():
        return body
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>{title}</title></head>
  <body>
    {body}
  </body>
</html>
"""
