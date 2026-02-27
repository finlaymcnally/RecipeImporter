from __future__ import annotations

import os
from dataclasses import dataclass
from difflib import Match
from typing import Any

_DMP_CHECKLINES_ENV = "COOKIMPORT_DMP_CHECKLINES"
_DMP_CLEANUP_ENV = "COOKIMPORT_DMP_CLEANUP"
_DMP_TIMELIMIT_ENV = "COOKIMPORT_DMP_TIMELIMIT"

_DEFAULT_CHECKLINES = True
_DEFAULT_CLEANUP = "No"
_DEFAULT_TIMELIMIT = 0.0
_CLEANUP_MAP = {
    "no": "No",
    "semantic": "Semantic",
    "efficiency": "Efficiency",
}


def _coerce_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0.0:
        return default
    return parsed


@dataclass(frozen=True)
class DmpRuntimeOptions:
    cleanup: str
    checklines: bool
    timelimit: float


def resolve_dmp_runtime_options() -> DmpRuntimeOptions:
    cleanup_raw = str(os.getenv(_DMP_CLEANUP_ENV, _DEFAULT_CLEANUP) or _DEFAULT_CLEANUP)
    cleanup = _CLEANUP_MAP.get(cleanup_raw.strip().lower(), _DEFAULT_CLEANUP)
    return DmpRuntimeOptions(
        cleanup=cleanup,
        checklines=_coerce_bool(
            os.getenv(_DMP_CHECKLINES_ENV),
            default=_DEFAULT_CHECKLINES,
        ),
        timelimit=_coerce_float(
            os.getenv(_DMP_TIMELIMIT_ENV),
            default=_DEFAULT_TIMELIMIT,
        ),
    )


class DmpSequenceMatcher:
    def __init__(
        self,
        isjunk: Any = None,
        a: str = "",
        b: str = "",
        autojunk: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        # isjunk/autojunk are accepted for drop-in constructor compatibility.
        self.isjunk = isjunk
        self.autojunk = bool(autojunk)
        self._options = resolve_dmp_runtime_options()
        self.a = ""
        self.b = ""
        self._ops: list[tuple[str, int]] | None = None
        self._matching_blocks: list[Match] | None = None
        self._opcodes: list[tuple[str, int, int, int, int]] | None = None
        self.set_seqs(str(a or ""), str(b or ""))

    def set_seqs(self, a: str, b: str) -> None:
        self.a = str(a or "")
        self.b = str(b or "")
        self._ops = None
        self._matching_blocks = None
        self._opcodes = None

    def set_seq1(self, a: str) -> None:
        self.set_seqs(a, self.b)

    def set_seq2(self, b: str) -> None:
        self.set_seqs(self.a, b)

    def _ops_from_dmp(self) -> list[tuple[str, int]]:
        if self._ops is not None:
            return self._ops
        from fast_diff_match_patch import diff as dmp_diff

        raw_ops = dmp_diff(
            self.a,
            self.b,
            cleanup=self._options.cleanup,
            checklines=self._options.checklines,
            timelimit=self._options.timelimit,
            counts_only=True,
        )
        ops: list[tuple[str, int]] = []
        for raw_op, raw_count in raw_ops:
            op = str(raw_op)
            count = int(raw_count)
            if count <= 0:
                continue
            if op not in {"=", "-", "+"}:
                raise RuntimeError(f"Unsupported diff op from fast-diff-match-patch: {op!r}")
            ops.append((op, count))
        self._ops = ops
        return ops

    def get_matching_blocks(self) -> list[Match]:
        if self._matching_blocks is not None:
            return self._matching_blocks

        i = 0
        j = 0
        blocks: list[Match] = []
        for op, count in self._ops_from_dmp():
            if op == "=":
                blocks.append(Match(i, j, count))
                i += count
                j += count
                continue
            if op == "-":
                i += count
                continue
            if op == "+":
                j += count
                continue
        blocks.append(Match(len(self.a), len(self.b), 0))
        self._matching_blocks = blocks
        return blocks

    def get_opcodes(self) -> list[tuple[str, int, int, int, int]]:
        if self._opcodes is not None:
            return self._opcodes

        i = 0
        j = 0
        pending_del = 0
        pending_ins = 0
        pending_i = 0
        pending_j = 0
        opcodes: list[tuple[str, int, int, int, int]] = []

        def flush_pending() -> None:
            nonlocal pending_del, pending_ins
            if pending_del <= 0 and pending_ins <= 0:
                return
            if pending_del > 0 and pending_ins > 0:
                opcodes.append(
                    ("replace", pending_i, pending_i + pending_del, pending_j, pending_j + pending_ins)
                )
            elif pending_del > 0:
                opcodes.append(
                    ("delete", pending_i, pending_i + pending_del, pending_j, pending_j)
                )
            else:
                opcodes.append(
                    ("insert", pending_i, pending_i, pending_j, pending_j + pending_ins)
                )
            pending_del = 0
            pending_ins = 0

        for op, count in self._ops_from_dmp():
            if op == "=":
                flush_pending()
                opcodes.append(("equal", i, i + count, j, j + count))
                i += count
                j += count
                continue
            if pending_del <= 0 and pending_ins <= 0:
                pending_i = i
                pending_j = j
            if op == "-":
                pending_del += count
                i += count
                continue
            if op == "+":
                pending_ins += count
                j += count
                continue

        flush_pending()
        self._opcodes = opcodes
        return opcodes

    def ratio(self) -> float:
        denom = len(self.a) + len(self.b)
        if denom <= 0:
            return 1.0
        matched = sum(int(block.size) for block in self.get_matching_blocks()[:-1])
        return (2.0 * matched) / float(denom)

    def quick_ratio(self) -> float:
        return self.ratio()

    def real_quick_ratio(self) -> float:
        return self.ratio()
