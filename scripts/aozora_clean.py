#!/usr/bin/env python3
"""青空文庫の本文テキストを整える（第2段階）。

第1段階（aozora_honbun.py）の出力を入力にして、次の処理をする。
  1. ルビ《…》とルビの始まりを示す｜、入力者注［＃…］を削除する
  2. UTF-8 で保存する
  3. 外字の注記 ※［＃…］ を、面区点番号（例: 第3水準1-84-77）や
     Unicode番号（例: U+29D69）から本来の字に置き換える。
     番号がなく字が決まらないものは 〓 にする。

ルビと注記の扱いは、形態素解析・ルビ照合のプログラム
（01_keitaisokaiseki_ruby_autocorret.py）の parse_line と同じ規則にしている。
  - 行の数は元のまま変えない（注記だけの行は空行になる）
  - 外字は1字に置き換わる
そのため、このプログラムの出力と照合プログラムの出力（_morphs.txt など）とで、
行番号と行内の文字位置がそのまま対応する。

使い方
  python aozora_clean.py 入力フォルダ 出力フォルダ

出力
  出力フォルダ/<作品>.txt        整えた本文（UTF-8、改行CRLF）
  出力フォルダ/_gaiji_unresolved.txt  字が決まらず 〓 にした外字の一覧（作品・行・注記）
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# 照合プログラムと同じ定義（KANJI には、外字で入る CJK 拡張B以降の漢字も加えている。
# 照合プログラムでは外字が 〓 になり漢字扱いされるので、それに合わせるため）
KANJI = r"[㐀-䶿一-鿿豈-﫿々〆ヶ〇仝〓〻\U00020000-\U0003FFFF]"
GAIJI_RE = re.compile(r"※［＃([^］]*)］")
NOTE_RE = re.compile(r"［＃[^］]*］")
GAIJI_MARK = "〓"  # 字が決まらない外字の代用文字（1文字）

# 面区点番号: 「第3水準1-84-77」「感嘆符二つ、1-8-75」など
MENKUTEN_RE = re.compile(r"(?:水準|、)([12])-(\d{1,2})-(\d{1,2})(?=、|$)")
UCS_RE = re.compile(r"U\+([0-9A-Fa-f]{4,6})")

# 番号のない外字を手で指定したいときは、注記の中身（※［＃ と ］ の間）をキーにして書き足す
# 例: "「てへん＋弃」、（三）-132-2": "拚",
MANUAL = {}

# 外字として書かれた記号（例: ※［＃始め二重山括弧、1-1-52］）がルビや注記の印と
# 取り違えられないよう、処理中だけ私用領域の字に置き換える（1字のままなので位置は変わらない）
_SPECIAL = "《》｜［］＃※"
PROTECT = {c: chr(0xF0000 + i) for i, c in enumerate(_SPECIAL)}
RESTORE = str.maketrans({v: k for k, v in PROTECT.items()})


def gaiji_char(note):
    """外字注記の中身から字を返す。決まらなければ None。"""
    if note in MANUAL:
        return MANUAL[note]
    m = MENKUTEN_RE.search(note)
    if m:
        men, ku, ten = map(int, m.groups())
        # JIS X 0213 の面区点を EUC-JIS-2004 のバイト列にして復号する
        b = bytes([0xA0 + ku, 0xA0 + ten]) if men == 1 else bytes([0x8F, 0xA0 + ku, 0xA0 + ten])
        try:
            return b.decode("euc_jis_2004")
        except UnicodeDecodeError:
            return None
    m = UCS_RE.search(note)
    if m:
        return chr(int(m.group(1), 16))
    return None


def parse_line(line, unresolved=None):
    """1行を (ルビ・注記を除いた本文, [(開始, 終了, 親文字, ルビ)]) に分ける。
    照合プログラムの parse_line と同じ処理で、外字だけを本来の字に置き換える。"""
    def sub_gaiji(m):
        ch = gaiji_char(m.group(1))
        if ch is None:
            if unresolved is not None:
                unresolved.append(m.group(1))
            return GAIJI_MARK
        # 《》｜［］ などの記号は、ルビ・注記の処理が終わるまで仮の字にしておく
        return PROTECT.get(ch, ch)

    line = GAIJI_RE.sub(sub_gaiji, line)
    line = NOTE_RE.sub("", line)
    out, rubies, bar, i = [], [], None, 0
    while i < len(line):
        c = line[i]
        if c == "｜":
            bar = len(out)
            i += 1
            continue
        if c == "《":
            j = line.find("》", i)
            if j < 0:
                out.append(c)
                i += 1
                continue
            ruby = line[i + 1:j]
            end = len(out)
            if bar is not None:
                start = bar
            else:  # 直前の漢字列が親文字
                start = end
                while start > 0 and re.match(KANJI, out[start - 1]):
                    start -= 1
            if start < end:
                rubies.append((start, end, "".join(out[start:end]), ruby))
            bar = None
            i = j + 1
            continue
        out.append(c)
        i += 1
    text = "".join(out).translate(RESTORE)
    rubies = [(s, e, b.translate(RESTORE), r.translate(RESTORE)) for s, e, b, r in rubies]
    return text, rubies


def read_text(path):
    """UTF-8 / Shift_JIS を自動判別して行のリストを返す。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            pass
    return raw.decode("cp932", errors="replace").splitlines()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_dir")
    ap.add_argument("output_dir")
    args = ap.parse_args()

    src, dst = Path(args.input_dir), Path(args.output_dir)
    dst.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.glob("*.txt") if not p.name.startswith("_"))
    stats = Counter()
    unresolved_rows = []
    for f in files:
        out_lines = []
        for ln, line in enumerate(read_text(f), 1):
            stats["外字"] += line.count("※［＃")
            unresolved = []
            text, rubies = parse_line(line, unresolved)
            stats["ルビ"] += len(rubies)
            for note in unresolved:
                unresolved_rows.append(f"{f.stem}\t{ln}\t※［＃{note}］")
            out_lines.append(text)
        (dst / f.name).write_bytes(("\r\n".join(out_lines) + "\r\n").encode("utf-8"))

    (dst / "_gaiji_unresolved.txt").write_text(
        "作品\t行\t注記\n" + "".join(r + "\n" for r in unresolved_rows), encoding="utf-8")
    n_un = len(unresolved_rows)
    print(f"{len(files)} 件を処理しました。")
    print(f"ルビ {stats['ルビ']} 件を削除。外字 {stats['外字']} 件のうち "
          f"{stats['外字'] - n_un} 件を置き換え、{n_un} 件は 〓 にしました"
          f"（一覧: {dst / '_gaiji_unresolved.txt'}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
