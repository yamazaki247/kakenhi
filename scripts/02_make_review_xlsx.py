#!/usr/bin/env python3
"""形態素解析の結果（<作品>_morphs.txt）から、人手確認用のエクセルを作る。

01_keitaisokaiseki_ruby_autocorret.py の出力フォルダにある *_morphs.txt をすべて読み、
同じ名前の .xlsx（例: 005_127_羅生門_morphs.xlsx）を作る。
列は morphs の14列のあとに、確認用の空欄の3列を加える。
    O列: 判定　P列: エラーの種類　Q列: 正解、備考

すでに同じ名前の .xlsx があるときは、記入した内容を消さないよう上書きしない。
作り直したいときは、その .xlsx を削除してから実行する。

使い方:
    下の「設定」でフォルダを指定してから
    python 02_make_review_xlsx.py
    を実行する。

必要なもの: pip install openpyxl
"""
import glob
import os
import sys

from openpyxl import Workbook

# ================================================================ 設定
INPUT_DIR = r"D:/Dropbox/KAKENHI_語彙データ/output"          # morphs.txt のあるフォルダ
OUTPUT_DIR = r"D:/Dropbox/KAKENHI_語彙データ/output_確認用"  # エクセルの出力フォルダ
# ================================================================

EXTRA_COLUMNS = ["判定", "エラーの種類", "正解、備考"]
NUMERIC_COLUMNS = {"語の連番", "行", "開始", "終了", "語彙素ID"}
# 見本に合わせた列幅（指定のない列はエクセルの既定の幅）
COLUMN_WIDTHS = {"A": 14.875, "C": 3.5, "D": 5.25, "K": 12.5, "L": 16.875, "P": 12.125, "Q": 10.25}


def convert(value, numeric):
    """セルの値にする。空欄は空のセル、数値の列は数値にする（UNK など数字でないものは文字のまま）。"""
    if value == "":
        return None
    if numeric:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def make_xlsx(src, dst):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    for col, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[col].width = width
    with open(src, encoding="utf-8") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        numeric = [h in NUMERIC_COLUMNS for h in header]
        ws.append(header + EXTRA_COLUMNS)
        n = 0
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                continue
            cells = line.split("\t")
            ws.append([convert(v, numeric[i] if i < len(numeric) else False)
                       for i, v in enumerate(cells)])
            n += 1
    wb.save(dst)
    return n


def main():
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*_morphs.txt")))
    if not files:
        print(f"morphs ファイルがありません: {INPUT_DIR}")
        return 1
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"入力フォルダ: {INPUT_DIR}")
    print(f"出力フォルダ: {OUTPUT_DIR}")
    made = skipped = 0
    for src in files:
        name = os.path.splitext(os.path.basename(src))[0] + ".xlsx"
        dst = os.path.join(OUTPUT_DIR, name)
        if os.path.exists(dst):
            print(f"既にあるので作りません: {name}")
            skipped += 1
            continue
        n = make_xlsx(src, dst)
        print(f"{name}: {n} 語")
        made += 1
    print(f"作成 {made} 件、既存のため省略 {skipped} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
