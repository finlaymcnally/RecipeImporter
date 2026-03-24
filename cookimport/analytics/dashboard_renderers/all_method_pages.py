from __future__ import annotations

from cookimport.analytics.dashboard_renderers.templates import _HTML, _CSS, _JS
from cookimport.analytics.dashboard_renderers import formatting as _formatting

globals().update(
    {
        name: getattr(_formatting, name)
        for name in dir(_formatting)
        if not name.startswith("__")
    }
)


def _collect_all_method_groups(data: DashboardData) -> list[_AllMethodGroup]:
    # First pass: collect per-group canonical records from benchmark_records (executed eval reports).
    group_meta: dict[str, tuple[str, str | None, str]] = {}
    best_by_group_config: dict[str, dict[str, BenchmarkRecord]] = {}

    for record in data.benchmark_records:
        key_info = _all_method_group_key(record)
        if key_info is None:
            continue
        group_dir_raw, run_root_dir_raw, run_dir_timestamp, source_slug = key_info
        try:
            group_dir = str(Path(group_dir_raw).expanduser().resolve(strict=False))
        except OSError:
            group_dir = group_dir_raw
        try:
            run_root_dir = str(Path(run_root_dir_raw).expanduser().resolve(strict=False))
        except OSError:
            run_root_dir = run_root_dir_raw

        group_meta[group_dir] = (run_root_dir, run_dir_timestamp, source_slug)
        configs = best_by_group_config.setdefault(group_dir, {})

        config_dir_name = None
        _, parts = _normalize_path_parts(record.artifact_dir)
        lower_parts = [part.lower() for part in parts]
        for idx, part in enumerate(lower_parts):
            if part == _ALL_METHOD_BENCHMARK_SEGMENT:
                if idx + 2 >= len(parts):
                    continue
                candidate = parts[idx + 2]
                if candidate.startswith(_ALL_METHOD_CONFIG_PREFIX):
                    config_dir_name = candidate
                    break
            elif part == _SINGLE_PROFILE_BENCHMARK_SEGMENT:
                config_hash = str(record.run_config_hash or "").strip().lower()
                config_dir_name = (
                    f"profile_{config_hash}"
                    if config_hash
                    else "single_profile"
                )
                break
        if config_dir_name is None:
            config_dir_name = _config_name(record)

        prior = configs.get(config_dir_name)
        if prior is None or _run_timestamp_sort_key(record.run_timestamp) > _run_timestamp_sort_key(prior.run_timestamp):
            configs[config_dir_name] = record

    # Second pass: prefer all_method_benchmark_report.json when present (it includes reused variants).
    groups_by_dir: dict[str, _AllMethodGroup] = {}
    allowed_run_roots: set[str] = set()
    for run_root_dir, _, _ in group_meta.values():
        try:
            allowed_run_roots.add(str(Path(run_root_dir).expanduser().resolve(strict=False)))
        except OSError:
            allowed_run_roots.add(run_root_dir)
    golden_root = Path(str(data.golden_root or "")).expanduser()
    try:
        golden_root = golden_root.resolve(strict=False)
    except OSError:
        pass

    report_paths: list[Path] = []
    try:
        if golden_root.is_dir():
            report_paths = list(golden_root.rglob(_ALL_METHOD_REPORT_JSON))
    except OSError:
        report_paths = []

    for report_path in report_paths:
        info = _all_method_group_info_from_path(report_path.parent)
        if info is None:
            continue
        group_dir, run_root_dir, run_dir_timestamp, source_slug = info
        if allowed_run_roots:
            try:
                run_root_dir_key = str(Path(run_root_dir).expanduser().resolve(strict=False))
            except OSError:
                run_root_dir_key = run_root_dir
            if run_root_dir_key not in allowed_run_roots:
                continue

        report = _load_all_method_report(Path(group_dir))
        if report is None:
            continue
        created_at = str(report.get("created_at") or "").strip() or None
        variants = report.get("variants") or []
        if not isinstance(variants, list) or not variants:
            continue

        executed = best_by_group_config.get(group_dir, {})
        manifest_cache: dict[str, tuple[str | None, str | None, int | None, dict[str, Any] | None]] = {}

        synthetic: list[BenchmarkRecord] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            config_dir_name = str(variant.get("config_dir") or "").strip()
            if not config_dir_name:
                continue

            config_dir_path = Path(group_dir) / config_dir_name
            rep_name = str(variant.get("evaluation_representative_config_dir") or config_dir_name).strip()
            base = executed.get(rep_name)

            manifest_key = str(config_dir_path)
            fields = manifest_cache.get(manifest_key)
            if fields is None:
                fields = _load_manifest_fields(config_dir_path)
                manifest_cache[manifest_key] = fields
            importer_name, source_file, recipe_count, run_config = fields

            def _f(key: str) -> float | None:
                value = variant.get(key)
                try:
                    return float(value) if value is not None else None
                except (TypeError, ValueError):
                    return None

            run_config_hash = str(variant.get("run_config_hash") or "").strip() or None
            run_config_summary = str(variant.get("run_config_summary") or "").strip() or None

            eval_report_json = str(variant.get("eval_report_json") or "").strip()
            report_path_abs = None
            if eval_report_json:
                report_path_abs = str((Path(group_dir) / eval_report_json).expanduser().resolve(strict=False))

            synthetic.append(
                BenchmarkRecord(
                    run_timestamp=created_at,
                    artifact_dir=str(config_dir_path.expanduser().resolve(strict=False)),
                    report_path=report_path_abs,
                    strict_accuracy=_f("strict_accuracy"),
                    macro_f1_excluding_other=_f("macro_f1_excluding_other"),
                    precision=_f("precision"),
                    recall=_f("recall"),
                    f1=_f("f1"),
                    practical_precision=_f("practical_precision"),
                    practical_recall=_f("practical_recall"),
                    practical_f1=_f("practical_f1"),
                    gold_total=base.gold_total if base else None,
                    gold_recipe_headers=base.gold_recipe_headers if base else None,
                    pred_total=base.pred_total if base else None,
                    gold_matched=base.gold_matched if base else None,
                    recipes=recipe_count,
                    supported_precision=base.supported_precision if base else None,
                    supported_recall=base.supported_recall if base else None,
                    supported_practical_precision=base.supported_practical_precision if base else None,
                    supported_practical_recall=base.supported_practical_recall if base else None,
                    supported_practical_f1=base.supported_practical_f1 if base else None,
                    granularity_mismatch_likely=base.granularity_mismatch_likely if base else None,
                    pred_width_p50=base.pred_width_p50 if base else None,
                    gold_width_p50=base.gold_width_p50 if base else None,
                    per_label=list(base.per_label) if base else [],
                    boundary_correct=base.boundary_correct if base else None,
                    boundary_over=base.boundary_over if base else None,
                    boundary_under=base.boundary_under if base else None,
                    boundary_partial=base.boundary_partial if base else None,
                    task_count=base.task_count if base else None,
                    source_file=source_file or (str(report.get("source_file") or "").strip() or None),
                    importer_name=importer_name or (base.importer_name if base else None),
                    run_config=run_config or (base.run_config if base else None),
                    run_config_hash=run_config_hash or (base.run_config_hash if base else None),
                    run_config_summary=run_config_summary or (base.run_config_summary if base else None),
                    processed_report_path=base.processed_report_path if base else None,
                )
            )

        if not synthetic:
            continue

        records = sorted(synthetic, key=_config_name)
        records = sorted(
            records,
            key=lambda row: (
                _metric(row.f1),
                _metric(row.practical_f1),
                _metric(row.precision),
                _metric(row.recall),
            ),
            reverse=True,
        )

        groups_by_dir[group_dir] = _AllMethodGroup(
            group_dir=group_dir,
            run_root_dir=run_root_dir,
            run_dir_timestamp=run_dir_timestamp,
            source_slug=source_slug,
            records=records,
        )

    # Final pass: add any all-method groups that were present only via benchmark_records (older runs).
    for group_dir, (run_root_dir, run_dir_timestamp, source_slug) in group_meta.items():
        if group_dir in groups_by_dir:
            continue
        records = list((best_by_group_config.get(group_dir) or {}).values())
        if not records:
            continue
        records = sorted(records, key=_config_name)
        records = sorted(
            records,
            key=lambda row: (
                _metric(row.f1),
                _metric(row.practical_f1),
                _metric(row.precision),
                _metric(row.recall),
            ),
            reverse=True,
        )
        groups_by_dir[group_dir] = _AllMethodGroup(
            group_dir=group_dir,
            run_root_dir=run_root_dir,
            run_dir_timestamp=run_dir_timestamp,
            source_slug=source_slug,
            records=records,
        )

    groups = list(groups_by_dir.values())
    groups.sort(key=lambda group: _run_timestamp_sort_key(group.run_dir_timestamp), reverse=True)
    return groups


def _best_record(records: list[BenchmarkRecord]) -> BenchmarkRecord | None:
    if not records:
        return None
    return max(
        records,
        key=lambda row: (
            _metric(row.f1),
            _metric(row.practical_f1),
            _metric(row.precision),
            _metric(row.recall),
        ),
    )


def _group_source_label(group: _AllMethodGroup) -> str:
    names = sorted(
        {
            _source_label(record)
            for record in group.records
            if _source_label(record) != "-"
        }
    )
    if not names:
        return group.source_slug
    if len(names) == 1:
        return names[0]
    return f"{names[0]} (+{len(names) - 1} more)"


def _group_page_name(group: _AllMethodGroup) -> str:
    return (
        f"{_ALL_METHOD_BENCHMARK_SEGMENT}__"
        f"{_slug_token(group.run_dir_timestamp)}__"
        f"{_slug_token(group.source_slug)}.html"
    )


def _run_page_name(run: _AllMethodRun) -> str:
    return (
        f"{_ALL_METHOD_RUN_PAGE_PREFIX}"
        f"{_slug_token(run.run_dir_timestamp)}.html"
    )


def _aggregate_config_key(record: BenchmarkRecord) -> str:
    config_hash = str(record.run_config_hash or "").strip().lower()
    if config_hash:
        return f"hash:{config_hash}"
    return f"name:{_config_name(record)}"


def _aggregate_run_configs(
    groups: list[_AllMethodGroup],
) -> list[_AllMethodConfigAggregate]:
    state: dict[str, dict[str, Any]] = {}

    for group in groups:
        group_gold_total = _group_gold_recipe_headers(group)
        winner = _best_record(group.records)
        winner_key = _aggregate_config_key(winner) if winner is not None else None
        for record in group.records:
            config_key = _aggregate_config_key(record)
            entry = state.get(config_key)
            if entry is None:
                config_hash = str(record.run_config_hash or "").strip() or None
                summary = _run_config_summary(record)
                if summary and config_hash:
                    run_config_text = f"{summary} [{config_hash[:10]}]"
                elif config_hash:
                    run_config_text = f"[{config_hash[:10]}]"
                else:
                    run_config_text = summary or "-"
                extractor_dim, parser_dim, skiphf_dim, preprocess_dim = _all_method_dims(
                    record
                )
                entry = {
                    "config_names": set(),
                    "book_keys": set(),
                    "wins": 0,
                    "extractor": extractor_dim,
                    "parser": parser_dim,
                    "skiphf": skiphf_dim,
                    "preprocess": preprocess_dim,
                    "importer_name": str(record.importer_name or "-"),
                    "run_config_text": run_config_text,
                    "run_config_hash": config_hash,
                    "strict_precision_values": [],
                    "strict_recall_values": [],
                    "strict_f1_values": [],
                    "practical_f1_values": [],
                    "recipes_values": [],
                    "recipe_identified_pct_values": [],
                }
                state[config_key] = entry

            entry["config_names"].add(_config_name(record))
            entry["book_keys"].add(group.group_dir)
            if record.precision is not None:
                entry["strict_precision_values"].append(float(record.precision))
            if record.recall is not None:
                entry["strict_recall_values"].append(float(record.recall))
            if record.f1 is not None:
                entry["strict_f1_values"].append(float(record.f1))
            if record.practical_f1 is not None:
                entry["practical_f1_values"].append(float(record.practical_f1))
            if record.recipes is not None:
                entry["recipes_values"].append(float(record.recipes))
            recipe_identified_ratio = _recipes_identified_ratio(
                record,
                group_gold_recipe_headers=group_gold_total,
            )
            if recipe_identified_ratio is not None:
                entry["recipe_identified_pct_values"].append(recipe_identified_ratio)

        if winner_key is not None and winner_key in state:
            state[winner_key]["wins"] += 1

    aggregates: list[_AllMethodConfigAggregate] = []
    for config_key, entry in state.items():
        config_names = sorted(str(name) for name in entry["config_names"] if str(name))
        config_name = config_names[0] if config_names else "<unknown>"
        aggregates.append(
            _AllMethodConfigAggregate(
                config_key=config_key,
                config_name=config_name,
                extractor=entry["extractor"],
                parser=entry["parser"],
                skiphf=entry["skiphf"],
                preprocess=entry["preprocess"],
                importer_name=entry["importer_name"],
                run_config_text=entry["run_config_text"],
                run_config_hash=entry["run_config_hash"],
                books=len(entry["book_keys"]),
                wins=int(entry["wins"]),
                strict_precision_mean=_mean(entry["strict_precision_values"]),
                strict_recall_mean=_mean(entry["strict_recall_values"]),
                strict_f1_mean=_mean(entry["strict_f1_values"]),
                practical_f1_mean=_mean(entry["practical_f1_values"]),
                recipes_mean=_mean(entry["recipes_values"]),
                recipe_identified_pct_mean=_mean(
                    entry["recipe_identified_pct_values"]
                ),
            )
        )

    aggregates = sorted(aggregates, key=lambda row: row.config_name.lower())
    aggregates = sorted(
        aggregates,
        key=lambda row: (
            row.books,
            _metric(row.practical_f1_mean),
            _metric(row.strict_f1_mean),
            row.wins,
            _metric(row.strict_precision_mean),
            _metric(row.strict_recall_mean),
        ),
        reverse=True,
    )
    return aggregates


def _collect_all_method_runs(groups: list[_AllMethodGroup]) -> list[_AllMethodRun]:
    runs_by_key: dict[str, _AllMethodRun] = {}
    for group in groups:
        run_key = group.run_root_dir or group.group_dir
        run = runs_by_key.get(run_key)
        if run is None:
            run = _AllMethodRun(
                run_key=run_key,
                run_dir_timestamp=group.run_dir_timestamp,
            )
            runs_by_key[run_key] = run
        run.groups.append(group)
        if _run_timestamp_sort_key(group.run_dir_timestamp) > _run_timestamp_sort_key(
            run.run_dir_timestamp
        ):
            run.run_dir_timestamp = group.run_dir_timestamp

    runs: list[_AllMethodRun] = []
    for run in runs_by_key.values():
        run.groups = sorted(
            run.groups,
            key=lambda group: _group_source_label(group).lower(),
        )
        run.config_aggregates = _aggregate_run_configs(run.groups)
        runs.append(run)

    runs.sort(
        key=lambda run: _run_timestamp_sort_key(run.run_dir_timestamp),
        reverse=True,
    )
    return runs


def _run_best_config(run: _AllMethodRun) -> _AllMethodConfigAggregate | None:
    if not run.config_aggregates:
        return None
    return run.config_aggregates[0]


def _render_all_method_run_html(run: _AllMethodRun) -> str:
    best = _run_best_config(run)
    winner_line = "-"
    if best is not None:
        winner_line = (
            f"{best.config_name} "
            f"(books={best.books}, wins={best.wins}, "
            f"mean_strict_f1={_fmt_float(best.strict_f1_mean)}, "
            f"mean_practical_f1={_fmt_float(best.practical_f1_mean)})"
        )

    aggregate_rows: list[str] = []
    for rank, aggregate in enumerate(run.config_aggregates, start=1):
        aggregate_rows.append(
            (
                "<tr>"
                f"<td class=\"num\">{rank}</td>"
                f"<td>{escape(aggregate.config_name)}</td>"
                f"<td>{escape(aggregate.extractor)}</td>"
                f"<td>{escape(aggregate.parser)}</td>"
                f"<td>{escape(aggregate.skiphf)}</td>"
                f"<td>{escape(aggregate.preprocess)}</td>"
                f"<td class=\"num\">{aggregate.books}</td>"
                f"<td class=\"num\">{aggregate.wins}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_precision_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_recall_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.strict_f1_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.practical_f1_mean)}</td>"
                f"<td class=\"num\">{_fmt_float(aggregate.recipes_mean, digits=1)}</td>"
                f"<td>{escape(aggregate.importer_name or '-')}</td>"
                f"<td title=\"{escape(aggregate.run_config_text)}\">{escape(aggregate.run_config_text)}</td>"
                "</tr>"
            )
        )

    book_rows: list[str] = []
    book_averages: list[_AllMethodBookAggregate] = []
    for group in run.groups:
        source_label = _group_source_label(group)
        best_group = _best_record(group.records)
        group_gold_headers = _group_gold_recipe_headers(group)
        recipe_identified_values = [
            ratio
            for ratio in (
                _recipes_identified_ratio(
                    record,
                    group_gold_recipe_headers=group_gold_headers,
                )
                for record in group.records
            )
            if ratio is not None
        ]
        book_averages.append(
            _AllMethodBookAggregate(
                source_label=source_label,
                config_count=len(group.records),
                mean_strict_precision=_mean(
                    [
                        float(record.precision)
                        for record in group.records
                        if record.precision is not None
                    ]
                ),
                mean_strict_recall=_mean(
                    [
                        float(record.recall)
                        for record in group.records
                        if record.recall is not None
                    ]
                ),
                mean_strict_f1=_mean(
                    [
                        float(record.f1)
                        for record in group.records
                        if record.f1 is not None
                    ]
                ),
                mean_practical_f1=_mean(
                    [
                        float(record.practical_f1)
                        for record in group.records
                        if record.practical_f1 is not None
                    ]
                ),
                mean_recipe_identified_pct=_mean(
                    [float(value) for value in recipe_identified_values]
                ),
            )
        )
        book_rows.append(
            (
                "<tr>"
                f"<td>{escape(source_label)}</td>"
                f"<td class=\"num\">{len(group.records)}</td>"
                f"<td>{escape(_config_name(best_group) if best_group else '-')}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.f1 if best_group else None)}</td>"
                f"<td class=\"num\">{_fmt_float(best_group.practical_f1 if best_group else None)}</td>"
                f"<td><a href=\"{escape(group.detail_page_name)}\">Open book details</a></td>"
                "</tr>"
            )
        )

    summary_specs: list[tuple[str, int, list[float]]] = [
        (
            "Mean Strict Precision",
            4,
            [
                float(aggregate.strict_precision_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_precision_mean is not None
            ],
        ),
        (
            "Mean Strict Recall",
            4,
            [
                float(aggregate.strict_recall_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_recall_mean is not None
            ],
        ),
        (
            "Mean Strict F1",
            4,
            [
                float(aggregate.strict_f1_mean)
                for aggregate in run.config_aggregates
                if aggregate.strict_f1_mean is not None
            ],
        ),
        (
            "Mean Practical F1",
            4,
            [
                float(aggregate.practical_f1_mean)
                for aggregate in run.config_aggregates
                if aggregate.practical_f1_mean is not None
            ],
        ),
        (
            "Recipes Identified %",
            1,
            [
                float(aggregate.recipe_identified_pct_mean)
                for aggregate in run.config_aggregates
                if aggregate.recipe_identified_pct_mean is not None
            ],
        ),
    ]
    summary_rows: list[str] = []
    for label, digits, values in summary_specs:
        summary_rows.append(
            (
                "<tr>"
                f"<td>{escape(label)}</td>"
                f"<td class=\"num\">{len(values)}</td>"
                f"<td class=\"num\">{_fmt_float(min(values) if values else None, digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_median(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_mean(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(max(values) if values else None, digits=digits)}</td>"
                "</tr>"
            )
        )

    chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Mean Strict Precision",
            4,
            [aggregate.strict_precision_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Strict Recall",
            4,
            [aggregate.strict_recall_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Strict F1",
            4,
            [aggregate.strict_f1_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Mean Practical F1",
            4,
            [aggregate.practical_f1_mean for aggregate in run.config_aggregates],
            1.0,
        ),
        (
            "Recipes Identified %",
            1,
            [aggregate.recipe_identified_pct_mean for aggregate in run.config_aggregates],
            1.0,
        ),
    ]
    chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for config_index, value in enumerate(raw_values, start=1):
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\">Config {config_index:02d}</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    def _book_leader_text(metric_label: str, values: list[tuple[str, float | None]]) -> str:
        best_label = "-"
        best_value: float | None = None
        for label, value in values:
            if value is None:
                continue
            if best_value is None or value > best_value:
                best_label = label
                best_value = float(value)
        if best_value is None:
            return f"{metric_label}: -"
        return f"{metric_label}: {best_label} ({best_value * 100.0:.1f}%)"

    book_highlights = [
        _book_leader_text(
            "Highest avg strict precision",
            [
                (book.source_label, book.mean_strict_precision)
                for book in book_averages
            ],
        ),
        _book_leader_text(
            "Highest avg strict recall",
            [
                (book.source_label, book.mean_strict_recall)
                for book in book_averages
            ],
        ),
        _book_leader_text(
            "Highest avg strict F1",
            [(book.source_label, book.mean_strict_f1) for book in book_averages],
        ),
    ]
    book_highlight_html = "".join(
        f"<p class=\"section-note\">{escape(line)}</p>"
        for line in book_highlights
    )

    book_chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Avg Strict Precision",
            4,
            [
                book.mean_strict_precision
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Strict Recall",
            4,
            [
                book.mean_strict_recall
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Strict F1",
            4,
            [
                book.mean_strict_f1
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Practical F1",
            4,
            [
                book.mean_practical_f1
                for book in book_averages
            ],
            1.0,
        ),
        (
            "Avg Recipes Identified %",
            1,
            [book.mean_recipe_identified_pct for book in book_averages],
            1.0,
        ),
    ]
    book_chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in book_chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for book_index, value in enumerate(raw_values, start=1):
            source_label = book_averages[book_index - 1].source_label
            config_count = book_averages[book_index - 1].config_count
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\" title=\"{escape(source_label)}\">Book {book_index:02d} (n={config_count})</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        book_chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    book_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Avg Strict Precision", 4, 1.0),
        ("Strict R", "Avg Strict Recall", 4, 1.0),
        ("Strict F1", "Avg Strict F1", 4, 1.0),
        ("Prac F1", "Avg Practical F1", 4, 1.0),
        ("Recipes", "Avg Recipes Identified %", 1, 1.0),
    ]
    book_radar_items = [
        _MetricRadarItem(
            label=f"Book {book_index:02d}",
            title=f"{book.source_label} (configs={book.config_count})",
            values=[
                book.mean_strict_precision,
                book.mean_strict_recall,
                book.mean_strict_f1,
                book.mean_practical_f1,
                book.mean_recipe_identified_pct,
            ],
        )
        for book_index, book in enumerate(book_averages, start=1)
    ]
    book_radar_cards = _render_metric_radar_cards(
        items=book_radar_items,
        metric_specs=book_radar_metric_specs,
        aria_prefix="Cookbook",
    )

    run_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Mean Strict Precision", 4, 1.0),
        ("Strict R", "Mean Strict Recall", 4, 1.0),
        ("Strict F1", "Mean Strict F1", 4, 1.0),
        ("Prac F1", "Mean Practical F1", 4, 1.0),
        ("Recipes", "Recipes Identified %", 1, 1.0),
    ]
    run_radar_items = [
        _MetricRadarItem(
            label=f"Config {config_index:02d}",
            title=aggregate.config_name,
            values=[
                aggregate.strict_precision_mean,
                aggregate.strict_recall_mean,
                aggregate.strict_f1_mean,
                aggregate.practical_f1_mean,
                aggregate.recipe_identified_pct_mean,
            ],
        )
        for config_index, aggregate in enumerate(run.config_aggregates, start=1)
    ]
    run_radar_cards = _render_metric_radar_cards(
        items=run_radar_items,
        metric_specs=run_radar_metric_specs,
        aria_prefix="Run config",
    )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>cookimport – All Method Benchmark Run {escape(run.run_dir_timestamp or '')}</title>"
        "<link rel=\"stylesheet\" href=\"../assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Run Summary</h1>"
        f"<p><a href=\"../index.html\">Dashboard home</a> · <a href=\"{_PREVIOUS_RUNS_SECTION_HREF}\">Previous runs</a></p>"
        "</header>"
        "<main>"
        "<nav class=\"all-method-quick-nav\" aria-label=\"Run page sections\">"
        "<a href=\"#run-summary\">Summary</a>"
        "<a href=\"#run-charts\">Charts</a>"
        "<a href=\"#run-config-table\">Ranked Table</a>"
        "<a href=\"#run-drilldown\">Drilldown</a>"
        "</nav>"
        "<section id=\"run-overview\">"
        f"<p><strong>Run folder:</strong> {escape(run.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Book jobs:</strong> {len(run.groups)}</p>"
        f"<p><strong>Configs aggregated:</strong> {len(run.config_aggregates)}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section id=\"run-summary\">"
        "<h2>Run Summary</h2>"
        "<p class=\"section-note\">Compact stats across aggregated config rows: count, min, median, mean, max.</p>"
        "<table class=\"summary-compact\"><thead><tr>"
        "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>"
        "</tr></thead><tbody>"
        f"{''.join(summary_rows)}"
        "</tbody></table>"
        "</section>"
        "<details id=\"run-charts\" class=\"section-details\" open>"
        "<summary>Charts</summary>"
        "<section id=\"run-chart-bars\">"
        "<h2>Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per aggregated configuration for each metric category. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book.</p>"
        f"{''.join(chart_blocks)}"
        "</section>"
        "<section id=\"run-chart-radar\">"
        "<h2>Metric Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one aggregated configuration. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for each book.</p>"
        f"{run_radar_cards}"
        "</section>"
        "<section id=\"run-book-chart-bars\">"
        "<h2>Per-Cookbook Average Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per cookbook. Values are averaged across all configs that ran for that cookbook. Labels use Book 01/Book 02 order from Per-Book Drilldown. All axes use fixed 0-100%; recipes is percent identified vs each cookbook's golden recipe headers.</p>"
        f"{book_highlight_html}"
        f"{''.join(book_chart_blocks)}"
        "</section>"
        "<section id=\"run-book-chart-radar\">"
        "<h2>Per-Cookbook Average Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one cookbook with metrics averaged across all configs that ran for that cookbook. All axes use fixed 0-100%; recipes is percent identified vs each cookbook's golden recipe headers.</p>"
        f"{book_radar_cards}"
        "</section>"
        "</details>"
        "<details id=\"run-config-table\" class=\"section-details\" open>"
        "<summary>Ranked Config Table</summary>"
        "<section>"
        "<h2>Config Performance Across Books</h2>"
        "<p class=\"section-note\">Aggregated by configuration across all per-book jobs in this run.</p>"
        "<table><thead><tr>"
        "<th>Rank</th>"
        "<th title=\"Configuration directory/name.\">Configuration</th>"
        "<th title=\"High-level dimension (extraction path).\"><span>Extractor</span></th>"
        "<th title=\"High-level dimension (parser choice).\"><span>Parser</span></th>"
        "<th title=\"Whether header/footer skipping was enabled.\">Skip HF</th>"
        "<th title=\"Whether preprocessing was enabled.\">Preprocess</th>"
        "<th title=\"How many books this configuration ran on.\">Books</th>"
        "<th title=\"How many books this configuration 'won' (best score within that book).\"><span>Wins</span></th>"
        "<th title=\"Average strict precision across books for this configuration.\">Mean Strict Precision</th>"
        "<th title=\"Average strict recall across books for this configuration.\">Mean Strict Recall</th>"
        "<th title=\"Average Strict F1 across books. Strict scoring is boundary-sensitive.\">Mean Strict F1</th>"
        "<th title=\"Average Practical F1 across books. Practical scoring is forgiving (any overlap counts).\"><span>Mean Practical F1</span></th>"
        "<th title=\"Average predicted recipe count (not a score).\"><span>Mean Recipes</span></th>"
        "<th title=\"Importer used to generate predictions.\">Importer</th>"
        "<th title=\"Key run settings summary (hover rows for full text).\"><span>Run Config</span></th>"
        "</tr></thead><tbody>"
        f"{''.join(aggregate_rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "<details id=\"run-drilldown\" class=\"section-details\" open>"
        "<summary>Per-Book Drilldown</summary>"
        "<section>"
        "<h2>Per-Book Drilldown</h2>"
        "<p class=\"section-note\">Open each source row for the existing per-book config breakdown page.</p>"
        "<table><thead><tr>"
        "<th title=\"Which book/source file this row refers to.\">Source</th>"
        "<th title=\"How many configurations were evaluated for this book.\">Configs</th>"
        "<th title=\"Best configuration for this book.\">Winner</th>"
        "<th title=\"Strict F1 for the best configuration (boundary-sensitive).\"><span>Strict F1</span></th>"
        "<th title=\"Practical F1 for the best configuration (forgiving; any overlap counts).\"><span>Practical F1</span></th>"
        "<th>Details</th>"
        "</tr></thead><tbody>"
        f"{''.join(book_rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_detail_html(
    group: _AllMethodGroup,
    *,
    run_detail_page_name: str | None = None,
) -> str:
    best = _best_record(group.records)
    source_label = _group_source_label(group)
    rows: list[str] = []
    for rank, record in enumerate(group.records, start=1):
        extractor_dim, parser_dim, skiphf_dim, preprocess_dim = _all_method_dims(record)
        config_hash = str(record.run_config_hash or "")
        summary = _run_config_summary(record)
        if summary and config_hash:
            summary = f"{summary} [{config_hash[:10]}]"
        elif config_hash:
            summary = f"[{config_hash[:10]}]"
        artifact_href = str(record.artifact_dir or "").strip()
        artifact_cell = "-"
        if artifact_href:
            artifact_cell = (
                f"<a href=\"{escape(artifact_href)}\">"
                f"{escape(_config_name(record))}</a>"
            )
        rows.append(
            (
                "<tr>"
                f"<td class=\"num\">{rank}</td>"
                f"<td>{escape(_config_name(record))}</td>"
                f"<td>{escape(extractor_dim)}</td>"
                f"<td>{escape(parser_dim)}</td>"
                f"<td>{escape(skiphf_dim)}</td>"
                f"<td>{escape(preprocess_dim)}</td>"
                f"<td class=\"num\">{_fmt_float(record.precision)}</td>"
                f"<td class=\"num\">{_fmt_float(record.recall)}</td>"
                f"<td class=\"num\">{_fmt_float(record.f1)}</td>"
                f"<td class=\"num\">{_fmt_float(record.practical_f1)}</td>"
                f"<td class=\"num\">{_fmt_int(record.recipes)}</td>"
                f"<td>{escape(record.importer_name or '-')}</td>"
                f"<td>{escape(_source_label(record))}</td>"
                f"<td title=\"{escape(summary)}\">{escape(summary or '-')}</td>"
                f"<td>{artifact_cell}</td>"
                "</tr>"
            )
        )

    winner_line = "-"
    if best is not None:
        winner_line = (
            f"{_config_name(best)} "
            f"(strict_f1={_fmt_float(best.f1)}, practical_f1={_fmt_float(best.practical_f1)})"
        )
    group_gold_total = _group_gold_recipe_headers(group)
    recipes_identified_values = [
        _recipes_identified_ratio(
            record,
            group_gold_recipe_headers=group_gold_total,
        )
        for record in group.records
    ]

    summary_specs: list[tuple[str, int, list[float]]] = [
        (
            "Strict Precision",
            4,
            [float(record.precision) for record in group.records if record.precision is not None],
        ),
        (
            "Strict Recall",
            4,
            [float(record.recall) for record in group.records if record.recall is not None],
        ),
        (
            "Strict F1",
            4,
            [float(record.f1) for record in group.records if record.f1 is not None],
        ),
        (
            "Practical F1",
            4,
            [float(record.practical_f1) for record in group.records if record.practical_f1 is not None],
        ),
        (
            "Recipes Identified %",
            1,
            [
                float(value)
                for value in recipes_identified_values
                if value is not None
            ],
        ),
    ]
    summary_rows = []
    for label, digits, values in summary_specs:
        summary_rows.append(
            (
                "<tr>"
                f"<td>{escape(label)}</td>"
                f"<td class=\"num\">{len(values)}</td>"
                f"<td class=\"num\">{_fmt_float(min(values) if values else None, digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_median(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(_mean(values), digits=digits)}</td>"
                f"<td class=\"num\">{_fmt_float(max(values) if values else None, digits=digits)}</td>"
                "</tr>"
            )
        )

    chart_specs: list[tuple[str, int, list[float | None], float | None]] = [
        (
            "Strict Precision",
            4,
            [record.precision for record in group.records],
            1.0,
        ),
        (
            "Strict Recall",
            4,
            [record.recall for record in group.records],
            1.0,
        ),
        (
            "Strict F1",
            4,
            [record.f1 for record in group.records],
            1.0,
        ),
        (
            "Practical F1",
            4,
            [record.practical_f1 for record in group.records],
            1.0,
        ),
        (
            "Recipes Identified %",
            1,
            recipes_identified_values,
            1.0,
        ),
    ]
    chart_blocks: list[str] = []
    for label, digits, raw_values, fixed_max in chart_specs:
        present_values = [value for value in raw_values if value is not None]
        if fixed_max is not None and fixed_max > 0:
            max_value = float(fixed_max)
        else:
            max_value = max(present_values) if present_values else 0.0
        bar_rows: list[str] = []
        for run_index, value in enumerate(raw_values, start=1):
            width_pct = 0.0
            if value is not None and max_value > 0:
                width_pct = max(0.0, min(100.0, float(value) / float(max_value) * 100.0))
            bar_fill_class = "metric-bar-fill" if value is not None else "metric-bar-fill metric-bar-fill-missing"
            if value is None:
                value_text = "-"
            elif fixed_max == 1.0:
                value_text = f"{float(value) * 100.0:.1f}%"
            else:
                value_text = _fmt_float(float(value), digits=digits)
            bar_rows.append(
                (
                    "<div class=\"metric-bar-row\">"
                    f"<span class=\"metric-bar-label\">Run {run_index:02d}</span>"
                    "<span class=\"metric-bar-track\">"
                    f"<span class=\"{bar_fill_class}\" style=\"width:{width_pct:.2f}%\"></span>"
                    "</span>"
                    f"<span class=\"metric-bar-value\">{escape(value_text)}</span>"
                    "</div>"
                )
            )
        chart_blocks.append(
            (
                "<section class=\"metric-chart-block\">"
                f"<h3>{escape(label)}</h3>"
                f"<div class=\"metric-chart-grid\">{''.join(bar_rows)}</div>"
                "</section>"
            )
        )

    detail_radar_metric_specs: list[tuple[str, str, int, float | None]] = [
        ("Strict P", "Strict Precision", 4, 1.0),
        ("Strict R", "Strict Recall", 4, 1.0),
        ("Strict F1", "Strict F1", 4, 1.0),
        ("Prac F1", "Practical F1", 4, 1.0),
        ("Recipes", "Recipes Identified %", 1, 1.0),
    ]
    detail_radar_items = [
        _MetricRadarItem(
            label=f"Run {run_index:02d}",
            title=_config_name(record),
            values=[
                record.precision,
                record.recall,
                record.f1,
                record.practical_f1,
                recipes_identified_values[run_index - 1],
            ],
        )
        for run_index, record in enumerate(group.records, start=1)
    ]
    detail_radar_cards = _render_metric_radar_cards(
        items=detail_radar_items,
        metric_specs=detail_radar_metric_specs,
        aria_prefix="Config",
    )

    nav_links = ["<a href=\"../index.html\">Dashboard home</a>"]
    nav_links.append(
        f"<a href=\"{_PREVIOUS_RUNS_SECTION_HREF}\">Previous runs</a>"
    )
    if run_detail_page_name:
        nav_links.append(
            f"<a href=\"{escape(run_detail_page_name)}\">Run summary</a>"
        )

    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>cookimport – All Method Benchmark {escape(group.run_dir_timestamp or '')}</title>"
        "<link rel=\"stylesheet\" href=\"../assets/style.css\">"
        "</head>"
        "<body>"
        "<header>"
        "<h1>All Method Benchmark Details</h1>"
        f"<p>{' · '.join(nav_links)}</p>"
        "</header>"
        "<main>"
        "<nav class=\"all-method-quick-nav\" aria-label=\"Detail page sections\">"
        "<a href=\"#detail-summary\">Summary</a>"
        "<a href=\"#detail-charts\">Charts</a>"
        "<a href=\"#detail-ranked-table\">Ranked Table</a>"
        "</nav>"
        "<section id=\"detail-overview\">"
        f"<p><strong>Run folder:</strong> {escape(group.run_dir_timestamp or '-')}</p>"
        f"<p><strong>Source:</strong> {escape(source_label)}</p>"
        f"<p><strong>Total configs:</strong> {len(group.records)}</p>"
        f"<p><strong>Golden recipes:</strong> {escape(_fmt_int(group_gold_total))}</p>"
        f"<p><strong>Winner:</strong> {escape(winner_line)}</p>"
        "</section>"
        "<section id=\"detail-summary\">"
        "<h2>Run Summary</h2>"
        "<p class=\"section-note\">Compact stats only (no per-config labels): count, min, median, mean, max.</p>"
        "<table class=\"summary-compact\"><thead><tr>"
        "<th>Stat</th><th>N</th><th>Min</th><th>Median</th><th>Mean</th><th>Max</th>"
        "</tr></thead><tbody>"
        f"{''.join(summary_rows)}"
        "</tbody></table>"
        "</section>"
        "<details id=\"detail-charts\" class=\"section-details\" open>"
        "<summary>Charts</summary>"
        "<section id=\"detail-chart-bars\">"
        "<h2>Metric Bar Charts</h2>"
        "<p class=\"section-note\">One bar per run/configuration for each metric category. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source.</p>"
        f"{''.join(chart_blocks)}"
        "</section>"
        "<section id=\"detail-chart-radar\">"
        "<h2>Metric Web Charts (Radar)</h2>"
        "<p class=\"section-note\">Each web is one run/configuration. All axes use fixed 0-100%; recipes is percent identified vs golden recipe headers for this source.</p>"
        f"{detail_radar_cards}"
        "</section>"
        "</details>"
        "<details id=\"detail-ranked-table\" class=\"section-details\" open>"
        "<summary>Ranked Config Table</summary>"
        "<section>"
        "<h2>Ranked Configurations</h2>"
        "<table><thead><tr>"
        "<th>Rank</th>"
        "<th title=\"Configuration directory/name.\">Configuration</th>"
        "<th title=\"High-level dimension (extraction path).\"><span>Extractor</span></th>"
        "<th title=\"High-level dimension (parser choice).\"><span>Parser</span></th>"
        "<th title=\"Whether header/footer skipping was enabled.\">Skip HF</th>"
        "<th title=\"Whether preprocessing was enabled.\">Preprocess</th>"
        "<th title=\"Strict precision for this config.\"><span>Strict Precision</span></th>"
        "<th title=\"Strict recall for this config.\"><span>Strict Recall</span></th>"
        "<th title=\"Strict F1 for this config (boundary-sensitive).\"><span>Strict F1</span></th>"
        "<th title=\"Practical F1 for this config (forgiving; any overlap counts).\"><span>Practical F1</span></th>"
        "<th title=\"Predicted recipe count (not a score).\"><span>Recipes</span></th>"
        "<th title=\"Importer used to generate predictions.\">Importer</th>"
        "<th title=\"Which book/source file this config was evaluated on.\">Source</th>"
        "<th title=\"Key run settings summary (hover rows for full text).\"><span>Run Config</span></th>"
        "<th>Artifact</th>"
        "</tr></thead><tbody>"
        f"{''.join(rows)}"
        "</tbody></table>"
        "</section>"
        "</details>"
        "</main>"
        "<footer>Generated by <code>cookimport stats-dashboard</code></footer>"
        "</body>"
        "</html>"
    )


def _render_all_method_pages(out_dir: Path, data: DashboardData) -> None:
    groups = _collect_all_method_groups(data)
    runs = _collect_all_method_runs(groups)
    all_method_dir = out_dir / _ALL_METHOD_OUTPUT_SUBDIR
    all_method_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / f"{_ALL_METHOD_BENCHMARK_SEGMENT}.html").unlink(missing_ok=True)
    for stale_detail_page in out_dir.glob(f"{_ALL_METHOD_BENCHMARK_SEGMENT}__*.html"):
        stale_detail_page.unlink(missing_ok=True)
    for stale_run_page in out_dir.glob(f"{_ALL_METHOD_RUN_PAGE_PREFIX}*.html"):
        stale_run_page.unlink(missing_ok=True)
    for stale_subdir_page in all_method_dir.glob("*.html"):
        stale_subdir_page.unlink(missing_ok=True)

    used_page_names: set[str] = set()
    for group in groups:
        base_name = _group_page_name(group)
        page_name = base_name
        suffix = 2
        while page_name in used_page_names:
            page_name = f"{base_name[:-5]}_{suffix}.html"
            suffix += 1
        used_page_names.add(page_name)
        group.detail_page_name = page_name

    for run in runs:
        base_name = _run_page_name(run)
        page_name = base_name
        suffix = 2
        while page_name in used_page_names:
            page_name = f"{base_name[:-5]}_{suffix}.html"
            suffix += 1
        used_page_names.add(page_name)
        run.detail_page_name = page_name

    run_page_by_key = {
        run.run_key: run.detail_page_name
        for run in runs
    }

    for group in groups:
        detail_path = all_method_dir / group.detail_page_name
        detail_path.write_text(
            _render_all_method_detail_html(
                group,
                run_detail_page_name=run_page_by_key.get(group.run_root_dir),
            ),
            encoding="utf-8",
        )

    for run in runs:
        run_path = all_method_dir / run.detail_page_name
        run_path.write_text(
            _render_all_method_run_html(run),
            encoding="utf-8",
        )

    return None
