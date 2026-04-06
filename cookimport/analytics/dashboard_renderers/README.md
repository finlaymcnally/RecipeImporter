# Dashboard Renderers

`dashboard_render.py` is now a thin public facade over this package. `assets.py` owns the top-level artifact write, `html_shell.py` and `style_asset.py` own the static shell, and `script_asset.py` assembles the shared JavaScript bundle.

The dashboard is single-surface now: all-method sweeps stay inside `index.html` as a compact summary section instead of generating standalone sweep pages.

`script_bootstrap.py` and `script_compare_control.py` still own Python-side JS fragments directly. `script_filters.py` and `script_tables.py` are thin loaders over the checked-in source-of-truth files in `assets/script_filters.js` and `assets/script_tables.js`.
