#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 封存内容哈希

    python3 self_seal.py <档案目录>            # 封存 SELF.md 与 PRINCIPLES.md
    python3 self_seal.py <档案目录> --check    # 只校验，不写

哈希是「下游产物是否还基于当前这版档案」的**唯一异地依据**：
用户把 `self_sha256` 交给下游，之后档案被改过，下游就能发现。

**改完必须重新封存**（反模式 #29）——不封存的话 `self_check.py` 第 12 项
会当硬性 FAIL 拦下来，因为它证明不了档案与哈希一致。

**不要手抄哈希**（反模式 #28）：手抄的哈希会在下一次改动后变成谎话。

退出码：0 成功/未过期 · 1 过期或缺失 · 2 用法错误。
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = "python3 self_seal.py <档案目录> [--check]"

#: 被封存的文件 → manifest 里对应的字段名。
SEALED = (("SELF.md", "self_sha256"),
          ("PRINCIPLES.md", "principles_sha256"))


def today():
    return datetime.now().strftime("%Y-%m-%d")


def status_of(root, manifest, fname, key):
    """返回 `(状态, 实际哈希, 记录哈希)`。状态 ∈ ok / expired / unsealed / missing。"""
    path = os.path.join(root, fname)
    if not os.path.isfile(path):
        return "missing", None, (manifest or {}).get(key)
    actual = L.sha256_file(path)
    recorded = (manifest or {}).get(key)
    if not recorded:
        return "unsealed", actual, None
    return ("ok" if recorded == actual else "expired"), actual, recorded


def cmd_check(root, manifest):
    if manifest is None:
        sys.stderr.write("读不到 %s/manifest.json\n" % root)
        return 1
    bad = 0
    print("封存校验 · %s" % root)
    print()
    for fname, key in SEALED:
        st, actual, recorded = status_of(root, manifest, fname, key)
        mark = {"ok": "✅", "expired": "❌", "unsealed": "⚠️ ", "missing": "—"}[st]
        note = {"ok": "未过期",
                "expired": "已过期——%s 改动后没有重新封存" % fname,
                "unsealed": "未封存（跑 self_seal.py）",
                "missing": "文件不存在"}[st]
        print("%s %-16s %s" % (mark, fname, note))
        if actual:
            print("     当前 %s" % actual[:16])
        if recorded and recorded != actual:
            print("     记录 %s" % recorded[:16])
        if st in ("expired", "unsealed"):
            bad += 1
    print()
    if bad:
        print("❌ %d 个哈希未通过。档案改了就必须重新封存（反模式 #29）。" % bad)
        return 1
    print("✅ 哈希与档案一致。")
    return 0


def cmd_seal(root, manifest):
    if manifest is None:
        sys.stderr.write("读不到 %s/manifest.json——先跑 evidence_ingest.py 建工作区\n" % root)
        return 1
    changed, missing = [], []
    for fname, key in SEALED:
        path = os.path.join(root, fname)
        if not os.path.isfile(path):
            missing.append(fname)
            continue
        digest = L.sha256_file(path)
        if manifest.get(key) != digest:
            manifest[key] = digest
            changed.append((fname, digest))

    if changed:
        manifest["updated"] = today()
        L.write_json(os.path.join(root, "manifest.json"), manifest)

    for fname, digest in changed:
        print("已封存 %-16s %s" % (fname, digest[:16]))
    if not changed and not missing:
        print("哈希已是最新，无需改动。")
    for fname in missing:
        print("⚠️  跳过 %s：文件不存在" % fname)

    if missing:
        print("\n%s 尚未生成——若流程还在 Phase 3，这是正常的；"
              "但交付前必须存在，否则 self_check.py 第 12 项会 FAIL。" % "、".join(missing))
    if changed:
        print("\n提示：哈希已写进 manifest。**把 self_sha256 交给下游产物**，"
              "之后档案被改过就能被发现。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="self_seal.py",
        description="封存 / 校验 SELF.md 与 PRINCIPLES.md 的内容哈希。",
        epilog="退出码：0 成功/未过期 · 1 过期或缺失 · 2 用法错误")
    ap.add_argument("archive", help="档案目录")
    ap.add_argument("--check", action="store_true", help="只校验，不写")
    args = ap.parse_args(argv)

    root = L.resolve_archive_dir(args.archive)
    if not os.path.isdir(root):
        return L.usage_error("目录不存在：%s" % args.archive, USAGE)

    manifest = L.load_manifest(root)
    return cmd_check(root, manifest) if args.check else cmd_seal(root, manifest)


if __name__ == "__main__":
    sys.exit(main())
