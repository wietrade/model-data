#!/usr/bin/env python3
"""Sync official model metadata and list prices into this repository.

Two artifacts, one tool:

* ``api/**/models.json`` / ``vendors.json`` - consumed by new-api's
  metadata sync (field-level preview + apply on the server side)
* ``api/newapi/pricing.json`` - list prices for review; new-api does
  not read it yet, prices are applied deliberately by an operator

Usage
-----
    python3 -m tools.model_sync.sync_models --dry-run
    python3 -m tools.model_sync.sync_models --check
    python3 -m tools.model_sync.sync_models --only metadata
    python3 -m tools.model_sync.sync_models --only pricing
    python3 -m tools.model_sync.sync_models --allow-new --min-release-date 2026-01-01

Exit codes: 0 = ok/no change, 1 = --check found pending changes, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in (None, ""):  # allow `python3 -m tools.model_sync.sync_models`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from model_sync import merge, sources  # type: ignore
    from model_sync.normalize import normalize_key  # type: ignore
else:
    from . import merge, sources
    from .normalize import normalize_key

DEFAULT_VENDORS = ("anthropic", "openai")
DEFAULT_SOURCES = ("models.dev", "openrouter")
I18N_LOCALES = ("zh", "en")


def repo_root_from_script():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_envelope(path):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        return payload, list(payload.get("data") or [])
    return {"success": True, "message": "ok"}, list(payload or [])


def dump_envelope(envelope, data):
    payload = dict(envelope)
    payload["success"] = True
    payload["message"] = payload.get("message") or "ok"
    payload["data"] = data
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == text:
                return False
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return True


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default if default is not None else {}


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        choices=("metadata", "pricing", "all"),
        default="all",
        help="which artifact to produce (default: all)",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="comma separated aggregator list, priority order (default: config or %s)"
        % ",".join(DEFAULT_SOURCES),
    )
    parser.add_argument(
        "--vendors",
        default=None,
        help="comma separated provider keys (default: config or %s)"
        % ",".join(DEFAULT_VENDORS),
    )
    parser.add_argument(
        "--official",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="also query vendor APIs when OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY exist",
    )
    parser.add_argument(
        "--allow-new",
        action="store_true",
        help="create models that are not in models.json yet",
    )
    parser.add_argument(
        "--allow-new-models",
        default="",
        help="with --allow-new: comma separated allowlist of model names to create",
    )
    parser.add_argument(
        "--min-release-date",
        default="",
        help="with --allow-new, ignore models released before this YYYY-MM-DD",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--root", default=repo_root_from_script(), help="repository root")
    parser.add_argument(
        "--config",
        default=None,
        help="sync config JSON (default: <root>/reference-data/metadata/sync.config.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the working tree would change (CI guard)",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the summary line")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    api_dir = os.path.join(root, "api")
    src_dir = os.path.join(root, "reference-data")
    models_path = os.path.join(api_dir, "newapi", "models.json")
    vendors_path = os.path.join(api_dir, "newapi", "vendors.json")
    pricing_path = os.path.join(api_dir, "newapi", "pricing.json")
    official_pricing_path = os.path.join(src_dir, "price", "pricing.official.json")

    if not os.path.exists(models_path):
        print("error: %s not found (wrong --root?)" % models_path, file=sys.stderr)
        return 2

    config_path = args.config or os.path.join(src_dir, "metadata", "sync.config.json")
    config = load_json(config_path, {})

    if args.vendors is None:
        args.vendors = ",".join(config.get("vendors") or DEFAULT_VENDORS)
    if args.sources is None:
        args.sources = ",".join(config.get("sources") or DEFAULT_SOURCES)
    if args.official is None:
        args.official = bool(config.get("official", False))
    if not args.allow_new and config.get("allow_new"):
        args.allow_new = True
    if not args.allow_new_models and config.get("allow_new_models"):
        args.allow_new_models = ",".join(config["allow_new_models"])

    vendors = [item.strip() for item in args.vendors.split(",") if item.strip()]
    source_names = [item.strip() for item in args.sources.split(",") if item.strip()]

    incoming, errors, stats = sources.collect(
        source_names,
        vendors,
        timeout=args.timeout,
        environ=os.environ,
        official=args.official,
    )
    for error in errors:
        print("warn: %s" % error, file=sys.stderr)
    if not incoming:
        print("error: no models fetched from any source", file=sys.stderr)
        return 2

    index, duplicates = merge.index_incoming(incoming)
    conflicts = merge.detect_conflicts(index)
    skip_fields = {(item["key"], item["field"]) for item in conflicts}

    models_envelope, models = load_envelope(models_path)
    vendors_envelope, vendor_records = load_envelope(vendors_path)
    models_before = list(models)
    source_keys = set(index)

    pending = []

    if args.only in ("metadata", "all"):
        models, changes, added, ambiguous, missing, tie_broken = merge.merge_metadata(
            models,
            index,
            allow_new=args.allow_new,
            min_release_date=args.min_release_date,
            allowed_new={
                item.strip()
                for item in args.allow_new_models.split(",")
                if item.strip()
            }
            or None,
            skip_fields=skip_fields,
            tie_break=config.get("tie_break") or None,
        )
        override_path = os.path.join(root, config.get("overrides") or "")
        overrides = load_json(override_path, {}) if config.get("overrides") else {}
        override_applied, override_missing = merge.apply_overrides(
            models, overrides, changes
        )
        vendor_added = merge.ensure_vendors(vendor_records, models)

        models_text = dump_envelope(models_envelope, models)
        vendors_text = dump_envelope(vendors_envelope, vendor_records)

        targets = [models_path, vendors_path]
        for locale in I18N_LOCALES:
            locale_dir = os.path.join(api_dir, "i18n", locale, "newapi")
            targets.append(os.path.join(locale_dir, "models.json"))
            targets.append(os.path.join(locale_dir, "vendors.json"))

        for path in targets:
            text = models_text if os.path.basename(path) == "models.json" else vendors_text
            pending.append((path, text))

        if not args.quiet:
            matched = sum(
                1
                for record in models_before
                if normalize_key(str(record.get("model_name", ""))) in source_keys
            )
            print("sources: %s" % ", ".join("%s=%d" % kv for kv in stats.items()))
            print(
                "models: %d in file, %d matched to sources, %d added, %d ambiguous, %d without source"
                % (
                    len(models_before),
                    matched,
                    len(added),
                    len(ambiguous),
                    len(missing),
                )
            )
            for name in added:
                print("  + %s" % name)
            for name in ambiguous:
                print("  ? source conflict: %s" % name)
            for item in tie_broken:
                print(
                    "  ~ tie-break %s.%s <- %s"
                    % (item["model"], item["field"], item["source"])
                )
            for name in missing:
                print("  - not in sources: %s" % name)
            for name in vendor_added:
                print("  + vendor %s" % name)
            if override_applied or override_missing:
                print(
                    "overrides: %d applied, %d target model(s) missing"
                    % (override_applied, len(override_missing))
                )
                for name in override_missing:
                    print("  ! override target not found: %s" % name)
            for change in changes:
                print(
                    "  ~ %s.%s: %s -> %s"
                    % (
                        change["model"],
                        change["field"],
                        json.dumps(change["from"], ensure_ascii=False),
                        json.dumps(change["to"], ensure_ascii=False),
                    )
                )
            for conflict in conflicts:
                values = ", ".join(
                    "%s (%s)" % (value, "/".join(names))
                    for value, names in sorted(conflict["values"].items())
                )
                print(
                    "  ! conflict %s.%s: %s"
                    % (conflict["key"], conflict["field"], values)
                )

    if args.only in ("pricing", "all"):
        official_prices = merge.load_official_prices(official_pricing_path)
        previous_rows = []
        if os.path.exists(pricing_path):
            previous_rows = load_json(pricing_path, {}).get("data") or []
        rows = merge.price_records(
            models, index, official_prices, previous=previous_rows
        )
        pricing_envelope = {
            "success": True,
            "message": "ok",
            "price_kind": "mixed",
            "notice": (
                "vendor official list prices (pricing.official.json) win; "
                "aggregator reference rows only fill models without an official entry"
            ),
            "currency": "USD",
            "unit": "per_1m_tokens",
            "sources": source_names,
        }
        pricing_text = dump_envelope(pricing_envelope, rows)
        pending.append((pricing_path, pricing_text))
        if not args.quiet:
            kinds = {}
            for row in rows:
                kind = row.get("price_kind") or "unknown"
                kinds[kind] = kinds.get(kind, 0) + 1
            detail = ", ".join("%d %s" % (n, k) for k, n in sorted(kinds.items()))
            print("prices: %d rows (%s)" % (len(rows), detail))

    changed = []
    for path, text in pending:
        if args.dry_run or args.check:
            try:
                with open(path, encoding="utf-8") as handle:
                    same = handle.read() == text
            except FileNotFoundError:
                same = False
            if not same:
                changed.append(os.path.relpath(path, root))
        elif write_if_changed(path, text):
            changed.append(os.path.relpath(path, root))

    print("changed: %s" % (", ".join(changed) if changed else "(none)"))

    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
