#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 行为痕迹归集

    python3 evidence_ingest.py <材料...> --out <档案目录> [选项]

把用户**主动提供**的材料归入 `evidence/<type>/`，并登记到 `manifest.evidence[]`。

**硬门槛：没有 `--consent` 拒绝写入。** 这不是仪式——它保证每一次归集都过一道
显式同意（隐私硬规则 4 / 反模式 #25）。档案里存的是「一个人最不设防的那部分」，
别的东西泄露是数据事故，这个泄露是**把人交出去**。

**脚本不做语义判断**：一份材料覆盖哪些维度、它的信度是什么，脚本判不出——
`dimensions` 与 `reliability` 一律写 `null`，由 agent 回填（反模式 #27）。

**不改写用户材料**：原样复制（`copy2`，保留时间戳）。素材是证据，证据不能加工。

退出码：0 成功 · 2 用法错误 · 3 未给同意（拒绝写入）。
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = ("python3 evidence_ingest.py <材料...> --out <档案目录> "
         "[--type <slug>] [--title <标题>] --consent\n"
         "  --type 默认 chat|calendar|transactions|decisions|notes|others|other，\n"
         "  也接受任意自定义 slug（gitlog / ledger / …，小写字母开头、≤24 字符）")

REFUSED = 3


def now_iso():
    """本地时间戳，秒级（契约里 `consent_at` / `frozen_at` 的形态）。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def blank_manifest(slug):
    """新工作区的最小合法 manifest。字段与契约 §五 一致。"""
    return {
        "schema_version": L.SUPPORTED_SCHEMA_VERSION,
        "slug": slug,
        "created": today(),
        "updated": today(),
        "version": 1,
        "self_sha256": None,
        "principles_sha256": None,
        "interview_rounds": 0,
        "evidence": [],
        "probes": [],
        "changes": [{"version": 1, "date": today(), "note": "建档"}],
    }


def load_or_init(root):
    """读 manifest；没有就初始化一个。返回 `(manifest, created)`。"""
    m = L.load_manifest(root)
    if isinstance(m, dict):
        return m, False
    return blank_manifest(os.path.basename(root.rstrip("/"))), True


def guess_type(path):
    """按扩展名猜痕迹类型。猜不出归 `other`——**不猜语义**（反模式 #27）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ics", ".ical"):
        return "calendar"
    if ext in (".csv", ".xls", ".xlsx", ".tsv"):
        return "transactions"
    if ext in (".md", ".markdown"):
        return "notes"
    if ext in (".txt", ".log", ".json", ".html", ".htm"):
        return "chat"
    return "other"


def next_id(existing, prefix="E"):
    """下一个编号，形如 `E003`。"""
    n = 0
    for e in existing:
        eid = str(e.get("id") or "")
        if eid.startswith(prefix) and eid[len(prefix):].isdigit():
            n = max(n, int(eid[len(prefix):]))
    return "%s%03d" % (prefix, n + 1)


def ingest_one(root, manifest, src, etype, title, consent_at):
    """归集一份材料。返回 `(状态字符串, 是否新增)`。"""
    if not os.path.isfile(src):
        return "跳过（不是文件）：%s" % src, False

    digest = L.sha256_file(src)
    for e in manifest.get("evidence") or []:
        if e.get("sha256") == digest:
            return "跳过（内容已存在，记为 %s）：%s" % (e.get("id"), src), False

    dest_dir = os.path.join(root, "evidence", etype)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.exists(dest):
        stem, ext = os.path.splitext(os.path.basename(src))
        dest = os.path.join(dest_dir, "%s-%s%s" % (stem, digest[:8], ext))

    shutil.copy2(src, dest)          # 原样复制，不加工（素材是证据）

    rel = os.path.relpath(dest, root).replace(os.sep, "/")
    text = L.read_text(dest)
    manifest.setdefault("evidence", []).append({
        "id": next_id(manifest.get("evidence") or []),
        "path": rel,
        "type": etype,
        "title": title or os.path.basename(src),
        "words": L.count_words(text) if text is not None else None,
        "sha256": digest,
        "added": today(),
        "consent_at": consent_at,
        "dimensions": None,          # 语义判断 → 由 agent 回填（反模式 #27）
        "reliability": None,
    })
    return "已归集：%s → %s" % (src, rel), True


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="evidence_ingest.py",
        description="归集行为痕迹到 evidence/，登记到 manifest。无 --consent 拒绝写入。",
        epilog="退出码：0 成功 · 2 用法错误 · 3 未给同意")
    ap.add_argument("materials", nargs="+", help="要归集的材料（文件路径）")
    ap.add_argument("--out", required=True, help="档案目录（不存在则新建）")
    ap.add_argument("--type",
                    help="痕迹类型（默认按扩展名猜，猜不出归 other）。"
                         "默认值：%s；**也接受自定义类型**（如 gitlog / ledger / "
                         "成绩单拼音），须为小写字母开头的 ASCII slug"
                         % "/".join(L.DEFAULT_EVIDENCE_TYPES))
    ap.add_argument("--title", help="材料标题（默认用文件名）")
    ap.add_argument("--consent", action="store_true",
                    help="确认已就**这些具体材料**逐份取得用户明示同意")
    args = ap.parse_args(argv)

    if args.type and not L.valid_evidence_type(args.type):
        return L.usage_error(
            "痕迹类型 %r 不合法——须为小写字母开头、只含小写字母/数字/连字符"
            "（它要当目录名，所以限 ASCII）。默认值：%s"
            % (args.type, "/".join(L.DEFAULT_EVIDENCE_TYPES)), USAGE)

    if not args.consent:
        sys.stderr.write(
            "拒绝写入：缺少 --consent。\n\n"
            "隐私硬规则 4：归集前必须**逐份**问用户——\n"
            "    「这份是 <文件名>，我打算归入 evidence/，同意吗？」\n"
            "用户说「只看不用」时不要落盘（读后凭记忆提问即可）。\n"
            "若材料含他人原话（群聊、他人评价），必须额外说明这一层。\n\n"
            "取得同意后重跑并加上 --consent。\n")
        return REFUSED

    root = L.resolve_archive_dir(args.out)
    os.makedirs(root, exist_ok=True)
    manifest, created = load_or_init(root)
    if created:
        print("已初始化工作区：%s" % root)

    consent_at = now_iso()
    lines, added = [], 0
    for src in args.materials:
        etype = args.type or guess_type(src)
        status, ok = ingest_one(root, manifest, src, etype, args.title, consent_at)
        lines.append(status)
        added += 1 if ok else 0

    if added:
        manifest["updated"] = today()
        L.write_json(os.path.join(root, "manifest.json"), manifest)

    for line in lines:
        print(line)
    print("\n新增 %d 份 · evidence 共 %d 份"
          % (added, len(manifest.get("evidence") or [])))
    if added:
        print("下一步：由 agent 回填每份的 dimensions 与 reliability"
              "（脚本判不出语义——反模式 #27）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
