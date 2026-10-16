#!/usr/bin/env python3
"""Build a MySQL database of BLS Local Area Unemployment Statistics (LAUS).

Downloads the LAUS flat files from the BLS time series server
(https://download.bls.gov/pub/time.series/la/), keeps every series and
observation for one reference year across all LAUS geographies, writes
cleaned tab-delimited files, and optionally loads them into MySQL.

BLS blocks anonymous scripted downloads, so a contact string (name and
email) must be supplied; it is sent only to BLS as the User-Agent header.

Usage
-----
    python build_laus_db.py --year 2023 --contact "Your Name you@example.edu"
    mysql --local-infile=1 -u root -p < out/load_laus_2023.sql

or load directly (needs `pip install pymysql`):

    python build_laus_db.py --year 2023 --contact "..." --load \
        --mysql-user root --mysql-password secret --database laus_2023
"""

import argparse
import html.parser
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://download.bls.gov/pub/time.series/la/"

# Lookup files: BLS file name -> (table name, columns kept, in schema order).
# Columns are matched by header name, so column order changes at BLS are harmless.
LOOKUPS = {
    "la.area_type": ("area_type", ["area_type_code", "areatype_text"]),
    "la.measure": ("measure", ["measure_code", "measure_text"]),
    "la.period": ("period", ["period", "period_abbr", "period_name"]),
    "la.seasonal": ("seasonal", ["seasonal_code", "seasonal_text"]),
    "la.footnote": ("footnote", ["footnote_code", "footnote_text"]),
    "la.state_region_division": ("state_region_division", ["srd_code", "srd_text"]),
}
AREA_COLS = ["area_type_code", "area_code", "area_text", "display_level",
             "selectable", "sort_sequence"]
SERIES_COLS = ["series_id", "area_type_code", "area_code", "measure_code",
               "seasonal", "srd_code", "series_title", "footnote_codes",
               "begin_year", "begin_period", "end_year", "end_period"]
OBS_COLS = ["series_id", "year", "period", "value", "footnote_codes"]


class _LinkParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href.rstrip("/").rsplit("/", 1)[-1])


class BLSClient:
    def __init__(self, base_url, contact, raw_dir, refresh=False):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.headers = {"User-Agent": contact}
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh

    def _get(self, url, dest=None, tries=4):
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=120) as resp:
                    if dest is None:
                        return resp.read()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as fh:
                        while chunk := resp.read(1 << 20):
                            fh.write(chunk)
                    tmp.replace(dest)
                    return dest
            except Exception as exc:  # network errors, 403s, timeouts
                if attempt == tries - 1:
                    raise RuntimeError(f"failed to download {url}: {exc}") from exc
                time.sleep(2 ** (attempt + 1))

    def list_files(self):
        parser = _LinkParser()
        parser.feed(self._get(self.base_url).decode("utf-8", "replace"))
        return sorted({name for name in parser.links if name.startswith("la.")})

    def fetch(self, name):
        dest = self.raw_dir / name
        if dest.exists() and not self.refresh:
            print(f"  cached   {name}")
            return dest
        print(f"  download {name}")
        return self._get(self.base_url + name, dest)


def read_bls(path):
    """Yield dict rows from a BLS tab-delimited file with padded fields."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    lines = text.splitlines()
    header = [h.strip() for h in lines[0].split("\t")]
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = [f.strip() for f in line.split("\t")]
        fields += [""] * (len(header) - len(fields))
        yield dict(zip(header, fields))


def iter_bls_lines(path):
    """Stream a (possibly very large) data file without loading it whole."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        header = [h.strip() for h in next(fh).split("\t")]
        for line in fh:
            fields = [f.strip() for f in line.split("\t")]
            if len(fields) >= len(header):
                yield dict(zip(header, fields))


def choose_data_files(names, year):
    """Pick the smallest set of data files that contains every area for `year`.

    BLS publishes la.data.0.CurrentU<yy>-<yy> (all areas, not seasonally
    adjusted, five-year blocks) and la.data.0.CurrentS (all seasonally
    adjusted series, recent years). If those are missing, fall back to every
    area-type file (la.data.<n>.<name>); duplicates are removed on load by
    the primary key.
    """
    yy = year % 100
    chosen = []
    for name in names:
        m = re.fullmatch(r"la\.data\.0\.CurrentU(\d\d)-(\d\d)", name)
        if m and int(m.group(1)) <= yy <= int(m.group(2)):
            chosen.append(name)
    if chosen and "la.data.0.CurrentS" in names:
        return chosen + ["la.data.0.CurrentS"], False
    fallback = [n for n in names if re.fullmatch(r"la\.data\.\d+\.[A-Za-z].*", n)
                and not n.startswith("la.data.0.")]
    return fallback, True


def clean(value):
    """Escape a value for MySQL LOAD DATA (tab-delimited, \\N for NULL)."""
    if value is None or value == "":
        return r"\N"
    return value.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")


def write_tsv(path, cols, rows):
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(cols) + "\n")
        for row in rows:
            fh.write("\t".join(clean(row.get(c)) for c in cols) + "\n")
            n += 1
    return n


def numeric_or_null(v):
    try:
        float(v)
        return v
    except ValueError:
        return ""  # BLS uses "-" and similar markers for unavailable values


def build(args):
    year = args.year
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    client = BLSClient(args.base_url, args.contact, args.raw_dir, args.refresh)

    print(f"Listing {client.base_url}")
    names = client.list_files()
    data_files, used_fallback = choose_data_files(names, year)
    if not data_files:
        sys.exit("No LAUS data files found on the server listing.")
    if used_fallback:
        print("  CurrentU/CurrentS files not found; using per-area-type files.")
    print(f"Data files: {', '.join(data_files)}")

    # 1. Observations for the reference year.
    counts = {}
    series_seen = set()
    obs_path = out / "observation.tsv"
    seen_keys = set()
    with open(obs_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(OBS_COLS) + "\n")
        n = 0
        for name in data_files:
            path = client.fetch(name)
            for row in iter_bls_lines(path):
                if row.get("year") != str(year):
                    continue
                if len(row["series_id"]) > 30:  # schema width; real IDs are 20
                    sys.exit(f"Unexpected series_id {row['series_id']!r} in {name}")
                key = (row["series_id"], row["period"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                series_seen.add(row["series_id"])
                row["value"] = numeric_or_null(row["value"])
                fh.write("\t".join(clean(row.get(c)) for c in OBS_COLS) + "\n")
                n += 1
    counts["observation"] = n
    del seen_keys
    if n == 0:
        sys.exit(f"No observations found for {year}.")

    # 2. Series metadata, restricted to series with data in the year.
    series_rows = [r for r in read_bls(client.fetch("la.series"))
                   if r["series_id"] in series_seen]
    counts["series"] = write_tsv(out / "series.tsv", SERIES_COLS, series_rows)
    missing = len(series_seen) - counts["series"]
    if missing:
        print(f"  warning: {missing} series in data files have no la.series row")

    # 3. Areas referenced by those series.
    area_keys = {r["area_code"] for r in series_rows}
    area_rows = [r for r in read_bls(client.fetch("la.area"))
                 if r["area_code"] in area_keys]
    counts["area"] = write_tsv(out / "area.tsv", AREA_COLS, area_rows)

    # 4. Small lookup tables, kept whole.
    for fname, (table, cols) in LOOKUPS.items():
        if fname not in names:
            print(f"  warning: {fname} not on server; table {table} left empty")
            write_tsv(out / f"{table}.tsv", cols, [])
            counts[table] = 0
            continue
        counts[table] = write_tsv(out / f"{table}.tsv", cols,
                                  read_bls(client.fetch(fname)))

    load_sql = out / f"load_laus_{year}.sql"
    write_load_sql(load_sql, out, args.database, year, counts)

    print("\nRows written:")
    for table, n in counts.items():
        print(f"  {table:<24}{n:>12,}")
    print(f"\nLoad script: {load_sql}")
    return load_sql


TABLE_ORDER = ["area_type", "measure", "period", "seasonal", "footnote",
               "state_region_division", "area", "series", "observation"]


def write_load_sql(path, out, database, year, counts):
    schema = (Path(__file__).with_name("schema.sql")).read_text()
    parts = [f"CREATE DATABASE IF NOT EXISTS `{database}` "
             "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
             f"USE `{database}`;", schema]
    for table in TABLE_ORDER:
        tsv = (out / f"{table}.tsv").resolve().as_posix()
        with open(out / f"{table}.tsv", encoding="utf-8") as fh:
            cols = fh.readline().rstrip("\n").split("\t")
        parts.append(
            f"LOAD DATA LOCAL INFILE '{tsv}' IGNORE INTO TABLE `{table}`\n"
            "  CHARACTER SET utf8mb4 FIELDS TERMINATED BY '\\t' "
            "LINES TERMINATED BY '\\n' IGNORE 1 LINES\n"
            f"  ({', '.join(f'`{c}`' for c in cols)});")
    # Row-count check: LOAD DATA ... IGNORE skips rows silently, so compare.
    checks = " UNION ALL\n".join(
        f"SELECT '{t}' AS tbl, {counts[t]} AS expected, COUNT(*) AS loaded FROM `{t}`"
        for t in TABLE_ORDER)
    parts.append(f"-- LAUS reference year {year}: expected vs loaded rows\n{checks};")
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def load_mysql(args, load_sql):
    import pymysql  # optional dependency, only needed for --load
    conn = pymysql.connect(host=args.mysql_host, port=args.mysql_port,
                           user=args.mysql_user, password=args.mysql_password,
                           local_infile=True, autocommit=True, charset="utf8mb4")
    sql = load_sql.read_text(encoding="utf-8")
    sql = re.sub(r"^\s*--.*$", "", sql, flags=re.M)
    with conn.cursor() as cur:
        for stmt in (s.strip() for s in sql.split(";\n")):
            if stmt:
                cur.execute(stmt)
        rows = cur.fetchall()  # result of the final expected-vs-loaded query
    conn.close()
    bad = False
    for table, expected, loaded in rows:
        flag = "" if expected == loaded else "  <-- MISMATCH"
        bad = bad or bool(flag)
        print(f"  {table:<24}{loaded:>12,} loaded of {expected:,}{flag}")
    if bad:
        sys.exit("Row counts differ; check MySQL warnings (SHOW WARNINGS).")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--contact", default=os.environ.get("BLS_CONTACT"),
                   help="Name and email sent to BLS as User-Agent "
                        "(or set BLS_CONTACT)")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--raw-dir", default="raw", help="cache for BLS downloads")
    p.add_argument("--out-dir", default="out", help="cleaned TSVs and load script")
    p.add_argument("--refresh", action="store_true", help="re-download cached files")
    p.add_argument("--database", default=None, help="default: laus_<year>")
    p.add_argument("--load", action="store_true", help="load into MySQL via pymysql")
    p.add_argument("--mysql-host", default="127.0.0.1")
    p.add_argument("--mysql-port", type=int, default=3306)
    p.add_argument("--mysql-user", default="root")
    p.add_argument("--mysql-password", default=os.environ.get("MYSQL_PWD", ""))
    args = p.parse_args()
    if not args.contact:
        p.error("--contact (or BLS_CONTACT) is required; BLS rejects anonymous scripts")
    args.database = args.database or f"laus_{args.year}"
    load_sql = build(args)
    if args.load:
        print(f"\nLoading into MySQL database `{args.database}`")
        load_mysql(args, load_sql)


if __name__ == "__main__":
    main()
