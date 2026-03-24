# Import Session Flows

`import_session.py` is now only the public compatibility seam. `import_session_contracts.py` keeps
the shared public result dataclass/types, while `output_stage.py` owns the active implementation and
`authority.py` owns the label-first artifact helpers.
