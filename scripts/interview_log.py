#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 访谈台账

    python3 interview_log.py append --dir <档案目录> --round 1 \
            --q "..." --a "..." [--qtype event_recall] [--reliability 述] \
            [--uncertain] [--blocked] [--note "..."] \
            [--contradicts C1] [--probe-contamination P01]
    python3 interview_log.py show  --dir <档案目录> [--round N]
    python3 interview_log.py stats --dir <档案目录>

**台账是追加式的，只增不改。** 每问一答落一行 `interview/LEDGER.jsonl`，
同时按轮次追加进 `interview/round-NN.md`（逐字记录，也**只增不改**）。

为什么要台账而不是只有逐字记录：逐字记录是给人读的，台账是给**统计**用的——
信度分布、取证率、被阻塞的问题、对质过的冲突、探针污染事件，都要能被数出来。
`self_report.py` 的检查点摘要就建在它上面。

`--probe-contamination <探针号>`：用户在访谈里主动提起了某条封存探针的决定。
记下来并把该探针标 `contaminated`——**它不计入保真度 G 的分母**（反模式 #14）。
这不是惩罚，是诚实：档案已经「见过」那个答案了。

退出码：0 成功 · 2 用法错误。
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = "python3 interview_log.py {append|show|stats} --dir <档案目录> ..."

#: 七类问题（`interview-engine.md` §二）。脚本只校验取值，不判断用得好不好。
QTYPES = (
    "event_recall", "counterfactual", "cost", "others_view",
    "exception", "confrontation", "pattern",
)

QTYPE_CN = {
    "event_recall": "①具体事件回溯",
    "counterfactual": "②反事实",
    "cost": "③代价追问",
    "others_view": "④他者视角",
    "exception": "⑤例外挖掘",
    "confrontation": "⑥矛盾对质",
    "pattern": "⑦模式识别",
}


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def round_path(root, rnd):
    return os.path.join(root, "interview", "round-%02d.md" % rnd)


def ledger_path(root):
    return os.path.join(root, "interview", "LEDGER.jsonl")


def round_header(rnd):
    return "\n".join([
        "# 第 %02d 轮访谈" % rnd,
        "",
        "> 逐字记录，**只增不改**。台账见 `LEDGER.jsonl`。",
        "",
    ])


def render_entry(seq, row):
    flags = []
    if row.get("uncertain"):
        flags.append("疑")
    if row.get("blocked"):
        flags.append("🚧阻塞")
    for c in row.get("contradicts") or []:
        flags.append("对质 %s" % c)
    tail = ("（%s%s）" % (row.get("reliability") or "未定",
                         " · " + " · ".join(flags) if flags else ""))
    lines = [
        "## Q%d · %s %s" % (seq, QTYPE_CN.get(row.get("qtype"), "—"), tail),
        "",
        "**问**：%s" % (row.get("q") or "").strip(),
        "",
        "**答**：%s" % (row.get("a") or "").strip(),
        "",
    ]
    if row.get("note"):
        lines += ["**记**：%s" % row["note"].strip(), ""]
    return "\n".join(lines)


def append_round_file(root, row):
    path = round_path(root, row["round"])
    text = L.read_text(path)
    if text is None:
        text = round_header(row["round"]) + "\n"
    text = text.rstrip() + "\n\n" + render_entry(row["seq"], row) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def cmd_append(args):
    root = L.resolve_archive_dir(args.dir)
    if not os.path.isdir(root):
        return L.usage_error("目录不存在：%s" % args.dir, USAGE)
    os.makedirs(os.path.join(root, "interview"), exist_ok=True)

    rows = L.load_jsonl(ledger_path(root))
    seq = len([r for r in rows if r.get("round") == args.round]) + 1

    contradicts = []
    for c in args.contradicts or []:
        c = c.strip().lstrip("C") or ""
        if c:
            contradicts.append("C%s" % c)

    row = {
        "round": args.round,
        "seq": seq,
        "at": now_iso(),
        "qtype": args.qtype,
        "q": args.q,
        "a": args.a,
        "reliability": args.reliability,
        "uncertain": bool(args.uncertain),
        "blocked": bool(args.blocked),
        "dimensions": args.dimensions or None,
        "contradicts": contradicts,
        "probe_contamination": args.probe_contamination,
        "note": args.note,
    }
    L.append_jsonl(ledger_path(root), row)
    append_round_file(root, row)

    # manifest 的轮数要跟上（它是 SELF.md frontmatter 对账的依据之一）
    manifest = L.load_manifest(root)
    if isinstance(manifest, dict):
        manifest["interview_rounds"] = max(
            manifest.get("interview_rounds") or 0, args.round)
        if args.probe_contamination:
            for p in manifest.get("probes") or []:
                if p.get("id") == args.probe_contamination:
                    p["status"] = "contaminated"
                    p["contaminated_at"] = now_iso()
                    p["contaminated_reason"] = "访谈中讨论了该探针的决定"
        manifest["updated"] = today()
        L.write_json(os.path.join(root, "manifest.json"), manifest)

    print("已记：第 %d 轮 Q%d · %s · 信度 %s"
          % (args.round, seq, QTYPE_CN.get(args.qtype, args.qtype or "—"),
             args.reliability or "未定"))
    if args.probe_contamination:
        print("⚠️  探针 %s 已标 contaminated——**不计入保真度 G 的分母**（反模式 #14）。"
              % args.probe_contamination)
    if args.blocked:
        print("🚧 记为阻塞。追问「那你打算怎么知道」→ 转成一个取证动作，"
              "而不是替 ta 补答案（反模式 #4）。")
    return 0


def cmd_show(args):
    root = L.resolve_archive_dir(args.dir)
    rows = L.load_jsonl(ledger_path(root))
    if args.round is not None:
        rows = [r for r in rows if r.get("round") == args.round]
    if not rows:
        print("台账为空。")
        return 0
    table = []
    for r in rows:
        flags = []
        if r.get("uncertain"):
            flags.append("疑")
        if r.get("blocked"):
            flags.append("🚧")
        for c in r.get("contradicts") or []:
            flags.append(c)
        if r.get("probe_contamination"):
            flags.append("污染:%s" % r["probe_contamination"])
        table.append([
            "%d-%d" % (r.get("round", 0), r.get("seq", 0)),
            QTYPE_CN.get(r.get("qtype"), r.get("qtype") or "—"),
            r.get("reliability") or "—",
            " ".join(flags) or "—",
            r.get("q") or "",
        ])
    print("访谈台账 · %s" % root)
    print()
    print(L.render_table(["轮次", "类型", "信度", "标记", "问题"],
                         table, [6, 16, 4, 14, 44]))
    print("\n共 %d 条" % len(rows))
    return 0


def cmd_stats(args):
    root = L.resolve_archive_dir(args.dir)
    rows = L.load_jsonl(ledger_path(root))
    if not rows:
        print("台账为空——还没有访谈记录。")
        return 0

    rounds = sorted({r.get("round", 0) for r in rows})
    counts = {g: 0 for g in L.RELIABILITY_GRADES}
    counts[L.UNCERTAIN_FLAG] = 0
    blocked = uncertain = 0
    conflicts = set()
    contaminations = []
    for r in rows:
        g = r.get("reliability")
        if g in L.RELIABILITY_GRADES:
            counts[g] += 1
        if r.get("uncertain"):
            uncertain += 1
            counts[L.UNCERTAIN_FLAG] += 1
        if r.get("blocked"):
            blocked += 1
        for c in r.get("contradicts") or []:
            conflicts.add(c)
        if r.get("probe_contamination"):
            contaminations.append(r["probe_contamination"])

    total = L.reliability_total(counts)
    print("访谈统计 · %s" % root)
    print()
    print("轮次      %d 轮（%s）" % (len(rounds), "、".join(str(x) for x in rounds)))
    print("问答      %d 条" % len(rows))
    print("信度分布  %s" % L.format_reliability(counts))
    if total:
        print("取证率    %s（行 / 已标记条数）——这是访谈有没有产出「行」的指标"
              % L.fmt_pct(L.xing_ratio(counts)))
    print("阻塞      %d 条%s" % (blocked, "  ← 连续两次答不上来本身就是信号" if blocked else ""))
    print("存疑      %d 条" % uncertain)
    print("对质冲突  %d 条（%s）" % (len(conflicts), "、".join(sorted(conflicts)) or "—"))
    if contaminations:
        print("探针污染  %s  ← 不计入 G 的分母（反模式 #14）"
              % "、".join(sorted(set(contaminations))))

    # 收束信号：最近两轮有没有新痕迹 / 新冲突
    if len(rounds) >= 2:
        last2 = set(rounds[-2:])
        new_trace = [r for r in rows if r.get("round") in last2
                     and r.get("reliability") == "行"]
        new_conf = [r for r in rows if r.get("round") in last2
                    and (r.get("contradicts") or [])]
        print()
        print("收束信号（三信号见 interview-engine.md §六）")
        print("  最近两轮新痕迹：%d 条 · 新冲突：%d 条" % (len(new_trace), len(new_conf)))
        if not new_trace and not new_conf:
            print("  ⚠️  连续两轮无新痕迹也无新冲突——已到收束信号，"
                  "该交付而不是继续追问（反模式 #21）。")
        else:
            print("  仍有增量，可继续。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="interview_log.py",
        description="访谈台账：追加问答、展示、统计（追加式，只增不改）。",
        epilog="退出码：0 成功 · 2 用法错误")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append", help="追加一条问答")
    p.add_argument("--dir", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--q", required=True, help="问题原文")
    p.add_argument("--a", required=True, help="回答原文（**逐字**，不要润色）")
    p.add_argument("--qtype", choices=QTYPES, help="问题类型（七类）")
    p.add_argument("--reliability", choices=list(L.RELIABILITY_GRADES),
                   help="这条回答的信度：行 / 述 / 推")
    p.add_argument("--uncertain", action="store_true", help="标「疑」（正交标记）")
    p.add_argument("--blocked", action="store_true", help="答不上来（🚧）")
    p.add_argument("--dimensions", action="append", metavar="决策",
                   help="这条问答覆盖的维度（可重复）。取值域是档案声明的维度"
                        "（核心六维 + 扩展维度）——**覆盖矩阵靠它算**，"
                        "漏标会让维度看起来比实际薄")
    p.add_argument("--note", help="记录者的备注")
    p.add_argument("--contradicts", action="append", metavar="C1",
                   help="这条对质了哪个冲突（可重复）")
    p.add_argument("--probe-contamination", metavar="P01",
                   help="用户主动提起了该封存探针的决定 → 标 contaminated")
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("show", help="展示台账")
    p.add_argument("--dir", required=True)
    p.add_argument("--round", type=int)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("stats", help="统计信度分布 / 取证率 / 收束信号")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
