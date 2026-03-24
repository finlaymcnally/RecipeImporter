# Import Session Flows

`import_session.py` keeps the public session seam, but `output_stage.py` now owns the active implementation, `authority.py` owns label-first artifact helpers, and the recipe/nonrecipe modules mark the stage-runtime ownership split.
