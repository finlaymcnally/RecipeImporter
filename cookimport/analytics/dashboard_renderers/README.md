# Dashboard Renderers

`dashboard_render.py` is now a thin public facade over this package. `assets.py` owns the top-level artifact write, `all_method_pages.py` owns all-method page generation, `formatting.py` holds the shared dashboard shaping helpers, and the static page shell now lives in `html_shell.py`, `style_asset.py`, and `script_asset.py` instead of one giant `templates.py`.
