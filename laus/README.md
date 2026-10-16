# LAUS database builder

Builds a MySQL database of BLS Local Area Unemployment Statistics for one
reference year (default 2023) covering every LAUS geography: census regions
and divisions, states, metropolitan and micropolitan areas, metropolitan
divisions, combined areas, counties, cities and towns, and the other area
types listed in `la.area_type`.

```
python build_laus_db.py --year 2023 --contact "Your Name you@utsa.edu"
mysql --local-infile=1 -u root -p < out/load_laus_2023.sql
```

Or load directly with `pip install pymysql` and `--load --mysql-user ... --mysql-password ...`.
The server must allow `local_infile` (`SET GLOBAL local_infile = 1;`).

Tables mirror the BLS flat files (`area`, `area_type`, `series`, `observation`,
`measure`, `period`, `seasonal`, `footnote`, `state_region_division`).
`v_laus_long` attaches all labels; `v_laus_annual` gives one row per area with
2023 annual averages (period M13, not seasonally adjusted).
