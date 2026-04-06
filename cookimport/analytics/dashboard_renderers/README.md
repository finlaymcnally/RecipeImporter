# Dashboard Renderers

`dashboard_render.py` now owns the top-level artifact write directly. This package only keeps the real asset owners: `html_shell.py`, `style_asset.py`, `script_bootstrap.py`, `script_compare_control.py`, and the checked-in JS files under `assets/`.

The dashboard is single-surface now: all-method sweeps stay inside `index.html` as a compact summary section instead of generating standalone sweep pages.

`dashboard_render.py` concatenates the Python-side JS fragments with the checked-in source-of-truth files in `assets/script_filters.js` and `assets/script_tables.js`.
