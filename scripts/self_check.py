#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 结构自检（12 项）

    python3 self_check.py <档案目录> [--json]

**结构检查 ≠ 质量评分。** 它拦的是**结构缺陷**，不是内容真伪——
一份字段齐全、标记规范的档案完全可能是编造的。过了 12 项只等于
「没有结构性缺陷，值得花一次评分」，绝不能代替评分卡。

退出码：0 = 无 FAIL（可能有 WARN）· 1 = 有 FAIL · 2 = 用法错误。

只读，不写任何东西。检查规则与 `references/self-archive-format.md` §8.1 一一对应。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _lib as L  # noqa: E402

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"

USAGE = "python3 self_check.py <档案目录> [--json]"


class Report:
    """收集检查结果。`fail` 与 `warn` 都带编号，编号是外部契约（反模式编号同源）。"""

    def __init__(self):
        self.items = []

    def add(self, level, num, title, detail=""):
        self.items.append({"level": level, "num": num,
                           "title": title, "detail": detail})

    def passed(self, num, title, detail=""):
        self.add(PASS, num, title, detail)

    def failed(self, num, title, detail=""):
        self.add(FAIL, num, title, detail)

    def warned(self, num, title, detail=""):
        self.add(WARN, num, title, detail)

    @property
    def fails(self):
        return [i for i in self.items if i["level"] == FAIL]

    @property
    def warns(self):
        return [i for i in self.items if i["level"] == WARN]


# --------------------------------------------------------------------------
# 各项检查
# --------------------------------------------------------------------------


def check_frontmatter(rep, fm, root):
    """#1 frontmatter 完整性。"""
    if fm is None:
        rep.failed(1, "frontmatter 完整性",
                   "SELF.md 没有可解析的 frontmatter（须以 `---` 开头并闭合）")
        return False
    missing = [f for f in L.REQUIRED_FIELDS if f not in fm]
    if missing:
        rep.failed(1, "frontmatter 完整性", "缺字段：%s" % "、".join(missing))
        return False
    ver = fm.get("schema_version")
    if not isinstance(ver, int) or ver > L.SUPPORTED_SCHEMA_VERSION:
        rep.failed(1, "frontmatter 完整性",
                   "schema_version=%r 高于本工具支持的 %d，"
                   "不得猜测解析，请升级工具" % (ver, L.SUPPORTED_SCHEMA_VERSION))
        return False
    rep.passed(1, "frontmatter 完整性",
               "%d 个必填字段齐备，schema_version=%d" % (len(L.REQUIRED_FIELDS), ver))
    return True


def check_dimensions(rep, root, fm, manifest):
    """#2 的维度部分：`dimensions` ↔ `dims/` ↔ `manifest.dimensions[]` 三方对账。

    单独成一个函数是因为它是**契约里最灵活的一块**——核心六维是默认透镜，
    扩展维度是这个人独有的领域。灵活性不能变成「随便写」，所以对账照做：

    | 判据 | 为什么 |
    |------|--------|
    | 每个声明的维度都有非空的 `dims/NN-slug.md` | 声明了却没有底稿 = 名义覆盖 |
    | 维度文件的 H1 标题 == 声明的维度名 | 文件与声明对不上，下游按名字找不到 |
    | 文件 `## 证据` 段 ≥1 条带信度标记 | **防止维度文件写成散文**——那是灌水 |
    | 文件 `## 还没查到` 段存在 | 说不出自己缺什么 = 多半没真查（深化循环的原料） |
    | 核心六维按契约顺序、且都在扩展维度之前 | 编号即排序，乱了读不出哪些是通用透镜 |
    | 扩展维度在 `manifest.dimensions[]` 里声明了 `why` + `opened` | 扩展维度要**有理由**，不是随手加的格子 |
    | `evidence[].dimensions` 的取值 ⊆ 声明的维度 | 指向一个不存在的维度 = 悬空归类 |

    返回 `(problems, warns)`。
    """
    problems, warns = [], []
    dims = L.declared_dimensions(fm)

    if not dims:
        problems.append("dimensions 为空——至少要声明一个已建立的维度"
                        "（核心六维里覆盖到的那些，或扩展维度）")
        return problems, warns
    bad_type = [d for d in dims if not isinstance(d, str) or not d.strip()]
    if bad_type:
        problems.append("dimensions 含非字符串项：%r" % (bad_type[:3],))
        return problems, warns
    if len(set(dims)) != len(dims):
        dupes = sorted({d for d in dims if dims.count(d) > 1})
        problems.append("dimensions 有重复项：%s" % "、".join(dupes))

    # --- 顺序：核心六维按契约顺序，且都排在扩展维度之前 -------------------
    core_names = L.core_dimension_names()
    core_order = {n: i for i, n in enumerate(core_names)}
    seen_core = [d for d in dims if d in core_order]
    idx = [core_order[d] for d in seen_core]
    if idx != sorted(idx):
        problems.append("核心维度顺序乱了：%s（契约顺序 %s）"
                        % ("、".join(seen_core), "、".join(core_names)))
    first_ext = next((i for i, d in enumerate(dims) if d not in core_order), None)
    if first_ext is not None:
        stray = [d for d in dims[first_ext:] if d in core_order]
        if stray:
            problems.append("核心维度 %s 排在了扩展维度之后——核心在前，扩展在后"
                            % "、".join(stray))

    # --- 声明 ↔ 文件 -----------------------------------------------------
    files = {}
    for dim_id, slug, path in L.dim_file_paths(root):
        text = L.read_text(path) or ""
        files[L.dim_title(text) or slug] = (dim_id, slug, path, text)

    if not files:
        problems.append("dims/ 下没有维度文件——声明了 %d 个维度却没有底稿"
                        % len(dims))

    for name in dims:
        hit = files.get(name)
        if hit is None:
            near = [k for k in files if name in k or k in name]
            hint = "（相近文件：%s）" % "、".join(near) if near else ""
            problems.append("维度「%s」没有对应的 dims/NN-<slug>.md%s" % (name, hint))
            continue
        dim_id, slug, path, text = hit
        if not (text or "").strip():
            problems.append("维度文件 dims/%s-%s.md 是空的" % (dim_id, slug))
            continue
        if L.section(text, L.DIM_SECTION_EVIDENCE) is None:
            problems.append("dims/%s-%s.md 缺「## %s」段"
                            % (dim_id, slug, L.DIM_SECTION_EVIDENCE))
        elif not L.dim_evidence_items(text):
            problems.append("dims/%s-%s.md 的「## %s」段里没有一条带信度标记"
                            "——维度文件不是散文（灌水红线）"
                            % (dim_id, slug, L.DIM_SECTION_EVIDENCE))
        if L.section(text, L.DIM_SECTION_GAPS) is None:
            problems.append("dims/%s-%s.md 缺「## %s」段——说不出自己缺什么，"
                            "多半没真查" % (dim_id, slug, L.DIM_SECTION_GAPS))

    # --- 扩展维度必须在 manifest 里声明理由 ------------------------------
    declared_ext = {}
    for d in L.manifest_dimensions(manifest):
        if not isinstance(d, dict):
            problems.append("manifest.dimensions[] 含非对象项：%r" % (d,))
            continue
        name = d.get("name")
        if d.get("kind") == "extended" and isinstance(name, str):
            declared_ext[name] = d
        fid = str(d.get("id") or "")
        if fid.isdigit() and int(fid) < L.EXT_DIM_MIN_ID and d.get("kind") == "extended":
            problems.append("扩展维度「%s」用了编号 %s——01-06 留给核心六维，"
                            "扩展维度从 %02d 起" % (name, fid, L.EXT_DIM_MIN_ID))

    ext_in_dims = [d for d in dims if d not in core_order]
    if len(ext_in_dims) > L.EXT_DIM_MAX:
        warns.append("扩展维度 %d 个（上限 %d）——多于 %d 个通常说明没提炼："
                     "领域不是越多越好，是越「只有他才会这样」越好"
                     % (len(ext_in_dims), L.EXT_DIM_MAX, L.EXT_DIM_MAX))
    for name in ext_in_dims:
        d = declared_ext.get(name)
        if d is None:
            problems.append("扩展维度「%s」没有在 manifest.dimensions[] 里声明"
                            "（须 kind: extended + why + opened）" % name)
            continue
        if not (d.get("why") or "").strip():
            problems.append("扩展维度「%s」缺 why——扩展维度要有理由，"
                            "不是随手加的格子" % name)
        if not d.get("opened"):
            problems.append("扩展维度「%s」缺 opened（发现它的日期）" % name)

    # --- 悬空归类：evidence[].dimensions 必须指向已声明的维度 --------------
    dangling = {}
    for e in (manifest or {}).get("evidence") or []:
        for d in (e.get("dimensions") or []):
            if isinstance(d, str) and d and d not in dims:
                dangling.setdefault(d, []).append(e.get("id") or "?")
    for d, ids in sorted(dangling.items()):
        problems.append("evidence[].dimensions 指向未声明的维度「%s」（%s）"
                        "——悬空归类" % (d, "、".join(ids[:3])))

    # --- 软诊断：覆盖得太少 -------------------------------------------------
    missing_core = [n for n in core_names if n not in dims]
    if len(missing_core) >= 2:
        warns.append("核心六维里有 %d 个没建（%s）——不用为了凑满而编，"
                     "但**每一个都要在存疑与缺口里交代**（空着不写 ≠ 不存在）"
                     % (len(missing_core), "、".join(missing_core)))
    if len(dims) < 3:
        warns.append("只声明了 %d 个维度——档案多半太薄，值得再取证"
                     % len(dims))
    return problems, warns


def check_cross_fields(rep, fm, root, body, manifest):
    """#2 frontmatter 交叉校验（含维度三方对账）。"""
    problems = []
    slug = fm.get("slug")
    if slug != os.path.basename(root):
        problems.append("slug=%r 与目录名 %r 不一致" % (slug, os.path.basename(root)))

    dim_problems, dim_warns = check_dimensions(rep, root, fm, manifest)
    problems += dim_problems

    rel = fm.get("reliability")
    if not isinstance(rel, dict):
        problems.append("reliability 不是行内映射 {行: n, 述: n, 推: n, 疑: n}")
    else:
        for g in list(L.RELIABILITY_GRADES) + [L.UNCERTAIN_FLAG]:
            if g not in rel:
                problems.append("reliability 缺键 %r" % g)
            elif not isinstance(rel[g], int):
                problems.append("reliability[%r]=%r 不是整数" % (g, rel[g]))

    for key in ("created", "updated"):
        v = fm.get(key)
        if not (isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-"):
            problems.append("%s=%r 不是 YYYY-MM-DD" % (key, v))

    actual_skel = len(L.skeleton_items(body))
    if fm.get("skeleton_count") != actual_skel:
        problems.append("skeleton_count=%r 与实测骨架条目数 %d 不一致"
                        % (fm.get("skeleton_count"), actual_skel))

    if isinstance(rel, dict):
        actual_rel = L.count_reliability(body)
        for g in list(L.RELIABILITY_GRADES) + [L.UNCERTAIN_FLAG]:
            if isinstance(rel.get(g), int) and rel[g] != actual_rel.get(g, 0):
                problems.append("reliability[%r]=%d 与全文实测 %d 不一致"
                                % (g, rel[g], actual_rel.get(g, 0)))

    n_dims = len(L.declared_dimensions(fm))
    if problems:
        rep.failed(2, "frontmatter 交叉校验", "；".join(problems))
    else:
        rep.passed(2, "frontmatter 交叉校验",
                   "slug/维度(%d 个)/信度/日期/骨架数 一致" % n_dims)
    for w in dim_warns:
        rep.warned(2, "frontmatter 交叉校验（软诊断）", w)


def check_skeleton_count(rep, body):
    """#3 核心骨架 3-10 条。"""
    items = L.skeleton_items(body)
    if not items:
        near = L.near_miss_headings(body, L.SECTION_SKELETON)
        hint = "（发现相近标题：%s）" % "、".join(near) if near else ""
        rep.failed(3, "核心骨架条数",
                   "取不到 `## %s` 段的顶层条目%s" % (L.SECTION_SKELETON, hint))
        return
    n = len(items)
    if n < L.SKELETON_MIN or n > L.SKELETON_MAX:
        rep.failed(3, "核心骨架条数",
                   "%d 条，超出 %d-%d 区间" % (n, L.SKELETON_MIN, L.SKELETON_MAX))
    else:
        rep.passed(3, "核心骨架条数", "%d 条" % n)


def check_skeleton_meta(rep, body):
    """#4 每条骨架条目带信度标记且带出处指针。"""
    items = L.skeleton_items(body)
    if not items:
        rep.failed(4, "骨架条目元数据", "无骨架条目可查")
        return
    no_grade = [t for t, g, _, _, _ in items if g is None]
    no_pointer = [t for t, g, _, _, p in items if g is not None and not p]
    if no_grade:
        rep.failed(4, "骨架条目元数据",
                   "%d 条无信度标记，如：%s" % (len(no_grade), no_grade[0][:40]))
        return
    if no_pointer:
        # 有等级无指针 = 无法回查。硬性要求是"带指针"，所以这是 FAIL。
        rep.failed(4, "骨架条目元数据",
                   "%d 条只有信度、没有出处指针，如：%s"
                   % (len(no_pointer), no_pointer[0][:40]))
        return
    rep.passed(4, "骨架条目元数据", "%d 条都带信度与出处指针" % len(items))


def check_ratios(rep, body):
    """#5 推 ≤ 20% 且 核心骨架 行 ≥ 30%。"""
    counts = L.skeleton_reliability(body)
    total = L.reliability_total(counts)
    if total == 0:
        rep.failed(5, "信度硬指标", "核心骨架无带信度标记的条目")
        return
    push = L.push_ratio(counts)
    xing = L.xing_ratio(counts)
    problems = []
    if push > L.PUSH_MAX_RATIO:
        problems.append("推占比 %s 超过上限 %s——越过这条线，档案推的是蒸馏者自己"
                        % (L.fmt_pct(push), L.fmt_pct(L.PUSH_MAX_RATIO)))
    if xing < L.XING_MIN_RATIO:
        problems.append("行占比 %s 低于下限 %s——低于此，档案只是「自述誊清稿」"
                        % (L.fmt_pct(xing), L.fmt_pct(L.XING_MIN_RATIO)))
    detail = "行 %s · 述 %s · 推 %s（核心骨架 %d 条）" % (
        L.fmt_pct(xing), L.fmt_pct(counts["述"] / total), L.fmt_pct(push), total)
    if problems:
        rep.failed(5, "信度硬指标", detail + "｜" + "；".join(problems))
    else:
        rep.passed(5, "信度硬指标", detail)


def check_conflicts(rep, root, self_body):
    """#6 CONFLICTS.md 存在；冲突已分类或无调和式抹平。"""
    path = os.path.join(root, "CONFLICTS.md")
    text = L.read_text(path)
    if text is None:
        rep.failed(6, "述行冲突台账", "CONFLICTS.md 不存在")
        return

    hits = L.harmony_matches(text)
    if hits:
        rep.failed(6, "述行冲突台账",
                   "检出否认对立式调和：%s —— 抹平 = 信息量净减少（铁律 2）"
                   % "、".join("「%s」" % h for h in hits[:3]))
        return

    ids = L.conflict_ids(text)
    labels = L.labeled_tension_types(text)
    if ids:
        unlabeled = []
        for m in L.CONFLICT_HEAD_RE.finditer(text):
            start = m.end()
            nxt = text.find("\n## ", start)
            chunk = text[start:nxt if nxt != -1 else len(text)]
            if not L.TENSION_LABEL_RE.search(chunk):
                unlabeled.append("C" + m.group(1))
        if unlabeled:
            rep.failed(6, "述行冲突台账",
                       "%d 条冲突未分类（%s）——每条须标 本质性/领域性/时间性/未解决"
                       % (len(unlabeled), "、".join(unlabeled[:4])))
            return
        rep.passed(6, "述行冲突台账",
                   "%d 条冲突，分类齐备：%s" % (len(ids), "、".join(labels)))
        return

    decl = L.declaration_sentence(text)
    if not decl:
        rep.failed(6, "述行冲突台账",
                   "既没有冲突条目，也没有「未发现述行冲突」的显式声明"
                   "——沉默区分不了「没有」与「没看」")
        return
    if len(decl) < L.NO_CONFLICT_MIN_CHARS:
        rep.failed(6, "述行冲突台账",
                   "「未发现冲突」声明只有 %d 字（须 ≥%d 且交代核查范围）：%s"
                   % (len(decl), L.NO_CONFLICT_MIN_CHARS, decl))
        return
    rep.passed(6, "述行冲突台账", "已显式声明无冲突并交代核查范围")


def check_doubt(rep, root, self_body):
    """#7 存疑段非空，且 疑 条目 / 维度缺口都在此出现。"""
    sec = L.section(self_body, L.SECTION_DOUBT)
    if not sec or not sec.strip():
        rep.failed(7, "存疑与缺口",
                   "`## %s` 段为空——「没有缺口」本身就是可疑的（铁律 1）"
                   % L.SECTION_DOUBT)
        return

    # 维度文件的缺口要**汇总**到 SELF.md 的存疑段。分开写 = 两处缺口表各说各的，
    # 用户读到的那份（SELF.md）漏掉了取证底稿里记着的东西。
    orphans = []
    for dim_id, slug, path in L.dim_file_paths(root):
        text = L.read_text(path) or ""
        if not L.dim_gaps(text):
            continue
        name = L.dim_title(text) or slug
        if name not in (sec or ""):
            orphans.append(name)
    if orphans:
        rep.failed(7, "存疑与缺口",
                   "%d 个维度文件有「## %s」缺口却没汇总进 SELF.md 的存疑段：%s"
                   "——缺口要出现在**用户读到的那一份**里"
                   % (len(orphans), L.DIM_SECTION_GAPS, "、".join(orphans)))
        return

    counts = L.count_reliability(self_body)
    n_doubt = counts.get(L.UNCERTAIN_FLAG, 0)
    if n_doubt == 0:
        rep.passed(7, "存疑与缺口", "段非空，无「疑」标记条目")
        return
    if L.count_words(sec) < n_doubt:
        rep.warned(7, "存疑与缺口",
                   "全文有 %d 条带「疑」标记，但存疑段只有 %d 字——"
                   "疑似有存疑条目没在这里出现"
                   % (n_doubt, L.count_words(sec)))
        return
    rep.passed(7, "存疑与缺口", "%d 条「疑」标记，段非空" % n_doubt)


def check_evidence(rep, root, manifest):
    """#8 evidence/ 非空。"""
    ev_dir = os.path.join(root, "evidence")
    files = []
    for dirpath, _, names in os.walk(ev_dir):
        for n in names:
            if not n.startswith("."):
                files.append(os.path.join(dirpath, n))
    if not files:
        rep.failed(8, "行为痕迹", "evidence/ 为空——档案必须有行为痕迹依据（铁律 1）")
        return
    listed = len((manifest or {}).get("evidence") or [])
    if listed != len(files):
        rep.warned(8, "行为痕迹",
                   "evidence/ 有 %d 个文件，manifest.evidence[] 记了 %d 条"
                   % (len(files), listed))
        return
    rep.passed(8, "行为痕迹", "%d 份素材，manifest 索引一致" % len(files))


def check_interview(rep, root):
    """#9 interview/ 非空且 LEDGER.jsonl 存在。"""
    iv_dir = os.path.join(root, "interview")
    ledger = os.path.join(iv_dir, "LEDGER.jsonl")
    rounds = []
    if os.path.isdir(iv_dir):
        rounds = [n for n in os.listdir(iv_dir)
                  if n.startswith("round-") and n.endswith(".md")]
    if not rounds:
        rep.failed(9, "访谈记录", "interview/ 下没有 round-NN.md")
        return
    if not os.path.isfile(ledger):
        rep.failed(9, "访谈记录", "interview/LEDGER.jsonl 不存在")
        return
    rows = L.load_jsonl(ledger)
    if not rows:
        rep.warned(9, "访谈记录", "LEDGER.jsonl 存在但没有有效记录")
        return
    rep.passed(9, "访谈记录", "%d 轮记录，台账 %d 条" % (len(rounds), len(rows)))


def check_probes(rep, root, manifest):
    """#10 探针 3-5 条，且 verify 通过（封存未被篡改）。"""
    probes = (manifest or {}).get("probes") or []
    if not probes:
        rep.failed(10, "留出探针", "manifest.probes[] 为空——没有探针，保真度无法验证")
        return
    if len(probes) < L.PROBE_MIN or len(probes) > L.PROBE_MAX:
        rep.warned(10, "留出探针",
                   "%d 条，超出建议区间 %d-%d" % (len(probes), L.PROBE_MIN, L.PROBE_MAX))

    bad = []
    for p in probes:
        sealed = os.path.join(root, p.get("sealed_file", ""))
        if not os.path.isfile(sealed):
            bad.append("%s 封存答案缺失" % p.get("id"))
            continue
        if L.sha256_file(sealed) != p.get("sealed_sha256"):
            bad.append("%s 封存答案已被篡改" % p.get("id"))
    if bad:
        rep.failed(10, "留出探针", "；".join(bad))
        return

    active = [p for p in probes if p.get("status") == "active"]
    contaminated = [p for p in probes if p.get("status") == "contaminated"]
    detail = "%d 条封存校验通过（有效 %d" % (len(probes), len(active))
    if contaminated:
        detail += "，被污染 %d" % len(contaminated)
    detail += "）"
    if len(active) < L.PROBE_MIN:
        rep.failed(10, "留出探针", detail + "——有效探针少于 %d 条，保真度 G 不给分"
                   % L.PROBE_MIN)
        return
    rep.passed(10, "留出探针", detail)


def check_portrait(rep, root):
    """#11 分身层每条公理都能回指 SELF.md 条目。"""
    missing_files = [f for f in L.PORTRAIT_FILES
                     if not os.path.isfile(os.path.join(root, f))]
    if missing_files:
        rep.failed(11, "分身层同源", "缺文件：%s" % "、".join(missing_files))
        return
    text = L.read_text(os.path.join(root, "PRINCIPLES.md")) or ""
    axioms = L.parse_axioms(text)
    if not axioms:
        rep.failed(11, "分身层同源",
                   "PRINCIPLES.md 里解析不到公理表——须为五列"
                   " `| **A1** | **立场** | 理由 | 代价 | src |`")
        return
    n = len(axioms)
    if n < 3 or n > 7:
        rep.warned(11, "分身层同源", "%d 条公理，超出 3-7 区间" % n)
    no_src = [a[0] for a in axioms if "SELF.md#" not in (a[4] or "")]
    if no_src:
        rep.failed(11, "分身层同源",
                   "%d 条公理没有回指 SELF.md（%s）——分身层与认识层必须同源"
                   % (len(no_src), "、".join(no_src)))
        return
    if not L.section(text, L.SECTION_TENSION):
        rep.failed(11, "分身层同源", "PRINCIPLES.md 缺「## %s」段" % L.SECTION_TENSION)
        return
    if not L.section(text, L.SECTION_CLOSURE):
        rep.failed(11, "分身层同源", "PRINCIPLES.md 缺「## %s」段" % L.SECTION_CLOSURE)
        return
    rep.passed(11, "分身层同源", "%d 条公理全部回指 SELF.md，张力与闭包边界齐备" % n)


def check_manifest(rep, root, manifest):
    """#12 manifest 契约字段 + 两个哈希已封存且未过期。"""
    if manifest is None:
        rep.failed(12, "manifest 与封存", "manifest.json 缺失或损坏")
        return
    problems = []
    for f in ("schema_version", "slug", "version", "self_sha256",
              "principles_sha256", "evidence", "probes", "changes"):
        if f not in manifest:
            problems.append("缺字段 %s" % f)

    for key, fname in (("self_sha256", "SELF.md"),
                       ("principles_sha256", "PRINCIPLES.md")):
        path = os.path.join(root, fname)
        if not os.path.isfile(path):
            problems.append("%s 不存在" % fname)
            continue
        recorded = manifest.get(key)
        if not recorded:
            problems.append("%s 未封存（跑 self_seal.py）" % key)
        elif recorded != L.sha256_file(path):
            problems.append("%s 已过期——%s 改动后没有重新封存" % (key, fname))

    if problems:
        rep.failed(12, "manifest 与封存", "；".join(problems))
        return
    rep.passed(12, "manifest 与封存", "契约字段齐备，两个哈希未过期")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def run_checks(root):
    rep = Report()
    self_path = os.path.join(root, "SELF.md")
    text = L.read_text(self_path)
    if text is None:
        rep.failed(1, "SELF.md", "读不到 SELF.md")
        return rep
    fm, body = L.parse_frontmatter(text)
    manifest = L.load_manifest(root)

    if check_frontmatter(rep, fm, root):
        check_cross_fields(rep, fm, root, body, manifest)
    else:
        rep.failed(2, "frontmatter 交叉校验", "前置检查未过，跳过")

    check_skeleton_count(rep, body)
    check_skeleton_meta(rep, body)
    check_ratios(rep, body)
    check_conflicts(rep, root, body)
    check_doubt(rep, root, body)
    check_evidence(rep, root, manifest)
    check_interview(rep, root)
    check_probes(rep, root, manifest)
    check_portrait(rep, root)
    check_manifest(rep, root, manifest)
    return rep


def render(rep, root):
    out = []
    out.append("结构自检 · %s" % root)
    out.append("")
    for item in sorted(rep.items, key=lambda i: i["num"]):
        mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}[item["level"]]
        out.append("%s %2d. %s" % (mark, item["num"], item["title"]))
        if item["detail"]:
            out.append("       %s" % item["detail"])
    out.append("")
    out.append("=" * 62)
    out.append("结构检查通过 ≠ 质量合格。它拦的是**结构缺陷**，不是内容真伪——")
    out.append("一份字段齐全、标记规范的档案完全可能是编造的。过了只等于")
    out.append("「没有结构性缺陷，值得花一次评分」，绝不能代替评分卡。")
    out.append("=" * 62)
    out.append("FAIL %d · WARN %d" % (len(rep.fails), len(rep.warns)))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="self_check.py",
        description="BuildSelf 结构自检（12 项）。只读，不写任何东西。",
        epilog="退出码：0 无 FAIL · 1 有 FAIL · 2 用法错误")
    ap.add_argument("archive", help="档案目录（含 manifest.json）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    root = L.resolve_archive_dir(args.archive)
    if not os.path.isdir(root):
        return L.usage_error("目录不存在：%s" % args.archive, USAGE)

    rep = run_checks(root)
    if args.json:
        import json
        print(json.dumps({
            "archive": root,
            "items": rep.items,
            "fails": len(rep.fails),
            "warns": len(rep.warns),
        }, ensure_ascii=False, indent=2))
    else:
        print(render(rep, root))
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
