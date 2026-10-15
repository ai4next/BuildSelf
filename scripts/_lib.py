#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BuildSelf · 共享工具库（唯一事实源 / single source of truth）

本文件是所有 `scripts/` 下工具共用的底层实现：契约常量（字段、维度、信度枚举、
痕迹类型）、frontmatter 子集解析、信度统计、述行冲突检测、终端表格渲染、哈希。

设计约束（改动前必读）：

  1. **契约的权威定义在 `references/self-archive-format.md`**，本文件只是它的
     可执行形式。改字段名 / 枚举 / 目录名 / 检查规则 → 必须同步改契约文档，
     两边不得漂移。
  2. 本文件只做**机械**工作：解析、统计、渲染、哈希。
     语义判断（两条主张是不是在回答同一个问题、某条算不算真冲突）
     **不在这里**，也不在任何脚本里——那是 agent 的活（反模式 #27）。
  3. **纯标准库**。skill 必须自包含，不引入第三方依赖（Python 标准库无 yaml，
     所以 frontmatter 只支持契约限定的子集，见 `parse_frontmatter`）。
  4. 本文件是**库**，不是可执行脚本——没有 `main()`，不打印任何东西。

被谁用：evidence_ingest / probe_seal / interview_log / self_seal /
        self_check / self_report
"""

import hashlib
import json
import os
import re
import sys
import unicodedata

# --------------------------------------------------------------------------
# 契约常量（与 references/self-archive-format.md 一一对应）
# --------------------------------------------------------------------------

#: 契约版本。消费者遇到高于此值的档案必须停止并提示升级，不得猜测解析。
#:
#: v2 变更：`dimensions` 从「固定六维」改成「**已建立的维度**」——核心六维是默认
#: 透镜，**覆盖到才建文件**；此外允许**扩展维度**（这个人才有的领域）。
#: 同时新增 `dims/` 目录与 `manifest.dimensions[]`。字段语义变了，故 +1。
SUPPORTED_SCHEMA_VERSION = 2

#: `SELF.md` frontmatter 必填字段（契约 §2.2）。
REQUIRED_FIELDS = [
    "schema_version", "slug", "title", "created", "updated", "version",
    "dimensions", "skeleton_count", "reliability", "evidence_total",
    "interview_rounds", "probes_total", "probes_valid", "gaps",
]

#: 维度文件目录。每个**已建立**的维度一个文件（契约 §2.5）。
#: 核心六维与扩展维度**同构**——都只是 `dims/` 下的一个文件，区别只在编号与来源。
DIMS_DIR = "dims"

#: 核心六维：(编号, 维度名, 文件名)。与 references/self-schema.md 一致。
#:
#: **它们是默认透镜，不是必须填满的格子。** 没覆盖到的核心维度**不建文件**，
#: 但要进 `存疑与缺口`——空着不写 ≠ 不存在，那是「没看」，不是「没有」（反模式 #4 的同族）。
CORE_DIMENSIONS = [
    ("01", "身份", "01-identity.md"),
    ("02", "决策", "02-decisions.md"),
    ("03", "表达", "03-expression.md"),
    ("04", "关系", "04-relationships.md"),
    ("05", "价值", "05-values.md"),
    ("06", "时间线", "06-timeline.md"),
]

#: 扩展维度的起始编号。01-06 留给核心六维，扩展维度从 07 起——**编号即排序**，
#: 阅读时一眼能看出哪些是通用透镜、哪些是这个人独有的。
EXT_DIM_MIN_ID = 7

#: 扩展维度条数上限。多于 5 个通常说明没提炼——**领域不是越多越好，
#: 是越「只有他才会这样」越好**（见 `deepening-engine.md` §三）。
EXT_DIM_MAX = 5

#: 维度文件名的文法：`NN-<slug>.md`。
DIM_FILE_RE = re.compile(r"^(\d{2})-([a-z0-9][a-z0-9-]*)\.md$")

#: 维度文件必须有的两段（契约 §2.5）。
#:
#: `## 证据` 段是取证底稿（≥1 条带信度标记），`## 还没查到` 段是**该维度的缺口**。
#: 后者是硬性的——它是**深化循环的原料**（`deepening-engine.md`）。
#: 一个说不出自己缺什么的维度文件，多半是把叙事当成了证据。
DIM_SECTION_EVIDENCE = "证据"
DIM_SECTION_GAPS = "还没查到"

#: 缺口的两种性质（写在缺口条目末尾的括号里）：
#:
#:   `（可补）`   —— 去取证 / 去问就能补上。**深化循环处理这一类。**
#:   `（待事件）` —— 只能等它真实发生（如「他面对背叛的反应」）。
#:                  **不是懒，是诚实**：档案不该为这种缺口编内容。
#:                  **深化循环遇到全是「待事件」的维度，就该收手。**
GAP_OPEN = "可补"
GAP_PENDING = "待事件"
GAP_KIND_RE = re.compile(r"[（(]\s*(%s|%s)\s*[）)]" % (GAP_OPEN, GAP_PENDING))

#: 覆盖等级（从低到高）。**是标签，不是分数**——理由见 `self-scorecard.md` §零。
COVERAGE_LEVELS = ("稀疏", "标准", "丰富", "饱和")

#: 判「丰富」的门槛（`self_gaps.py` 与评分 agent 共用，避免两处各有一套数）。
COVERAGE_RICH_MIN_ENTRIES = 3      # 每个已建维度至少这么多条带信度的条目
COVERAGE_RICH_MIN_EVIDENCE = 6     # 痕迹份数
COVERAGE_RICH_MIN_EVIDENCE_KINDS = 4   # 痕迹类型数
COVERAGE_RICH_MIN_MODELS = 5       # 心智模型条数

#: 默认行为痕迹类型，与 `evidence/` 子目录名一一对应（契约 §一）。
#:
#: **这是默认值，不是白名单。** 每个人的痕迹长得不一样——程序员给 git log、
#: 父母给家庭账本、学生给成绩单。`evidence_ingest.py --type` 接受任意合法 slug，
#: 自定义类型同样写进 `manifest.evidence[].type`（见 `valid_evidence_type`）。
DEFAULT_EVIDENCE_TYPES = (
    "chat", "calendar", "transactions", "decisions", "notes", "others", "other",
)

#: 痕迹类型的文法：小写字母开头，允许小写字母 / 数字 / 连字符。
#: 刻意**只允许 ASCII**——它要当目录名，中文目录名在不同文件系统上行为不一。
EVIDENCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")

#: **证据距离轴**三级：行（行为痕迹）/ 述（本人陈述）/ 推（推断）。
#: 三者互斥且穷尽——`行 + 述 + 推 = 条目总数`。
RELIABILITY_GRADES = ("行", "述", "推")

#: **正交标记**，不是第四个等级。表示本人不确定 / 前后矛盾 / 与痕迹冲突。
#: 它是 `行/述/推` 的子集，**不计入分母**。
UNCERTAIN_FLAG = "疑"

#: `推` 占比上限。越过这条线，档案推的是蒸馏者自己，不是这个人。
PUSH_MAX_RATIO = 0.20

#: 核心骨架里 `行` 占比下限。低于此，档案只是"自述誊清稿"。
XING_MIN_RATIO = 0.30

#: 核心骨架条目数区间。少于 3 没提炼，多于 10 没取舍。
SKELETON_MIN, SKELETON_MAX = 3, 10

#: 留出探针条数区间（契约 §六）。
PROBE_MIN, PROBE_MAX = 3, 5

#: 四轴（名称, 满分）。**不合并、不相加、不互相补偿**。
SCORE_AXES = (
    ("保真度", 30),
    ("诚实度", 25),
    ("可执行性", 20),
    ("溯源", 25),
)
SCORE_TOTAL = 100

#: 等级线（从高到低）。
GRADE_CUTOFFS = (("A", 85), ("B", 70), ("C", 55))

#: `SELF.md` 正文段标题。`section()` **严格匹配**，不做模糊。
SECTION_SUMMARY = "一句话"
SECTION_SKELETON = "核心骨架"
SECTION_MODELS = "心智模型"
SECTION_VALUES = "价值排序"
SECTION_VOICE = "表达特征"
SECTION_CONFLICT = "冲突与张力"
SECTION_DOUBT = "存疑与缺口"
SECTION_CHANGES = "变更记录"

#: 分身层四文档。`PRINCIPLES.md` 是根，其余三份从它派生。
PORTRAIT_FILES = ("PRINCIPLES.md", "DECISIONS.md", "VOICE.md", "BOUNDARIES.md")
SECTION_AXIOMS = "公理"
SECTION_TENSION = "内在张力"
SECTION_CLOSURE = "闭包边界"
SECTION_DERIVE = "推演预览"

#: 「未发现述行冲突」声明的最小长度。一行「未发现冲突。」大概率是漏读而非真的没有。
NO_CONFLICT_MIN_CHARS = 20

#: 显式空值记号。用于区分「未回填」（null）与「判定为零」（0）——
#: 这是本 skill 诚实哲学在数据层的体现（不知道就说不知道）。
NULL_TOKENS = ("null", "none", "nil", "~", "")

# --------------------------------------------------------------------------
# 正则
# --------------------------------------------------------------------------

#: 任意层级的 Markdown 标题：`## 核心骨架`。用于给 `section()` 的 miss 定位真因。
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

#: Markdown 表格行与分隔行。
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")

#: 行尾的元数据括号：`…（行 · evidence/x.md）`。
TRAILING_META_RE = re.compile(
    r"[（(【\[]([^（）()【】\[\]]*)[）)】\]]([。．.；;，,]*)\s*$")

#: 信度标记的**完整文法**（契约 §2.3）：
#:
#:     （<等级>[ · 疑][ · <出处指针或推导链>]）
#:
#: 分隔符**只认 `·`（U+00B7）**。这是刻意的严格：`（行、列都对齐）` 是正文，
#: 不该被当成信度标记；`（行为模式）` 里 `行` 后面跟的是 `为` 而不是 `·`，
#: 整段按正文处理。宁可漏认，不可误吃正文。
RELIABILITY_META_RE = re.compile(
    r"^([行述推])(?:\s*·\s*(疑))?(?:\s*·\s*(.+))?$")

#: 否认对立式调和——**抹平的实质**（铁律 2 要拦的东西）。
#:
#: 只收**否认对立**的断言，**不收裸的「虽然…但是」**：转折句式是描述张力的
#: 合法形式，用它写一条已分类的张力恰恰是正确写法。把句式当罪证，等于惩罚
#: 正确输出，并诱导作者删掉真实矛盾——那正是铁律 2 要防的事。
HARMONY_RE = re.compile(
    r"其实(?:两者|二者)?(?:是)?(?:互补|一致|统一|相通)的?"
    r"|(?:两者|二者|二者之间|其实)并?不矛盾"
    r"|本质(?:上)?(?:是)?统一(?:的)?"
    r"|并不冲突"
    r"|殊途同归"
    r"|说到底是(?:同一|一)回事"
)

#: 转折句式。**它本身不是和稀泥**，只是抹平的高发句式。
#: 仅当冲突段**没有任何分类标注**时，才作为软诊断提示复核。
TURN_RE = re.compile(r"虽然[^。；！？\n]{0,40}但是")

#: 显式声明「查过了，确实没有述行冲突」。与 HARMONY_RE 是**相反**的两件事：
#:   HARMONY_RE 惩罚「有冲突却抹平」；NO_CONFLICT_RE 承认「没有就是没有」。
#: 没有它，一份内部自洽的档案会被硬性要求编造一条冲突出来——直接违反铁律 1。
NO_CONFLICT_RE = re.compile(
    r"未(?:发现|检出|见到|观察到)(?:任何)?(?:述行冲突|冲突|前后不一致|自相矛盾|不一致之处)"
    r"|无述行冲突"
    r"|不存在冲突"
    r"|冲突状态\s*[:：]\s*无"
)

#: 冲突分类标签。三种「张力」须与 张力/冲突 连用，才算"做了分类"而不是"提到了这个词"；
#: `未解决` **单独成立**——契约里它的取值就是「未解决」，后面没有「张力」二字。
#: （早期版本要求 `未解决` 也带名词，导致合法分类被判成未分类——这是契约与实现的漂移。）
TENSION_LABEL_RE = re.compile(
    r"(?:本质性|领域性|时间性)\s*(?:的)?\s*(?:张力|冲突)"
    r"|未解决")

#: 引号包裹的片段。里面的字是**被引用的**，不是作者的主张——
#: 判定和稀泥时必须先剥掉，否则「本节刻意未使用『其实两者并不冲突』这类表述」
#: 会被当成和稀泥本身（惩罚正确输出）。
QUOTED_SPAN_RE = re.compile(
    r"「[^」]*」|『[^』]*』|“[^”]*”|\"[^\"]*\"|‘[^’]*’|《[^》]*》")

#: 「提及而非主张」的前置否定词。命中片段前 16 字内出现这些词，
#: 说明作者在**讨论**这种写法（禁止/避免/不使用），而不是在用它。
MENTION_GUARD_RE = re.compile(
    r"禁止|不许|不要|不得|避免|未使用|不使用|没有使用|刻意未|不采用|拒用|警惕")

#: 出处指针：痕迹路径 / 访谈轮次 / 探针 / 档案内文档锚点 / 骨架条目引用。
#:
#: 刻意收紧——`#3 与 #7` 这类条目引用、`evidence/...` 这类路径才算指针。
#: 松到「出现字母数字就算」的话，检查 #4 就形同虚设了。
SOURCE_POINTER_RE = re.compile(
    r"(?:evidence|interview|probes)/[\w./一-鿿-]+"
    r"|(?:SELF|CONFLICTS|PRINCIPLES|DECISIONS|VOICE|BOUNDARIES|README)\.md#\S+"
    r"|#[0-9]+(?:\s*(?:与|和|,|、)\s*#[0-9]+)*"
)

#: 核心骨架的顶层条目符号。`+` 与 `1)` / `1、` 都是合法 Markdown 列表。
#: 顿号分支用 `\s*`：中文序号列表最常见的形式是「1、内容」**不带空格**。
SKELETON_ITEM_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+|\d+、\s*)(.+?)\s*$")

#: 公理表的一行：`| **A1** | **立场** | 理由 | 代价 | src |`
AXIOM_ROW_RE = re.compile(
    r"^\s*\|\s*\*\*(A\d+)\*\*\s*\|\s*\*\*(.+?)\*\*\s*\|([^|]*)\|([^|]*)\|([^|]*)\|")

#: 冲突条目标题：`## C1 · <概括>`
CONFLICT_HEAD_RE = re.compile(r"^#{2,3}\s*C(\d+)\s*[·:：]?\s*(.*)$", re.M)

# --------------------------------------------------------------------------
# frontmatter 子集解析（契约 §2.1）
# --------------------------------------------------------------------------


def strip_quotes(s):
    """去掉首尾成对的引号。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def is_null(value):
    """判断一个值是否表示「未回填」。

    兼容三种来源：解析后的 `None`、旧档案里写成字符串的 `"null"`、
    以及 frontmatter 里留空的值。数值 `0` **不是** null——零是判定结果。
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in NULL_TOKENS:
        return True
    return False


def parse_scalar(val):
    """解析一个 YAML 子集标量：行内列表 / 行内映射 / 普通标量。

    普通标量会做类型收敛：带引号的保持字符串，纯整数转 int，
    null 记号转 None。这样 `version: 3` 可直接参与比较，
    `gaps: null` 可被 `is_null()` 识别。
    """
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(x) for x in re.split(r"[,，]", inner)]
    if val.startswith("{") and val.endswith("}"):
        out = {}
        for part in re.split(r"[,，]", val[1:-1]):
            if ":" in part:
                k, _, v = part.partition(":")
                out[strip_quotes(k)] = parse_scalar(v)
        return out
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]          # 显式引号 → 恒为字符串
    if val.lower() in NULL_TOKENS:
        return None
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val


def parse_frontmatter(text):
    """解析契约限定的 YAML 子集，返回 `(frontmatter_dict, body)`。

    解析失败（无 frontmatter / 未闭合）返回 `(None, 原文)`。

    支持：`key: 标量` / `key: [行内列表]` / `key: {行内映射}` / `key:` + `- 项` 块列表。
    不支持（契约禁止）：嵌套多行映射、多行字符串、锚点别名、注释。
    """
    if text is None:
        return None, text
    text = text.lstrip("﻿")          # 容忍 BOM
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text

    data, current_key = {}, None
    pending_empty = set()
    for line in lines[1:end]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_key:
            data.setdefault(current_key, [])
            if not isinstance(data[current_key], list):
                data[current_key] = []
            data[current_key].append(parse_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = strip_quotes(key)
        if val.strip() == "":
            current_key = key
            pending_empty.add(key)
            data[key] = None
            continue
        current_key = key
        data[key] = parse_scalar(val)

    for key in pending_empty:
        if data.get(key) is None:
            data[key] = []                # 空值且无块列表项 → 空列表
    body = "\n".join(lines[end + 1:])
    return data, body


# --------------------------------------------------------------------------
# 正文段定位
# --------------------------------------------------------------------------


def heading_matches(text, title):
    """标题是否命中 `title`。

    命中三种形态：

        `## 核心骨架`              —— 逐字相同
        `## 内在张力（至少 1 对）`   —— 后接**括号补注**（契约模板就是这么写的）
        `## 存疑与缺口 `            —— 后接空白

    刻意只放行「括号 / 空白后缀」，**不做任意前缀匹配**——
    `## 内在张力测试` 这种近亲不算命中，否则错标题会被静默接受。
    """
    text = (text or "").strip()
    if text == title:
        return True
    for sep in ("（", "(", " ", "\t"):
        if text.startswith(title + sep):
            return True
    return False


def section(body, *titles):
    """取 `## <title>` 段的正文；标题匹配规则见 `heading_matches`。

    多个 `titles` 时按顺序返回第一个命中的（兼容同义标题）。
    段的范围到**下一个同级或更高级标题**为止。
    """
    if not body:
        return None
    lines = body.splitlines()
    heads = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    for title in titles:
        for idx, (i, level, text) in enumerate(heads):
            if not heading_matches(text, title):
                continue
            start = i + 1
            end = len(lines)
            for j, lv, _ in heads[idx + 1:]:
                if lv <= level:
                    end = j
                    break
            return "\n".join(lines[start:end])
    return None


def near_miss_headings(body, title):
    """返回与 `title` 相近（包含关系）的标题，用于定位 `section()` 未命中的真因。"""
    out = []
    for m in HEADING_RE.finditer(body or ""):
        text = m.group(2).strip()
        if text != title and (title in text or text in title):
            out.append(text)
    return out


def count_words(text):
    """粗略字数：CJK 按字计，拉丁按词计。用于压缩比与素材体量。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + latin


# --------------------------------------------------------------------------
# 信度标记的解析与统计（契约 §2.3）
# --------------------------------------------------------------------------


def split_trailing_meta(text):
    """拆出行尾的信度元数据。

    返回 `(正文, 等级或 None, 是否带疑标记, 备注或 None)`。

        `主张……（行 · evidence/chat/x.md）`   → (…, "行", False, "evidence/chat/x.md")
        `主张……（述）`                        → (…, "述", False, None)
        `主张……（述 · 疑）`                    → (…, "述", True,  None)
        `主张……（推 · 由 #3 与 #7 推出）`       → (…, "推", False, "由 #3 与 #7 推出")
        `主张……（行为模式）`                    → (原文, None, False, None)   ← 正文，不误吃

    只认**行尾**的括号。括号内容不匹配 `RELIABILITY_META_RE` 时整段按正文处理。
    """
    text = (text or "").strip()
    m = TRAILING_META_RE.search(text)
    if not m:
        return text, None, False, None
    inner = m.group(1).strip()
    mm = RELIABILITY_META_RE.match(inner)
    if not mm:
        return text, None, False, None
    grade, flag, note = mm.group(1), mm.group(2), mm.group(3)
    return text[:m.start()].strip(), grade, bool(flag), (note or "").strip() or None


def has_source_pointer(text):
    """判断一行文本里有没有可回查的出处指针。

    注意：这是**软诊断**用的启发式——有指针不等于指针是真的。
    真伪核对只能由拿到 `evidence/` 的 agent 做（Phase 5 溯源抽查）。
    """
    return bool(SOURCE_POINTER_RE.search(text or ""))


def count_reliability(text):
    """统计全文**行尾带信度标记**的条目，返回 `{行: n, 述: n, 推: n, 疑: n}`。

    `疑` 是**子集**（带疑标记的条目数），不是第四个分区——
    所以 `行 + 述 + 推` 才是条目总数，`疑` 不再计入。
    """
    counts = {g: 0 for g in RELIABILITY_GRADES}
    counts[UNCERTAIN_FLAG] = 0
    for line in (text or "").splitlines():
        _, grade, uncertain, _ = split_trailing_meta(line)
        if grade is None:
            continue
        counts[grade] += 1
        if uncertain:
            counts[UNCERTAIN_FLAG] += 1
    return counts


def reliability_total(counts):
    """条目总数 = 行 + 述 + 推（`疑` 不计入分母）。"""
    return sum(counts.get(g, 0) for g in RELIABILITY_GRADES)


def push_ratio(counts):
    """`推` 占比。分母为 0 时返回 0.0（无条目 ≠ 推断超标）。"""
    total = reliability_total(counts)
    return (counts.get("推", 0) / total) if total else 0.0


def xing_ratio(counts):
    """`行` 占比。分母为 0 时返回 0.0。"""
    total = reliability_total(counts)
    return (counts.get("行", 0) / total) if total else 0.0


def format_reliability(counts):
    """渲染信度分布：`行 12 · 述 9 · 推 3 · 疑 4`。"""
    parts = ["%s %d" % (g, counts.get(g, 0)) for g in RELIABILITY_GRADES]
    parts.append("%s %d" % (UNCERTAIN_FLAG, counts.get(UNCERTAIN_FLAG, 0)))
    return " · ".join(parts)


def skeleton_items(body):
    """取「## 核心骨架」段的顶层条目。

    返回 `[(去元数据文本, 等级或 None, 是否带疑, 备注, 是否有出处指针), ...]`。

    只取**顶层**条目：缩进的子条目是对上一条的展开，不是并列的骨架条目，
    算进来会让骨架数量虚高（进而撞上 >10 的上限）。
    """
    sec = section(body, SECTION_SKELETON)
    if sec is None:
        return []
    out = []
    for line in sec.splitlines():
        m = SKELETON_ITEM_RE.match(line)
        if not m:
            continue
        raw = m.group(1)
        clean, grade, uncertain, note = split_trailing_meta(raw)
        out.append((clean, grade, uncertain, note, has_source_pointer(raw)))
    return out


def skeleton_reliability(body):
    """核心骨架子集的信度分布。**硬指标（行≥30% / 推≤20%）在这上面算。**"""
    counts = {g: 0 for g in RELIABILITY_GRADES}
    counts[UNCERTAIN_FLAG] = 0
    for _, grade, uncertain, _, _ in skeleton_items(body):
        if grade is None:
            continue
        counts[grade] += 1
        if uncertain:
            counts[UNCERTAIN_FLAG] += 1
    return counts


# --------------------------------------------------------------------------
# 维度体系：核心六维 + 扩展维度（契约 §2.5）
#
# 核心六维是**默认透镜**，扩展维度是**这个人独有的领域**。两者在磁盘上同构——
# 都是 `dims/NN-slug.md`。区分只在编号（01-06 vs ≥07）与来源（通用 vs 他才有）。
# --------------------------------------------------------------------------


def core_dimension_names():
    """核心六维的维度名，按契约顺序。"""
    return [d[1] for d in CORE_DIMENSIONS]


def is_core_dimension(name):
    """`name` 是不是核心六维之一。"""
    return name in core_dimension_names()


def valid_evidence_type(s):
    """痕迹类型名是否合法（可作目录名）。

    **不是白名单**——`DEFAULT_EVIDENCE_TYPES` 只是默认值。每个人的痕迹长得
    不一样，`--type gitlog` 与 `--type 家庭账本` 里的前者合法、后者不合法
    （ASCII-only，见 `EVIDENCE_TYPE_RE`）。
    """
    return bool(isinstance(s, str) and EVIDENCE_TYPE_RE.match(s))


def dim_dir(root):
    """档案的维度目录路径（不保证存在）。"""
    return os.path.join(root, DIMS_DIR)


def dim_file_paths(root):
    """列出 `dims/` 下的维度文件。

    返回 `[(编号, slug, 绝对路径), ...]`，按编号排序。**只认
    `NN-<slug>.md` 这个形状**——不合形状的文件不在这里返回，由检查项报出来。
    """
    d = dim_dir(root)
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        m = DIM_FILE_RE.match(name)
        if m:
            out.append((m.group(1), m.group(2), os.path.join(d, name)))
    return out


def dim_title(text):
    """取维度文件的 H1 标题（`# 金钱` → `金钱`）；没有则返回 `None`。"""
    for line in (text or "").splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def dim_evidence_items(text):
    """取维度文件 `## 证据` 段里**带信度标记**的条目。

    返回 `[(去元数据文本, 等级, 是否带疑, 备注), ...]`。段落缺失返回 `[]`。

    只认带标记的行——**这是「维度文件不是散文」的机械保证**。
    一段读着很顺、却没有一条可回查的叙述，正是深化循环要清掉的东西。
    """
    sec = section(text, DIM_SECTION_EVIDENCE)
    if sec is None:
        return []
    out = []
    for line in sec.splitlines():
        clean, grade, uncertain, note = split_trailing_meta(line)
        if grade is not None and clean:
            out.append((clean, grade, uncertain, note))
    return out


def parse_table(text):
    """解析 Markdown 表格，返回**数据行**（表头与分隔行已剔除）。

    返回 `[[cell, cell, ...], ...]`。判定规则：分隔行（`|---|---|`）的**上一行**
    是表头，一并丢掉。没有分隔行的表格按原样返回——宁可多留一行，
    也不要因为格式不规范就把整张表吃掉。

    契约里的缺口段两种形态都有（`PRINCIPLES.md#信息缺口` 是表格，
    `SELF.md#存疑与缺口` 是列表），所以需要一个统一的读法。
    """
    rows, sep_at = [], None
    for line in (text or "").splitlines():
        if TABLE_SEP_RE.match(line):
            sep_at = len(rows)
            continue
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        rows.append(cells)
    if sep_at is not None and sep_at > 0:
        del rows[sep_at - 1]          # 丢掉表头
    return rows


def list_or_table_items(sec):
    """把一段正文读成条目列表：**列表项**取其文本，**表格**取每行首列。

    两种形态都跳过空行与纯标题行。表格的**数据行**才收（表头由
    `parse_table` 剔除）。这是缺口段、信息缺口段的统一读法——
    作者用列表还是用表格是风格问题，不该影响脚本读不读得到。
    """
    if not sec:
        return []
    out = []
    if any(TABLE_SEP_RE.match(ln) for ln in sec.splitlines()):
        for cells in parse_table(sec):
            first = (cells[0] if cells else "").strip()
            if first:
                out.append(first)
        return out
    for line in sec.splitlines():
        raw = line.strip()
        if not raw or HEADING_RE.match(raw):
            continue
        item = SKELETON_ITEM_RE.match(raw)
        raw = (item.group(1) if item else raw).strip()
        if raw:
            out.append(raw)
    return out


def dim_gaps(text):
    """取维度文件 `## 还没查到` 段的缺口条目。

    返回 `[(缺口文本, 性质或 None), ...]`，性质 ∈ `可补` / `待事件` / `None`
    （没标性质的记 `None`——**不替它猜**，由检查项提示补标）。

    **段缺失返回 `[]`**，与「段存在但为空」在检查项里是两种不同的失败，
    别在这里合并。列表与表格两种写法都认（`list_or_table_items`）。
    """
    sec = section(text, DIM_SECTION_GAPS)
    if sec is None:
        return []
    out = []
    for raw in list_or_table_items(sec):
        m = GAP_KIND_RE.search(raw)
        out.append((GAP_KIND_RE.sub("", raw).strip(), m.group(1) if m else None))
    return out


def manifest_dimensions(manifest):
    """读 `manifest.dimensions[]`，返回 `[{id, name, kind, file, why, opened}, ...]`。

    形状不对的条目**原样返回**（缺键就是缺键），由检查项报出来——
    脚本不替作者补默认值。
    """
    dims = (manifest or {}).get("dimensions")
    return dims if isinstance(dims, list) else []


def declared_dimensions(fm):
    """读 `SELF.md` frontmatter 的 `dimensions`，返回维度名列表。"""
    dims = (fm or {}).get("dimensions")
    return dims if isinstance(dims, list) else []


def evidence_dimension_counts(manifest):
    """按维度统计痕迹份数：`{维度名: 份数}`。

    `dimensions` 为 `null`（未回填）的**不计入任何维度**——那不是「这个维度没有
    痕迹」，是「还没判」，两件事不能混（契约 §五）。
    """
    counts = {}
    for e in (manifest or {}).get("evidence") or []:
        for d in (e.get("dimensions") or []):
            if isinstance(d, str) and d:
                counts[d] = counts.get(d, 0) + 1
    return counts


def ledger_dimension_counts(rows):
    """按维度统计访谈条数：`{维度名: 条数}`。"""
    counts = {}
    for r in rows or []:
        for d in (r.get("dimensions") or []):
            if isinstance(d, str) and d:
                counts[d] = counts.get(d, 0) + 1
    return counts


def dimension_coverage(root, manifest, fm):
    """汇总每个维度的覆盖情况——**覆盖矩阵**的机械形式。

    返回 `[{name, kind, id, slug, path, entries, rel, gaps, gaps_open,
    gaps_pending, ev_count, iv_count, declared, why}, ...]`。

    **未建的核心维度也在列表里**（`path=None`、`declared=False`）——
    「没建」和「建了但空」是两种不同的失败，混成一种就看不出该先补哪个。

    只做数数。判断「这个维度够不够厚」是 `assess_coverage_level` 与
    评分 agent 的事（反模式 #27）。
    """
    file_by_name = {}
    for dim_id, slug, path in dim_file_paths(root):
        text = read_text(path) or ""
        file_by_name[dim_title(text) or slug] = (dim_id, slug, path, text)

    ext_decl = {}
    for d in manifest_dimensions(manifest):
        if isinstance(d, dict) and isinstance(d.get("name"), str):
            ext_decl[d["name"]] = d

    ev_counts = evidence_dimension_counts(manifest)
    iv_counts = ledger_dimension_counts(
        load_jsonl(os.path.join(root, "interview", "LEDGER.jsonl")))

    declared = declared_dimensions(fm)
    # 核心六维按契约顺序在前，然后是扩展维度（顺序即排序，契约 §2.2）
    names = core_dimension_names() + [n for n in declared if not is_core_dimension(n)]

    out = []
    for name in names:
        rec = {
            "name": name,
            "kind": "core" if is_core_dimension(name) else "extended",
            "id": None, "slug": None, "path": None,
            "entries": 0, "rel": {}, "gaps": [], "gaps_open": 0, "gaps_pending": 0,
            "ev_count": ev_counts.get(name, 0),
            "iv_count": iv_counts.get(name, 0),
            "declared": name in declared,
            "why": (ext_decl.get(name) or {}).get("why"),
        }
        hit = file_by_name.get(name)
        if hit:
            dim_id, slug, path, text = hit
            items = dim_evidence_items(text)
            rel = {g: 0 for g in RELIABILITY_GRADES}
            for _, g, _, _ in items:
                rel[g] = rel.get(g, 0) + 1
            rec.update({"id": dim_id, "slug": slug, "path": path,
                        "entries": len(items), "rel": rel})
            for gap, kind in dim_gaps(text):
                rec["gaps"].append({"text": gap, "kind": kind})
                if kind == GAP_OPEN:
                    rec["gaps_open"] += 1
                elif kind == GAP_PENDING:
                    rec["gaps_pending"] += 1
        out.append(rec)
    return out


def assess_coverage_level(dims, manifest, self_body, root):
    """算覆盖等级——**是标签，不是分数**（理由见 `self-scorecard.md` §零）。

    返回 `(等级, 依据列表, 统计字典)`，等级 ∈ `COVERAGE_LEVELS`。

    判据（与下面的常量同源，改动请改常量而不是散落的数字）：

    | 等级 | 判据 |
    |------|------|
    | 稀疏 | 核心六维没建齐，或痕迹 < 3 份 |
    | 标准 | 核心六维都建了，且痕迹 ≥ 3 份 |
    | 丰富 | 核心六维全建且每维 ≥3 条；痕迹 ≥6 份 / ≥4 类；有扩展维度；心智模型 ≥5；冲突 ≥2 |
    | 饱和 | 丰富 + **已无可补缺口**（剩下的全是「待事件」） |

    **为什么「饱和」要求可补缺口清零**：丰富是「资料多」，饱和是
    「能问的都问完了」。前者靠堆，后者只能靠真问——
    所以它是深化循环的停止条件，而不是一个可以刷的成就。
    """
    built = [d for d in dims if d["path"]]
    core_built = [d for d in built if d["kind"] == "core"]
    ext_built = [d for d in built if d["kind"] == "extended"]
    ev = len((manifest or {}).get("evidence") or [])
    kinds = {e.get("type") for e in (manifest or {}).get("evidence") or [] if e.get("type")}
    sec = section(self_body or "", SECTION_MODELS) or ""
    models = len([ln for ln in sec.splitlines() if ln.strip().startswith("### ")])
    n_conf = len(conflict_ids(read_text(os.path.join(root, "CONFLICTS.md")) or ""))
    reasons = []

    rich = (len(core_built) >= len(CORE_DIMENSIONS)
            and all(d["entries"] >= COVERAGE_RICH_MIN_ENTRIES for d in built)
            and ev >= COVERAGE_RICH_MIN_EVIDENCE
            and len(kinds) >= COVERAGE_RICH_MIN_EVIDENCE_KINDS
            and bool(ext_built)
            and models >= COVERAGE_RICH_MIN_MODELS
            and n_conf >= 2)
    if rich:
        level = "丰富"
        reasons.append("核心六维全建且每维 ≥%d 条；痕迹 %d 份 / %d 类；"
                       "扩展维度 %d 个；心智模型 %d；冲突 %d"
                       % (COVERAGE_RICH_MIN_ENTRIES, ev, len(kinds),
                          len(ext_built), models, n_conf))
        open_gaps = sum(d["gaps_open"] for d in dims)
        if open_gaps == 0:
            level = "饱和"
            reasons.append("**且已无可补缺口**——剩下的都是「待事件」"
                           "（只能等它真实发生，不要硬答）")
        else:
            reasons.append("可补缺口还有 %d 条 → 补完即达「饱和」" % open_gaps)
    elif len(core_built) >= len(CORE_DIMENSIONS) and ev >= PROBE_MIN:
        level = "标准"
        reasons.append("核心六维都建了；痕迹 %d 份" % ev)
    else:
        level = "稀疏"
        if len(core_built) < len(CORE_DIMENSIONS):
            reasons.append("核心六维只建了 %d/%d 个"
                           % (len(core_built), len(CORE_DIMENSIONS)))
        if ev < PROBE_MIN:
            reasons.append("痕迹只有 %d 份" % ev)
    stats = {"evidence": ev, "evidence_kinds": len(kinds), "models": models,
             "conflicts": n_conf, "core_built": len(core_built),
             "ext_built": len(ext_built),
             "gaps_open": sum(d["gaps_open"] for d in dims),
             "gaps_pending": sum(d["gaps_pending"] for d in dims)}
    return level, reasons, stats


# --------------------------------------------------------------------------
# 述行冲突检测
# --------------------------------------------------------------------------


def harmony_matches(text):
    """返回正文里**否认对立**式调和的命中片段（已排除引用与提及）。

    `HARMONY_RE` 本身是纯字符串匹配，分不清「主张」与「提及」。一份**明确否定
    抹平写法**的档案——「本节刻意未使用『其实两者并不冲突』这类表述」——
    会被原样判成和稀泥并硬性 FAIL。

    所以这里做两层剥离：

    1. **剥引号**：`「」『』“”""《》` 里的字是被引用的，不是作者的主张。
    2. **剥提及**：命中片段前 16 字内出现 `MENTION_GUARD_RE` 的否定词，
       说明作者在**讨论**这种写法，不是在使用。

    宁可漏认（多拦一个没拦住的调和），不可误认（把否定抹平的句子判成抹平）——
    误认会训练作者删掉真实冲突，那正是铁律 2 要防的事。
    """
    if not text:
        return []
    scrubbed = QUOTED_SPAN_RE.sub("", text)
    out = []
    for m in HARMONY_RE.finditer(scrubbed):
        left = scrubbed[max(0, m.start() - 16):m.start()]
        if MENTION_GUARD_RE.search(left):
            continue
        out.append(m.group(0))
    return out


def has_harmony(text):
    """正文里是否存在否认对立式调和（判据见 `harmony_matches`）。"""
    return bool(harmony_matches(text))


def labeled_tension_types(text):
    """返回正文里**成标签**出现的冲突分类（去重，保持出现顺序）。

    「出现『时间性』三个字」不等于「做了时间性张力的分类」。判据见
    `TENSION_LABEL_RE`：类型词要与 张力/冲突 连用。
    """
    out = []
    for m in TENSION_LABEL_RE.finditer(text or ""):
        label = re.sub(r"\s+", "", m.group(0))
        if label not in out:
            out.append(label)
    return out


def declaration_sentence(text, pattern=NO_CONFLICT_RE):
    """返回「未发现冲突」声明**所在的整句**；没有声明则返回空串。

    长度门槛必须量在**声明句**上，而不是整段上。量整段的话，
    「未发现冲突。」后面接 30 个「哈」就能过——契约要的是「显式声明
    **并说明核查范围**」，即那句话本身得说清楚比对了什么。
    """
    m = pattern.search(text or "")
    if not m:
        return ""
    bounds = "。！？\n"
    start = max([text.rfind(c, 0, m.start()) for c in bounds] + [-1]) + 1
    ends = [text.find(c, m.end()) for c in bounds]
    ends = [e for e in ends if e != -1]
    end = min(ends) + 1 if ends else len(text)
    return text[start:end].strip()


def conflict_ids(text):
    """返回 `CONFLICTS.md` 里的冲突编号列表，如 `["C1", "C2"]`。"""
    return ["C" + m.group(1) for m in CONFLICT_HEAD_RE.finditer(text or "")]


def parse_axioms(text):
    """解析 `PRINCIPLES.md` 的公理表，返回 `[(编号, 立场, 理由, 代价, src), ...]`。

    形状约束（契约 §4.1）：五列，编号与立场都要加粗。不匹配的行直接跳过——
    脚本不猜作者意图，格式不对就是解析不出来，由 `self_check.py` 报出来。
    """
    out = []
    for line in (text or "").splitlines():
        m = AXIOM_ROW_RE.match(line)
        if not m:
            continue
        out.append(tuple(x.strip() for x in m.groups()))
    return out


# --------------------------------------------------------------------------
# 终端渲染（CJK 全角按 2 列计宽）
# --------------------------------------------------------------------------


def dw(s):
    """字符串的终端显示宽度：CJK 全角算 2 列。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in str(s))


def truncate(s, width):
    """按显示宽度截断，超出加省略号。"""
    s = str(s)
    if width <= 1:
        return ""
    if dw(s) <= width:
        return s
    out, used = "", 0
    for c in s:
        w = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if used + w > width - 1:
            break
        out += c
        used += w
    return out + "…"


def pad(s, width):
    """按显示宽度右侧补空格。"""
    s = str(s)
    return s + " " * max(0, width - dw(s))


def render_table(header, rows, widths):
    """渲染一张终端表格。`header` 与 `rows` 都是字符串列表的列表。"""
    lines = ["  ".join(pad(h, w) for h, w in zip(header, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(
            pad(truncate(c, w), w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 文件与哈希
# --------------------------------------------------------------------------


def sha256_file(path):
    """文件内容的 sha256（64 位小写十六进制）。

    **算法是契约的一部分，不要动**——`manifest` 里的哈希与 `--check`
    都依赖它保持稳定。
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    """字符串内容的 sha256，编码固定为 UTF-8（与 `sha256_file` 同一算法）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def read_text(path):
    """读文本文件；不存在或读不出返回 `None`（不抛）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def load_json(path, default=None):
    """读 JSON；不存在或损坏返回 `default`（不抛）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    """写 JSON，UTF-8、缩进 2、保留中文原样、末尾换行。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_jsonl(path, obj):
    """追加一行 JSONL。**追加式，只增不改**（契约 §五）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_jsonl(path):
    """读 JSONL；坏行跳过（不让一行坏数据毁掉整个台账）。"""
    out = []
    text = read_text(path)
    if not text:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def load_manifest(root_or_path):
    """读档案目录下的 `manifest.json`；传入文件路径也认。"""
    path = root_or_path
    if os.path.isdir(path):
        path = os.path.join(path, "manifest.json")
    return load_json(path, default=None)


def resolve_archive_dir(path):
    """把用户给的各种路径形态收敛到档案根目录。

    接受：档案目录本身 / `manifest.json` 的路径 / `SELF.md` 的路径。
    找不到 `manifest.json` 时返回原路径——由调用方决定怎么报错。
    """
    if not path:
        return path
    path = os.path.abspath(path)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if os.path.isfile(os.path.join(path, "manifest.json")):
        return path
    return path


# --------------------------------------------------------------------------
# CLI 小工具
# --------------------------------------------------------------------------


def usage_error(msg, usage):
    """统一的用法错误输出：打到 stderr 并返回退出码 2。"""
    sys.stderr.write("错误：%s\n\n用法：%s\n" % (msg, usage))
    return 2


def fmt_pct(x):
    """比例 → 百分数字符串，如 `0.3333` → `33.3%`。"""
    return "%.1f%%" % (x * 100)
