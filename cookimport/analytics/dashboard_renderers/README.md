# Dashboard Renderers

`dashboard_render.py` is now a thin public facade over this package. `assets.py` owns the top-level artifact write, `all_method_pages.py` owns all-method page generation, `formatting.py` holds the shared dashboard shaping helpers, `html_shell.py` and `style_asset.py` own the static shell, and `script_asset.py` is the tiny JavaScript assembly seam.

`script_bootstrap.py` and `script_compare_control.py` still own Python-side JS fragments directly. `script_filters.py` and `script_tables.py` are now thin loaders over the checked-in source-of-truth files in `assets/script_filters.js` and `assets/script_tables.js`.
