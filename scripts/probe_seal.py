#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 留出探针封存（本 skill 独有）

    python3 probe_seal.py freeze --dir <档案目录> --id P01 \
            --situation "..." --decision "..." [--options "..."] [--reason "..."]
    python3 probe_seal.py list    --dir <档案目录>
    python3 probe_seal.py verify  --dir <档案目录>
    python3 probe_seal.py unseal  --dir <档案目录> --id P01 --confirm
    python3 probe_seal.py unfreeze --dir <档案目录> --id P01 --reason "..."

留出探针是判定线可信的**机械保证**（铁律 3）：先冻结真实往事，
再建档案，最后拿档案盲测它。**后出题等于让写档案的人自己挑考题**（反模式 #6）。

一份探针拆两半落盘：

    probes/P01.md              只写情境（可见）
    probes/sealed/P01.answer.md  决定 + 理由（**Phase 2/3/4 禁读**，反模式 #14）

`freeze` 会做**机械**的泄露检查（反模式 #15）：情境里若出现决定原文或
「最后选了」这类暗示性措辞，直接拒绝落盘。语义上的泄露（暗示性背景）
仍要 agent 自己把住——脚本只拦得住字面。

退出码：0 成功 · 1 校验失败 · 2 用法错误。
"""

import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = ("python3 probe_seal.py {freeze|list|verify|unseal|unfreeze} --dir <档案目录> ...")

#: 情境里出现这些词，说明决定被写进去了（反模式 #15）。
LEAK_MARKERS = (
    "最后选了", "最后选择", "最终选", "决定是", "结果是", "答案是",
    "他选了", "我选了", "选择了", "决定不", "拒绝了", "接受了",
)


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def norm(s):
    """归一化：去掉所有非文字字符，用于字面比对。"""
    return re.sub(r"[^\w一-鿿]+", "", (s or "")).lower()


def leak_reasons(situation, decision, window=8):
    """机械泄露检查。返回原因列表（空 = 通过）。"""
    out = []
    sit, dec = norm(situation), norm(decision)
    if not dec:
        return out
    if len(dec) >= 6 and dec in sit:
        out.append("情境里出现了决定原文")
    else:
        for i in range(0, max(0, len(dec) - window + 1)):
            frag = dec[i:i + window]
            if frag and frag in sit:
                out.append("情境里出现了决定的连续片段「%s」" % frag)
                break
    hits = [m for m in LEAK_MARKERS if m in (situation or "")]
    if hits:
        out.append("情境里有暗示性措辞：%s" % "、".join(hits))
    return out


def probe_paths(root, pid):
    return (os.path.join(root, "probes", "%s.md" % pid),
            os.path.join(root, "probes", "sealed", "%s.answer.md" % pid))


def render_situation(pid, situation, options, frozen_at):
    parts = [
        "# %s · 探针情境" % pid,
        "",
        "> 冻结于 %s。**本文件只写情境**——不含决定、不含暗示性理由（反模式 #15）。" % frozen_at,
        "> 决定与当时的理由封存在 `sealed/%s.answer.md`；" % pid,
        "> **Phase 2 / 3 / 4 禁读**（反模式 #14）。",
        "",
        "## 当时面对的选择",
        "",
        situation.strip(),
        "",
    ]
    if options:
        parts += ["## 当时可选的项", "", options.strip(), ""]
    return "\n".join(parts)


def render_answer(pid, decision, reason, frozen_at):
    parts = [
        "# %s · 封存答案" % pid,
        "",
        "> 冻结于 %s。**Phase 2 / 3 / 4 禁读**（反模式 #14）。" % frozen_at,
        "> 只有评分阶段的盲测 agent 在**给出预测之后**才可 `unseal`。",
        "",
        "## 决定",
        "",
        decision.strip(),
        "",
    ]
    if reason:
        parts += ["## 当时的理由", "", reason.strip(), ""]
    return "\n".join(parts)


def find_probe(manifest, pid):
    for p in (manifest or {}).get("probes") or []:
        if p.get("id") == pid:
            return p
    return None


def cmd_freeze(args):
    root = L.resolve_archive_dir(args.dir)
    manifest = L.load_manifest(root)
    if manifest is None:
        return L.usage_error("读不到 %s/manifest.json——先跑 evidence_ingest.py 建工作区"
                             % root, USAGE)

    existing = find_probe(manifest, args.id)
    if existing is not None:
        return L.usage_error(
            "%s 已存在（status=%s）。探针一旦冻结不可改——"
            "要改先 `unfreeze --id %s --reason \"...\"`，再重新 freeze。"
            % (args.id, existing.get("status"), args.id), USAGE)

    reasons = leak_reasons(args.situation, args.decision)
    if reasons:
        sys.stderr.write("拒绝冻结：情境不干净（反模式 #15）。\n\n")
        for r in reasons:
            sys.stderr.write("  - %s\n" % r)
        sys.stderr.write(
            "\n情境必须只描述「当时面对什么选择」；写了决定或暗示性理由，"
            "探针就废了。\n把决定挪到 --decision，情境只留选项与处境。\n")
        return 2

    frozen_at = args.frozen_at or now_iso()
    sit_path, ans_path = probe_paths(root, args.id)
    os.makedirs(os.path.dirname(ans_path), exist_ok=True)

    with open(sit_path, "w", encoding="utf-8") as f:
        f.write(render_situation(args.id, args.situation, args.options, frozen_at))
    with open(ans_path, "w", encoding="utf-8") as f:
        f.write(render_answer(args.id, args.decision, args.reason, frozen_at))

    manifest.setdefault("probes", []).append({
        "id": args.id,
        "situation_file": os.path.relpath(sit_path, root).replace(os.sep, "/"),
        "sealed_file": os.path.relpath(ans_path, root).replace(os.sep, "/"),
        "sealed_sha256": L.sha256_file(ans_path),
        "frozen_at": frozen_at,
        "status": "active",
    })
    manifest["updated"] = datetime.now().strftime("%Y-%m-%d")
    L.write_json(os.path.join(root, "manifest.json"), manifest)

    print("已冻结 %s @ %s" % (args.id, frozen_at))
    print("  情境（可见）：%s" % os.path.relpath(sit_path, root))
    print("  答案（封存）：%s" % os.path.relpath(ans_path, root))
    n = len([p for p in manifest["probes"] if p.get("status") == "active"])
    print("  有效探针：%d 条（区间 %d-%d）" % (n, L.PROBE_MIN, L.PROBE_MAX))
    if n < L.PROBE_MIN:
        print("  ⚠️  少于 %d 条时保真度 G 不给分，等级封顶 C。" % L.PROBE_MIN)
    if n > L.PROBE_MAX:
        print("  ⚠️  超过 %d 条，建议收敛。" % L.PROBE_MAX)
    print("\n提醒：**Phase 2 起主动回避这些决定**，不在访谈中讨论（反模式 #14）。")
    return 0


def cmd_list(args):
    root = L.resolve_archive_dir(args.dir)
    manifest = L.load_manifest(root)
    if manifest is None:
        return L.usage_error("读不到 %s/manifest.json" % root, USAGE)
    probes = manifest.get("probes") or []
    if not probes:
        print("没有探针。")
        return 0
    rows = []
    for p in probes:
        sealed = os.path.join(root, p.get("sealed_file") or "")
        ok = os.path.isfile(sealed) and L.sha256_file(sealed) == p.get("sealed_sha256")
        rows.append([p.get("id", "?"), p.get("status", "?"),
                     p.get("frozen_at", "?"), "✅" if ok else "❌",
                     (p.get("sealed_sha256") or "")[:12]])
    print("探针 · %s" % root)
    print()
    print(L.render_table(["ID", "状态", "冻结时间", "封存", "sha256"],
                         rows, [6, 14, 20, 4, 12]))
    active = len([p for p in probes if p.get("status") == "active"])
    print("\n共 %d 条 · 有效 %d 条（G 的分母用有效条数）" % (len(probes), active))
    return 0


def cmd_verify(args):
    root = L.resolve_archive_dir(args.dir)
    manifest = L.load_manifest(root)
    if manifest is None:
        return L.usage_error("读不到 %s/manifest.json" % root, USAGE)
    probes = manifest.get("probes") or []
    if not probes:
        sys.stderr.write("没有探针可校验——没有探针，保真度无法验证。\n")
        return 1

    rows, bad = [], 0
    for p in probes:
        pid = p.get("id", "?")
        sit = os.path.join(root, p.get("situation_file") or "")
        sealed = os.path.join(root, p.get("sealed_file") or "")
        problems = []
        if not os.path.isfile(sit):
            problems.append("情境缺失")
        if not os.path.isfile(sealed):
            problems.append("封存答案缺失")
        elif L.sha256_file(sealed) != p.get("sealed_sha256"):
            problems.append("封存答案已被篡改")
        bad += 1 if problems else 0
        rows.append([pid, p.get("status", "?"), "✅" if not problems else "❌",
                     "；".join(problems) or "—"])
    print("探针封存校验 · %s" % root)
    print()
    print(L.render_table(["ID", "状态", "结果", "问题"], rows, [6, 14, 4, 40]))
    active = len([p for p in probes if p.get("status") == "active"])
    print("\n共 %d 条 · 有效 %d 条 · 异常 %d 条" % (len(probes), active, bad))
    if bad:
        print("\n❌ 封存被破坏。篡改过的探针不能用来测保真度——"
              "它已经不能证明「档案没见过答案」了。")
        return 1
    if active < L.PROBE_MIN:
        print("\n⚠️  有效探针少于 %d 条：保真度 G 不给分，等级封顶 C。" % L.PROBE_MIN)
        return 1
    print("\n✅ 封存完好。探针可用于盲测。")
    return 0


def cmd_unseal(args):
    root = L.resolve_archive_dir(args.dir)
    manifest = L.load_manifest(root)
    if manifest is None:
        return L.usage_error("读不到 %s/manifest.json" % root, USAGE)
    probe = find_probe(manifest, args.id)
    if probe is None:
        return L.usage_error("没有探针 %s" % args.id, USAGE)

    if not args.confirm:
        sys.stderr.write(
            "拒绝开封：缺少 --confirm。\n\n"
            "开封等于让档案**见过答案**。只有一种合法时机：\n"
            "  盲测 agent 已经**写下预测并指明依据条目之后**（反模式 #14）。\n"
            "先预测、后开封——顺序反了，保真度 G 就不可信了。\n\n"
            "确认已提交预测后，重跑并加 --confirm。\n")
        return 2

    path = os.path.join(root, probe.get("sealed_file") or "")
    text = L.read_text(path)
    if text is None:
        return L.usage_error("读不到封存答案：%s" % path, USAGE)

    print("=== %s 封存答案（已开封）===" % args.id)
    print(text.rstrip())
    print("=== 结束 ===")

    probe["unsealed_at"] = now_iso()
    manifest["updated"] = datetime.now().strftime("%Y-%m-%d")
    L.write_json(os.path.join(root, "manifest.json"), manifest)
    return 0


def cmd_unfreeze(args):
    root = L.resolve_archive_dir(args.dir)
    manifest = L.load_manifest(root)
    if manifest is None:
        return L.usage_error("读不到 %s/manifest.json" % root, USAGE)
    probe = find_probe(manifest, args.id)
    if probe is None:
        return L.usage_error("没有探针 %s" % args.id, USAGE)
    if not args.reason:
        return L.usage_error("unfreeze 必须给 --reason（留痕：为什么作废）", USAGE)

    probe["status"] = "unfrozen"
    probe["unfrozen_at"] = now_iso()
    probe["unfrozen_reason"] = args.reason
    manifest["updated"] = datetime.now().strftime("%Y-%m-%d")
    manifest.setdefault("changes", []).append({
        "version": manifest.get("version", 1),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "note": "作废探针 %s：%s" % (args.id, args.reason),
    })
    L.write_json(os.path.join(root, "manifest.json"), manifest)

    print("已作废 %s（status=unfrozen）。文件保留在磁盘上，理由已记入 manifest.changes。" % args.id)
    print("重新出题请用新的编号（P02…）——**探针一旦变过，前后两次保真度分数就不可比了**。")
    active = len([p for p in manifest["probes"] if p.get("status") == "active"])
    print("当前有效探针：%d 条" % active)
    if active < L.PROBE_MIN:
        print("⚠️  少于 %d 条：保真度 G 不给分，等级封顶 C。" % L.PROBE_MIN)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="probe_seal.py",
        description="留出探针的冻结 / 列举 / 校验 / 开封 / 作废。",
        epilog="退出码：0 成功 · 1 校验失败 · 2 用法错误")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("freeze", help="冻结一条探针（情境可见 + 答案封存）")
    p.add_argument("--dir", required=True)
    p.add_argument("--id", required=True, help="探针编号，如 P01")
    p.add_argument("--situation", required=True, help="情境（只写面对什么选择，不写决定）")
    p.add_argument("--decision", required=True, help="真实决定（会被封存）")
    p.add_argument("--options", help="当时可选的项")
    p.add_argument("--reason", help="当时的理由（会被封存）")
    p.add_argument("--frozen-at", help="冻结时间（默认当前时间；回填旧档案时用）")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("list", help="列出探针与封存状态")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("verify", help="校验封存未被篡改")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("unseal", help="开封探针答案（须 --confirm）")
    p.add_argument("--dir", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--confirm", action="store_true",
                   help="确认盲测预测**已经**提交（先预测、后开封）")
    p.set_defaults(func=cmd_unseal)

    p = sub.add_parser("unfreeze", help="作废一条探针（留痕）")
    p.add_argument("--dir", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True, help="为什么作废（记入 manifest.changes）")
    p.set_defaults(func=cmd_unfreeze)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
