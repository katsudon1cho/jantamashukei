# ベースイメージとして軽量な Python イメージを使用
FROM python:3.10-slim

# 必要なシステムパッケージをインストール
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && apt-get clean

# 作業ディレクトリを設定
WORKDIR /app

# Pythonライブラリをインストール
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# アプリのコードをコンテナ内にコピー
COPY . /app

# Flaskアプリが使用するポートを指定
EXPOSE 5000

# Flask アプリの起動コマンド
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
