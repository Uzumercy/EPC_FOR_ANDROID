# v5 ビルド記録（2026-11-19）

3枚統合（DISC1 11CD081 + 21CD10Z + 21CD08X）で Android アプリ v5.0 をビルドした。

## コンバーター拡張（converter/）

- `epcconv/parsers.py`: PLMST末尾パーサを C班の汎用文法に差し替え
  （備考欄は固定3バイト、コードは常に group+9 開始。旧文法が成功した
  レコードでは解釈一致を全件確認済み）。3枚とも末尾パース 100%。
- `epcconv/isosrc.py`: `DiscSet(..., master_disc=N)` を追加。ルートマスタ
  （KSRBHMH.CD / SYSBMST.CD）を指定ディスクから取る（未指定時は従来の
  先勝ち）。カタログ所有は従来どおり引数順の先勝ち。
- `convert_epc.py`: `--master-disc N` / `--db-name NAME` オプション追加。
- `epcconv/stages.py`: 出力DB名を `--db-name` から取得。figures ステージは
  既存PNGがあれば検証（ロード＋寸法一致）のうえ再利用する。

実行コマンド:

```sh
python3 converter/convert_epc.py --iso cd/HONDA_EPC.ISO \
  --iso2 cd2/21CD10Z.iso --iso2 cd2/21CD08X.iso \
  --master-disc 1 --db-name epc_v5.db --out v5out
```

カタログ採用: DISC1=82 / 10Z=97（共有81含む）/ 08Xのみ=19 → 計198。
マスタは 10Z（KSRBHMH 29,536件・209カタログ、SYSBMST 209件）。

## 統合DB epc_v5.db（v5out/epc_v5.db、335,503,360 バイト）

| テーブル | 件数 |
|---|---|
| catalogs | 198 |
| models | 27,935（198カタログ分。マスタ全件は29,536） |
| groups / block_groups | 1,484 / 1,484 |
| blocks | 37,564（うち png あり 37,563） |
| parts | 1,300,190 |
| hotspots | 1,082,915 |
| equip | 209 |

- figure_map: 37,563件すべて drawcode・スコア1.0 で割当。
  未割当は 11TW2A01 B-42（subなし）の1件のみ＝既知の未参照28部品で、
  検索にのみ現れる正しい姿。
- 適用コードのカバレッジ: 全行で部品コードが所属カタログのモデルID
  空間に 100% 収まることを確認。
- コードなし部品の割合: DISC1分 18.0%（v4 と同率。文法修正で旧失敗
  247件のうち232件がコードを回復）、10Z分 29.1%、08Xのみ分 24.4%
  （DISC2側のデータ特性）。
- 図デコード: 38,416件・失敗0（うち既存PNG再利用 22,453件）。

## 図パック

`v5out/packs/` に198本生成（計1,279.6MB）。DISC2側116本
（783,352,980 バイト）をプロジェクトの `packs/` へ追加し、計198本に。
形式は従来と同一（ZIP_STORED、`<catalog>/<subdir>/<name>.png`）。

## Android アプリ v5.0

- `android/epc-search-v5.apk`（67,044,611 バイト、versionCode 16 /
  versionName 5.0、署名は v4 系と同一鍵）。
- AndroidManifest: versionCode 15→16、versionName 4.9.2→5.0。
- MainActivity: 同梱DB名 epc_v4.db→epc_v5.db、DB_VERSION 5→6
  （アップグレード時に再コピーを強制）。userdata.db と
  localStorage キー（epc_fav_cars_v4 / epc_cart_v4 / epc_sec_bm_v4 /
  epc_subs_v1）は不変。
- index.html ヘッダー: 「全カタログ版 v5.0 ・ DISC1+DISC2
  (11CD081 / 21CD08X / 21CD10Z)」（表示箇所2件）。
- 旧アセットDBは `android/epc_v4.db.bak` として保全（バイト不変）。
- ビルドスクリプトは `android/build_v5.sh`（build_v4.sh の出力名変更版）。
- スモークテスト: ホーム車種810件、部品番号 957010601208 の逆引き
  3,943件（DISC1のみ時代は1,153件）、NSX（11SL001）の図表示
  （部品31件・ホットスポット29件）、11TW2A01 B-42 の png=NULL・28部品。

## 備考

- 途中で VM が再起動し figures ステージが中断したが、スタンプ
  （extract / index）と再利用機構により損失なく再開できた。
- epc_v4.db 本体・v4系APK には手を入れていない。GitHub への push は
  していない（変換コードと本書のコミットは未実施）。
