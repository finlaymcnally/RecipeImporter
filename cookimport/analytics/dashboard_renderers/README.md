# Dashboard Renderers

`dashboard_render.py` is now a thin public facade over this package. `assets.py` owns the top-level artifact write, `all_method_pages.py` owns all-method page generation, `formatting.py` holds the shared dashboard shaping helpers, `html_shell.py` and `style_asset.py` own the static shell, and the JavaScript owner map is now `script_bootstrap.py`, `script_filters.py`, `script_compare_control.py`, and `script_tables.py` behind the tiny `script_asset.py` seam.
