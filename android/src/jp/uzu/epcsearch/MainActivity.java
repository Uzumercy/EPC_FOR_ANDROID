package jp.uzu.epcsearch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.JsResult;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.Normalizer;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final int DB_VERSION = 5;
    private static final int REQ_PICK_PACK = 1001;
    private WebView webView;
    private SQLiteDatabase db;
    private SQLiteDatabase userDb;
    private final Object userDbLock = new Object();
    private String pendingPackCatalog = null;
    private final Map<String, Boolean> bundledCache = new HashMap<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            File dbFile = prepareDb();
            db = SQLiteDatabase.openDatabase(dbFile.getPath(), null, SQLiteDatabase.OPEN_READONLY);
        } catch (Exception e) {
            // DBが開けない場合は各ブリッジ呼び出しでエラー表示
        }
        try {
            userDb = openUserDb();
        } catch (Exception e) {
            userDb = null; // 代用品メモ機能のみ無効化（他機能は継続）
        }
        webView = new WebView(this);
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setBuiltInZoomControls(true);
        webView.getSettings().setDisplayZoomControls(false);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String url = request.getUrl().toString();
                String marker = "/fig/";
                int i = url.indexOf(marker);
                if (i >= 0 && url.contains("android_asset")) {
                    String rel = Uri.decode(url.substring(i + marker.length()));
                    WebResourceResponse r = serveFigure(rel);
                    if (r != null) return r;
                }
                return super.shouldInterceptRequest(view, request);
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onJsConfirm(WebView view, String url, String message,
                                       final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                    .setMessage(message)
                    .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int w) { result.confirm(); }
                    })
                    .setNegativeButton("キャンセル", new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int w) { result.cancel(); }
                    })
                    .setOnCancelListener(new DialogInterface.OnCancelListener() {
                        @Override public void onCancel(DialogInterface d) { result.cancel(); }
                    })
                    .show();
                return true;
            }
            @Override
            public boolean onJsAlert(WebView view, String url, String message,
                                     final JsResult result) {
                new AlertDialog.Builder(MainActivity.this)
                    .setMessage(message)
                    .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int w) { result.confirm(); }
                    })
                    .setOnCancelListener(new DialogInterface.OnCancelListener() {
                        @Override public void onCancel(DialogInterface d) { result.cancel(); }
                    })
                    .show();
                return true;
            }
        });
        webView.addJavascriptInterface(new Bridge(), "EPC");
        setContentView(webView);
        webView.loadUrl("file:///android_asset/index.html");
    }

    /** Figure image resolution: imported pack first, then bundled assets, else 1x1 transparent PNG. */
    private WebResourceResponse serveFigure(String rel) {
        try {
            File f = new File(packDir(), rel);
            if (f.isFile()) {
                return new WebResourceResponse("image/png", null, new FileInputStream(f));
            }
        } catch (Exception ignored) {}
        try {
            InputStream in = getAssets().open("fig/" + rel);
            return new WebResourceResponse("image/png", null, in);
        } catch (Exception ignored) {}
        // 1x1 transparent PNG
        byte[] px = new byte[] {
            (byte)0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,
            0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x06,0x00,0x00,0x00,0x1F,0x15,(byte)0xC4,
            (byte)0x89,0x00,0x00,0x00,0x0A,0x49,0x44,0x41,0x54,0x78,(byte)0x9C,0x63,0x00,0x01,0x00,0x00,
            0x05,0x00,0x01,0x0D,0x0A,0x2D,(byte)0xB4,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,0x44,(byte)0xAE,
            0x42,0x60,(byte)0x82 };
        return new WebResourceResponse("image/png", null, new java.io.ByteArrayInputStream(px));
    }

    private File packDir() {
        return new File(getFilesDir(), "figpacks");
    }

    private java.util.Map<Integer, String> equipCache = null;

    /** Equipment master (SYSBMST order): id -> display name, loaded once. */
    private java.util.Map<Integer, String> equipMap() {
        if (equipCache != null) return equipCache;
        java.util.Map<Integer, String> m = new java.util.HashMap<>();
        try {
            if (db != null) {
                Cursor cur = db.rawQuery("SELECT id, name FROM equip", null);
                while (cur.moveToNext()) m.put(cur.getInt(0), cur.getString(1));
                cur.close();
            }
        } catch (Exception ignored) {}
        equipCache = m;
        return m;
    }

    /** User-data DB (user-registered part info: substitute-part memos, and
     *  future user data such as stock memos). Design rules:
     *  - Single self-contained SQLite file (files/userdata.db). No absolute
     *    paths or device-specific state inside the data tables, so copying
     *    this one file to another device carries all user data with it.
     *  - Fully separate from the bundled read-only base DB (epc_v4.db):
     *    prepareDb()/DB_VERSION re-copies never touch it, so user data
     *    survives base-DB replacements.
     *  - subs is a plain self-describing schema: the original part number,
     *    the substitute part number, the memo text, and created/updated
     *    timestamps (ISO strings) — everything a future migration needs. */
    private SQLiteDatabase openUserDb() {
        File f = new File(getFilesDir(), "userdata.db");
        SQLiteDatabase u = SQLiteDatabase.openOrCreateDatabase(f, null);
        u.execSQL("CREATE TABLE IF NOT EXISTS subs(" +
            "id INTEGER PRIMARY KEY AUTOINCREMENT, partno TEXT NOT NULL, " +
            "sub TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', " +
            "created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')");
        u.execSQL("CREATE INDEX IF NOT EXISTS idx_subs_partno ON subs(partno)");
        u.execSQL("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)");
        return u;
    }

    private File prepareDb() throws Exception {
        File out = new File(getFilesDir(), "epc_v4.db");
        SharedPreferences p = getSharedPreferences("epc", Context.MODE_PRIVATE);
        if (out.exists() && p.getInt("dbver", 0) == DB_VERSION) return out;
        InputStream in = getAssets().open("epc_v4.db");
        OutputStream os = new FileOutputStream(out);
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
        os.close(); in.close();
        p.edit().putInt("dbver", DB_VERSION).apply();
        return out;
    }

    @Override
    public void onBackPressed() {
        if (webView != null) {
            webView.evaluateJavascript("window.App && App.back()", null);
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_PICK_PACK) return;
        final String catalog = pendingPackCatalog;
        pendingPackCatalog = null;
        if (resultCode != RESULT_OK || data == null || data.getData() == null || catalog == null) {
            notifyPack(catalog, false, 0);
            return;
        }
        final Uri uri = data.getData();
        new Thread(new Runnable() {
            @Override public void run() {
                int count = 0;
                boolean ok = false;
                try {
                    count = importPack(catalog, uri);
                    ok = count > 0;
                } catch (Exception e) {
                    ok = false;
                }
                notifyPack(catalog, ok, count);
            }
        }).start();
    }

    private int importPack(String catalog, Uri uri) throws Exception {
        File base = packDir();
        if (!base.exists()) base.mkdirs();
        String basePath = base.getCanonicalPath();
        int count = 0;
        InputStream in = getContentResolver().openInputStream(uri);
        ZipInputStream zis = new ZipInputStream(in);
        byte[] buf = new byte[65536];
        ZipEntry e;
        while ((e = zis.getNextEntry()) != null) {
            String name = e.getName();
            if (e.isDirectory() || !name.endsWith(".png")) continue;
            File out = new File(base, name);
            if (!out.getCanonicalPath().startsWith(basePath + File.separator)) continue; // zip-slip guard
            File parent = out.getParentFile();
            if (parent != null && !parent.exists()) parent.mkdirs();
            OutputStream os = new FileOutputStream(out);
            int n;
            while ((n = zis.read(buf)) > 0) os.write(buf, 0, n);
            os.close();
            count++;
        }
        zis.close();
        if (count > 0) {
            OutputStream mos = new FileOutputStream(new File(base, catalog + ".ok"));
            mos.write(String.valueOf(count).getBytes("UTF-8"));
            mos.close();
        }
        return count;
    }

    private void notifyPack(final String catalog, final boolean ok, final int count) {
        if (catalog == null || webView == null) return;
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override public void run() {
                webView.evaluateJavascript(
                    "window.App && App.onPackImported('" + catalog + "'," + ok + "," + count + ")", null);
            }
        });
    }

    private boolean isBundled(String catalog) {
        Boolean b = bundledCache.get(catalog);
        if (b != null) return b;
        boolean v = false;
        try {
            String[] list = getAssets().list("fig/" + catalog);
            v = list != null && list.length > 0;
        } catch (Exception ignored) {}
        bundledCache.put(catalog, v);
        return v;
    }

    private JSONArray queryJson(String sql, String... args) throws Exception {
        JSONArray rows = new JSONArray();
        Cursor cur = db.rawQuery(sql, args);
        String[] cols = cur.getColumnNames();
        while (cur.moveToNext()) {
            JSONObject r = new JSONObject();
            for (int i = 0; i < cols.length; i++) {
                if (cur.isNull(i)) r.put(cols[i], JSONObject.NULL);
                else if (cur.getType(i) == Cursor.FIELD_TYPE_INTEGER) r.put(cols[i], cur.getLong(i));
                else if (cur.getType(i) == Cursor.FIELD_TYPE_FLOAT) r.put(cols[i], cur.getDouble(i));
                else r.put(cols[i], cur.getString(i));
            }
            rows.put(r);
        }
        cur.close();
        return rows;
    }

    private JSONObject wrap(String key, JSONArray rows) {
        JSONObject result = new JSONObject();
        try {
            if (db == null) { result.put("error", "DBを開けませんでした"); return result; }
            result.put(key, rows);
        } catch (Exception e) {
            try { result.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
        }
        return result;
    }

    public class Bridge {
        @JavascriptInterface
        public void finish() {
            new Handler(Looper.getMainLooper()).post(new Runnable() {
                @Override public void run() { MainActivity.this.finish(); }
            });
        }

        @JavascriptInterface
        public String home() {
            try {
                JSONArray cars = queryJson(
                    "SELECT DISTINCT name, type_full, type_code, catalog FROM models ORDER BY name, type_full");
                JSONObject result = wrap("cars", cars);
                result.put("catalogs", queryJson("SELECT catalog, label FROM catalogs ORDER BY catalog"));
                return result.toString();
            } catch (Exception e) {
                return wrap("cars", new JSONArray()).toString();
            }
        }

        @JavascriptInterface
        public String variants(String catalog) {
            try {
                JSONArray rows = queryJson(
                    "SELECT name, type_full, grade, trans, engine, serial_from, serial_to, ids " +
                    "FROM models WHERE catalog = ? ORDER BY name, type_full, serial_from, grade, trans",
                    catalog);
                // tags: equipment names for this spec. The model tail (ids) is
                // [band pair (2k-1, 2k), equipment indices...]; the equipment
                // indices past the first two values key into the equip table
                // (SYSBMST record order). Deduped, ascending, joined.
                java.util.Map<Integer, String> equip = equipMap();
                for (int i = 0; i < rows.length(); i++) {
                    JSONObject r = rows.getJSONObject(i);
                    java.util.TreeSet<Integer> eq = new java.util.TreeSet<>();
                    String idsCsv = r.optString("ids", "");
                    String[] parts = idsCsv.isEmpty() ? new String[0] : idsCsv.split(",");
                    for (int k = 2; k < parts.length; k++) {
                        try { eq.add(Integer.parseInt(parts[k].trim())); }
                        catch (Exception ignored) {}
                    }
                    StringBuilder sb = new StringBuilder();
                    for (Integer id : eq) {
                        String nm = equip.get(id);
                        if (nm == null || nm.isEmpty()) continue;
                        if (sb.length() > 0) sb.append(" / ");
                        sb.append(nm);
                    }
                    r.put("tags", sb.toString());
                }
                return wrap("rows", rows).toString();
            } catch (Exception e) { return wrap("rows", new JSONArray()).toString(); }
        }

        @JavascriptInterface
        public String groups(String catalog) {
            try {
                return wrap("rows", queryJson(
                    "SELECT g.seq, g.gno, g.name, g.code, " +
                    "(SELECT COUNT(*) FROM blocks b JOIN block_groups bg " +
                    "  ON bg.catalog = b.catalog AND bg.block = b.block " +
                    "  AND CAST(b.figure AS INTEGER) BETWEEN bg.fig_from AND bg.fig_to " +
                    "  WHERE b.catalog = g.catalog AND bg.group_seq = g.seq) AS nblocks " +
                    "FROM groups g WHERE g.catalog = ? ORDER BY g.seq", catalog)).toString();
            } catch (Exception e) { return wrap("rows", new JSONArray()).toString(); }
        }

        @JavascriptInterface
        public String blocks(String catalog, int groupSeq) {
            try {
                return wrap("rows", queryJson(
                    "SELECT b.block, b.figure, b.sub, b.title, b.drawcode FROM blocks b " +
                    "JOIN block_groups bg ON bg.catalog = b.catalog AND bg.block = b.block " +
                    "AND CAST(b.figure AS INTEGER) BETWEEN bg.fig_from AND bg.fig_to " +
                    "WHERE b.catalog = ? AND bg.group_seq = ? " +
                    "ORDER BY b.block, CAST(b.figure AS INTEGER), b.sub",
                    catalog, String.valueOf(groupSeq))).toString();
            } catch (Exception e) { return wrap("rows", new JSONArray()).toString(); }
        }

        @JavascriptInterface
        public String figure(String catalog, String block, String figure, String sub) {
            JSONObject result = new JSONObject();
            try {
                if (db == null) { result.put("error", "DBを開けませんでした"); return result.toString(); }
                JSONArray info = queryJson(
                    "SELECT blkid, title, drawcode, png, width, height FROM blocks " +
                    "WHERE catalog = ? AND block = ? AND figure = ? AND sub = ?",
                    catalog, block, figure, sub);
                if (info.length() > 0) {
                    JSONObject inf = info.getJSONObject(0);
                    result.put("info", inf);
                    String blkid = String.valueOf(inf.getLong("blkid"));
                    JSONArray partsArr = queryJson(
                        "SELECT id, item, partno, name_norm AS name, price, qty, gjson FROM parts " +
                        "WHERE blkid = ? ORDER BY CAST(item AS INTEGER)", blkid);
                    // codes column was dropped to save ~40MB; it is exactly the
                    // union of the per-group code lists inside gjson (set-verified
                    // over all 609,952 rows), so rebuild it here.
                    for (int i = 0; i < partsArr.length(); i++) {
                        JSONObject row = partsArr.getJSONObject(i);
                        StringBuilder codes = new StringBuilder();
                        try {
                            JSONArray gs = new JSONArray(row.optString("gjson", "[]"));
                            java.util.LinkedHashSet<Integer> seen = new java.util.LinkedHashSet<>();
                            for (int g = 0; g < gs.length(); g++) {
                                JSONArray cs = gs.getJSONArray(g).getJSONArray(1);
                                for (int k = 0; k < cs.length(); k++) seen.add(cs.getInt(k));
                            }
                            for (Integer c : seen) {
                                if (codes.length() > 0) codes.append(',');
                                codes.append(c.intValue());
                            }
                        } catch (Exception ignored) {}
                        row.put("codes", codes.toString());
                    }
                    result.put("parts", partsArr);
                    result.put("hotspots", queryJson(
                        "SELECT item, x1, y1, x2, y2 FROM hotspots WHERE blkid = ?", blkid));
                }
            } catch (Exception e) {
                try { result.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
            }
            return result.toString();
        }

        @JavascriptInterface
        public String search(String mode, String query) {
            JSONObject result = new JSONObject();
            try {
                if (db == null) { result.put("error", "DBを開けませんでした"); return result.toString(); }
                String cols =
                    "SELECT p.partno, p.name_norm AS name, p.price, b.catalog, b.block, b.figure, b.sub, p.item, " +
                    "IFNULL(c.label, b.catalog) AS label FROM parts p " +
                    "JOIN blocks b ON b.blkid = p.blkid " +
                    "LEFT JOIN catalogs c ON c.catalog = b.catalog ";
                JSONArray rows;
                if ("partno".equals(mode)) {
                    String q = query.toUpperCase().replaceAll("[\\s\\-]", "");
                    rows = queryJson(cols + "WHERE p.partno LIKE '%' || ? || '%' ORDER BY p.partno LIMIT 300", q);
                } else {
                    String q = Normalizer.normalize(query, Normalizer.Form.NFKC);
                    rows = queryJson(cols + "WHERE p.name_norm LIKE '%' || ? || '%' ORDER BY p.partno LIMIT 300", q);
                }
                result.put("rows", rows);
                result.put("count", rows.length());
            } catch (Exception e) {
                try { result.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
            }
            return result.toString();
        }

        @JavascriptInterface
        public String packState(String catalog) {
            JSONObject result = new JSONObject();
            try {
                result.put("bundled", isBundled(catalog));
                File marker = new File(packDir(), catalog + ".ok");
                result.put("imported", marker.isFile());
                int n = 0;
                if (db != null) {
                    Cursor cur = db.rawQuery(
                        "SELECT COUNT(*) FROM blocks WHERE catalog = ? AND png IS NOT NULL",
                        new String[] { catalog });
                    if (cur.moveToFirst()) n = cur.getInt(0);
                    cur.close();
                }
                result.put("figures", n);
            } catch (Exception e) {
                try { result.put("error", String.valueOf(e.getMessage())); } catch (Exception ignored) {}
            }
            return result.toString();
        }

        @JavascriptInterface
        public void pickPack(final String catalog) {
            new Handler(Looper.getMainLooper()).post(new Runnable() {
                @Override public void run() {
                    pendingPackCatalog = catalog;
                    Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("*/*");
                    intent.putExtra(Intent.EXTRA_MIME_TYPES,
                        new String[] { "application/zip", "application/x-zip-compressed", "application/octet-stream" });
                    try {
                        startActivityForResult(intent, REQ_PICK_PACK);
                    } catch (Exception e) {
                        pendingPackCatalog = null;
                        notifyPack(catalog, false, 0);
                    }
                }
            });
        }

        /* ---- user-data DB: substitute-part memos (userdata.db) ---- */

        private JSONObject subsError(String msg) {
            JSONObject r = new JSONObject();
            try { r.put("error", msg); } catch (Exception ignored) {}
            return r;
        }

        /** All substitute memos as flat rows ordered by partno, id.
         *  "ts" is updated_at (what the UI shows as the saved time);
         *  "created" is created_at. */
        @JavascriptInterface
        public String subsAll() {
            JSONObject result = new JSONObject();
            try {
                if (userDb == null) return subsError("ユーザDBを開けませんでした").toString();
                JSONArray rows = new JSONArray();
                synchronized (userDbLock) {
                    Cursor cur = userDb.rawQuery(
                        "SELECT id, partno, sub, text, created_at, updated_at " +
                        "FROM subs ORDER BY partno, id", null);
                    while (cur.moveToNext()) {
                        JSONObject r = new JSONObject();
                        r.put("id", cur.getLong(0));
                        r.put("partno", cur.getString(1));
                        r.put("sub", cur.getString(2));
                        r.put("text", cur.getString(3));
                        r.put("created", cur.getString(4));
                        r.put("ts", cur.getString(5));
                        rows.put(r);
                    }
                    cur.close();
                }
                result.put("rows", rows);
            } catch (Exception e) {
                return subsError(String.valueOf(e.getMessage())).toString();
            }
            return result.toString();
        }

        @JavascriptInterface
        public String subAdd(String partno, String sub, String text, String ts) {
            JSONObject result = new JSONObject();
            try {
                if (userDb == null) return subsError("ユーザDBを開けませんでした").toString();
                ContentValues v = new ContentValues();
                v.put("partno", partno == null ? "" : partno);
                v.put("sub", sub == null ? "" : sub);
                v.put("text", text == null ? "" : text);
                v.put("created_at", ts == null ? "" : ts);
                v.put("updated_at", ts == null ? "" : ts);
                long id;
                synchronized (userDbLock) { id = userDb.insertOrThrow("subs", null, v); }
                result.put("id", id);
            } catch (Exception e) {
                return subsError(String.valueOf(e.getMessage())).toString();
            }
            return result.toString();
        }

        @JavascriptInterface
        public String subUpdate(long id, String sub, String text, String ts) {
            JSONObject result = new JSONObject();
            try {
                if (userDb == null) return subsError("ユーザDBを開けませんでした").toString();
                ContentValues v = new ContentValues();
                v.put("sub", sub == null ? "" : sub);
                v.put("text", text == null ? "" : text);
                v.put("updated_at", ts == null ? "" : ts); // created_at preserved
                int n;
                synchronized (userDbLock) {
                    n = userDb.update("subs", v, "id=?", new String[] { String.valueOf(id) });
                }
                result.put("updated", n);
            } catch (Exception e) {
                return subsError(String.valueOf(e.getMessage())).toString();
            }
            return result.toString();
        }

        @JavascriptInterface
        public String subDelete(long id) {
            JSONObject result = new JSONObject();
            try {
                if (userDb == null) return subsError("ユーザDBを開けませんでした").toString();
                int n;
                synchronized (userDbLock) {
                    n = userDb.delete("subs", "id=?", new String[] { String.valueOf(id) });
                }
                result.put("deleted", n);
            } catch (Exception e) {
                return subsError(String.valueOf(e.getMessage())).toString();
            }
            return result.toString();
        }

        /** One-time import of the legacy v4.6 localStorage store
         *  (epc_subs_v1: {partno: [{sub, text, ts}]}). Guarded by the
         *  meta flag 'subs_imported' so it can never run twice; the
         *  legacy single ts becomes both created_at and updated_at.
         *  On any error nothing is committed and the flag stays unset,
         *  so the caller keeps the legacy copy and retries next launch. */
        @JavascriptInterface
        public String subsImport(String json) {
            JSONObject result = new JSONObject();
            try {
                if (userDb == null) return subsError("ユーザDBを開けませんでした").toString();
                int imported = 0;
                boolean skipped = false;
                synchronized (userDbLock) {
                    Cursor cur = userDb.rawQuery(
                        "SELECT value FROM meta WHERE key='subs_imported'", null);
                    boolean done = cur.moveToFirst();
                    cur.close();
                    if (done) {
                        skipped = true;
                    } else {
                        JSONObject o = new JSONObject(json == null ? "{}" : json);
                        userDb.beginTransaction();
                        try {
                            JSONArray names = o.names();
                            if (names != null) {
                                for (int i = 0; i < names.length(); i++) {
                                    String partno = names.getString(i);
                                    JSONArray arr = o.optJSONArray(partno);
                                    if (arr == null) continue;
                                    for (int j = 0; j < arr.length(); j++) {
                                        JSONObject m = arr.optJSONObject(j);
                                        if (m == null) continue;
                                        ContentValues v = new ContentValues();
                                        v.put("partno", partno);
                                        v.put("sub", m.optString("sub", ""));
                                        v.put("text", m.optString("text", ""));
                                        v.put("created_at", m.optString("ts", ""));
                                        v.put("updated_at", m.optString("ts", ""));
                                        userDb.insertOrThrow("subs", null, v);
                                        imported++;
                                    }
                                }
                            }
                            ContentValues mv = new ContentValues();
                            mv.put("key", "subs_imported");
                            mv.put("value", "1");
                            userDb.insertOrThrow("meta", null, mv);
                            userDb.setTransactionSuccessful();
                        } finally {
                            userDb.endTransaction();
                        }
                    }
                }
                result.put("imported", imported);
                result.put("skipped", skipped);
            } catch (Exception e) {
                return subsError(String.valueOf(e.getMessage())).toString();
            }
            return result.toString();
        }
    }
}
