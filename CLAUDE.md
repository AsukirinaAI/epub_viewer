# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is a small Flask web EPUB reader. The backend in `app.py` serves the HTML UI, uploads/stores `.epub` files under `books/`, parses EPUB container/OPF/TOC metadata, serves EPUB-internal files through Flask routes, and persists reader state in JSON files. The frontend is a jQuery single-page reader in `templates/index.html`, `static/js/main.js`, and `static/css/style.css`.

## Common commands

- Run the reader locally: `python app.py`
  - Starts Flask in debug mode on port 5000 via `app.run(debug=True, port=5000)`.
- Run the EPUB-to-Markdown smoke script: `python test.py`
  - This is an ad hoc MarkItDown conversion script, not an automated test suite.
- There is currently no dependency manifest, build step, lint command, pytest/unittest configuration, or configured single-test command.
  - `app.py` imports `flask` and `bs4`; XML parsing with BeautifulSoup uses the `xml` parser.
  - `test.py` imports `markitdown`.

## Architecture notes

- `app.py` is both the Flask app factory location and route implementation. There is no package split or blueprint structure.
- Persistent local data lives at repository root:
  - `history.json` stores last-read state keyed by EPUB filename, including scroll position, spine index, and timestamp.
  - `reader_settings.json` stores UI settings such as theme, Japanese text visibility, and font size.
- EPUB uploads are saved directly into `books/`; the app only accepts filenames ending in `.epub` at upload time.
- `parse_epub_structure()` reads `META-INF/container.xml`, resolves the OPF rootfile, builds the spine from `<spine><itemref>`, and builds the TOC from either EPUB 3 nav documents (`properties="nav"`) or NCX files (`application/x-dtbncx+xml`). Returned spine and TOC paths are normalized to forward-slash paths inside the EPUB archive.
- `/api/book/<filename>/file/<path:filepath>` proxies files from inside the ZIP archive. For XHTML/HTML files it rewrites image and stylesheet URLs so nested EPUB assets load through the same Flask endpoint.
- The frontend loads settings and history on document ready, uploads local EPUB files with `FormData`, opens books through `/api/book/<filename>`, renders TOC entries mapped back to spine indices, and lazy-loads subsequent spine items as the scroll container approaches the bottom.
- Reading progress is scroll-based, not page-based. `#content-container` owns scrolling; `#reader-content` accumulates `.chapter-container` elements as chapters are loaded.
- Bilingual/Japanese visibility is controlled in CSS via the `--jp-display` custom property and selectors such as `.calibre3, .jp-text`; EPUB-specific class names may affect whether this works for a given book.
- The sidebar is fixed-position and hidden/shown by toggling the `open` class; the left-edge trigger and toggle button behavior live in `static/js/main.js`.

## Important current caveats

- `saveHistoryMap()` in `static/js/main.js` is incomplete and currently points at `/api/settings`; uploaded books rely on later progress updates to persist history correctly.
- `history.json` and `reader_settings.json` are tracked-style project files in the working directory, but they are runtime state. Be careful before overwriting them.
- There are no Cursor rules, Copilot instructions, README, or existing CLAUDE.md in this repository at the time this file was created.
