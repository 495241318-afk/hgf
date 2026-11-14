#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""易错点自动出题脚本

思路：不自动改写句子，只把教师写的「易错点」原文拆成“正确项 / 错误项”，
原位替换成一个括号，因此题干永远通顺，不会出现机器造句的病句。

    辨析题（二选一）  来自「易错点」：洋务运动是（A. 地主阶级的自救运动 / B. 资产阶级改革）
    填空题           来自「知识点」：挖掉年代、《书名》、引号名词
    简答题           按「重难点」设问，答案为本课要点，供背诵自测

不做自动四选一：干扰项若来自其他课，语义类别对不上，选项一眼可排除，反而误导学生。

用法：
    python3 scripts/quiz.py                          # 六册，每课 3 辨析 + 3 填空
    python3 scripts/quiz.py --book 八年级上册
    python3 scripts/quiz.py --book 八年级上册 --unit 第三单元
    python3 scripts/quiz.py --type 辨析,填空,简答 --per-lesson 4
    python3 scripts/quiz.py --type 辨析,填空,简答 --no-html

产物：
    题库/<册别>.md            分册题库（含答案与出处），便于校对
    题库/<册别>-打印版.html    A4 打印版，题目在前、答案另起一页
    题库/打印版.html          多册合并版
"""

import argparse
import html as htmllib
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import BOOK_ORDER, INDEX_DIR, ROOT, parse_lesson  # noqa: E402

OUT_DIR = ROOT / "题库"

SEG_SPLIT = re.compile(r"[；;。]\s*")
PAREN = re.compile(r"[（(][^）)]{0,40}[）)]")
YEAR = re.compile(r"(\d{3,4})\s*年")
BOOKNAME = re.compile(r"《[^》]{2,20}》")
QUOTED = re.compile(r"“[^”]{2,18}”")

# 原文：“……是 A，不是 B” → 题干：“……是（ A / B ）”
PAT_PAIR = re.compile(
    r"^(?P<pre>.{2,58}?)"
    r"(?P<pred>是|为|在于|属于|指|始于|开始于|发生在|出现在|发生于|形成于|完成于|结束于|建立于|定都于|约(?=\s*\d))"
    r"(?P<a>[^，,；;《》]{2,30})"
    r"[，,]\s*(?:不是|而不是|而非|不属于)"
    r"(?P<b>[^，,；;《》]{2,30})$"
)

TYPE_TITLE = {"辨析": "一、辨析题（在括号内选正确的一项）",
              "填空": "二、填空题",
              "简答": "三、简答题"}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", PAREN.sub("", str(text or ""))).strip()


def segments(text: str) -> list[str]:
    return [s.strip() for s in SEG_SPLIT.split(clean(text)) if len(s.strip()) >= 8]


def cut(text: str, limit: int = 44) -> str:
    text = text.strip().rstrip("。；;，,、：:")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------- 拆易错点：正确项 / 错误项 ----------

def pairs(lesson: dict) -> list[dict]:
    """把易错点拆成 (题干前半, 正确项, 错误项)。"""
    out = []
    for seg in segments(lesson.get("易错点")):
        m = PAT_PAIR.match(seg)
        if not m:
            continue
        pre = m.group("pre").strip()
        pred = m.group("pred")
        a = m.group("a").strip(" ，,")
        b = m.group("b").strip(" ，,")
        lead = f"{pre}{pred}"
        if not pre or pre.endswith(("的", "之")) or len(a) < 2 or len(b) < 2:
            continue
        if b.startswith(("那", "此", "这")) or a == b:
            continue
        # 书名号必须成对，避免把《辛丑条约》从中间切开
        if lead.count("《") != lead.count("》") or len(lead) < 4:
            continue
        out.append({"lead": lead, "right": a, "wrong": b, "raw": seg})
    return out


# ---------- 填空题 ----------

def blanks(lesson: dict, limit: int) -> list[dict]:
    out = []
    for kp in lesson.get("知识点") or []:
        s = clean(kp)
        if len(s) < 12:
            continue
        seg = s.split("；")[0]
        if len(seg) > 72:
            seg = cut(seg, 68)
        m = YEAR.search(seg)
        if m:
            out.append({"stem": seg[: m.start(1)] + "____" + seg[m.end(1):],
                        "answer": m.group(1), "note": "填年代数字", "raw": s})
        else:
            m = BOOKNAME.search(seg) or QUOTED.search(seg)
            if not m:
                continue
            out.append({"stem": seg[: m.start()] + "________" + seg[m.end():],
                        "answer": m.group(0), "note": "", "raw": s})
        if len(out) >= limit:
            break
    return out


# ---------- 简答题 ----------

def short_answers(lesson: dict) -> list[dict]:
    kps = [clean(k) for k in (lesson.get("知识点") or [])][:4]
    if len(kps) < 2:
        return []
    focus = clean(lesson.get("重难点") or lesson.get("课标要求") or "")
    return [{
        "stem": f"《{lesson['课题']}》：围绕“{cut(focus, 28)}”，分点写出本课要点。",
        "answer": "；".join(cut(k, 40) for k in kps),
        "note": "答出 3 点即可",
    }]


# ---------- 组卷 ----------

def build_bank(lessons: list[dict], per_lesson: int, types: set[str], seed: int) -> dict:
    rng = random.Random(seed)
    bank = {t: [] for t in ("辨析", "填空", "简答")}
    seen: set[str] = set()

    for ls in lessons:
        tag = f"{ls['册别']} 第{ls['课序']:02d}课《{ls['课题']}》"
        ps = pairs(ls)

        if "辨析" in types:
            for p in ps[:per_lesson]:
                key = p["lead"] + p["right"]
                if key in seen:
                    continue
                seen.add(key)
                opts = [p["right"], p["wrong"]]
                rng.shuffle(opts)
                bank["辨析"].append({
                    "stem": f"{p['lead']}（　　）",
                    "options": opts,
                    "answer": "ABCD"[opts.index(p["right"])],
                    "note": f"错误项：{p['wrong']}",
                    "source": tag, "raw": p["raw"],
                })

        if "填空" in types:
            for b in blanks(ls, per_lesson):
                bank["填空"].append({**b, "source": tag})

        if "简答" in types:
            for q in short_answers(ls):
                bank["简答"].append({**q, "source": tag})

    return bank


def to_markdown(bank: dict, title: str) -> str:
    lines = [f"# {title}", "",
             "> 由 `scripts/quiz.py` 依据 `index/` 下的课时索引生成；题干取自课时原文，只把易错点原位改成选项。",
             "> 印前请扫一眼答案里的「出处」，个别表述可按本班情况微调。", ""]
    for t in ("辨析", "填空", "简答"):
        items = bank[t]
        if not items:
            continue
        lines += [f"## {TYPE_TITLE[t]}", ""]
        for i, q in enumerate(items, 1):
            if t == "辨析":
                opt = "　".join(f"{'ABCD'[k]}. {o}" for k, o in enumerate(q["options"]))
                lines += [f"{i}. {q['stem']}　{opt}", ""]
            else:
                lines += [f"{i}. {q['stem']}", ""]
    lines += ["---", "", "## 参考答案", ""]
    for t in ("辨析", "填空", "简答"):
        items = bank[t]
        if not items:
            continue
        lines += [f"### {TYPE_TITLE[t]}", ""]
        for i, q in enumerate(items, 1):
            if t == "辨析":
                lines.append(f"{i}. **{q['answer']}**（{q['options']['ABCD'.index(q['answer'])]}）　*{q['source']}*")
            else:
                note = f"（{q['note']}）" if q.get("note") else ""
                lines.append(f"{i}. **{q['answer']}** {note}　*{q['source']}*")
        lines.append("")
    return "\n".join(lines)


PRINT_CSS = """
@page { size: A4; margin: 16mm 15mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Songti SC", SimSun, "Noto Serif CJK SC", serif; font-size: 11.5pt;
       line-height: 1.85; color: #111; margin: 0; }
h1 { font-size: 18pt; text-align: center; margin: 0 0 2mm; letter-spacing: .5px; }
.sub { text-align: center; font-size: 9.5pt; color: #555; margin-bottom: 4mm; }
h2 { font-size: 12.5pt; margin: 6mm 0 2.5mm; padding-bottom: 1mm; border-bottom: 1px solid #bbb; }
.q { margin: 0 0 3mm; page-break-inside: avoid; }
.q .no { font-weight: 700; margin-right: 3px; }
.optrow { margin: 0.5mm 0 0 5mm; }
.opt { display: inline-block; width: 48%; vertical-align: top; }
.opt i { font-style: normal; font-weight: 600; margin-right: 1mm; }
.ans-block { page-break-before: always; }
.ans { margin: 0 0 2.2mm; font-size: 10.5pt; page-break-inside: avoid; }
.src { color: #666; font-size: 9pt; }
.tip { border: 1px solid #999; padding: 2.5mm 3mm; font-size: 9.5pt; color: #333; margin-bottom: 4mm; }
"""


def to_html(bank: dict, title: str) -> str:
    e = htmllib.escape
    p = ['<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
         f'<title>{e(title)}</title><style>{PRINT_CSS}</style></head><body>',
         f'<h1>{e(title)}</h1>',
         '<div class="sub">姓名：__________　班级：__________　得分：__________</div>',
         '<div class="tip">辨析题把正确选项的字母写在括号内；填空题一格填一项；简答题分点作答。</div>']
    for t in ("辨析", "填空", "简答"):
        items = bank[t]
        if not items:
            continue
        p.append(f"<h2>{TYPE_TITLE[t]}</h2>")
        for i, q in enumerate(items, 1):
            body = f'<span class="no">{i}.</span>{e(q["stem"])}'
            if t == "辨析":
                opts = "".join(f'<span class="opt"><i>{"ABCD"[k]}.</i>{e(o)}</span>'
                               for k, o in enumerate(q["options"]))
                body += f'<div class="optrow">{opts}</div>' 
            p.append(f'<div class="q">{body}</div>')
    p.append('<div class="ans-block"><h2>参考答案</h2>')
    for t in ("辨析", "填空", "简答"):
        items = bank[t]
        if not items:
            continue
        p.append(f'<h2 style="border:0;margin-top:4mm">{TYPE_TITLE[t]}</h2>')
        for i, q in enumerate(items, 1):
            if t == "辨析":
                right = q["options"]["ABCD".index(q["answer"])]
                p.append(f'<div class="ans">{i}. <b>{q["answer"]}</b>　{e(right)} '
                         f'<span class="src">{e(q["source"])}</span></div>')
            else:
                p.append(f'<div class="ans">{i}. <b>{e(q["answer"])}</b>　'
                         f'<span class="src">{e(q["source"])}</span></div>')
    p.append("</div></body></html>")
    return "".join(p)


# ---------- 命令行 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="从课时索引批量出题（辨析 / 填空 / 简答）")
    ap.add_argument("-b", "--book", default="", help="册别，逗号分隔，如 八年级上册,八年级下册")
    ap.add_argument("-u", "--unit", default="", help="单元名包含的文字，如 第三单元")
    ap.add_argument("-t", "--type", default="辨析,填空", help="题型：辨析,填空,简答")
    ap.add_argument("-n", "--per-lesson", type=int, default=3, help="每课最多几道（辨析/填空各按此数）")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    types = {t.strip() for t in args.type.split(",") if t.strip()}
    books = [b.strip() for b in args.book.split(",") if b.strip()]

    lessons = []
    for path in sorted(INDEX_DIR.rglob("*.md")):
        try:
            ls = parse_lesson(path)
        except Exception:
            continue
        if books and ls.get("册别") not in books:
            continue
        if args.unit and args.unit not in str(ls.get("单元", "")):
            continue
        lessons.append(ls)
    if not lessons:
        print("没有匹配的课时，检查 --book / --unit")
        return 1

    lessons.sort(key=lambda x: (BOOK_ORDER.index(x["册别"]) if x["册别"] in BOOK_ORDER else 9,
                                int(x["课序"])))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[dict]] = {}
    for ls in lessons:
        groups.setdefault(ls["册别"], []).append(ls)

    total = {t: 0 for t in ("辨析", "填空", "简答")}
    merged = {t: [] for t in total}

    for book, items in groups.items():
        bank = build_bank(items, args.per_lesson, types, args.seed)
        scope = book + (f"（{args.unit}）" if args.unit else "")
        (out_dir / f"{book}.md").write_text(to_markdown(bank, f"{scope} · 课时练习"), encoding="utf-8")
        if not args.no_html:
            (out_dir / f"{book}-打印版.html").write_text(to_html(bank, f"{scope} 课时练习"), encoding="utf-8")
        for t in total:
            total[t] += len(bank[t])
            merged[t].extend(bank[t])
        print(f"{book}：辨析 {len(bank['辨析'])}、填空 {len(bank['填空'])}、"
              f"简答 {len(bank['简答'])}")

    if len(groups) > 1:
        label = (args.book or "六册") + (f"（{args.unit}）" if args.unit else "")
        (out_dir / "全部.md").write_text(to_markdown(merged, f"{label} · 课时练习（汇总）"), encoding="utf-8")
        if not args.no_html:
            (out_dir / "打印版.html").write_text(to_html(merged, f"{label} 课时练习"), encoding="utf-8")

    print(f"合计 {sum(total.values())} 题（辨析 {total['辨析']}、填空 {total['填空']}、"
          f"简答 {total['简答']}）→ {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
