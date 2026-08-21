from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path.cwd()


def cmd_init(args: argparse.Namespace) -> None:
    from scripts.cc_patcher.baseline import (
        BaselineManager,
        DEV_BASELINE,
        RELEASE_BASELINE,
    )
    from scripts.cc_patcher.scanner import scan
    from scripts.cc_patcher.differ import DiffResult

    version = _read_version()
    files = scan(ROOT)

    for name, path in [("dev", DEV_BASELINE), ("release", RELEASE_BASELINE)]:
        bm = BaselineManager(path)
        if bm.load() is not None and not args.force:
            print(
                f"error: {name} baseline already exists, use --force to overwrite",
                file=sys.stderr,
            )
            sys.exit(1)
        bm.save(version, files)
        print(f"Created {name} baseline ({len(files)} files, version {version})")


def cmd_diff(args: argparse.Namespace) -> None:
    from scripts.cc_patcher.baseline import BaselineManager, DEV_BASELINE
    from scripts.cc_patcher.scanner import scan
    from scripts.cc_patcher.differ import diff as compute_diff

    bm = BaselineManager(DEV_BASELINE)
    baseline = bm.load()
    if baseline is None:
        print("fatal: dev baseline not found — run 'init' first", file=sys.stderr)
        sys.exit(1)

    current = scan(ROOT)
    result = compute_diff(current, baseline["files"])

    if not result.has_changes:
        print("No changes since last baseline.")
        return

    snapshot = baseline.get("snapshot_at", "unknown")
    print(f"Changes since last baseline ({snapshot}):\n")
    for p in result.added:
        print(f"  New:     {p}")
    for p in result.changed:
        print(f"  Changed: {p}")
    for p in result.deleted:
        print(f"  Deleted: {p}")
    print(f"\n{result.total} file(s) changed. Run 'publish' to create a patch.")


def cmd_publish(args: argparse.Namespace) -> None:
    from scripts.cc_patcher.baseline import BaselineManager, DEV_BASELINE
    from scripts.cc_patcher.scanner import scan
    from scripts.cc_patcher.differ import diff as compute_diff
    from scripts.cc_patcher.packer import build_manifest, pack_patch
    from scripts.cc_patcher.publisher import (
        check_path_available,
        get_network_path,
        publish_patch,
    )

    bm = BaselineManager(DEV_BASELINE)
    baseline = bm.load()
    if baseline is None:
        print("fatal: dev baseline not found — run 'init' first", file=sys.stderr)
        sys.exit(1)

    version = baseline["version"]
    current = scan(ROOT)
    result = compute_diff(current, baseline["files"])

    if not result.has_changes:
        print("No changes since last baseline — nothing to publish.")
        return

    manifest = build_manifest(
        version=version,
        description=args.description,
        added=result.added,
        changed=result.changed,
        deleted=result.deleted,
    )

    patch_path = pack_patch(ROOT, manifest, output_dir=Path.cwd())
    print(f"Built patch: {patch_path.name}")

    network_path = get_network_path(args.network_path)
    if not check_path_available(network_path):
        print(
            f"fatal: network path not available: {network_path}",
            file=sys.stderr,
        )
        patch_path.unlink(missing_ok=True)
        sys.exit(1)

    publish_patch(patch_path, version, network_path)
    bm.save(version, current)
    print(f"Dev baseline updated (next diff will be from this point)")


def cmd_release(args: argparse.Namespace) -> None:
    from scripts.cc_patcher.baseline import (
        BaselineManager,
        DEV_BASELINE,
        RELEASE_BASELINE,
    )
    from scripts.cc_patcher.scanner import scan
    from scripts.cc_patcher.differ import diff as compute_diff
    from scripts.cc_patcher.packer import pack_upgrade
    from scripts.cc_patcher.publisher import (
        check_path_available,
        get_network_path,
        publish_release,
    )

    to_version = args.version
    current = scan(ROOT)

    release_bm = BaselineManager(RELEASE_BASELINE)
    release_data = release_bm.load()

    prev_version = None
    upgrade_patch = None

    if release_data is not None:
        prev_version = release_data.get("version")
        result = compute_diff(current, release_data["files"])

        if result.has_changes:
            output_dir = Path.cwd()
            upgrade_patch = pack_upgrade(
                root=ROOT,
                from_version=prev_version,
                to_version=to_version,
                added=result.added,
                changed=result.changed,
                deleted=result.deleted,
                output_dir=output_dir,
            )
            print(f"Built upgrade patch: {upgrade_patch.name}")
        else:
            print("No changes since release baseline — upgrade patch is empty.")
    else:
        print("First release — no upgrade patch needed.")

    network_path = get_network_path(args.network_path)
    if not check_path_available(network_path):
        print(
            f"fatal: network path not available: {network_path}",
            file=sys.stderr,
        )
        if upgrade_patch:
            upgrade_patch.unlink(missing_ok=True)
        sys.exit(1)

    publish_release(to_version, prev_version, upgrade_patch, network_path)

    release_bm.save(to_version, current)
    BaselineManager(DEV_BASELINE).save(to_version, current)
    print(f"Dev and release baselines updated to version {to_version}")


def cmd_config(args: argparse.Namespace) -> None:
    from scripts.cc_patcher.publisher import load_config, save_config

    if args.network_path:
        save_config(network_path=args.network_path)
        print(f"network_path set to: {args.network_path}")
    else:
        cfg = load_config()
        if cfg:
            for k, v in cfg.items():
                print(f"  {k} = {v}")
        else:
            print("No configuration set.")


def _read_version() -> str:
    vf = ROOT / "version.txt"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()
    print("fatal: version.txt not found", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CashControl patch manager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize baselines from current state")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing baselines")
    p_init.set_defaults(func=cmd_init)

    p_diff = sub.add_parser("diff", help="Show changes since last baseline")
    p_diff.set_defaults(func=cmd_diff)

    p_pub = sub.add_parser("publish", help="Create and publish a point patch")
    p_pub.add_argument("--description", required=True, help="Human-readable patch description")
    p_pub.add_argument("--network-path", help="Override configured network path")
    p_pub.set_defaults(func=cmd_publish)

    p_rel = sub.add_parser("release", help="Create and publish a release (upgrade patch + exe)")
    p_rel.add_argument("--version", required=True, help="New version number (e.g. 3.0.2)")
    p_rel.add_argument("--network-path", help="Override configured network path")
    p_rel.set_defaults(func=cmd_release)

    p_cfg = sub.add_parser("config", help="View or set configuration")
    p_cfg.add_argument("--network-path", help="Set network share path")
    p_cfg.set_defaults(func=cmd_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
