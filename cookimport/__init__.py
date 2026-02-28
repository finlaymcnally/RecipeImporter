"""Core package for the cookimport CLI and import pipeline."""

from cookimport.core.joblib_runtime import (
    configure_joblib_runtime_for_restricted_hosts,
)

configure_joblib_runtime_for_restricted_hosts()

__version__ = "0.1.0"
