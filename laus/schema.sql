-- Schema for BLS Local Area Unemployment Statistics (LAUS), one reference year.
-- Mirrors the BLS flat file layout at https://download.bls.gov/pub/time.series/la/
-- (see la.txt on that server for the official field definitions).

DROP VIEW IF EXISTS v_laus_annual;
DROP VIEW IF EXISTS v_laus_long;
DROP TABLE IF EXISTS observation;
DROP TABLE IF EXISTS series;
DROP TABLE IF EXISTS area;
DROP TABLE IF EXISTS area_type;
DROP TABLE IF EXISTS measure;
DROP TABLE IF EXISTS period;
DROP TABLE IF EXISTS seasonal;
DROP TABLE IF EXISTS footnote;
DROP TABLE IF EXISTS state_region_division;

CREATE TABLE area_type (
  area_type_code CHAR(1)      NOT NULL PRIMARY KEY,
  areatype_text  VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE measure (
  measure_code CHAR(2)      NOT NULL PRIMARY KEY,
  measure_text VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE period (
  period      CHAR(3)     NOT NULL PRIMARY KEY,
  period_abbr VARCHAR(5),
  period_name VARCHAR(30)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE seasonal (
  seasonal_code CHAR(1)     NOT NULL PRIMARY KEY,
  seasonal_text VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE footnote (
  footnote_code VARCHAR(5)   NOT NULL PRIMARY KEY,
  footnote_text VARCHAR(500)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE state_region_division (
  srd_code CHAR(2)      NOT NULL PRIMARY KEY,
  srd_text VARCHAR(100) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE area (
  area_code      VARCHAR(30)  NOT NULL PRIMARY KEY,
  area_type_code CHAR(1)      NOT NULL,
  area_text      VARCHAR(255) NOT NULL,
  display_level  TINYINT,
  selectable     CHAR(1),
  sort_sequence  INT,
  KEY idx_area_type (area_type_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE series (
  series_id      VARCHAR(30)  NOT NULL PRIMARY KEY,
  area_type_code CHAR(1)      NOT NULL,
  area_code      VARCHAR(30)  NOT NULL,
  measure_code   CHAR(2)      NOT NULL,
  seasonal       CHAR(1)      NOT NULL,
  srd_code       CHAR(2),
  series_title   VARCHAR(255),
  footnote_codes VARCHAR(10),
  begin_year     SMALLINT,
  begin_period   CHAR(3),
  end_year       SMALLINT,
  end_period     CHAR(3),
  KEY idx_series_area (area_code, measure_code, seasonal),
  KEY idx_series_type (area_type_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- value: counts are persons; rates and ratios are percents.
-- NULL means BLS published a non-numeric marker (for example "-") for that cell.
-- period M01..M12 are months; M13 is the annual average (not seasonally adjusted series only).
CREATE TABLE observation (
  series_id      VARCHAR(30)   NOT NULL,
  year           SMALLINT      NOT NULL,
  period         CHAR(3)       NOT NULL,
  value          DECIMAL(15,1),
  footnote_codes VARCHAR(10),
  PRIMARY KEY (series_id, year, period),
  KEY idx_obs_period (year, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Long format with all labels attached.
CREATE VIEW v_laus_long AS
SELECT o.series_id, a.area_code, a.area_text, s.area_type_code, at.areatype_text,
       s.srd_code, srd.srd_text AS state_name, s.measure_code, m.measure_text,
       s.seasonal, o.year, o.period, p.period_name, o.value, o.footnote_codes
FROM observation o
JOIN series s                  ON s.series_id = o.series_id
LEFT JOIN area a               ON a.area_code = s.area_code
LEFT JOIN area_type at         ON at.area_type_code = s.area_type_code
LEFT JOIN measure m            ON m.measure_code = s.measure_code
LEFT JOIN period p             ON p.period = o.period
LEFT JOIN state_region_division srd ON srd.srd_code = s.srd_code;

-- One row per area: annual averages (M13) of the not seasonally adjusted series.
-- Measure codes per la.measure: 03 rate, 04 unemployed, 05 employed, 06 labor force,
-- 07 employment-population ratio, 08 participation rate, 09 civ. noninst. population
-- (07 to 09 exist only for states and a few other areas).
CREATE VIEW v_laus_annual AS
SELECT s.area_code, a.area_text, s.area_type_code, at.areatype_text,
       s.srd_code, o.year,
       MAX(CASE WHEN s.measure_code = '06' THEN o.value END) AS labor_force,
       MAX(CASE WHEN s.measure_code = '05' THEN o.value END) AS employed,
       MAX(CASE WHEN s.measure_code = '04' THEN o.value END) AS unemployed,
       MAX(CASE WHEN s.measure_code = '03' THEN o.value END) AS unemployment_rate,
       MAX(CASE WHEN s.measure_code = '07' THEN o.value END) AS emp_pop_ratio,
       MAX(CASE WHEN s.measure_code = '08' THEN o.value END) AS lf_participation_rate,
       MAX(CASE WHEN s.measure_code = '09' THEN o.value END) AS civ_noninst_pop
FROM observation o
JOIN series s          ON s.series_id = o.series_id
LEFT JOIN area a       ON a.area_code = s.area_code
LEFT JOIN area_type at ON at.area_type_code = s.area_type_code
WHERE s.seasonal = 'U' AND o.period = 'M13'
GROUP BY s.area_code, a.area_text, s.area_type_code, at.areatype_text, s.srd_code, o.year;
