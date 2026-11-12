#!/usr/bin/env python3
"""Honda EPC data converter — ISO image(s) in, app data out.

    python3 convert_epc.py --iso HONDA_EPC.ISO --out ./out
    python3 convert_epc.py --iso DISC1.ISO --iso2 DISC2.ISO --out ./out
    python3 convert_epc.py --iso HONDA_EPC.ISO --out ./out \
        --ipad-catalogs 11SA702,11SC701

Outputs (into --out):
    epc_v4.db          Android app database
    packs/<CAT>.zip    per-catalog figure image packs
    epc-*.html         single-file HTML viewer (only with --ipad-catalogs)

Intermediate data lives in --work (default: <out>/work): the extracted
.CD files, the decoded figure PNGs and the master index database.
Each finished stage writes a stamp file there, so re-running the
command resumes where it stopped; use --force to redo stages, or
--stage extract,index,... to run specific stages (in pipeline order).

Only the CD ISO image(s) are needed.  The FD installer holds the
original Windows program and plays no role in the data conversion.

Requires: Python 3.10+, pycdlib, Pillow  (pip install pycdlib Pillow)
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from epcconv import stages          # noqa: E402
from epcconv.isosrc import DiscSet  # noqa: E402

STAGE_ORDER = ['extract', 'index', 'figures', 'figuremap', 'export',
               'packs', 'ipad']
STAGE_FUNCS = {
    'extract': stages.stage_extract,
    'index': stages.stage_index,
    'figures': stages.stage_figures,
    'figuremap': stages.stage_figuremap,
    'export': stages.stage_export,
    'packs': stages.stage_packs,
    'ipad': stages.stage_ipad,
}
DISC_STAGES = {'extract', 'figures'}


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--iso', action='append', required=True,
                    help='ISO image of an EPC data CD (DISC1 first). '
                         'Repeatable; later discs add catalogs.')
    ap.add_argument('--iso2', action='append', default=[],
                    help='additional ISO image (e.g. DISC2); same as '
                         'giving --iso again')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--work', default=None,
                    help='work directory (default: <out>/work)')
    ap.add_argument('--stage', default=None,
                    help='comma-separated stages to run, in pipeline '
                         'order (default: all applicable). Stages with '
                         'an existing stamp are normally skipped; naming '
                         'a stage here forces it to run.')
    ap.add_argument('--force', action='store_true',
                    help='re-run stages even if their stamp exists')
    ap.add_argument('--ipad-catalogs', default=None,
                    help='comma-separated catalog codes for which to '
                         'also build a single-file HTML viewer')
    ap.add_argument('--html', default=None,
                    help='app index.html used for the HTML viewer '
                         '(default: <project>/android/assets/index.html)')
    args = ap.parse_args()

    iso_paths = list(args.iso) + list(args.iso2)
    for p in iso_paths:
        if not os.path.exists(p):
            ap.error(f'ISO not found: {p}')
    args.work = args.work or os.path.join(args.out, 'work')
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    stamp_dir = os.path.join(args.work, 'stamps')
    os.makedirs(stamp_dir, exist_ok=True)

    if args.stage:
        wanted = [s.strip() for s in args.stage.split(',') if s.strip()]
        unknown = [s for s in wanted if s not in STAGE_ORDER]
        if unknown:
            ap.error(f'unknown stage(s): {unknown} '
                     f'(choose from {STAGE_ORDER})')
        run = [s for s in STAGE_ORDER if s in wanted]
        explicit = set(wanted)
    else:
        run = [s for s in STAGE_ORDER
               if s != 'ipad' or args.ipad_catalogs]
        explicit = set()
    if 'ipad' in run and not args.ipad_catalogs:
        ap.error('--stage ipad requires --ipad-catalogs')

    discs = None
    if any(s in DISC_STAGES for s in run):
        pending = [s for s in run if s in DISC_STAGES
                   and (args.force or s in explicit
                        or not os.path.exists(
                            os.path.join(stamp_dir, s + '.json')))]
        if pending:
            discs = DiscSet(iso_paths)

    ctx = stages.Ctx(args, discs, log)
    t_all = time.time()
    try:
        for name in run:
            stamp = os.path.join(stamp_dir, name + '.json')
            if (not args.force and name not in explicit
                    and os.path.exists(stamp)):
                log(f'stage {name}: skipped (stamp exists; '
                    f'use --force or --stage to redo)')
                continue
            if name in DISC_STAGES and discs is None:
                discs = ctx.discs = DiscSet(iso_paths)
            log(f'stage {name}: start')
            t0 = time.time()
            summary = STAGE_FUNCS[name](ctx)
            summary = summary or {}
            summary['seconds'] = round(time.time() - t0, 1)
            with open(stamp, 'w') as f:
                json.dump(summary, f, indent=1, ensure_ascii=False)
            log(f'stage {name}: done in {summary["seconds"]}s -> {summary}')
    finally:
        if discs is not None:
            discs.close()
    log(f'all done in {time.time() - t_all:.0f}s')
    log(f'outputs in {args.out}: epc_v4.db'
        + (', packs/' if 'packs' in run else '')
        + (' (+ HTML viewer)' if 'ipad' in run else ''))


if __name__ == '__main__':
    main()
