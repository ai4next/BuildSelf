#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 深化议程（缺口体检）

    python3 self_gaps.py <档案目录> [--json] [--top N]

**这份档案哪里最薄，下一轮该问什么。** 它是 Phase 7「深化循环」的起点，
也是「构建尽可能全面、丰富的自我资料」这句话的可执行形式。

它和另外两个脚本的分工：

    self_report.py  **现在到哪一步了**（进度与体量）
    self_check.py   **结构对不对**（12 项硬检查）
    self_gaps.py    **还差什么、先补哪块**（覆盖矩阵 + 排序后的提问议程）

## 只做机械活（反模式 #27）

本脚本**不发明问题**。它做三件机械的事：

  1. **数**：每个维度的证据份数 / 访谈条数 / 条目数 / 信度构成 / 缺口数
  2. **收**：把散落在五个地方的缺口收成一张表
     （维度文件的 `## 还没查到`、未解决的冲突、无痕迹的「述」、
      公理缺「代价」、未建的核心维度）
  3. **排**：按**边际信息量**排序（依据写在 `deepening-engine.md` §三）

每条议程只给「**问哪一类**」（七类问题里的哪一类）+「**要什么素材**」——
**具体怎么措辞是 agent 的活**。脚本能判的是"这里有个洞"，
判不了"该怎么问他"。硬要脚本写问句，写出来的就是模板腔。

退出码：0（报告）· 2 用法错误。**只读，不写任何东西。**
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = "python3 self_gaps.py <档案目录> [--json] [--top N]"

#: 优先级。数字越小越先问。**顺序即理由**，依据见 `deepening-engine.md` §三。
P_CONFLICT = 0    # 未解决的述行冲突——信息量最高处，且 H 轴直接受益
P_DIM_GAP = 1     # 维度文件里标了「可补」的缺口——深化循环的主战场
P_NO_TRACE = 2    # 「述」无痕迹 → 去取证升「行」——直接影响硬指标
P_AXIOM = 3       # 公理缺「代价」/ 张力不足——X 轴
P_COVERAGE = 4    # 未建的核心维度 / 覆盖太薄的维度

PRIORITY_LABEL = {
    P_CONFLICT: "P0 · 未解决的述行冲突",
    P_DIM_GAP: "P1 · 可补的维度缺口",
    P_NO_TRACE: "P2 · 「述」无痕迹 → 去取证升「行」",
    P_AXIOM: "P3 · 公理集的「代价」与张力",
    P_COVERAGE: "P4 · 覆盖：未建的维度与太薄的维度",
}

#: 缺口性质 → 用哪一类问题。**这是机械映射，不是措辞**——
#: 七类问题的定义与示例见 `interview-engine.md` §二。
QTYPE_BY_GAP = "① 具体事件回溯"
QTYPE_BY_CONFLICT = "⑥ 矛盾对质"
QTYPE_BY_COST = "③ 代价追问"
QTYPE_BY_TIMELINE = "② 反事实"


def h(title):
    return "\n" + title + "\n" + "─" * 60


def collect_conflicts(root):
    """未解决的述行冲突（分类为「未解决」的那些）。"""
    text = L.read_text(os.path.join(root, "CONFLICTS.md"))
    if not text:
        return []
    out = []
    for m in L.CONFLICT_HEAD_RE.finditer(text):
        start = m.end()
        nxt = text.find("\n## ", start)
        chunk = text[start:nxt if nxt != -1 else len(text)]
        if "未解决" in chunk:
            out.append({"id": "C" + m.group(1), "title": m.group(2).strip()})
    return out


def collect_axiom_gaps(root):
    """公理缺「代价」的，以及 `PRINCIPLES.md` 的「信息缺口」段。"""
    text = L.read_text(os.path.join(root, "PRINCIPLES.md"))
    out = {"no_cost": [], "gaps": []}
    if not text:
        return out
    for aid, stance, _reason, cost, _src in L.parse_axioms(text):
        if not (cost or "").strip() or len((cost or "").strip()) < 6:
            out["no_cost"].append({"id": aid, "stance": stance})
    sec = L.section(text, "信息缺口")
    out["gaps"] = L.list_or_table_items(sec)
    return out


def build_agenda(dims, conflicts, axioms, self_body, root):
    """把五处缺口收成一张**排好序**的议程。

    返回 `[(priority, item_dict), ...]`，已按优先级稳定排序。
    """
    items = []

    for c in conflicts:
        items.append((P_CONFLICT, {
            "where": "CONFLICTS.md#%s" % c["id"],
            "what": "%s（分类=未解决）" % (c["title"] or c["id"]),
            "why": "冲突是信息量最高的条目；「未解决」意味着解释权还没交回给他",
            "qtype": QTYPE_BY_CONFLICT,
            "need": "他自己的解释——承认 / 条件差异 / 质疑痕迹 / 回避都行，"
                    "回避也要如实记为「未解决」",
        }))

    for d in dims:
        for gap in d["gaps"]:
            if gap["kind"] == L.GAP_OPEN:
                items.append((P_DIM_GAP, {
                    "where": "dims/%s-%s.md" % (d["id"], d["slug"]),
                    "what": "[%s] %s" % (d["name"], gap["text"]),
                    "why": "取证底稿自己声明了「可补」——它比任何猜测都准",
                    "qtype": QTYPE_BY_TIMELINE if d["name"] == "时间线" else QTYPE_BY_GAP,
                    "need": "缺口条目里写的「需要什么才能补上」",
                }))

    # 「述」无痕迹 → 去取证。维度文件里的「述」条目是主来源。
    for d in dims:
        if d["path"] and d["rel"].get("述") and d["rel"].get("行", 0) == 0:
            items.append((P_NO_TRACE, {
                "where": "dims/%s-%s.md" % (d["id"], d["slug"]),
                "what": "[%s] %d 条「述」、0 条「行」" % (d["name"], d["rel"]["述"]),
                "why": "整维只有自述没有痕迹 = 自述誊清稿；硬指标要求骨架 行 ≥ 30%",
                "qtype": QTYPE_BY_GAP,
                "need": "任何可核对的痕迹（聊天 / 日历 / 账单 / 提交记录）",
            }))
    if self_body:
        no_ptr = [t for t, g, _, _, p in L.skeleton_items(self_body)
                  if g is not None and not p]
        if no_ptr:
            items.append((P_NO_TRACE, {
                "where": "SELF.md#核心骨架",
                "what": "%d 条骨架条目只有信度、没有出处指针" % len(no_ptr),
                "why": "没有指针就无法回查，溯源 S 轴测的就是这个",
                "qtype": QTYPE_BY_GAP,
                "need": "每条指向具体痕迹或访谈轮次",
            }))

    for a in axioms["no_cost"]:
        items.append((P_AXIOM, {
            "where": "PRINCIPLES.md#%s" % a["id"],
            "what": "%s「代价」栏为空或过短" % a["id"],
            "why": "答不出代价的是套话——「有代价」是比「不可再分」可靠得多的正向检验",
            "qtype": QTYPE_BY_COST,
            "need": "他遵守这条会在什么情境下吃亏（须来自真实的放弃，不是你想的）",
        }))
    for g in axioms["gaps"]:
        items.append((P_AXIOM, {
            "where": "PRINCIPLES.md#信息缺口",
            "what": g,
            "why": "公理集自己声明的缺口",
            "qtype": QTYPE_BY_COST,
            "need": "缺口条目里写的「需要什么才能补」",
        }))

    for d in dims:
        if not d["declared"]:
            items.append((P_COVERAGE, {
                "where": "—",
                "what": "[%s] 核心维度未建" % d["name"],
                "why": "不用为了凑满而编，但**必须在存疑与缺口里交代**"
                       "——空着不写 ≠ 不存在，那是「没看」不是「没有」",
                "qtype": QTYPE_BY_GAP,
                "need": "任意能覆盖这个维度的痕迹或问答；补不上就如实写进存疑段",
            }))
        elif d["path"] and d["entries"] < L.COVERAGE_RICH_MIN_ENTRIES:
            items.append((P_COVERAGE, {
                "where": "dims/%s-%s.md" % (d["id"], d["slug"]),
                "what": "[%s] 只有 %d 条带信度的条目（丰富档要求 ≥%d）"
                        % (d["name"], d["entries"], L.COVERAGE_RICH_MIN_ENTRIES),
                "why": "这一维太薄，判定线在它上面没有承重",
                "qtype": QTYPE_BY_GAP,
                "need": "再取一次证，或再问一轮具体事件",
            }))

    return sorted(items, key=lambda x: x[0])


def render(root, dims, level, reasons, stats, agenda, pending, top):
    out = ["深化议程 · %s" % root]

    out.append(h("覆盖矩阵（核心六维 + 扩展维度）"))
    rows = []
    for d in dims:
        tag = "core" if d["kind"] == "core" else "ext"
        if not d["path"]:
            rows.append([("%s %s" % (d["id"] or "—", d["name"])), "—", "—",
                         "—", "—",
                         "未建" if not d["declared"] else "缺文件", tag])
            continue
        rel = d["rel"]
        rows.append([
            "%s %s" % (d["id"], d["name"]),
            d["slug"][:14],
            str(d["ev_count"]), str(d["iv_count"]),
            "%d(%d/%d/%d)" % (d["entries"], rel.get("行", 0),
                              rel.get("述", 0), rel.get("推", 0)),
            "%d/%d" % (d["gaps_open"], d["gaps_pending"]),
            tag,
        ])
    out.append(L.render_table(
        ["维度", "文件", "证据", "访谈", "条目(行/述/推)", "缺口(可补/待事件)", "类"],
        rows, [12, 14, 4, 4, 16, 16, 4]))
    out.append("")
    out.append("  覆盖等级：**%s**" % level)
    for r in reasons:
        out.append("    · %s" % r)
    out.append("  （等级是**标签不是分数**——丰富度可被灌水，所以它不计入总分，"
               "只用来驱动下一轮该问什么）")

    out.append(h("提问议程（按边际信息量排序）"))
    if not agenda:
        out.append("  ✅ 没有可补的缺口。")
        out.append("     → 若剩下的缺口全是「待事件」，**这就是饱和**，该停手而不是硬答。")
    else:
        shown = agenda if top <= 0 else agenda[:top]
        last = None
        for pri, it in shown:
            if pri != last:
                out.append("")
                out.append("  %s" % PRIORITY_LABEL[pri])
                last = pri
            out.append("    · %s" % it["what"])
            out.append("      出处 %s" % it["where"])
            out.append("      为什么问它：%s" % it["why"])
            out.append("      用哪类问题：%s ｜ 要的素材：%s"
                       % (it["qtype"], it["need"]))
        if top > 0 and len(agenda) > top:
            out.append("")
            out.append("  …还有 %d 条（--top 0 看全部）" % (len(agenda) - top))

    if pending:
        out.append(h("不可补的缺口（待事件）——**不要硬答**"))
        for p in pending:
            out.append("    · [%s] %s" % (p["dim"], p["text"]))
        out.append("")
        out.append("  这些只能等它真实发生。**为它们编内容是编造，不是丰富**——")
        out.append("  档案要如实留着它们，这正是「诚实边界」的原料。")

    out.append(h("下一步"))
    out.append("  1. 从议程顶部取 3-5 条，按 `deepening-engine.md` 的问法问（**别一次问完**）")
    out.append("  2. 新素材走 evidence_ingest.py（逐份明示同意）；新问答走")
    out.append("     interview_log.py append --dimensions <维度>")
    out.append("  3. 只重跑受影响的维度（dims/ 下对应文件 + SELF.md 对应段）")
    out.append("  4. self_seal.py → self_check.py → **再跑一次本脚本**，看覆盖等级是否上升")
    out.append("")
    out.append("  深化**不碰探针**——探针一旦冻结就不动（铁律 3）。")
    out.append("  连续两轮覆盖等级不升、且没有新的冲突与痕迹 → 收手，那是饱和。")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="self_gaps.py",
        description="深化议程：覆盖矩阵 + 按边际信息量排序的提问议程（只读）。",
        epilog="退出码：0（报告）· 2 用法错误")
    ap.add_argument("archive", help="档案目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--top", type=int, default=12,
                    help="议程最多显示几条（0 = 全部，默认 12）")
    args = ap.parse_args(argv)

    root = L.resolve_archive_dir(args.archive)
    if not os.path.isdir(root):
        return L.usage_error("目录不存在：%s" % args.archive, USAGE)

    manifest = L.load_manifest(root)
    text = L.read_text(os.path.join(root, "SELF.md"))
    fm, self_body = L.parse_frontmatter(text) if text else (None, None)

    dims = L.dimension_coverage(root, manifest, fm or {})
    conflicts = collect_conflicts(root)
    axioms = collect_axiom_gaps(root)
    level, reasons, stats = L.assess_coverage_level(dims, manifest, self_body, root)
    agenda = build_agenda(dims, conflicts, axioms, self_body, root)
    pending = [{"dim": d["name"], "text": g["text"]}
               for d in dims for g in d["gaps"]
               if g["kind"] == L.GAP_PENDING]

    if args.json:
        import json
        print(json.dumps({
            "archive": root,
            "coverage_level": level,
            "coverage_reasons": reasons,
            "stats": stats,
            "dimensions": [{k: v for k, v in d.items() if k != "path"} for d in dims],
            "agenda": [{"priority": p, **it} for p, it in agenda],
            "pending_gaps": pending,
        }, ensure_ascii=False, indent=2))
        return 0

    print("\n".join(render(root, dims, level, reasons, stats,
                          agenda, pending, args.top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
