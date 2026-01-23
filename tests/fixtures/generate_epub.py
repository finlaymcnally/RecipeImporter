from ebooklib import epub

def create_sample_epub(path):
    book = epub.EpubBook()

    # set metadata
    book.set_identifier('id123456')
    book.set_title('Sample Cookbook')
    book.set_language('en')

    book.add_author('Author Name')

    # create chapter
    c1 = epub.EpubHtml(title='Intro', file_name='intro.xhtml', lang='en')
    c1.content = '<h1>Introduction</h1><p>Welcome to the cookbook.</p>'

    c2 = epub.EpubHtml(title='Recipes', file_name='recipes.xhtml', lang='en')
    c2.content = '''
    <h1>Best Pancakes</h1>
    <p>These are great.</p>
    <h2>Ingredients</h2>
    <ul>
        <li>1 cup flour</li>
        <li>1 cup milk</li>
    </ul>
    <h2>Instructions</h2>
    <ol>
        <li>Mix contents.</li>
        <li>Cook on pan.</li>
    </ol>
    
    <h1>Simple Salad</h1>
    <h2>Ingredients</h2>
    <p>Lettuce</p>
    <p>Tomato</p>
    <h2>Directions</h2>
    <p>Toss together.</p>
    '''

    book.add_item(c1)
    book.add_item(c2)

    # define Table Of Contents
    book.toc = (epub.Link('intro.xhtml', 'Introduction', 'intro'),
                (epub.Section('Recipes'),
                 (c2, ))
                )

    # add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # define CSS style
    style = 'BODY {color: white;}'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    # basic spine
    book.spine = ['nav', c1, c2]

    # write to the file
    epub.write_epub(path, book, {})

if __name__ == '__main__':
    create_sample_epub('tests/fixtures/sample.epub')
