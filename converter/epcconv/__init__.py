"""Honda EPC data converter package.

Converts the original EPC CD-ROM data (ISO images) into the data files
used by the EPC search app: an SQLite app database, per-catalog figure
image packs, and optionally single-file HTML viewers.

All record parsers in this package are ports of the project's proven
analysis scripts (repair_plmst.py, rebuild_models.py, prep_v4.py);
see EPC_FORMAT_REPORT.md for the format documentation they implement.
"""
