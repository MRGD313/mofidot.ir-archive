"""Discover and assign categories for the @mofidot Telegram archive.

The taxonomy is discovered from the channel's own content first. Categories live
in ``src/data/categories.json`` as ``name`` + ``keywords`` entries. New posts can
be categorized with DeepSeek (when ``DEEPSEEK_API_KEY`` is set and ``--auto`` is
used) or with the free keyword fallback.

Typical workflow::

    python scraper/categorize.py --discover --from-json discovery.json
    python scraper/categorize.py --initial
    python scraper/categorize.py --incremental --auto

Only post JSON files and ``categories.json`` are touched. Media is never
downloaded.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = PROJECT_ROOT / "src" / "content" / "posts"
CATEGORIES_PATH = PROJECT_ROOT / "src" / "data" / "categories.json"

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
EMPTY_TAXONOMY_MESSAGE = (
    "categories.json is empty. Run --discover first, or add categories manually."
)

Category = dict[str, Any]


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically so an interrupted run cannot leave a broken file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_categories() -> list[Category]:
    if not CATEGORIES_PATH.exists():
        return []

    raw = _load_json(CATEGORIES_PATH)
    entries = raw.get("categories", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []

    categories: list[Category] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name or name in seen:
            continue
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        cleaned_keywords = _dedupe_strings(str(keyword).strip() for keyword in keywords)
        categories.append({"name": name, "keywords": cleaned_keywords})
        seen.add(name)
    return categories


def _dedupe_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _load_posts() -> list[tuple[Path, dict[str, Any]]]:
    posts: list[tuple[Path, dict[str, Any]]] = []
    if not POSTS_DIR.exists():
        return posts

    for path in sorted(POSTS_DIR.glob("*.json")):
        try:
            data = _load_json(path)
        except (OSError, ValueError) as exc:
            print(f"warning: skipping unreadable post {path.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict) or "id" not in data:
            print(f"warning: skipping post without id: {path.name}", file=sys.stderr)
            continue
        posts.append((path, data))

    posts.sort(key=lambda item: int(item[1]["id"]))
    return posts


def _normalize(value: str) -> str:
    """Normalize Persian/Arabic text for deterministic keyword matching."""
    translation = str.maketrans(
        {
            "ي": "ی",
            "ك": "ک",
            "ة": "ه",
            "ۀ": "ه",
            "أ": "ا",
            "إ": "ا",
        }
    )
    value = value.translate(translation)
    value = value.replace("\u200c", " ").replace("\u200d", " ")
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip().lower()


def _keyword_match(text: str, categories: list[Category]) -> Optional[str]:
    normalized_text = _normalize(text)
    if not normalized_text:
        return None

    best_name: Optional[str] = None
    best_score = 0

    for category in categories:
        score = 0
        for keyword in category.get("keywords", []):
            normalized_keyword = _normalize(keyword)
            if len(normalized_keyword) < 2:
                continue
            pattern = re.compile(
                rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)", re.UNICODE
            )
            score += len(pattern.findall(normalized_text))
        if score > best_score:
            best_score = score
            best_name = category["name"]

    return best_name


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    positions = [
        position for position in (text.find("{"), text.find("[")) if position >= 0
    ]
    start = min(positions, default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start < 0 or end < start:
        raise ValueError("model response did not contain JSON")
    return json.loads(text[start : end + 1])


def _deepseek_chat(messages: list[dict[str, str]]) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API network error: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"DeepSeek API error: {exc}") from exc

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DeepSeek API returned an unexpected response") from exc


def _clean_discovered_categories(raw: Any) -> list[Category]:
    entries = raw.get("categories", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError("discovery JSON must contain a categories array")

    categories: list[Category] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name or name in seen:
            continue
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        cleaned_keywords = _dedupe_strings(str(keyword).strip() for keyword in keywords)
        if not cleaned_keywords:
            continue
        description = str(entry.get("description", "")).strip()
        categories.append(
            {
                "name": name,
                "keywords": cleaned_keywords,
                "description": description,
            }
        )
        seen.add(name)

    if not categories:
        raise ValueError("no valid categories found in discovery data")
    return categories


def _print_category_table(categories: list[Category], title: str) -> None:
    print(title)
    print()
    print("| # | دسته | تعداد کلیدواژه | توضیح |")
    print("| --- | --- | --- | --- |")
    for index, category in enumerate(categories, start=1):
        description = str(category.get("description", "") or "—").replace("|", "\\|")
        print(
            f"| {index} | {category['name']} | "
            f"{len(category.get('keywords', []))} | {description} |"
        )
    print()


def _taxonomy_for_output(categories: list[Category]) -> dict[str, list[dict[str, Any]]]:
    return {
        "categories": [
            {"name": category["name"], "keywords": category["keywords"]}
            for category in categories
        ]
    }


def _discover_from_json(path: Path, dry_run: bool) -> int:
    try:
        raw = _load_json(path)
        categories = _clean_discovered_categories(raw)
    except (OSError, ValueError) as exc:
        print(f"error: could not load discovery file: {exc}", file=sys.stderr)
        return 1

    _print_category_table(categories, f"Discovered categories from {path}:")

    if dry_run:
        print("Dry run: categories.json was not modified.")
        return 0

    _atomic_write_json(CATEGORIES_PATH, _taxonomy_for_output(categories))
    print(f"Wrote {len(categories)} categories to {CATEGORIES_PATH}")
    return 0


def _discover_with_llm(
    sample_size: int, seed: int, dry_run: bool
) -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print(
            "error: --discover needs DEEPSEEK_API_KEY, or pass --from-json with a taxonomy.",
            file=sys.stderr,
        )
        return 1

    posts = _load_posts()
    if not posts:
        print("error: no posts found in src/content/posts.", file=sys.stderr)
        return 1

    randomizer = random.Random(seed)
    sample = randomizer.sample(posts, min(sample_size, len(posts)))
    sample.sort(key=lambda item: int(item[1]["id"]))

    post_blocks = []
    for _, post in sample:
        text = str(post.get("text", "")).strip().replace("\n", " ")
        post_blocks.append(f"{post['id']}: {text[:1200]}")

    messages = [
        {
            "role": "system",
            "content": (
                "You are designing a content taxonomy for a Persian Telegram archive. "
                "Return only JSON with a categories array. Each category must have a "
                "short Persian name, 5-12 Persian keywords, and a one-sentence Persian "
                "description. Create 5-10 distinct categories grounded in the posts."
            ),
        },
        {
            "role": "user",
            "content": (
                "Posts:\n\n" + "\n\n".join(post_blocks) + "\n\n"
                'Return {"categories":[{"name":"...","keywords":["..."],"description":"..."}]}'
            ),
        },
    ]

    try:
        raw = _extract_json(_deepseek_chat(messages))
        categories = _clean_discovered_categories(raw)
    except (RuntimeError, ValueError) as exc:
        print(f"error: discovery failed: {exc}", file=sys.stderr)
        return 1

    _print_category_table(categories, f"Discovered categories from {len(sample)} sampled posts:")

    if dry_run:
        print("Dry run: categories.json was not modified.")
        return 0

    _atomic_write_json(CATEGORIES_PATH, _taxonomy_for_output(categories))
    print(f"Wrote {len(categories)} categories to {CATEGORIES_PATH}")
    return 0


def _discover(args: argparse.Namespace) -> int:
    if args.from_json:
        return _discover_from_json(Path(args.from_json), args.dry_run)
    return _discover_with_llm(args.sample, args.seed, args.dry_run)


def _chunks(values: list[tuple[Path, dict[str, Any]]], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _categorize_with_llm(
    posts: list[tuple[Path, dict[str, Any]]], categories: list[Category]
) -> dict[int, Optional[str]]:
    category_names = [category["name"] for category in categories]
    assignments: dict[int, Optional[str]] = {}

    taxonomy_lines = []
    for category in categories:
        keywords = "، ".join(category.get("keywords", []))
        taxonomy_lines.append(f"- {category['name']}: {keywords}")

    for batch in _chunks(posts, 20):
        post_blocks = []
        for _, post in batch:
            text = str(post.get("text", "")).strip().replace("\n", " ")
            post_blocks.append(f"{post['id']}: {text[:1200]}")

        messages = [
            {
                "role": "system",
                "content": (
                    "You categorize Persian Telegram posts. Choose exactly one category "
                    "name from the provided list for each post, or null when no category "
                    "fits. Return only JSON in the form "
                    '{"assignments":{"POST_ID":"CATEGORY_NAME_OR_NULL"}}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Categories:\n"
                    + "\n".join(taxonomy_lines)
                    + "\n\nPosts:\n\n"
                    + "\n\n".join(post_blocks)
                ),
            },
        ]

        raw = _extract_json(_deepseek_chat(messages))
        mapping = raw.get("assignments", raw) if isinstance(raw, dict) else {}
        if not isinstance(mapping, dict):
            continue

        for post_id, category_name in mapping.items():
            try:
                normalized_id = int(post_id)
            except (TypeError, ValueError):
                continue
            if category_name in category_names:
                assignments[normalized_id] = str(category_name)
            elif category_name is None:
                assignments[normalized_id] = None

    return assignments


def _print_assignment_table(
    results: list[tuple[int, Optional[str], str]]
) -> None:
    print()
    print("| شناسه | دسته | روش |")
    print("| --- | --- | --- |")
    for post_id, category, method in results:
        print(f"| {post_id} | {category or '—'} | {method} |")
    print()


def _categorize(args: argparse.Namespace) -> int:
    categories = _load_categories()
    if not categories:
        print(EMPTY_TAXONOMY_MESSAGE, file=sys.stderr)
        return 1

    all_posts = _load_posts()
    selected = [
        item
        for item in all_posts
        if args.force or not str(item[1].get("category") or "").strip()
    ]
    if args.limit is not None:
        selected = selected[: args.limit]

    if not selected:
        print("No posts need categorization.")
        print("categorized 0 via LLM, 0 via fallback, 0 left null.")
        return 0

    llm_assignments: dict[int, Optional[str]] = {}
    use_llm = args.auto and bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if use_llm:
        try:
            llm_assignments = _categorize_with_llm(selected, categories)
        except RuntimeError as exc:
            print(
                f"warning: LLM categorization failed ({exc}); using keyword fallback.",
                file=sys.stderr,
            )

    results: list[tuple[int, Optional[str], str]] = []
    llm_count = 0
    fallback_count = 0
    null_count = 0

    for path, post in selected:
        post_id = int(post["id"])
        category = llm_assignments.get(post_id)
        method = "LLM"

        if not category:
            category = _keyword_match(str(post.get("text", "")), categories)
            method = "fallback" if category else "null"

        if category:
            if method == "LLM":
                llm_count += 1
            else:
                fallback_count += 1
        else:
            null_count += 1

        results.append((post_id, category, method))

        if not args.dry_run and post.get("category") != category:
            post["category"] = category
            _atomic_write_json(path, post)

    _print_assignment_table(results)
    print(
        f"categorized {llm_count} via LLM, {fallback_count} via fallback, "
        f"{null_count} left null."
    )
    if args.dry_run:
        print("Dry run: post files were not modified.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover categories for the @mofidot archive and assign them to posts. "
            "Uses DeepSeek when DEEPSEEK_API_KEY is set and --auto is passed; "
            "otherwise uses the free keyword fallback."
        )
    )

    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--discover",
        action="store_true",
        help="Discover a taxonomy from post content or --from-json.",
    )
    modes.add_argument(
        "--initial",
        action="store_true",
        help="Assign categories to posts that do not have one yet.",
    )
    modes.add_argument(
        "--incremental",
        action="store_true",
        help="Assign categories to new (still uncategorized) posts.",
    )

    parser.add_argument(
        "--auto",
        action="store_true",
        help="Use the LLM when DEEPSEEK_API_KEY is set; otherwise use keyword fallback.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-categorize posts even if they already have a category.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of posts to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing any files.",
    )
    parser.add_argument(
        "--from-json",
        default=None,
        help="Load discovered categories from this JSON file (with --discover).",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=40,
        help="Number of posts to sample for LLM discovery (default: 40).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for discovery sampling (default: 42).",
    )
    return parser


def _configure_stdio() -> None:
    """Use UTF-8 for Persian output on every platform, including Windows CI."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main() -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args()

    if args.from_json and not args.discover:
        parser.error("--from-json can only be used with --discover")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or a positive integer")
    if args.sample < 1:
        parser.error("--sample must be a positive integer")

    if args.discover:
        return _discover(args)
    return _categorize(args)


if __name__ == "__main__":
    raise SystemExit(main())
