import os
import cv2
import pytesseract
import difflib  # ← 類似度チェックのため追加
from flask import Flask, request, render_template, redirect, url_for
from PIL import Image


os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR/tessdata'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# ================================
# 1) members.txt から固定メンバーを読み込み
# ================================
def load_fixed_members(filepath='members.txt'):
    members = []
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                name = line.strip()
                if name:
                    members.append(name)
    return members

fixed_members = load_fixed_members('members.txt')

# 例: Windows環境の Tesseract 実行ファイルパス
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# ================================
# 2) 名前領域のOCR （日本語＋英数字）
# ================================
def ocr_read_image_for_name(image):
    """
    プレイヤー名領域をOCRする。
    """
    config_name = r"--psm 7 -c tessedit_char_blacklist=①②③④⑤⑥⑦⑧⑨"
    text = pytesseract.image_to_string(
        image,
        lang='jpn+eng',
        config=config_name
    )
    return text.strip()

# ================================
# 3) スコア領域のOCR（数字のみ）
# ================================
def ocr_read_image_for_score(image):
    config_digits_only = r"--psm 7 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(
        image,
        lang='eng',
        config=config_digits_only
    )
    return text.strip()

# ================================
# 4) 相対座標
# ================================
ROI_DEFINITIONS = {
    "player1_name":  (0.5925, 0.1793, 0.6744, 0.2218),
    "player1_score": (0.6018, 0.2356, 0.7058, 0.3172),
    "player2_name":  (0.6328, 0.3874, 0.6953, 0.4218),
    "player2_score": (0.6436, 0.4322, 0.7231, 0.4966),
    "player3_name":  (0.6761, 0.5552, 0.7539, 0.5931),
    "player3_score": (0.6881, 0.6034, 0.7662, 0.6667),
    "player4_name":  (0.7168, 0.7241, 0.7616, 0.7621),
    "player4_score": (0.7303, 0.7701, 0.8087, 0.8322),
}

# ================================
# 5) 画像ファイル → OCR
# ================================
def ocr_read_image_ratio(image_path):
    """
    各ROIを切り出して「名前」or「スコア」をOCR。
    """
    img = cv2.imread(image_path)
    if img is None:
        return {}

    h, w, _ = img.shape
    results = {}

    for roi_key, (rx1, ry1, rx2, ry2) in ROI_DEFINITIONS.items():
        x1 = int(rx1 * w)
        y1 = int(ry1 * h)
        x2 = int(rx2 * w)
        y2 = int(ry2 * h)

        roi = img[y1:y2, x1:x2]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)

        if "score" in roi_key:
            text = ocr_read_image_for_score(thresh)
        else:
            text = ocr_read_image_for_name(thresh)

        results[roi_key] = text.strip()
    return results

# ================================
# 6) ウマ計算用
# ================================
def custom_round(value):
    i = int(value)
    if (value - i) <= 0.5:
        return i
    else:
        return i + 1

def calculate_score(final_points_list):
    """
    ウマ10-30、30000点返し、5捨6入
    """
    sorted_list = sorted(final_points_list, key=lambda x: x[1], reverse=True)
    uma_list = [50, 10, -10, -30]
    player_score = {}
    for rank, (pname, points) in enumerate(sorted_list):
        base = (points - 30000)/1000
        score_raw = base + uma_list[rank]
        player_score[pname] = score_raw
    return player_score

# ================================
# 7) members.txt とのマッチング
# ================================
def match_with_fixed_members(raw_name, members, cutoff=0.7):
    """
    1) members.txt にある各 'member' を順に見て
       'member' が 'raw_name' に含まれていれば即マッチ
    2) 部分一致で該当が無ければ、従来どおり difflib.get_close_matches へ
    3) それでも無ければ None
    """
    # 1) 部分一致チェック
    for member in members:
        if member in raw_name:
            return member

    # 2) 類似度検索
    matches = difflib.get_close_matches(raw_name, members, n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    return None

# ================================
# 8) Flaskルーティング
# ================================
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('images')
        if not files:
            return redirect(url_for('index'))

        screenshot_scores = []
        all_players = set()

        for file in files:
            if file.filename == '':
                continue
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)

            # (1) OCR実行
            ocr_result = ocr_read_image_ratio(filepath)

            # (2) {正式名: スコア} dict を作成
            player_points = {}
            for i in range(1, 5):
                name_key = f"player{i}_name"
                score_key = f"player{i}_score"

                raw_name = ocr_result.get(name_key, "").replace(" ", "").replace("\n", "")
                raw_score = ocr_result.get(score_key, "").replace(" ", "").replace("\n", "")

                if not raw_name:
                    continue

                try:
                    score = int(raw_score)
                except ValueError:
                    score = 0

                # ★★ 修正: members(=fixed_members)を必ず第2引数に渡す ### CHANGED ###
                matched_name = match_with_fixed_members(raw_name, fixed_members, cutoff=0.7)
                if matched_name:
                    official_name = matched_name
                else:
                    # スキップ例
                    continue

                player_points[official_name] = score

            # (3) ウマ計算
            final_points_list = list(player_points.items())
            scores_dict = calculate_score(final_points_list)
            screenshot_scores.append(scores_dict)

            for pname in scores_dict.keys():
                all_players.add(pname)

        # (4) 表示用リスト化
        all_players = list(all_players)
        table_rows = []
        for scores_dict in screenshot_scores:
            row = []
            for p in all_players:
                row.append(scores_dict.get(p, 0))
            table_rows.append(row)

        # (5) 合計スコア
        total_scores = [0]*len(all_players)
        for row in table_rows:
            for i, val in enumerate(row):
                total_scores[i] += val

        return render_template('result.html',
                               players=all_players,
                               table_rows=table_rows,
                               total_scores=total_scores)
    else:
        return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
