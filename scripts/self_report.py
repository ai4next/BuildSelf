#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 检查点摘要

    python3 self_report.py <档案目录>

给 Phase 1.8（清点确认）与 Phase 2.5（质量确认）用的**只读**摘要：
探针、痕迹、访谈、骨架、冲突、存疑、封存各看一行，末尾给下一步动作。

它和 `self_check.py` 的分工：

    self_report.py  **现在到哪一步了**（进度与体量，供人决策）
    self_check.py   **结构对不对**（12 项硬检查，供交付把关）

`self_report.py` 不判 FAIL/WARN——检查点的作用是让用户纠偏，
不是扣住产出（反模式 #20）。**只读，不写任何东西。**

退出码：0（报告）· 2 用法错误。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

USAGE = "python3 self_report.py <档案目录>"


def h(title):
    return "\n" + title + "\n" + "─" * 56


def probes_section(root, manifest):
    probes = (manifest or {}).get("probes") or []
    out = [h("留出探针（判定线的机械保证）")]
    if not probes:
        out.append("  ❌ 没有探针。没有探针，保真度 G 无法验证，等级封顶 C。")
        out.append("     → Phase 1 就该冻结（后出题 = 让写档案的人自己挑考题，反模式 #6）")
        return out, 0
    active = contaminated = unfrozen = 0
    broken = []
    for p in probes:
        st = p.get("status")
        if st == "active":
            active += 1
        elif st == "contaminated":
            contaminated += 1
        elif st == "unfrozen":
            unfrozen += 1
        sealed = os.path.join(root, p.get("sealed_file") or "")
        if not os.path.isfile(sealed):
            broken.append("%s 封存答案缺失" % p.get("id"))
        elif L.sha256_file(sealed) != p.get("sealed_sha256"):
            broken.append("%s 封存答案被篡改" % p.get("id"))
    out.append("  总数 %d · 有效 %d · 被污染 %d · 已作废 %d"
               % (len(probes), active, contaminated, unfrozen))
    if broken:
        out.append("  ❌ %s" % "；".join(broken))
    if active < L.PROBE_MIN:
        out.append("  ⚠️  有效探针 %d < %d：G 不给分，标「留出集不足，保真度未验证」"
                   % (active, L.PROBE_MIN))
    elif active > L.PROBE_MAX:
        out.append("  ⚠️  有效探针 %d > %d：建议收敛" % (active, L.PROBE_MAX))
    else:
        out.append("  ✅ 有效探针 %d 条，在 %d-%d 区间内"
                   % (active, L.PROBE_MIN, L.PROBE_MAX))
    if contaminated:
        out.append("  ℹ️  被污染的探针**不计入 G 的分母**——这是诚实，不是惩罚")
    return out, active


def evidence_section(root, manifest):
    ev_dir = os.path.join(root, "evidence")
    files = []
    for dirpath, _, names in os.walk(ev_dir):
        for n in names:
            if not n.startswith("."):
                files.append(os.path.join(dirpath, n))
    out = [h("行为痕迹（铁律 1 的依据）")]
    if not files:
        out.append("  ❌ evidence/ 为空。")
        out.append("     → Phase 1.5 引导用户给**任意**痕迹（聊天 / 日历 / 待办都行）")
        out.append("     → 兜底：纯访谈模式，核心骨架「行」下限放宽到 20%，"
                   "并在 QUALITY.md 标「证据薄弱，保真度可能虚高」")
        return out, 0

    by_type, words, unbacked, no_consent = {}, 0, [], []
    for e in (manifest or {}).get("evidence") or []:
        by_type[e.get("type") or "?"] = by_type.get(e.get("type") or "?", 0) + 1
        words += e.get("words") or 0
        if e.get("dimensions") is None:
            unbacked.append(e.get("id") or "?")
        if not e.get("consent_at"):
            no_consent.append(e.get("id") or "?")

    out.append("  文件 %d 份 · 索引 %d 条 · 合计约 %s 字"
               % (len(files), len((manifest or {}).get("evidence") or []), words))
    out.append("  类型分布：%s"
               % " · ".join("%s %d" % (k, v) for k, v in sorted(by_type.items())))
    if len(files) != len((manifest or {}).get("evidence") or []):
        out.append("  ⚠️  目录里有 %d 个文件，manifest 只记了 %d 条——"
                   "可能有未登记的材料" % (len(files), len((manifest or {}).get("evidence") or [])))
    if no_consent:
        out.append("  ❌ %s 没有 consent_at——**没有它意味着这份材料不该在这里**（硬规则 4）"
                   % "、".join(no_consent[:5]))
    if unbacked:
        out.append("  ⚠️  %d 份的 dimensions 还是 null（脚本判不出语义，"
                   "须由 agent 回填——反模式 #27）" % len(unbacked))
    else:
        out.append("  ✅ dimensions 已全部回填")
    return out, len(files)


def interview_section(root, manifest):
    rows = L.load_jsonl(os.path.join(root, "interview", "LEDGER.jsonl"))
    out = [h("访谈（自述 → 取证 → 对质）")]
    if not rows:
        out.append("  ❌ 台账为空——没有访谈记录。")
        return out, 0
    rounds = sorted({r.get("round", 0) for r in rows})
    counts = {g: 0 for g in L.RELIABILITY_GRADES}
    counts[L.UNCERTAIN_FLAG] = 0
    blocked = conflicts = 0
    for r in rows:
        g = r.get("reliability")
        if g in L.RELIABILITY_GRADES:
            counts[g] += 1
        if r.get("uncertain"):
            counts[L.UNCERTAIN_FLAG] += 1
        if r.get("blocked"):
            blocked += 1
        conflicts += len(r.get("contradicts") or [])
    out.append("  %d 轮 · %d 条问答 · %s" % (len(rounds), len(rows),
                                             L.format_reliability(counts)))
    total = L.reliability_total(counts)
    if total:
        out.append("  取证率 %s（行 / 已标记条数）——访谈有没有产出「行」的指标"
                   % L.fmt_pct(L.xing_ratio(counts)))
    if blocked:
        out.append("  🚧 阻塞 %d 条。**连续两次答不上来本身就是信号**——"
                   "别替 ta 补答案（反模式 #4），标成存疑条目" % blocked)
    if conflicts:
        out.append("  ⚔️  对质过 %d 次冲突" % conflicts)
    elif len(rounds) >= 4:
        out.append("  ⚠️  已到第 %d 轮仍没有一次对质。矛盾对质是 signature move"
                   "（interview-engine.md §二·⑥）——第 4 轮起该有了" % len(rounds))
    return out, len(rounds)


def skeleton_section(root):
    text = L.read_text(os.path.join(root, "SELF.md"))
    out = [h("认识层（SELF.md）")]
    if text is None:
        out.append("  — SELF.md 尚未生成（Phase 3 的产物）")
        return out
    fm, body = L.parse_frontmatter(text)
    if fm is None:
        out.append("  ❌ SELF.md 没有可解析的 frontmatter")
        return out

    items = L.skeleton_items(body)
    out.append("  核心骨架 %d 条（区间 %d-%d）" % (len(items), L.SKELETON_MIN, L.SKELETON_MAX))
    counts = L.skeleton_reliability(body)
    total = L.reliability_total(counts)
    if not total:
        out.append("  ❌ 骨架条目没有一条带信度标记")
    else:
        out.append("  骨架信度：%s" % L.format_reliability(counts))
        push, xing = L.push_ratio(counts), L.xing_ratio(counts)
        out.append("  %s 推占比 %s（上限 %s）"
                   % ("✅" if push <= L.PUSH_MAX_RATIO else "❌",
                      L.fmt_pct(push), L.fmt_pct(L.PUSH_MAX_RATIO)))
        out.append("  %s 行占比 %s（下限 %s）"
                   % ("✅" if xing >= L.XING_MIN_RATIO else "❌",
                      L.fmt_pct(xing), L.fmt_pct(L.XING_MIN_RATIO)))
        if xing < L.XING_MIN_RATIO:
            out.append("     → 低于下限 = 自述誊清稿。回 Phase 2 补取证（去要痕迹），"
                       "**不要靠加长正文刷分**")
        if push > L.PUSH_MAX_RATIO:
            out.append("     → 越过上限，档案推的是蒸馏者自己。"
                       "把「推」换成取证，或如实降级为「述」")

    whole = L.count_reliability(body)
    out.append("  全文信度：%s（frontmatter.reliability 要与此对账）"
               % L.format_reliability(whole))
    doubt = L.section(body, L.SECTION_DOUBT)
    if not doubt or not doubt.strip():
        out.append("  ❌ 存疑段为空——「没有缺口」本身就是可疑的")
    else:
        out.append("  ✅ 存疑段非空（全文 %d 条带「疑」标记）" % whole.get(L.UNCERTAIN_FLAG, 0))
    return out


def conflicts_section(root):
    text = L.read_text(os.path.join(root, "CONFLICTS.md"))
    out = [h("述行冲突（信息量最高的一段）")]
    if text is None:
        out.append("  ❌ CONFLICTS.md 不存在（Phase 3 的产物）")
        return out
    hits = L.harmony_matches(text)
    if hits:
        out.append("  ❌ 检出否认对立式调和：%s" % "、".join("「%s」" % x for x in hits[:3]))
        out.append("     → 诚实度 H 直接 0 且等级封顶 C。判据是**信息量净减少**，"
                   "不是句式——「虽然…但是…」本身合法")
        return out
    ids = L.conflict_ids(text)
    labels = L.labeled_tension_types(text)
    if ids:
        out.append("  %d 条冲突：%s" % (len(ids), "、".join(ids)))
        out.append("  分类：%s" % ("、".join(labels) or "❌ 一条都没分类"))
        if not labels:
            out.append("     → 每条须标 本质性 / 领域性 / 时间性 / 未解决")
    else:
        decl = L.declaration_sentence(text)
        if not decl:
            out.append("  ❌ 既无冲突条目，也无「未发现述行冲突」的显式声明")
            out.append("     → 沉默区分不了「没有」与「没看」")
        elif len(decl) < L.NO_CONFLICT_MIN_CHARS:
            out.append("  ❌ 「未发现冲突」声明只有 %d 字（须 ≥%d 且交代核查范围）"
                       % (len(decl), L.NO_CONFLICT_MIN_CHARS))
        else:
            out.append("  ✅ 已显式声明无冲突并交代核查范围")
    return out


def portrait_section(root):
    out = [h("分身层（Phase 4）")]
    missing = [f for f in L.PORTRAIT_FILES if not os.path.isfile(os.path.join(root, f))]
    if missing:
        out.append("  — 缺：%s" % "、".join(missing))
        return out
    axioms = L.parse_axioms(L.read_text(os.path.join(root, "PRINCIPLES.md")) or "")
    if not axioms:
        out.append("  ❌ PRINCIPLES.md 里解析不到公理表（须五列："
                   "`| **A1** | **立场** | 理由 | 代价 | src |`）")
        return out
    no_src = [a[0] for a in axioms if "SELF.md#" not in (a[4] or "")]
    out.append("  公理 %d 条（区间 3-7）" % len(axioms))
    if no_src:
        out.append("  ❌ %s 没有回指 SELF.md——两层不同源 = 两份产物互相矛盾（反模式 #16）"
                   % "、".join(no_src))
    else:
        out.append("  ✅ 每条公理都回指 SELF.md")
    return out


def seal_section(root, manifest):
    out = [h("封存")]
    if manifest is None:
        out.append("  ❌ 读不到 manifest.json")
        return out
    for fname, key in (("SELF.md", "self_sha256"), ("PRINCIPLES.md", "principles_sha256")):
        path = os.path.join(root, fname)
        if not os.path.isfile(path):
            out.append("  — %s 尚未生成" % fname)
            continue
        recorded = manifest.get(key)
        if not recorded:
            out.append("  ⚠️  %s 未封存 → 跑 self_seal.py" % fname)
        elif recorded != L.sha256_file(path):
            out.append("  ❌ %s 已过期 → 改完必须重新封存（反模式 #29）" % fname)
        else:
            out.append("  ✅ %s @ %s" % (fname, recorded[:16]))
    return out


def coverage_section(root, manifest):
    """覆盖矩阵：每个维度查了多少、说了多少、还缺什么。

    这里只**报数**，不给议程——「下一轮该问什么」是 `self_gaps.py` 的活
    （它按边际信息量排序）。分工：本脚本回答「现在到哪一步了」，
    `self_gaps.py` 回答「还差什么」。
    """
    text = L.read_text(os.path.join(root, "SELF.md"))
    fm, body = L.parse_frontmatter(text) if text else (None, None)
    dims = L.dimension_coverage(root, manifest, fm or {})
    level, reasons, stats = L.assess_coverage_level(dims, manifest, body, root)

    out = [h("覆盖矩阵（核心六维 + 扩展维度）")]
    rows = []
    for d in dims:
        if not d["path"]:
            rows.append([d["name"], "—", "—", "—", "—",
                         "未建" if not d["declared"] else "缺文件"])
            continue
        rel = d["rel"]
        rows.append([d["name"], d["slug"][:14],
                     str(d["ev_count"]), str(d["iv_count"]),
                     "%d(%d/%d/%d)" % (d["entries"], rel.get("行", 0),
                                       rel.get("述", 0), rel.get("推", 0)),
                     "%d/%d" % (d["gaps_open"], d["gaps_pending"])])
    out.append(L.render_table(
        ["维度", "文件", "证据", "访谈", "条目(行/述/推)", "缺口(可补/待事件)"],
        rows, [12, 14, 4, 4, 16, 16]))
    out.append("")
    out.append("  覆盖等级：**%s**" % level)
    for r in reasons:
        out.append("    · %s" % r)
    if stats["gaps_pending"]:
        out.append("  ℹ️  %d 条缺口标了「待事件」——只能等它真实发生，"
                   "**为它们编内容是编造不是丰富**" % stats["gaps_pending"])
    out.append("  下一轮该问什么 → 跑 `python3 scripts/self_gaps.py %s`"
               % os.path.relpath(root))
    return out


def next_actions(root, active_probes, ev_files, rounds):
    out = [h("下一步")]
    todo = []
    if active_probes < L.PROBE_MIN:
        todo.append("冻结留出探针到 %d 条以上（probe_seal.py freeze）——"
                    "它必须在访谈之前" % L.PROBE_MIN)
    if ev_files == 0:
        todo.append("归集行为痕迹（evidence_ingest.py --consent，逐份明示同意）")
    if rounds < 3:
        todo.append("继续访谈（interview_log.py append），第 1 轮先问①具体事件回溯")
    if not os.path.isfile(os.path.join(root, "SELF.md")):
        todo.append("Phase 3：合成 SELF.md + CONFLICTS.md")
    elif not os.path.isfile(os.path.join(root, "PRINCIPLES.md")):
        todo.append("Phase 4：铸造分身层四文档（公理集是 🔴 检查点，**不确认不许放大**）")
    else:
        todo.append("Phase 5：self_seal.py → self_check.py → **独立 agent** 四轴评分卡")
        todo.append("Phase 7：跑 self_gaps.py 拿深化议程——**档案永远没做完**，"
                    "只是缺口越来越小、越来越具体")
    if not todo:
        todo.append("结构齐备。跑 self_check.py 确认 12 项，再交独立 agent 评分。")
    for i, t in enumerate(todo, 1):
        out.append("  %d. %s" % (i, t))
    out.append("")
    out.append("  提醒：检查点是让用户**纠偏**的，不是扣住产出（反模式 #20）。"
               "能给默认值就给默认值。")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="self_report.py",
        description="Phase 1.8 / 2.5 检查点摘要（只读）。",
        epilog="退出码：0（报告）· 2 用法错误")
    ap.add_argument("archive", help="档案目录")
    args = ap.parse_args(argv)

    root = L.resolve_archive_dir(args.archive)
    if not os.path.isdir(root):
        return L.usage_error("目录不存在：%s" % args.archive, USAGE)

    manifest = L.load_manifest(root)
    lines = ["检查点摘要 · %s" % root]
    if manifest is None:
        lines.append("（没有 manifest.json——工作区可能还没建）")

    plines, active = probes_section(root, manifest)
    elines, ev_files = evidence_section(root, manifest)
    ilines, rounds = interview_section(root, manifest)
    lines += plines + elines + ilines
    lines += skeleton_section(root)
    lines += coverage_section(root, manifest)
    lines += conflicts_section(root)
    lines += portrait_section(root)
    lines += seal_section(root, manifest)
    lines += next_actions(root, active, ev_files, rounds)

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
