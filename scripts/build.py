#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教材知识库索引构建脚本

用法：
    python3 scripts/build.py            # 校验 + 构建网页和报表
    python3 scripts/build.py --check    # 只校验，不生成文件（CI 里用于把关）

做三件事：
    1. 校验 index/ 下每课的 Markdown 元数据是否完整、课序是否重复
    2. 生成 docs/index.html —— 单文件检索页，手机和教室电脑都能打开
    3. 生成 报表/覆盖度报表.md —— 给教研组和教导处看的进度台账
"""

import json
import re
import sys
import html
from pathlib import Path

import yaml

try:  # 正文渲染为 HTML 用，缺了也能退化成纯文本
    import markdown
except ImportError:  # pragma: no cover
    markdown = None

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "index"
TOPIC_DIR = ROOT / "专题"
DOCS_DIR = ROOT / "docs"
REPORT_DIR = ROOT / "报表"

BOOK_ORDER = ["七年级上册", "七年级下册", "八年级上册", "八年级下册", "九年级上册", "九年级下册"]
STATUS_ORDER = ["已定稿", "待复核", "草稿"]
REQUIRED = [
    "册别", "单元", "课序", "课题", "课标要求", "核心素养",
    "关键词", "知识点", "重难点", "易错点", "教学建议", "状态",
]

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_lesson(path: Path) -> dict:
    """把一课的 Markdown 拆成 元数据 + 正文。"""
    raw = path.read_text(encoding="utf-8")
    m = FRONTMATTER.match(raw)
    if not m:
        raise ValueError("文件开头缺少 --- 包住的元数据块")
    meta = yaml.safe_load(m.group(1)) or {}
    meta["_body"] = m.group(2).strip()
    meta["_path"] = str(path.relative_to(ROOT))
    meta["_name"] = path.stem
    return meta


def load_all() -> tuple[list[dict], list[str]]:
    """读取全部课时，同时返回校验错误清单。"""
    lessons, errors = [], []
    if not INDEX_DIR.exists():
        return [], [f"找不到索引目录 {INDEX_DIR}"]

    for path in sorted(INDEX_DIR.rglob("*.md")):
        try:
            meta = parse_lesson(path)
        except Exception as exc:  # 解析失败也要汇总，不能中断整批
            errors.append(f"{path.name}：解析失败（{exc}）")
            continue

        miss = [k for k in REQUIRED if not meta.get(k)]
        if miss:
            errors.append(f"{meta['_path']}：缺少字段 {('、'.join(miss))}")

        book = str(meta.get("册别", "")).strip()
        if book and book not in BOOK_ORDER:
            errors.append(f"{meta['_path']}：册别「{book}」不在 {('/'.join(BOOK_ORDER))} 之内")

        order = meta.get("课序")
        if order is not None and not isinstance(order, int):
            errors.append(f"{meta['_path']}：课序必须是数字，当前是「{order}」")

        for key in ("核心素养", "关键词", "知识点"):
            val = meta.get(key)
            if val is not None and not isinstance(val, list):
                errors.append(f"{meta['_path']}：{key} 要写成 - 开头的列表")

        lessons.append(meta)

    seen = {}
    for meta in lessons:
        key = (meta.get("册别"), meta.get("课序"))
        if key in seen:
            errors.append(f"课序重复：{key[0]} 第{key[1]}课 —— {seen[key]} 与 {meta['_path']}")
        else:
            seen[key] = meta["_path"]

    def sort_key(meta):
        book = BOOK_ORDER.index(meta["册别"]) if meta.get("册别") in BOOK_ORDER else 99
        return (book, meta.get("课序") or 0)

    lessons.sort(key=sort_key)
    return lessons, errors


def load_topics(lessons: list[dict]) -> tuple[list[dict], list[str]]:
    """读取 专题/ 下的复习专题，并校验它引用的课时是否真实存在。"""
    topics, errors = [], []
    if not TOPIC_DIR.exists():
        return [], []

    lesson_map = {(m["册别"], m["课序"]): m for m in lessons}

    for path in sorted(TOPIC_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = FRONTMATTER.match(raw)
        if not m:
            errors.append(f"专题/{path.name}：文件开头缺少 --- 包住的元数据块")
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        meta["_body"] = m.group(2).strip()
        meta["_name"] = path.stem

        name = str(meta.get("专题", "")).strip()
        if not name:
            errors.append(f"专题/{path.name}：缺少「专题」名称")
            continue

        refs, bad = [], []
        for ref in (meta.get("涵盖课时") or []):
            mm = re.match(r"^(.+?)\s*第\s*(\d+)\s*课\s*$", str(ref).strip())
            if not mm:
                bad.append(f"{ref}（格式应为「八年级上册 第01课」）")
                continue
            key = (mm.group(1).strip(), int(mm.group(2)))
            if key not in lesson_map:
                bad.append(str(ref))
            else:
                refs.append(lesson_map[key])

        if bad:
            errors.append(f"专题/{name}：引用了不存在的课时 —— {('、'.join(bad))}")
        if not refs:
            errors.append(f"专题/{name}：没有关联任何课时")
            continue

        meta["_lessons"] = refs
        topics.append(meta)

    topics.sort(key=lambda t: (t.get("顺序") or 99, str(t.get("专题"))))
    return topics, errors


def as_text(val) -> str:
    """列表字段在网页里用顿号连起来，字典字段取它的值。"""
    if isinstance(val, list):
        return "、".join(str(v) for v in val)
    return str(val)


def render_body(text: str) -> str:
    """正文 Markdown 转 HTML；没有 markdown 库时退化为等宽纯文本。"""
    if not text:
        return ""
    if markdown is None:
        return f"<pre>{html.escape(text)}</pre>"
    return markdown.markdown(text, extensions=["fenced_code", "tables", "nl2br"])


def build_site(lessons: list[dict]) -> None:
    DOCS_DIR.mkdir(exist_ok=True)

    payload = []
    for meta in lessons:
        payload.append({
            "册别": meta["册别"],
            "单元": meta["单元"],
            "课序": meta["课序"],
            "课题": meta["课题"],
            "课标": meta.get("课标要求", ""),
            "素养": [str(x) for x in (meta.get("核心素养") or [])],
            "关键词": [str(x) for x in (meta.get("关键词") or [])],
            "知识点": [str(x) for x in (meta.get("知识点") or [])],
            "重难点": as_text(meta.get("重难点", "")),
            "易错点": as_text(meta.get("易错点", "")),
            "教学建议": as_text(meta.get("教学建议", "")),
            "状态": meta.get("状态", ""),
            "正文": meta.get("_body", ""),
            "正文HTML": render_body(meta.get("_body", "")),
            "路径": meta["_path"],
        })

    (DOCS_DIR / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stats = {b: {"total": 0, "done": 0} for b in BOOK_ORDER}
    for item in payload:
        stats[item["册别"]]["total"] += 1
        if item["状态"] == "已定稿":
            stats[item["册别"]]["done"] += 1

    total = len(payload)
    done = sum(s["done"] for s in stats.values())
    cards = "".join(
        f'<div class="stat"><b>{b}</b><span>{s["total"]} 课 / 定稿 {s["done"]}</span></div>'
        for b, s in stats.items()
    )

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>人教版初中历史教材知识库索引</title>
<style>
:root {{ --ink:#1f2328; --sub:#656d76; --line:#d8dee4; --bg:#f6f8fa;
        --accent:#8c2f2f; --card:#fff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:20px; font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       color:var(--ink); background:var(--bg); }}
header {{ max-width:960px; margin:0 auto 18px; }}
h1 {{ font-size:22px; margin:0 0 6px; }}
.sub {{ color:var(--sub); font-size:13px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
          gap:8px; margin:14px 0; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
         padding:8px 10px; font-size:12px; }}
.stat b {{ display:block; font-size:13px; margin-bottom:2px; }}
.stat span {{ color:var(--sub); }}
.toolbar {{ position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:5;
            display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
input[type=search] {{ flex:1 1 220px; padding:9px 12px; border:1px solid var(--line);
                      border-radius:8px; font-size:14px; }}
.chip {{ padding:5px 12px; border:1px solid var(--line); border-radius:99px; background:var(--card);
         font-size:13px; cursor:pointer; }}
.chip.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
main {{ max-width:960px; margin:0 auto; }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           margin-bottom:10px; padding:12px 14px; }}
summary {{ cursor:pointer; list-style:none; }}
summary::-webkit-details-marker {{ display:none; }}
.title {{ font-weight:600; }}
.meta {{ color:var(--sub); font-size:12px; margin-top:2px; }}
.badge {{ display:inline-block; font-size:11px; padding:1px 8px; border-radius:99px;
          margin-left:6px; vertical-align:1px; }}
.s-已定稿 {{ background:#e6f4ea; color:#1a7f37; }}
.s-待复核 {{ background:#fff4e5; color:#9a6700; }}
.s-草稿 {{ background:#eef1f4; color:#57606a; }}
.kw {{ display:inline-block; font-size:12px; background:var(--bg); border:1px solid var(--line);
       border-radius:4px; padding:0 6px; margin:2px 4px 2px 0; }}
.block {{ margin-top:10px; }}
.block h3 {{ font-size:13px; margin:12px 0 4px; color:var(--accent); }}
.block p, .block li {{ font-size:14px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
th {{ background:var(--bg); width:88px; font-weight:600; }}
.md h2 {{ font-size:14px; margin:16px 0 6px; padding-left:8px; border-left:3px solid var(--accent); }}
.md h3 {{ font-size:13px; margin:12px 0 4px; }}
.md ul, .md ol {{ padding-left:20px; margin:6px 0; }}
.md p {{ margin:6px 0; }}
.md pre {{ background:#f6f8fa; border:1px solid var(--line); border-radius:6px;
           padding:10px; overflow:auto; font:12.5px/1.5 ui-monospace,Consolas,monospace; }}
.md code {{ font-family:ui-monospace,Consolas,monospace; font-size:12.5px; }}
.md blockquote {{ margin:8px 0; padding:2px 12px; border-left:3px solid var(--line); color:var(--sub); }}
.nav {{ margin:2px 0 0; }}
.nav a {{ font-size:13px; color:var(--accent); text-decoration:none; }}
.nav a:hover {{ text-decoration:underline; }}
footer {{ max-width:960px; margin:24px auto; color:var(--sub); font-size:12px; }}
@media print {{ .toolbar {{ display:none; }} details {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<header>
  <h1>人教版初中历史教材知识库索引</h1>
  <div class="sub">共 {total} 课，已定稿 {done} 课 ｜ 数据源：仓库 index/ 目录下每课一个 Markdown 文件，本页由脚本自动生成</div>
  <div class="stats">{cards}</div>
  <div class="nav"><a href="topics.html">按专题复习 · 中考串课 →</a></div>
</header>
<div class="toolbar">
  <input type="search" id="q" placeholder="搜课题、关键词、知识点……">
  <span class="chip on" data-book="all">全部</span>
  {"".join(f'<span class="chip" data-book="{b}">{b}</span>' for b in BOOK_ORDER)}
</div>
<main id="list"></main>
<footer>内容为教师个人整理的索引，仅供备课参考，不代表教材原文。生成时间：{__import__("datetime").date.today()}</footer>
<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const list = document.getElementById('list');
let book = 'all', kw = '';
function esc(s) {{ return String(s).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function render() {{
  const rows = DATA.filter(d =>
    (book === 'all' || d['册别'] === book) &&
    (kw === '' || (d['课题'] + d['关键词'].join('') + d['知识点'].join('') + d['单元']).includes(kw))
  );
  if (!rows.length) {{ list.innerHTML = '<p style="color:#656d76">没有匹配的课时。</p>'; return; }}
  list.innerHTML = rows.map((d, i) => `
    <details>
      <summary>
        <div class="title">${{esc(d['册别'])}} 第${{d['课序']}}课 ${{esc(d['课题'])}}
          <span class="badge s-${{esc(d['状态'])}}">${{esc(d['状态'])}}</span></div>
        <div class="meta">${{esc(d['单元'])}}</div>
        <div style="margin-top:6px">${{d['关键词'].map(k => `<span class="kw">${{esc(k)}}</span>`).join('')}}</div>
      </summary>
      <div class="block">
        <h3>课标要求</h3><p>${{esc(d['课标'])}}</p>
        <h3>核心素养</h3><p>${{d['素养'].map(esc).join('、')}}</p>
        <h3>知识点梳理</h3><ul>${{d['知识点'].map(x => `<li>${{esc(x)}}</li>`).join('')}}</ul>
        <table>
          <tr><th>重难点</th><td>${{esc(d['重难点'])}}</td></tr>
          <tr><th>易错点</th><td>${{esc(d['易错点'])}}</td></tr>
          <tr><th>教学建议</th><td>${{esc(d['教学建议'])}}</td></tr>
        </table>
        <h3>备注与板书</h3>
        <div class="md" data-body="${{i}}"></div>
      </div>
    </details>`).join('');
  // 正文是渲染好的 HTML，单独注入避免转义与模板字符冲突
  list.querySelectorAll('[data-body]').forEach(el => {{
    el.innerHTML = rows[Number(el.dataset.body)]['正文HTML'] || '';
  }});
}}
document.getElementById('q').addEventListener('input', e => {{ kw = e.target.value.trim(); render(); }});
document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {{
  document.querySelectorAll('.chip').forEach(x => x.classList.remove('on'));
  c.classList.add('on'); book = c.dataset.book; render();
}}));
render();
</script>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")


TOPIC_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>中考专题复习 · 教材知识库索引</title>
<style>
:root{--ink:#1f2328;--sub:#656d76;--line:#d8dee4;--bg:#f6f8fa;--accent:#8c2f2f;--card:#fff}
*{box-sizing:border-box}
body{margin:0;padding:20px;font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}
header,main{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 6px}
.sub{color:var(--sub);font-size:13px}
.back{display:inline-block;margin:10px 0 0;font-size:13px;color:var(--accent);text-decoration:none}
.back:hover{text-decoration:underline}
.toolbar{position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:5;display:flex;gap:8px;overflow-x:auto;max-width:960px;margin:0 auto}
.chip{white-space:nowrap;padding:5px 12px;border:1px solid var(--line);border-radius:99px;background:var(--card);font-size:13px;cursor:pointer}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.topic{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:14px}
.topic h2{font-size:17px;margin:0 0 4px}
.topic .meta{color:var(--sub);font-size:12px;margin-bottom:8px}
.lead{font-size:14px;background:var(--bg);border-left:3px solid var(--accent);padding:8px 12px;margin:10px 0;border-radius:0 6px 6px 0}
.kw{display:inline-block;font-size:12px;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 6px;margin:2px 4px 2px 0}
.md h2{font-size:15px;margin:18px 0 6px;padding-left:8px;border-left:3px solid var(--accent)}
.md h3{font-size:14px;margin:12px 0 4px}
.md table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}
.md th,.md td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.md th{background:var(--bg);font-weight:600}
.md ul,.md ol{padding-left:20px;margin:6px 0}
.md p{margin:6px 0}
.md blockquote{margin:8px 0;padding:2px 12px;border-left:3px solid var(--line);color:var(--sub)}
.md code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--bg);padding:1px 4px;border-radius:3px}
.lessons{margin-top:14px;border-top:1px dashed var(--line);padding-top:10px}
.lessons summary{cursor:pointer;font-size:13px;color:var(--accent);font-weight:600}
.lesson{padding:8px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.lesson:last-child{border-bottom:0}
.lesson .err{color:var(--sub);font-size:13px;margin-top:3px}
footer{max-width:960px;margin:24px auto;color:var(--sub);font-size:12px}
@media (max-width:640px){
  body{padding:14px}
  .topic{padding:14px}
  .md table{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .md th,.md td{white-space:nowrap;font-size:12.5px;padding:5px 7px}
}
@media print{.toolbar{display:none}.topic{break-inside:avoid}}
</style>
</head>
<body>
<header>
  <h1>中考专题复习 · 横向串课</h1>
  <div class="sub">__COUNT__ 个专题，串起 __LESSONS__ 条课时 ｜ 与全量索引共用同一批数据，改课时后本页自动更新</div>
  <a class="back" href="index.html">← 返回全量课时索引</a>
</header>
<div class="toolbar" id="bar"></div>
<main id="list"></main>
<footer>内容为教师个人整理的复习线索，仅供备课参考，不代表教材原文。</footer>
<script>
const TOPICS = __DATA__;
const bar = document.getElementById('bar');
const list = document.getElementById('list');
let cur = -1;
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
bar.innerHTML = '<span class="chip on" data-i="-1">全部专题</span>' +
  TOPICS.map((t,i)=>`<span class="chip" data-i="${i}">${i+1}. ${esc(t['专题'])}</span>`).join('');
function render(){
  const rows = cur < 0 ? TOPICS : [TOPICS[cur]];
  list.innerHTML = rows.map(t => `
    <section class="topic">
      <h2>${TOPICS.indexOf(t)+1}. ${esc(t['专题'])}</h2>
      <div class="meta">${esc(t['适用'])} ｜ 关联 ${t['课时'].length} 课</div>
      <div>${t['关键词'].map(k=>`<span class="kw">${esc(k)}</span>`).join('')}</div>
      <div class="lead">${esc(t['概述'])}</div>
      <div class="md">${t['正文HTML']}</div>
      <details class="lessons"><summary>展开关联课时与易错点（${t['课时'].length}）</summary>
        ${t['课时'].map(l=>`<div class="lesson"><b>${esc(l['册别'])} 第${l['课序']}课 ${esc(l['课题'])}</b><div class="err">${esc(l['易错点'])}</div></div>`).join('')}
      </details>
    </section>`).join('');
}
bar.addEventListener('click', e => {
  const c = e.target.closest('.chip'); if(!c) return;
  bar.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); cur = Number(c.dataset.i); render();
  window.scrollTo({top:0,behavior:'smooth'});
});
render();
</script>
</body>
</html>
"""


def build_topics(topics: list[dict]) -> None:
    """生成 docs/topics.html —— 按专题横向串课，附每课易错点。"""
    if not topics:
        return
    DOCS_DIR.mkdir(exist_ok=True)

    payload = []
    for t in topics:
        payload.append({
            "专题": str(t.get("专题", "")),
            "适用": str(t.get("适用", "")),
            "概述": str(t.get("概述", "")),
            "关键词": [str(x) for x in (t.get("关键词") or [])],
            "正文HTML": render_body(t.get("_body", "")),
            "课时": [{
                "册别": m["册别"],
                "课序": m["课序"],
                "课题": m["课题"],
                "易错点": as_text(m.get("易错点", "")),
                "知识点": [str(x) for x in (m.get("知识点") or [])],
            } for m in t["_lessons"]],
        })

    page = (TOPIC_TEMPLATE
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
            .replace("__COUNT__", str(len(payload)))
            .replace("__LESSONS__", str(sum(len(p["课时"]) for p in payload))))
    (DOCS_DIR / "topics.html").write_text(page, encoding="utf-8")


def build_report(lessons: list[dict]) -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    lines = ["# 教材知识库索引 · 覆盖度报表", ""]
    lines.append(f"统计口径：`index/` 目录下全部课时文件，共 **{len(lessons)}** 课。")
    lines.append("")
    lines.append("## 一、分册进度")
    lines.append("")
    lines.append("| 册别 | 已录入 | 已定稿 | 定稿率 |")
    lines.append("| --- | --- | --- | --- |")
    for book in BOOK_ORDER:
        rows = [m for m in lessons if m.get("册别") == book]
        done = [m for m in rows if m.get("状态") == "已定稿"]
        rate = f"{len(done) / len(rows) * 100:.0f}%" if rows else "—"
        lines.append(f"| {book} | {len(rows)} | {len(done)} | {rate} |")

    lines += ["", "## 二、状态分布", ""]
    for status in STATUS_ORDER:
        n = sum(1 for m in lessons if m.get("状态") == status)
        lines.append(f"- {status}：{n} 课")

    lines += ["", "## 三、核心素养覆盖", ""]
    tally = {}
    for m in lessons:
        for s in (m.get("核心素养") or []):
            tally[str(s)] = tally.get(str(s), 0) + 1
    for name, n in sorted(tally.items(), key=lambda x: -x[1]):
        lines.append(f"- {name}：{n} 课")

    lines += ["", "## 四、待办：状态未定稿的课时", ""]
    todo = [m for m in lessons if m.get("状态") != "已定稿"]
    if todo:
        for m in todo:
            lines.append(f"- [ ] {m['册别']} 第{m['课序']}课 {m['课题']}（{m['状态']}）")
    else:
        lines.append("全部已定稿。")

    lines += ["", "> 本报表由 `scripts/build.py` 自动生成，请勿手工编辑。", ""]
    (REPORT_DIR / "覆盖度报表.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    lessons, errors = load_all()
    topics, topic_errors = load_topics(lessons)
    errors += topic_errors

    if errors:
        print("校验未通过，共 %d 处问题：" % len(errors))
        for e in errors:
            print("  -", e)
        if "--check" in sys.argv:
            return 1

    if "--check" in sys.argv:
        if not errors:
            print(f"校验通过：{len(lessons)} 课、{len(topics)} 个专题，字段完整、课序无重复、专题引用有效。")
        return 1 if errors else 0

    build_site(lessons)
    build_topics(topics)
    build_report(lessons)

    books = {}
    for m in lessons:
        books[m["册别"]] = books.get(m["册别"], 0) + 1
    print(f"已生成 docs/index.html 与 报表/覆盖度报表.md，共 {len(lessons)} 课")
    if topics:
        print(f"已生成 docs/topics.html，共 {len(topics)} 个复习专题")
    for book in BOOK_ORDER:
        print(f"  {book}：{books.get(book, 0)} 课")
    if errors:
        print("注意：存在 %d 处校验问题，已跳过中断，但请尽快修正。" % len(errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
