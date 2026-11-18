#!/usr/bin/env python3
"""青空文庫テキストのルビと形態素解析結果を照合し、可能なら自動修正する。

使い方:
    下の「設定」で入力フォルダ・出力フォルダ・辞書フォルダを指定してから
    python ruby_check.py
    を実行する。入力フォルダ内のすべての .txt が対象になる。

出力（出力フォルダに作品ごとに作る）:
    <作品>_morphs.txt  解析結果（1行1語、タブ区切り）
        作品 語の連番 行 開始 終了 表層形 語彙素 読み ルビ 一致 品詞大分類 品詞詳細 語種 語彙素ID
    <作品>_ruby.txt    ルビごとの照合結果（判定・修正前後の読み。レビュー用）
    <作品>_spread.txt  ルビのない同じ表記で、解析の読みがルビと違う箇所（参考）
    _summary.txt       全作品の集計（ターミナルに出るものと同じ）

必要なもの: pip install fugashi と MeCab 用 UniDic、同じフォルダの aozora_clean.py
"""
import csv
import glob
import os
import re
from collections import Counter
from datetime import datetime

import fugashi

# ================================================================ 設定
INPUT_DIR = r"D:/Dropbox/KAKENHI_語彙データ/候補作品"    # 入力フォルダ
OUTPUT_DIR = r"D:/Dropbox/KAKENHI_語彙データ/output"  # 出力フォルダ
DIC_DIR = r"C:/unidic-cwj-202302_full"  # 辞書フォルダ（sys.dic のある場所）。None なら unidic-lite
KYU = False      # True: 旧仮名遣いの作品として照合する
NBEST = 100      # 自動修正で調べる候補の数
GOSHU_IDX = 12     # 語種の素性番号（dicrc の %f[12]）
LEMMA_ID_IDX = 28  # 語彙素IDの素性番号（dicrc の %f[28]）
# ================================================================

# ---------------------------------------------------------------- 前処理
# ルビ・注記の除去と外字の置き換えは、第2段階のプログラム aozora_clean.py と共通にする
# （このファイルと同じフォルダに aozora_clean.py を置くこと）。
# 外字 ※［＃…］ は面区点番号・Unicode番号から本来の字に置き換え、字が決まらないものだけ 〓 にする。
# 位置・行番号は第2段階の出力テキストと一致する。
import aozora_clean


def parse_line(line):
    """1行を (ルビを除いた本文, [(開始, 終了, 親文字, ルビ)]) に分ける。
    位置はルビ除去後の本文での文字位置。"""
    text, rubies = aozora_clean.parse_line(line)
    return text, [(s, e, base, expand_iteration(ruby)) for s, e, base, ruby in rubies]


def expand_iteration(s):
    """ルビ中の ゝ ゞ を展開する。"""
    r = []
    for c in s:
        if c == "ゝ" and r:
            r.append(r[-1])
        elif c == "ゞ" and r:
            r.append(chr(ord(r[-1]) + 1))
        else:
            r.append(c)
    return "".join(r)


# ---------------------------------------------------------------- 正規化
SMALL = str.maketrans("ぁぃぅぇぉっゃゅょゎ", "あいうえおつやゆよわ")


def hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def fold(s, kyu=False):
    """照合用の正規化（表示には使わない）。"""
    s = hira(s).translate(SMALL)
    s = s.replace("ゐ", "い").replace("ゑ", "え").replace("ゔ", "ぶ")
    if kyu:  # 歴史的仮名遣いの簡易変換（照合用なので完全でなくてよい）
        s = s.replace("てふ", "ちよう").replace("くわ", "か").replace("ぐわ", "が")
        s = re.sub(r"(?<=.)は", "わ", s)
        s = re.sub(r"(?<=.)[ひふへほ]", lambda m: "いうえお"["ひふへほ".index(m.group())], s)
        s = s.replace("やう", "よう").replace("かう", "こう").replace("さう", "そう")
        s = s.replace("たう", "とう")
    return s


def is_kana(s):
    return all("ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c in "ーゝゞヽヾ" for c in s)


def is_katakana(s):
    return all("ァ" <= c <= "ヺ" or c == "ー" for c in s)


# ---------------------------------------------------------------- 解析
def val(x):
    return "" if x is None or x == "*" else str(x)


def kata(s):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


class Tok:
    __slots__ = ("surface", "start", "end", "pos", "pos1", "pos_full", "goshu", "lemma_id",
                 "lemma", "kana", "unk", "ruby", "status", "orig_kana")

    def __init__(self, surface, start, w):
        self.surface = surface
        self.start = start
        self.end = start + len(surface)
        f = w.feature
        pos = [p for p in (f.pos1, f.pos2, f.pos3, f.pos4) if p and p != "*"]
        self.pos = "-".join(pos[:3])          # 照合処理用
        self.pos1 = pos[0] if pos else ""     # 品詞大分類
        self.pos_full = "-".join(pos)         # 品詞詳細
        # 語種と語彙素IDは dicrc の番号どおり素の素性列から取る（f[12], f[28]）
        raw = next(csv.reader([w.feature_raw or ""]), [])
        self.goshu = val(raw[GOSHU_IDX]) if len(raw) > GOSHU_IDX else ""
        self.lemma_id = val(raw[LEMMA_ID_IDX]) if len(raw) > LEMMA_ID_IDX else ""
        self.lemma = val(f.lemma) or surface
        self.unk = w.is_unk or not f.kana or f.kana == "*"
        self.kana = "" if self.unk else f.kana
        self.ruby = ""
        self.status = ""
        self.orig_kana = ""


def to_toks(text, nodes, offset=0):
    """ノード列を文字位置付きトークンにする（空白などで位置がずれないよう検索で合わせる）。"""
    toks, pos = [], 0
    for w in nodes:
        s = w.surface
        if not s:
            continue
        k = text.find(s, pos)
        if k < 0:
            k = pos
        toks.append(Tok(s, k + offset, w))
        pos = k + len(s)
    return toks


# ---------------------------------------------------------------- 照合
_tagger = None


def part_kana(part):
    """はみ出した部分（漢字を含む）を単独で解析した読み。"""
    return "".join(w.feature.kana or "?" for w in _tagger(part))


def reading_over(span, toks, kyu):
    """ルビ区間に重なるトークンの読みを取り出す。
    はみ出した部分の読みを削ってルビの付いた部分だけの読みにする。
    戻り値: (読み, 問題) 問題は None / "境界" / "未知語"。"""
    s, e = span[0], span[1]
    parts, problem = [], None
    for t in toks:
        if t.end <= s or t.start >= e:
            continue
        if t.unk:
            problem = problem or "未知語"
        k = t.kana
        left = t.surface[: max(0, s - t.start)]
        right = t.surface[len(t.surface) - max(0, t.end - e):] if t.end > e else ""
        for side, part in (("L", left), ("R", right)):
            if not part:
                continue
            if not is_kana(part):
                # 漢字を含む部分にはみ出している: その部分の読みで削れるか試す
                pk = fold(part_kana(part), kyu)
                fk = fold(k, kyu)
                if side == "R" and fk.endswith(pk) and len(pk) < len(fk):
                    k = k[:len(k) - len(pk)]
                elif side == "L" and fk.startswith(pk) and len(pk) < len(fk):
                    k = k[len(pk):]
                else:
                    problem = "境界"
                continue
            n = len(part)
            if side == "R":
                k = k[:-n] if len(k) >= n else ""
            else:
                k = k[n:]
        parts.append(k)
    return "".join(parts), problem


def judge(span, toks, kyu):
    rd, problem = reading_over(span, toks, kyu)
    ruby = span[3]
    if problem == "境界":
        return "判定保留", rd
    if problem == "未知語":
        return "未知語", rd
    if hira(rd) == hira(ruby):
        return "一致", rd
    if fold(rd, kyu) == fold(ruby, kyu):
        return "正規化一致", rd
    return "不一致", rd


OK = {"一致", "正規化一致"}

# 再解析の単位（句読点などで区切る）
CLAUSE_SEP = re.compile(r"[、。，．！？!?「」『』（）()―…・　]")


def junk(toks):
    """不自然な解の目安: 未知語の数と、仮名が記号扱いされたトークンの数。"""
    return sum(t.unk or (t.pos.startswith(("記号", "補助記号")) and is_kana(t.surface))
               for t in toks)


def outside(toks, spans):
    """どのルビ区間にも重ならないトークンの集合（位置・品詞・読み）。"""
    return {(t.start, t.end, t.pos, t.kana) for t in toks
            if all(t.end <= s or t.start >= e for s, e, _, _ in spans)}


def clauses(text):
    """(開始, 終了) の列。"""
    res, st = [], 0
    for m in CLAUSE_SEP.finditer(text):
        if m.start() > st:
            res.append((st, m.start()))
        st = m.end()
    if st < len(text):
        res.append((st, len(text)))
    return res


def try_fix(tagger, text, toks, spans, nbest, kyu):
    """不一致の区間を含む節を N-best で再解析し、ルビと合う解に差し替える。"""
    bad = [sp for sp in spans if judge(sp, toks, kyu)[0] not in OK]
    fixed_spans = set()
    for cs, ce in clauses(text):
        inside = [sp for sp in spans if sp[0] >= cs and sp[1] <= ce]
        if not any(sp in bad for sp in inside):
            continue
        # 節の端がトークンの境界になっていなければ差し替えない
        cur = [t for t in toks if t.start >= cs and t.end <= ce]
        if not cur or cur[0].start != cs or cur[-1].end != ce:
            continue
        base_score = sum(judge(sp, cur, kyu)[0] in OK for sp in inside)
        best, best_score = None, base_score
        sub = text[cs:ce]
        for path in tagger.nbestToNodeList(sub, nbest):
            cand = to_toks(sub, path, cs)
            if junk(cand) > junk(cur):  # ルビには合っても解析が崩れる候補は採らない
                continue
            if outside(cand, inside) != outside(cur, inside):
                continue  # ルビの付いていない部分の解析は変えない
            sc =sum(judge(sp, cand, kyu)[0] in OK for sp in inside)
            if sc > best_score:
                best, best_score = cand, sc
                if sc == len(inside):
                    break
        if best is None:
            continue
        # 差し替え（修正前の読みを残す）
        old = {(t.start, t.end): t.kana for t in cur}
        for t in best:
            o = old.get((t.start, t.end))
            if o != t.kana:
                t.orig_kana = o if o is not None else "(分割変更)"
        i0 = toks.index(cur[0])
        toks[i0:i0 + len(cur)] = best
        for sp in inside:
            if sp in bad and judge(sp, toks, kyu)[0] in OK:
                fixed_spans.add(sp)
    return fixed_spans


def supplement(span, toks):
    """未知語1語に区間がちょうど重なるとき、ルビを読みとして補う。"""
    s, e = span[0], span[1]
    cov = [t for t in toks if not (t.end <= s or t.start >= e)]
    if len(cov) == 1 and cov[0].unk:
        t = cov[0]
        extra = t.surface[e - t.start:] if t.end > e else ""
        if t.start == s and (not extra or is_kana(extra)):
            t.orig_kana = "(未知語)"
            t.kana = kata(span[3] + extra)
            return True
    return False


# ---------------------------------------------------------------- 本体
OUT_SUFFIXES = ("_morphs", "_ruby", "_spread", "_summary")

# 「一致」列に出す値（ルビの判定 → 一致／修正／不一致／保留）
MATCH_LABEL = {"一致": "一致", "正規化一致": "一致", "自動修正": "修正", "補完": "修正",
               "判定保留": "保留"}  # それ以外（不一致・義訓の疑い・未知語を含む）は「不一致」
MATCH_RANK = {"": 0, "一致": 1, "修正": 2, "保留": 3, "不一致": 4}


def merge_match(old, new):
    """1語に複数のルビがかかるときは、より問題のある方を残す。"""
    return new if MATCH_RANK[new] > MATCH_RANK[old] else old


def read_text(path):
    """UTF-8 / Shift_JIS を自動判別して行のリストを返す。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            pass
    return raw.decode("cp932", errors="replace").splitlines()


def body_range(lines):
    """青空文庫の冒頭（題名・記号の説明）と末尾（底本情報）を除いた本文の行範囲。"""
    start, end = 0, len(lines)
    dash = [i for i, l in enumerate(lines[:80]) if re.fullmatch(r"-{10,}", l.strip())]
    if len(dash) >= 2:
        start = dash[1] + 1
    for i in range(start, len(lines)):
        if lines[i].startswith("底本："):
            end = i
            break
    return start, end


def write(path, header, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")


def process_file(path, tagger):
    work = os.path.splitext(os.path.basename(path))[0]
    lines = read_text(path)
    b0, b1 = body_range(lines)

    tok_rows, ruby_rows, all_tok, ruby_dict = [], [], [], {}
    stats = Counter()
    seq = 0
    for ln in range(b0 + 1, b1 + 1):  # 行番号は元ファイルの行番号
        text, spans = parse_line(lines[ln - 1])
        if not text.strip():
            continue
        toks = to_toks(text, tagger(text))
        before = {sp: judge(sp, toks, KYU) for sp in spans}
        fixed = try_fix(tagger, text, toks, spans, NBEST, KYU)

        for sp in spans:
            s, e, base, ruby = sp
            st0, rd0 = before[sp]
            st, rd = judge(sp, toks, KYU)
            if sp in fixed:
                status = "自動修正"
            elif st in OK:
                status = st
            elif st == "未知語" and supplement(sp, toks):
                status, rd = "補完", ruby
            elif st == "判定保留":
                status = "判定保留"
            elif st == "未知語":
                status = "未知語を含む"
            elif is_katakana(ruby):
                status = "義訓の疑い"
            else:
                status = "不一致"
            stats[status] += 1
            if len(base) >= 2:  # 1字の親文字は送り仮名次第で読みが変わるので伝播しない
                ruby_dict.setdefault(base, set()).add(ruby)
            for t in toks:
                if not (t.end <= s or t.start >= e):
                    t.ruby = (t.ruby + "／" if t.ruby else "") + f"{base}《{ruby}》"
                    t.status = merge_match(t.status, MATCH_LABEL.get(status, "不一致"))
            ctx = text[max(0, s - 10):s] + "【" + base + "】" + text[e:e + 10]
            ruby_rows.append([work, ln, base, ruby, rd0 or "-", status,
                              rd if status in ("自動修正", "補完") else "", ctx])

        for t in toks:
            if t.surface.isspace():
                continue
            seq += 1
            tok_rows.append([work, seq, ln, t.start, t.end, t.surface, t.lemma, t.kana,
                             t.ruby, t.status, t.pos1, t.pos_full, t.goshu, t.lemma_id])
            all_tok.append((ln, text, t))

    # ルビのない同じ表記（ルビ伝播の参考）
    spread = []
    for ln, text, t in all_tok:
        if t.ruby or len(ruby_dict.get(t.surface, ())) != 1:
            continue
        r = next(iter(ruby_dict[t.surface]))
        if fold(t.kana, KYU) != fold(r, KYU):
            ctx = text[max(0, t.start - 10):t.start] + "【" + t.surface + "】" + text[t.end:t.end + 10]
            spread.append([work, ln, t.surface, r, t.kana or "(未知語)", ctx])

    out = os.path.join(OUTPUT_DIR, work)
    write(out + "_morphs.txt",
          ["作品", "語の連番", "行", "開始", "終了", "表層形", "語彙素", "読み", "ルビ", "一致",
           "品詞大分類", "品詞詳細", "語種", "語彙素ID"], tok_rows)
    write(out + "_ruby.txt",
          ["作品", "行", "親文字", "ルビ", "解析の読み", "判定", "修正後の読み", "文脈"], ruby_rows)
    write(out + "_spread.txt",
          ["作品", "行", "表層形", "他所のルビ", "解析の読み", "文脈"], spread)

    return work, seq, stats, len(spread)


STATUS_ORDER = ["一致", "正規化一致", "自動修正", "補完", "不一致", "義訓の疑い",
                "未知語を含む", "判定保留"]


def summary_line(name, n_words, stats, n_spread):
    detail = "、".join(f"{k} {stats[k]}" for k in STATUS_ORDER if stats[k])
    return (f"{name}: {n_words} 語／ルビ {sum(stats.values())} 件（{detail}）"
            f"／ルビのない同表記の相違 {n_spread}")


def main():
    global _tagger
    if DIC_DIR:
        rc = os.path.join(DIC_DIR, "dicrc")  # mecabrc の代わりに辞書の dicrc を使う
        tagger = fugashi.Tagger(f'-r "{rc}" -d "{DIC_DIR}"')
    else:
        tagger = fugashi.Tagger()
    _tagger = tagger
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = [p for p in sorted(glob.glob(os.path.join(INPUT_DIR, "*.txt")))
             if not os.path.splitext(p)[0].endswith(OUT_SUFFIXES)]
    if not files:
        print(f"入力フォルダに .txt がありません: {INPUT_DIR}")
        return
    lines = [f"実行日時: {datetime.now():%Y-%m-%d %H:%M}",
             f"入力フォルダ: {INPUT_DIR}",
             f"辞書: {DIC_DIR or 'unidic-lite'}",
             f"旧仮名遣いとして照合: {'する' if KYU else 'しない'}／N-best: {NBEST}",
             ""]
    for line in lines:
        print(line)
    total_words, total_stats, total_spread = 0, Counter(), 0
    for p in files:
        work, n, st, sp = process_file(p, tagger)
        line = summary_line(work, n, st, sp)
        print(line)
        lines.append(line)
        total_words += n
        total_stats += st
        total_spread += sp
    if len(files) > 1:
        line = summary_line(f"合計（{len(files)} 作品）", total_words, total_stats, total_spread)
        print(line)
        lines.append(line)
    with open(os.path.join(OUTPUT_DIR, "_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"出力先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
