#!/usr/bin/env python3
"""Build a single-file HTML EPC viewer (iPad / desktop browser) from the
Android app's assets.

The Android UI (android/assets/index.html) talks to a native bridge exposed
as window.EPC whose methods return JSON strings.  This script generates an
export-only copy of that page in which window.EPC is a pure-JS shim backed
by data extracted from android/assets/epc_v4.db and figure PNGs embedded as
base64.  The android assets themselves are never modified.

Usage:
    python3 build_ipad.py [--catalogs 11SA702,11SC701] [--out epc-city.html]

Options:
    --catalogs   comma-separated catalog codes to include
                 (default: 11SA702,11SC701 = Honda City DISC1)
    --out        output file name, written next to this script
                 (default: epc-city.html for the City pair,
                  otherwise epc-<catalog>.html)
    --db         path to epc_v4.db   (default: ../android/assets/epc_v4.db)
    --figdir     figures root        (default: ../figures)
    --html       source index.html   (default: ../android/assets/index.html)

The queries mirror MainActivity.java's Bridge so behaviour (variant tags,
part "codes" rebuilt from gjson, search semantics) matches the Android app.
After writing the file, the script self-verifies: embedded record counts
against the DB, PNG magic of every embedded image, and (when node is
available) a syntax check of the generated page's scripts.
"""

import argparse
import base64
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

# ---------------------------------------------------------------- shim JS --
# EPC_DATA is injected between the two markers by the builder.
SHIM_JS = r"""
/* ===== iPad/browser export shim: replaces the Android native bridge ===== */
try { /* probe localStorage (may throw under some file:// settings) */
  window.localStorage.setItem('__epc_probe__', '1');
  window.localStorage.removeItem('__epc_probe__');
} catch (e) {
  var __mem = {};
  try {
    Object.defineProperty(window, 'localStorage', { value: {
      getItem: function(k) { return __mem.hasOwnProperty(k) ? __mem[k] : null; },
      setItem: function(k, v) { __mem[k] = String(v); },
      removeItem: function(k) { delete __mem[k]; }
    } });
  } catch (e2) {}
}
window.EPC = (function() {
  var D = EPC_DATA;
  var searchIndex = null;
  function js(o) { return JSON.stringify(o); }
  function buildIndex() {
    searchIndex = [];
    var labels = {};
    D.catalogs.forEach(function(c) { labels[c.catalog] = c.label || c.catalog; });
    Object.keys(D.figures).forEach(function(key) {
      var seg = key.split('|');
      D.figures[key].parts.forEach(function(p) {
        searchIndex.push({ partno: p.partno, name: p.name, price: p.price,
          catalog: seg[0], block: seg[1], figure: seg[2], sub: seg[3],
          item: p.item, label: labels[seg[0]] || seg[0] });
      });
    });
  }
  return {
    finish: function() { /* nowhere to go in a browser tab */ },
    pickPack: function(catalog) { /* all figures are embedded; never called */ },
    imgSrc: function(png) {
      var b = D.images[png];
      return b ? ('data:image/png;base64,' + b) : '';
    },
    home: function() { return js({ cars: D.cars, catalogs: D.catalogs }); },
    variants: function(catalog) { return js({ rows: D.models[catalog] || [] }); },
    groups: function(catalog) { return js({ rows: D.groups[catalog] || [] }); },
    blocks: function(catalog, seq) { return js({ rows: D.blocks[catalog + '|' + seq] || [] }); },
    figure: function(catalog, block, figure, sub) {
      return js(D.figures[catalog + '|' + block + '|' + figure + '|' + sub] || {});
    },
    packState: function(catalog) {
      return js({ bundled: true, imported: false, figures: D.packFigures[catalog] || 0 });
    },
    search: function(mode, query) {
      if (!searchIndex) buildIndex();
      var rows;
      if (mode === 'partno') {
        var q = String(query).toUpperCase().replace(/[\s\-]/g, '');
        rows = searchIndex.filter(function(r) {
          return String(r.partno).toUpperCase().indexOf(q) >= 0;
        });
      } else {
        var qn = String(query).normalize('NFKC');
        rows = searchIndex.filter(function(r) {
          return (r.name || '').indexOf(qn) >= 0;
        });
      }
      rows.sort(function(a, b) { return a.partno < b.partno ? -1 : (a.partno > b.partno ? 1 : 0); });
      rows = rows.slice(0, 300);
      return js({ rows: rows, count: rows.length });
    }
  };
})();
"""


# ------------------------------------------------------------- extraction --
def compute_tags(ids_csv, equip):
    """Mirror MainActivity.variants(): equipment indices are the model tail
    ids from the 3rd value on; deduped, ascending, names joined with ' / '."""
    if not ids_csv:
        return ""
    parts = ids_csv.split(",")
    eq = set()
    for k in range(2, len(parts)):
        try:
            eq.add(int(parts[k].strip()))
        except ValueError:
            pass
    names = []
    for eid in sorted(eq):
        nm = equip.get(eid)
        if nm:
            names.append(nm)
    return " / ".join(names)


def compute_codes(gjson_str):
    """Mirror MainActivity.figure(): codes = ordered union of the per-group
    code lists inside gjson."""
    try:
        groups = json.loads(gjson_str or "[]")
        seen, out = set(), []
        for g in groups:
            for c in g[1]:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return ",".join(str(c) for c in out)
    except Exception:
        return ""


def extract(db_path, figdir, catalogs):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ph = ",".join("?" for _ in catalogs)

    equip = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM equip")}

    data = {"catalogs": [], "cars": [], "models": {}, "groups": {},
            "blocks": {}, "figures": {}, "packFigures": {}, "images": {}}

    data["catalogs"] = [dict(r) for r in con.execute(
        f"SELECT catalog, label FROM catalogs WHERE catalog IN ({ph}) ORDER BY catalog",
        catalogs)]
    data["cars"] = [dict(r) for r in con.execute(
        "SELECT DISTINCT name, type_full, type_code, catalog FROM models "
        f"WHERE catalog IN ({ph}) ORDER BY name, type_full", catalogs)]

    for cat in catalogs:
        rows = []
        for r in con.execute(
                "SELECT name, type_full, grade, trans, engine, serial_from, "
                "serial_to, ids FROM models WHERE catalog = ? "
                "ORDER BY name, type_full, serial_from, grade, trans", (cat,)):
            d = dict(r)
            d["tags"] = compute_tags(d.get("ids"), equip)
            rows.append(d)
        data["models"][cat] = rows

        grows = [dict(r) for r in con.execute(
            "SELECT g.seq, g.gno, g.name, g.code, "
            "(SELECT COUNT(*) FROM blocks b JOIN block_groups bg "
            "  ON bg.catalog = b.catalog AND bg.block = b.block "
            "  AND CAST(b.figure AS INTEGER) BETWEEN bg.fig_from AND bg.fig_to "
            "  WHERE b.catalog = g.catalog AND bg.group_seq = g.seq) AS nblocks "
            "FROM groups g WHERE g.catalog = ? ORDER BY g.seq", (cat,))]
        data["groups"][cat] = grows

        for g in grows:
            brows = [dict(r) for r in con.execute(
                "SELECT b.block, b.figure, b.sub, b.title, b.drawcode FROM blocks b "
                "JOIN block_groups bg ON bg.catalog = b.catalog AND bg.block = b.block "
                "AND CAST(b.figure AS INTEGER) BETWEEN bg.fig_from AND bg.fig_to "
                "WHERE b.catalog = ? AND bg.group_seq = ? "
                "ORDER BY b.block, CAST(b.figure AS INTEGER), b.sub",
                (cat, g["seq"]))]
            data["blocks"][f"{cat}|{g['seq']}"] = brows

        data["packFigures"][cat] = con.execute(
            "SELECT COUNT(*) FROM blocks WHERE catalog = ? AND png IS NOT NULL",
            (cat,)).fetchone()[0]

    # figures: info + parts + hotspots for every block of the target catalogs
    pngs = set()
    for b in con.execute(
            "SELECT blkid, catalog, block, figure, sub, title, drawcode, png, "
            f"width, height FROM blocks WHERE catalog IN ({ph})", catalogs):
        info = {k: b[k] for k in
                ("blkid", "title", "drawcode", "png", "width", "height")}
        parts = []
        for p in con.execute(
                "SELECT id, item, partno, name_norm AS name, price, qty, gjson "
                "FROM parts WHERE blkid = ? ORDER BY CAST(item AS INTEGER)",
                (b["blkid"],)):
            d = dict(p)
            d["codes"] = compute_codes(d.get("gjson"))
            parts.append(d)
        hotspots = [dict(h) for h in con.execute(
            "SELECT item, x1, y1, x2, y2 FROM hotspots WHERE blkid = ?",
            (b["blkid"],))]
        key = f"{b['catalog']}|{b['block']}|{b['figure']}|{b['sub']}"
        if key in data["figures"]:
            print(f"WARNING: duplicate figure key {key} (blkid {b['blkid']})",
                  file=sys.stderr)
        data["figures"][key] = {"info": info, "parts": parts,
                                "hotspots": hotspots}
        if b["png"]:
            pngs.add(b["png"])

    for png in sorted(pngs):
        path = os.path.join(figdir, png)
        with open(path, "rb") as fh:
            data["images"][png] = base64.b64encode(fh.read()).decode("ascii")

    con.close()
    return data


# ----------------------------------------------------------------- build --
def json_for_script(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # keep the payload from terminating the <script> element / line terms
    return (s.replace("</", "<\\/")
             .replace("\u2028", "\\u2028")
             .replace("\u2029", "\\u2029"))


def build(html_src, out_path, catalogs, data):
    with open(html_src, encoding="utf-8") as fh:
        html = fh.read()

    subtitle = "単一HTML版（収録: " + ", ".join(catalogs) + "）・ DISC1 (11CD081 / 2008-01)"
    n = html.count("全カタログ版 v4 ・ DISC1 (11CD081 / 2008-01)")
    html = html.replace("全カタログ版 v4 ・ DISC1 (11CD081 / 2008-01)", subtitle)
    html = html.replace("全カタログから検索", "収録カタログから検索")

    old_img = "src=\"fig/' + esc(info.png) + '\""
    assert html.count(old_img) == 1, "img src pattern not found exactly once"
    html = html.replace(old_img, "src=\"' + EPC.imgSrc(info.png) + '\"")

    shim = ("<script>\nvar EPC_DATA = " + json_for_script(data) + ";\n"
            + SHIM_JS + "\n</script>\n")
    anchor = '<div id="toast"></div>\n<script>'
    assert html.count(anchor) == 1, "script anchor not found exactly once"
    html = html.replace(anchor, '<div id="toast"></div>\n' + shim + "<script>")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"subtitle replacements: {n}")
    return out_path


# ---------------------------------------------------------------- verify --
def verify(out_path, db_path, catalogs):
    import re
    with open(out_path, encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r"var EPC_DATA = (\{.*?\});\n", html, re.S)
    assert m, "EPC_DATA not found in generated HTML"
    data = json.loads(m.group(1))

    con = sqlite3.connect(db_path)
    ph = ",".join("?" for _ in catalogs)
    exp = {
        "models": con.execute(
            f"SELECT COUNT(*) FROM models WHERE catalog IN ({ph})",
            catalogs).fetchone()[0],
        "figures": con.execute(
            f"SELECT COUNT(*) FROM blocks WHERE catalog IN ({ph})",
            catalogs).fetchone()[0],
        "parts": con.execute(
            "SELECT COUNT(*) FROM parts p JOIN blocks b ON b.blkid = p.blkid "
            f"WHERE b.catalog IN ({ph})", catalogs).fetchone()[0],
        "hotspots": con.execute(
            "SELECT COUNT(*) FROM hotspots h JOIN blocks b ON b.blkid = h.blkid "
            f"WHERE b.catalog IN ({ph})", catalogs).fetchone()[0],
        "images": con.execute(
            "SELECT COUNT(DISTINCT png) FROM blocks "
            f"WHERE catalog IN ({ph}) AND png IS NOT NULL",
            catalogs).fetchone()[0],
    }
    got = {
        "models": sum(len(v) for v in data["models"].values()),
        "figures": len(data["figures"]),
        "parts": sum(len(f["parts"]) for f in data["figures"].values()),
        "hotspots": sum(len(f["hotspots"]) for f in data["figures"].values()),
        "images": len(data["images"]),
    }
    ok = True
    for k in exp:
        mark = "OK " if exp[k] == got[k] else "MISMATCH"
        if exp[k] != got[k]:
            ok = False
        print(f"  {mark} {k}: db={exp[k]} html={got[k]}")

    png_magic = b"\x89PNG\r\n\x1a\n"
    bad = [k for k, v in data["images"].items()
           if not base64.b64decode(v).startswith(png_magic)]
    print(f"  {'OK ' if not bad else 'MISMATCH'} images PNG magic: "
          f"{len(data['images']) - len(bad)}/{len(data['images'])} valid")
    if bad:
        ok = False

    # syntax-check every inline script with node, when available
    scripts = re.findall(r"<script>\n(.*?)</script>", html, re.S)
    print(f"  inline scripts: {len(scripts)}")
    try:
        for i, s in enumerate(scripts):
            tmp = f"/tmp/epc_ipad_script_{i}.js"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(s)
            r = subprocess.run(["node", "--check", tmp],
                               capture_output=True, text=True)
            print(f"  {'OK ' if r.returncode == 0 else 'FAIL'} node --check script[{i}]"
                  + ("" if r.returncode == 0 else ": " + r.stderr.strip()[:300]))
            if r.returncode != 0:
                ok = False
            os.unlink(tmp)
    except FileNotFoundError:
        print("  node not found; JS syntax check skipped")
    print("VERIFY:", "ALL OK" if ok else "PROBLEMS FOUND")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogs", default="11SA702,11SC701",
                    help="comma-separated catalog codes")
    ap.add_argument("--out", default=None, help="output file name (in this dir)")
    ap.add_argument("--db", default=os.path.join(PROJECT, "android", "assets", "epc_v4.db"))
    ap.add_argument("--figdir", default=os.path.join(PROJECT, "figures"))
    ap.add_argument("--html", default=os.path.join(PROJECT, "android", "assets", "index.html"))
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    catalogs = [c.strip() for c in args.catalogs.split(",") if c.strip()]
    if args.out:
        out_name = args.out
    elif catalogs == ["11SA702", "11SC701"]:
        out_name = "epc-city.html"
    else:
        out_name = "epc-" + "_".join(c.lower() for c in catalogs) + ".html"
    out_path = os.path.join(HERE, out_name)

    print(f"catalogs: {catalogs}")
    data = extract(args.db, args.figdir, catalogs)
    print(f"extracted: models={sum(len(v) for v in data['models'].values())} "
          f"figures={len(data['figures'])} "
          f"parts={sum(len(f['parts']) for f in data['figures'].values())} "
          f"hotspots={sum(len(f['hotspots']) for f in data['figures'].values())} "
          f"images={len(data['images'])}")
    build(args.html, out_path, catalogs, data)
    size = os.path.getsize(out_path)
    print(f"wrote {out_path} ({size:,} bytes = {size / 1e6:.2f} MB)")
    if not args.no_verify:
        print("verifying...")
        if not verify(out_path, args.db, catalogs):
            sys.exit(1)


if __name__ == "__main__":
    main()
