#!/usr/bin/env python3
"""青空文庫のテキストから本文だけを取り出す（第1段階）。

削除するもの
  - 冒頭: タイトル・著者名などの行と、
          【テキスト中に現れる記号について】の説明（-----で囲まれた部分）
  - 末尾: 底本・入力者などの情報
          （「［＃本文終わり］」があればそこから、なければ最後の「底本：」の行から）

本文中のルビ《》や注記［＃…］は残す（第2段階で処理する）。

使い方
  python aozora_honbun.py 入力フォルダ 出力フォルダ [--utf8]

  入力フォルダの *.txt をすべて処理し、同じファイル名で出力フォルダに保存する。
  文字コードは元と同じ Shift_JIS（cp932）・改行CRLF。--utf8 を付けると UTF-8 で保存する。
"""
import argparse
import re
import sys
from pathlib import Path

DASH = re.compile(r'^-{20,}\s*$')
TEIHON = re.compile(r'^(翻訳の)?底本[：:「]')
HONBUN_END = '［＃本文終わり］'


def extract(lines):
    """行のリストから本文部分を返す。(本文の行リスト, 開始の判定方法, 終了の判定方法)"""
    # 冒頭: -----で囲まれた記号の説明があれば、その2本目の線の次から
    dashes = [i for i, l in enumerate(lines[:100]) if DASH.match(l)]
    if len(dashes) >= 2:
        start, how_start = dashes[1] + 1, '記号説明の後'
    else:
        # 説明がない場合は、タイトル・著者の後の最初の空行の次から
        start = next((i + 1 for i, l in enumerate(lines) if not l.strip()), 0)
        how_start = 'タイトル後の空行の後'

    # 末尾: ［＃本文終わり］ → 最後の「底本：」の行
    ends = [i for i, l in enumerate(lines) if HONBUN_END in l and i >= start]
    if ends:
        end, how_end = ends[-1], '［＃本文終わり］'
    else:
        teihon = [i for i, l in enumerate(lines) if TEIHON.match(l) and i >= start]
        if not teihon:
            raise ValueError('本文の終わり（底本の行）が見つからない')
        end, how_end = teihon[-1], '底本の行'

    body = lines[start:end]
    # 前後の空行を取り除く
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return body, how_start, how_end


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input_dir')
    ap.add_argument('output_dir')
    ap.add_argument('--utf8', action='store_true', help='UTF-8で保存する（既定はShift_JIS）')
    args = ap.parse_args()

    src, dst = Path(args.input_dir), Path(args.output_dir)
    dst.mkdir(parents=True, exist_ok=True)
    enc = 'utf-8' if args.utf8 else 'cp932'

    files = sorted(src.glob('*.txt'))
    errors = 0
    for f in files:
        text = f.read_bytes().decode('cp932')
        try:
            body, how_start, how_end = extract(text.splitlines())
        except ValueError as e:
            print(f'エラー: {f.name}: {e}', file=sys.stderr)
            errors += 1
            continue
        (dst / f.name).write_bytes(('\r\n'.join(body) + '\r\n').encode(enc))
        if how_start != '記号説明の後' or how_end != '底本の行':
            print(f'注意: {f.name}: 開始={how_start}, 終了={how_end}')
    print(f'{len(files) - errors} / {len(files)} 件を処理しました。')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
