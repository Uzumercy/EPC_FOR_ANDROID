"""Multi-disc ISO source abstraction.

The EPC data ships on CD-ROM.  DISC1 (11CD081, 2008-01) carries 82
catalogs; DISC2 (21CD...) carries the remaining catalogs of the model
master.  A conversion may use one or more ISO images: the first disc
wins for any catalog present on several discs, later discs only add
catalogs/files that are missing.  The Windows program on the FD
installer is not needed — every data file lives on the CDs.

Catalog priority is therefore simply the ISO argument order.  The
3-disc build (DISC1 11CD081 + 21CD10Z + 21CD08X, in that order) gives:
DISC1's 82 catalogs from DISC1, the 81 catalogs shared by both DISC2
editions from the newer 21CD10Z, the 19 catalogs unique to 21CD08X
from 21CD08X and the 16 unique to 21CD10Z from 21CD10Z — 198 catalogs
in total.

Root master files (KSRBHMH.CD, SYSBMST.CD) are the exception: they
are global, every disc carries its own edition, and the editions are
monotonic supersets (model master: 190 -> 193 -> 209 catalogs).  Pass
``master_disc`` (an index into the ISO list) to take the masters from
that disc instead of the first one — the 3-disc build uses the
21CD10Z masters (index 1 in the order above) so that the model table
and the equipment master match the newest data.  Without
``master_disc`` the historical first-disc-wins rule applies.
"""
import io
import os

import pycdlib

# per-catalog data files the converter reads from each catalog directory
CATALOG_FILES = ('PLMST.CD', 'GRPTBL.CD', 'BLKTBL.CD', 'BLKTYTBL.CD')
# master files read from the ISO root
ROOT_FILES = ('KSRBHMH.CD', 'SYSBMST.CD')


def _clean(fn):
    return fn.split(';')[0]


class DiscSet:
    """An ordered set of opened ISO images (index 0 = primary disc).

    ``master_disc``: optional index of the disc that provides the root
    master files (see module docstring).  Falls back to the first disc
    carrying a file when the master disc does not have it.
    """

    def __init__(self, iso_paths, master_disc=None):
        self.paths = [os.path.abspath(p) for p in iso_paths]
        if master_disc is not None and not 0 <= master_disc < len(self.paths):
            raise ValueError(f'master_disc {master_disc} out of range '
                             f'for {len(self.paths)} ISO(s)')
        self.master_disc = master_disc
        self.isos = []
        for p in self.paths:
            iso = pycdlib.PyCdlib()
            iso.open(p)
            self.isos.append(iso)
        self._catalog_owner = None     # catalog -> disc index
        self._catalog_files = None     # (catalog, name) -> iso path
        self._root_files = None        # name -> (disc index, iso path)

    def close(self):
        for iso in self.isos:
            iso.close()

    # ---------------------------------------------------------- indexes --
    def _build_index(self):
        if self._catalog_owner is not None:
            return
        self._catalog_owner = {}
        self._catalog_files = {}
        self._root_files = {}
        root_found = {}                # name -> {disc index: iso path}
        for di, iso in enumerate(self.isos):
            for dirpath, dirnames, filenames in iso.walk(iso_path='/'):
                parts = [p for p in dirpath.split('/') if p]
                names = {_clean(f): f for f in filenames}
                if len(parts) == 0:
                    for want in ROOT_FILES:
                        if want in names:
                            root_found.setdefault(want, {})[di] = \
                                dirpath.rstrip('/') + '/' + names[want]
                elif len(parts) == 1:
                    cat = parts[0]
                    if cat.upper().startswith('PROGRAM'):
                        continue
                    if 'PLMST.CD' not in names:
                        continue
                    if cat not in self._catalog_owner:
                        self._catalog_owner[cat] = di
                    if self._catalog_owner[cat] == di:
                        for want in CATALOG_FILES:
                            if want in names:
                                self._catalog_files[(cat, want)] = \
                                    dirpath.rstrip('/') + '/' + names[want]
        # root masters: the designated master disc wins when it carries
        # the file; otherwise the first disc that has it (legacy rule)
        for want, by_disc in root_found.items():
            if self.master_disc is not None \
                    and self.master_disc in by_disc:
                di = self.master_disc
            else:
                di = min(by_disc)
            self._root_files[want] = (di, by_disc[di])

    # ------------------------------------------------------------ reads --
    def read_iso_file(self, disc_index, iso_path):
        buf = io.BytesIO()
        self.isos[disc_index].get_file_from_iso_fp(buf, iso_path=iso_path)
        return buf.getvalue()

    def catalogs(self):
        """All catalog codes found across the discs, sorted."""
        self._build_index()
        return sorted(self._catalog_owner)

    def catalog_disc(self, catalog):
        self._build_index()
        return self._catalog_owner[catalog]

    def catalog_file(self, catalog, name):
        """Bytes of a per-catalog data file, from the owning disc.
        Returns None if the file is absent."""
        self._build_index()
        ip = self._catalog_files.get((catalog, name))
        if ip is None:
            return None
        return self.read_iso_file(self._catalog_owner[catalog], ip)

    def root_file(self, name):
        """Bytes of a root master file (from the master disc when one
        is designated and carries it, else the first disc that has it).
        Returns None if no disc has it."""
        self._build_index()
        hit = self._root_files.get(name)
        if hit is None:
            return None
        di, ip = hit
        return self.read_iso_file(di, ip)

    def root_file_disc(self, name):
        self._build_index()
        hit = self._root_files.get(name)
        return hit[0] if hit else None

    def missing_catalog_files(self):
        """{catalog: [missing names]} for files in CATALOG_FILES."""
        self._build_index()
        out = {}
        for cat in self._catalog_owner:
            miss = [n for n in CATALOG_FILES
                    if (cat, n) not in self._catalog_files]
            if miss:
                out[cat] = miss
        return out

    # ---------------------------------------------------------- figures --
    def walk_figure_files(self):
        """Yield (catalog, subdir, filename, data) for every file inside
        catalog directories (the figure files), walking each disc in
        order.  This mirrors batch_decode.py's traversal exactly: the
        PROGRAM tree is skipped, directories deeper than catalog/subdir
        are skipped, and a file already yielded from an earlier disc is
        not yielded again."""
        seen = set()
        for iso in self.isos:
            for dirpath, dirnames, filenames in iso.walk(iso_path='/'):
                parts = [p for p in dirpath.split('/') if p]
                if parts and parts[0].upper().startswith('PROGRAM'):
                    continue
                if len(parts) > 2:
                    continue
                catalog = parts[0] if parts else ''
                subdir = parts[1] if len(parts) > 1 else ''
                if not catalog or not catalog[0].isdigit():
                    continue
                for fn in filenames:
                    name = _clean(fn)
                    key = (catalog, subdir, name)
                    if key in seen:
                        continue
                    seen.add(key)
                    ip = dirpath.rstrip('/') + '/' + fn
                    buf = io.BytesIO()
                    try:
                        iso.get_file_from_iso_fp(buf, iso_path=ip)
                    except Exception:
                        continue
                    yield catalog, subdir, name, buf.getvalue()
