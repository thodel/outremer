#!/usr/bin/env python3
"""Render validated tei.dh.unibe.ch deployment templates.

The renderer deliberately accepts only non-secret topology values. Credentials
belong in the host-managed environment file referenced by the systemd units.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

TOKENS = {
    "PUBLIC_BASE_PATH",
    "PUBLIC_BASE_PATH_NO_SLASH",
    "RELEASE_ROOT",
    "STATE_ROOT",
    "RUNTIME_USER",
    "WEB_UPSTREAM",
    "API_UPSTREAM",
}
TOKEN_RE = re.compile(r"@([A-Z_]+)@")
SAFE_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def public_base_path(value: str) -> str:
    """Return a canonical single-segment URL prefix with leading/trailing `/`."""
    if not value.startswith("/") or not value.endswith("/"):
        raise argparse.ArgumentTypeError("base path must start and end with '/'")
    if value == "/" or "//" in value or value.count("/") != 2:
        raise argparse.ArgumentTypeError("base path must be one non-root URL segment")
    segment = value.strip("/")
    if segment in {".", ".."}:
        raise argparse.ArgumentTypeError("base path cannot be a traversal segment")
    if not re.fullmatch(r"[A-Za-z0-9._~-]+", segment):
        raise argparse.ArgumentTypeError("base path contains unsafe characters")
    return value


def absolute_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or value == "/":
        raise argparse.ArgumentTypeError("path must be absolute, non-root, and contain no '..'")
    return str(path)


def runtime_user(value: str) -> str:
    if not SAFE_USER_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("runtime user is not a safe system account name")
    return value


def upstream(value: str) -> str:
    if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", value):
        raise argparse.ArgumentTypeError("upstream must be an IPv4 loopback HTTP URL with port")
    if int(value.rsplit(":", 1)[1]) > 65535:
        raise argparse.ArgumentTypeError("upstream port must be <= 65535")
    return value


def render_text(template: str, values: dict[str, str]) -> str:
    present = set(TOKEN_RE.findall(template))
    unknown = present - TOKENS
    missing = present - values.keys()
    if unknown or missing:
        raise ValueError(f"invalid template tokens: unknown={sorted(unknown)}, missing={sorted(missing)}")
    rendered = TOKEN_RE.sub(lambda match: values[match.group(1)], template)
    leftovers = TOKEN_RE.findall(rendered)
    if leftovers:
        raise ValueError(f"unresolved template tokens: {sorted(set(leftovers))}")
    return rendered


def render_directory(template_dir: Path, output_dir: Path, values: dict[str, str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for source in sorted(template_dir.glob("*.template")):
        target = output_dir / source.name.removesuffix(".template")
        target.write_text(render_text(source.read_text(), values))
        rendered.append(target)
    if not rendered:
        raise ValueError(f"no templates found in {template_dir}")
    return rendered


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--public-base-path", type=public_base_path, default="/outremer/")
    result.add_argument("--release-root", type=absolute_path, default="/opt/outremer")
    result.add_argument("--state-root", type=absolute_path, default="/var/lib/outremer")
    result.add_argument("--runtime-user", type=runtime_user, default="outremer")
    result.add_argument("--web-upstream", type=upstream, default="http://127.0.0.1:8088")
    result.add_argument("--api-upstream", type=upstream, default="http://127.0.0.1:8089")
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument(
        "--template-dir",
        type=Path,
        default=Path(__file__).with_name("templates"),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    values = {
        "PUBLIC_BASE_PATH": args.public_base_path,
        "PUBLIC_BASE_PATH_NO_SLASH": args.public_base_path.rstrip("/"),
        "RELEASE_ROOT": args.release_root,
        "STATE_ROOT": args.state_root,
        "RUNTIME_USER": args.runtime_user,
        "WEB_UPSTREAM": args.web_upstream,
        "API_UPSTREAM": args.api_upstream,
    }
    for path in render_directory(args.template_dir, args.output_dir, values):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
