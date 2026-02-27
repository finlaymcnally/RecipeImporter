from __future__ import annotations

import collections as coll
import itertools as itl
import os
import sys
from bisect import bisect_left as _bisect_left
from difflib import Match
from typing import Any

# Adapted from dg-pb reference implementation:
# https://gist.github.com/dg-pb/4e08bc770a3b52d3ec77af3e38fdbb20
# (linked from https://discuss.python.org/t/improvement-on-current-difflib-sequencematcher-algorithm/106221)

_PRINT_DHIST = False
_EMPTY_LIST: list[int] = []

_MULTILAYER_MEMULT_ENV = "COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER_MULTILAYER_MEMULT"
_DEFAULT_MULTILAYER_MEMULT = 1.0


def _adjust_indices(length: int, start: int, stop: int | None) -> tuple[int, int]:
    if start < 0:
        raise ValueError("Starting index can not be negative")
    if stop is None or stop > length:
        stop = length
    return start, stop


def _resolve_memult() -> float:
    raw_value = os.getenv(_MULTILAYER_MEMULT_ENV)
    if raw_value is None:
        return _DEFAULT_MULTILAYER_MEMULT
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return _DEFAULT_MULTILAYER_MEMULT
    if parsed <= 0:
        return _DEFAULT_MULTILAYER_MEMULT
    return parsed


def resolve_multilayer_runtime_options() -> dict[str, float]:
    return {"memult": float(_resolve_memult())}


class _P2Slicer:
    def __init__(self, pos2: dict[Any, list[int]], len2: int, start2: int, stop2: int):
        self.pos2 = pos2
        self.len2 = len2
        self.start2 = start2
        self.stop2 = stop2
        self.start2slc = start2 != 0
        self.stop2slc = stop2 < len2
        self.do_bisect = self.start2slc or self.stop2slc
        self.cache: dict[Any, tuple[int, int | None] | None] = {}

    def __getitem__(self, elt: Any) -> list[int]:
        p2 = self.pos2.get(elt, _EMPTY_LIST)
        if not p2 or not self.do_bisect:
            return p2
        cache = self.cache
        if elt in cache:
            slc = cache[elt]
        else:
            left = 0
            need_slice = False
            if self.start2slc and p2[0] < (start2 := self.start2):
                left = _bisect_left(p2, start2)
                need_slice = True
            right = None
            if self.stop2slc and p2[-1] >= (stop2 := self.stop2):
                right = _bisect_left(p2, stop2, left)
                need_slice = True
            slc = (left, right) if need_slice else None
            cache[elt] = slc

        if slc is None:
            return p2
        return p2[slc[0] : slc[1]]


class _LCSTRDictMultilayer:
    def __init__(self, seq2: Any, *, junk: frozenset[Any] | tuple[Any, ...] = (), autojunk: bool = False):
        if not isinstance(junk, frozenset):
            junk = frozenset(junk)
        self.seq2 = seq2
        self.len2 = len(seq2)
        self.junk = junk
        self.pos2: dict[Any, list[int]] | None = None
        self.autojunk = autojunk
        self.popular: frozenset[Any] | None = None

    def _get_pos2(self) -> dict[Any, list[int]]:
        pos2 = self.pos2
        if pos2 is not None:
            return pos2

        pos2 = {}
        for i, elt in enumerate(self.seq2):
            indices = pos2.setdefault(elt, [])
            indices.append(i)

        junk = self.junk
        if junk:
            for elt in junk:
                pos2.pop(elt, None)

        popular: set[Any] = set()
        n = self.len2
        if self.autojunk and n >= 200:
            ntest = n // 100 + 1
            for elt, idxs in pos2.items():
                if len(idxs) > ntest:
                    popular.add(elt)
            for elt in popular:
                del pos2[elt]

        self.pos2 = pos2
        self.popular = frozenset(popular)
        return pos2

    def _get_pos2_slicer(self, start2: int, stop2: int) -> _P2Slicer:
        return _P2Slicer(self._get_pos2(), self.len2, start2, stop2)

    def find_multilayer(
        self,
        seq1: Any,
        start1: int = 0,
        stop1: int | None = None,
        start2: int = 0,
        stop2: int | None = None,
        memult: float = 1,
    ) -> tuple[list[tuple[int, int, int]], Any]:
        len1 = len(seq1)
        len2 = self.len2
        if stop1 is None:
            stop1 = len1
        if stop2 is None:
            stop2 = len2
        if start1 >= stop1 or start2 >= stop2:
            return [], itl.repeat(0)

        p2slicer = self._get_pos2_slicer(start2, stop2)
        j2len: dict[int, int] = {}

        collected: dict[int, list[tuple[int, int]]] = {}
        min_ck = 1

        memleft = int((len1 + len2) * memult)
        if memleft < 100:
            memleft = 100
        has_gaps = False
        i = start1
        while i < stop1:
            p2 = p2slicer[seq1[i]]

            newj2len: dict[int, int] = {}
            j2lenpop = j2len.pop
            for j in p2:
                newj2len[j] = j2lenpop(j - 1, 0) + 1

            i_m1 = i - 1
            for j, k in j2len.items():
                if k >= min_ck:
                    collected.setdefault(k, []).append((i_m1, j))
                    memleft -= 1

            j2len = newj2len
            i += 1

            while memleft < 0:
                if len(collected) == 1:
                    break

                has_gaps = True
                min_k = min(collected)
                memleft += len(collected.pop(min_k))
                min_ck = min_k + 1
            else:
                continue

            break

        else:
            i_m1 = stop1 - 1
            for j, k in j2len.items():
                if k >= min_ck:
                    collected.setdefault(k, []).append((i_m1, j))

            results = self.layer_maximal_matches(collected, min_ck)
            gaps = itl.repeat(1 if has_gaps else 0)
            return results, gaps

        best_k = max(collected)
        it = iter(collected.pop(best_k))
        first = next(it)
        last_i_end, last_j_end = first
        results = [(last_i_end, last_j_end)]
        last_i_end += best_k
        last_j_end += best_k
        for i_cur, j_cur in it:
            if i_cur >= last_i_end and j_cur >= last_j_end:
                results.append((i_cur, j_cur))
                last_i_end = i_cur + best_k
                last_j_end = j_cur + best_k

        size2 = stop2 - start2
        k_cur = 0
        while i < stop1:
            if stop1 - i + k_cur < best_k:
                break

            p2 = p2slicer[seq1[i]]
            new_best = False
            i_cur = -1
            j_cur = -1
            k_cur = 0

            newj2len = {}
            j2lenpop = j2len.pop
            for j in p2:
                k = j2lenpop(j - 1, 0) + 1
                newj2len[j] = k
                if k > best_k:
                    best_k = k
                    i_cur = i
                    j_cur = j
                    new_best = True
                elif i_cur == -1 and k == best_k and i >= last_i_end and j >= last_j_end:
                    i_cur = i
                    j_cur = j

            if i_cur != -1:
                if new_best:
                    results.clear()
                results.append((i_cur, j_cur))
                last_i_end = i_cur + best_k
                last_j_end = j_cur + best_k

                if best_k == size2:
                    break

            j2len = newj2len
            i += 1

        if results:
            one_mk = 1 - best_k
            results = [(i + one_mk, j + one_mk, best_k) for i, j in results]

        gaps = itl.repeat(1)
        return results, gaps

    def layer_maximal_matches(
        self,
        maximals: dict[int, list[tuple[int, int]]],
        min_valid_k: int,
        assume_sorted: bool = True,
    ) -> list[tuple[int, int, int]]:
        results = [(sys.maxsize, sys.maxsize, 0)]
        needs_sort: set[int] = set()
        nr = 1
        while maximals:
            k = max(maximals)
            matches = maximals.pop(k)
            if not assume_sorted or k in needs_sort:
                matches.sort()
            buckets = [[] for _ in range(nr + 1)]
            ir = 0
            ig0 = -1
            jg0 = -1
            for i, j in matches:
                i2 = i + 1
                j2 = j + 1
                i = i2 - k
                j = j2 - k

                while 1:
                    ig1, jg1, kg1 = results[ir]
                    if i < ig1 + kg1 or j < jg1 + kg1:
                        break

                    ir += 1
                    ig0 = ig1 + kg1
                    jg0 = jg1 + kg1

                if ig0 <= i and jg0 <= j and i2 <= ig1 and j2 <= jg1:
                    buckets[ir].append((i, j, k))
                    ig0 = i2
                    jg0 = j2

                elif min_valid_k < k:
                    if i2 > ig1 + kg1 and j2 > jg1 + kg1:
                        delta = max(ig1 + kg1 - i, jg1 + kg1 - j, 0)
                        i += delta
                        j += delta
                        k_new = k - delta

                    elif i2 > ig0 and j2 > jg0 and i < ig1 and j < jg1:
                        delta_left = max(ig0 - i, jg0 - j, 0)
                        delta_right = max(i2 - ig1, j2 - jg1, 0)
                        i += delta_left
                        j += delta_left
                        k_new = k - delta_left - delta_right
                    else:
                        k_new = 0

                    if min_valid_k <= k_new:
                        one_mk = 1 - k_new
                        new = (i - one_mk, j - one_mk)
                        mxm = maximals.setdefault(k_new, [])
                        if assume_sorted and mxm and new < mxm[-1]:
                            needs_sort.add(k_new)
                        mxm.append(new)

            merged: list[tuple[int, int, int]] = []
            for bucket, result in zip(buckets, results):
                merged.extend(bucket)
                merged.append(result)
            merged.extend(buckets[-1])
            results = merged
            nr = len(results)

        results.pop()
        return results

    def _find_recursive_with_gaps(
        self,
        func: Any,
        seq1: Any,
        start1: int = 0,
        stop1: int | None = None,
        start2: int = 0,
        stop2: int | None = None,
        depth: int = 0,
        **kwds: Any,
    ) -> tuple[list[tuple[int, int, int]], list[int]]:
        if stop1 is None:
            stop1 = len(seq1)
        if stop2 is None:
            stop2 = self.len2
        if start1 >= stop1 or start2 >= stop2:
            return [], [depth]

        blocks, gaps = func(seq1, start1, stop1, start2, stop2, **kwds)

        if not blocks:
            return [], [depth + 1]

        result: list[tuple[int, int, int]] = []
        i0 = start1
        j0 = start2

        depths: list[int] = []
        gaps_it = iter(gaps)
        for (i, j, k), gap in zip(blocks, gaps_it):
            if gap:
                gap_matches, d = self._find_recursive_with_gaps(
                    func,
                    seq1,
                    i0,
                    i,
                    j0,
                    j,
                    depth + 1,
                    **kwds,
                )
                depths.extend(d)
                result.extend(gap_matches)

            result.append((i, j, k))

            i0 = i + k
            j0 = j + k

        if next(gaps_it):
            gap_matches, d = self._find_recursive_with_gaps(
                func,
                seq1,
                i0,
                stop1,
                j0,
                stop2,
                depth + 1,
                **kwds,
            )
            depths.extend(d)
            result.extend(gap_matches)

        if not depths:
            depths.append(depth + 1)
        return result, depths

    def get_matching_blocks(
        self,
        seq1: Any,
        start1: int = 0,
        stop1: int | None = None,
        start2: int = 0,
        stop2: int | None = None,
        **kwds: Any,
    ) -> list[tuple[int, int, int]]:
        start1, stop1 = _adjust_indices(len(seq1), start1, stop1)
        start2, stop2 = _adjust_indices(self.len2, start2, stop2)
        result, dhist = self._find_recursive_with_gaps(
            self.find_multilayer,
            seq1,
            start1,
            stop1,
            start2,
            stop2,
            **kwds,
        )
        if _PRINT_DHIST:
            print(sorted(coll.Counter(dhist).items()))
        return result


class MultiLayerSequenceMatcher:
    """Drop-in SequenceMatcher-like wrapper around _LCSTRDictMultilayer."""

    def __init__(
        self,
        isjunk: Any = None,
        a: Any = "",
        b: Any = "",
        autojunk: bool = True,
    ):
        self.isjunk = isjunk
        self.autojunk = autojunk
        self.a = a
        self.b = b
        self._memult = _resolve_memult()
        self._matcher: _LCSTRDictMultilayer | None = None
        self.matching_blocks: list[Match] | None = None
        self.opcodes: list[tuple[str, int, int, int, int]] | None = None
        self.set_seqs(a, b)

    def set_seq1(self, a: Any) -> None:
        self.a = a
        self.matching_blocks = None
        self.opcodes = None

    def set_seq2(self, b: Any) -> None:
        self.b = b
        junk = self._resolve_junk_elements(b)
        self._matcher = _LCSTRDictMultilayer(b, junk=junk, autojunk=self.autojunk)
        self.matching_blocks = None
        self.opcodes = None

    def set_seqs(self, a: Any, b: Any) -> None:
        self.set_seq2(b)
        self.set_seq1(a)

    def _resolve_junk_elements(self, seq: Any) -> frozenset[Any]:
        if self.isjunk is None:
            return frozenset()
        seen: set[Any] = set()
        junk: set[Any] = set()
        for elt in seq:
            if elt in seen:
                continue
            seen.add(elt)
            if bool(self.isjunk(elt)):
                junk.add(elt)
        return frozenset(junk)

    def get_matching_blocks(self) -> list[Match]:
        if self.matching_blocks is not None:
            return self.matching_blocks
        if self._matcher is None:
            self._matcher = _LCSTRDictMultilayer(
                self.b,
                junk=self._resolve_junk_elements(self.b),
                autojunk=self.autojunk,
            )
        blocks = self._matcher.get_matching_blocks(self.a, memult=self._memult)

        i1 = j1 = k1 = 0
        non_adjacent: list[Match] = []
        for i2, j2, k2 in blocks:
            if i1 + k1 == i2 and j1 + k1 == j2:
                k1 += k2
            else:
                if k1:
                    non_adjacent.append(Match(i1, j1, k1))
                i1, j1, k1 = i2, j2, k2

        if k1:
            non_adjacent.append(Match(i1, j1, k1))

        non_adjacent.append(Match(len(self.a), len(self.b), 0))
        self.matching_blocks = non_adjacent
        return self.matching_blocks

    def get_opcodes(self) -> list[tuple[str, int, int, int, int]]:
        if self.opcodes is not None:
            return self.opcodes

        i = 0
        j = 0
        answer: list[tuple[str, int, int, int, int]] = []
        for match in self.get_matching_blocks():
            ai = int(match.a)
            bj = int(match.b)
            size = int(match.size)

            tag = ""
            if i < ai and j < bj:
                tag = "replace"
            elif i < ai:
                tag = "delete"
            elif j < bj:
                tag = "insert"

            if tag:
                answer.append((tag, i, ai, j, bj))

            if size:
                answer.append(("equal", ai, ai + size, bj, bj + size))

            i = ai + size
            j = bj + size

        self.opcodes = answer
        return self.opcodes
