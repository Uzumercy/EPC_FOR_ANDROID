# Honda EPC 逆引き検索プロジェクト

ホンダ電子パーツカタログ（EPC）のデータ構造を解析し、本家 EPC には無い
「部品番号から使われている車種・使用箇所を逆引きする」検索アプリを
作るプロジェクトです。

## このリポジトリに含まれるもの

- **解析ドキュメント** — [EPC_FORMAT_REPORT.md](EPC_FORMAT_REPORT.md)
  （各 .CD ファイルのフォーマット仕様、図ファイルの復号方法など）
- **Android アプリのソース** — `android/`
  （完全オフライン動作、部品番号／部品名検索、車種→セクション→図の閲覧、
  図タップで部品を特定、代用品メモなど）
- **データコンバーター** — [`converter/`](converter/README.md)
  （正規の EPC データをお持ちの方が、ISO からアプリ用データを
  自分で生成するためのツール）
- **解析スクリプト群** — ルート直下の `*.py` と作業記録 `NOTES.md` /
  `V*BUILD.md`

## このリポジトリに含まれないもの

**ホンダのデータそのもの**（CD の ISO、抽出ファイル、部品 DB、
デコードした図、画像パック、署名済み APK）は著作権物のため
含まれていません。アプリ用データは、各自が正規に入手した EPC の
CD から、[コンバーター](converter/README.md) で生成してください。

## クイックスタート（データ生成）

```sh
pip install pycdlib Pillow
cd converter
python3 convert_epc.py --iso /path/to/HONDA_EPC.ISO --out ./out
# -> out/epc_v4.db と out/packs/*.zip が生成される
```

## 関連ドキュメント

| ファイル | 内容 |
|---|---|
| [EPC_FORMAT_REPORT.md](EPC_FORMAT_REPORT.md) | EPC データ構造の詳細レポート |
| [converter/README.md](converter/README.md) | データコンバーターの使い方 |
| [REQUIREMENTS.md](REQUIREMENTS.md) | アプリの要求仕様 |
| [NOTES.md](NOTES.md) | 解析作業メモ |
