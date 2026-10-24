-- Retrofit Check cache and rules. Zetaris reads every table here through the
-- retrofit_pg datasource; the agent only ever queries them through Zetaris.

-- One row per house we have looked at. Footprint is GeoJSON (lon, lat).
CREATE TABLE house (
    house_id      text PRIMARY KEY,          -- e.g. osm-way-460070558
    label         text NOT NULL,             -- what we show, never a house number
    lat           double precision NOT NULL,
    lon           double precision NOT NULL,
    building      text,                      -- OSM building tag
    footprint_m2  integer,
    footprint     text NOT NULL,             -- GeoJSON Polygon
    source        text NOT NULL,             -- e.g. OpenStreetMap way 460070558
    fetched_at    timestamptz NOT NULL DEFAULT now()
);

-- Walls of the footprint and whether each one faces a road (OSM highways).
CREATE TABLE house_wall (
    house_id        text REFERENCES house ON DELETE CASCADE,
    wall_no         integer,
    facing_deg      integer,                 -- outward direction of the wall
    length_m        real,
    fronts_highway  boolean NOT NULL,
    highway_name    text,
    distance_m      real,
    adjoins         boolean NOT NULL DEFAULT false,   -- party wall with the next house
    PRIMARY KEY (house_id, wall_no)
);

-- Roof planes measured from Environment Agency LIDAR (DSM 1 m).
CREATE TABLE roof_plane (
    house_id     text REFERENCES house ON DELETE CASCADE,
    facing       text NOT NULL,              -- N, NE, E, ...
    azimuth_deg  integer NOT NULL,
    pitch_deg    integer NOT NULL,
    area_m2      integer NOT NULL,
    PRIMARY KEY (house_id, facing)
);

CREATE TABLE roof_survey (
    house_id     text PRIMARY KEY REFERENCES house ON DELETE CASCADE,
    noise_pct    integer NOT NULL,           -- trees, chimneys, dormers: slope above 65 degrees
    flat_pct     integer NOT NULL,
    eaves_m      real,
    ridge_m      real,
    method       text NOT NULL,
    measured_at  timestamptz NOT NULL DEFAULT now()
);

-- PVGIS yearly output for the best roof plane.
CREATE TABLE pv_estimate (
    house_id     text PRIMARY KEY REFERENCES house ON DELETE CASCADE,
    facing       text NOT NULL,
    kwp          real NOT NULL,
    kwh_year     integer NOT NULL,
    params       text NOT NULL,
    source       text NOT NULL,
    fetched_at   timestamptz NOT NULL DEFAULT now()
);

-- planning.data designations that touch the footprint (cache of the live REST read).
CREATE TABLE designation (
    house_id     text REFERENCES house ON DELETE CASCADE,
    dataset      text NOT NULL,
    reference    text NOT NULL,
    name         text,
    grade        text,
    start_date   text,
    end_date     text,
    entity       bigint,
    organisation text,
    PRIMARY KEY (house_id, dataset, reference)
);

-- What each Article 4 direction removes, read from the council's own documents.
-- planning.data lists where they apply but not what they remove.
CREATE TABLE article4_rule (
    organisation    text NOT NULL,
    reference       text NOT NULL,
    name            text NOT NULL,
    start_date      date,
    end_date        date,
    removes_solar   boolean NOT NULL,        -- Part 14 Class A
    removes_ashp    boolean NOT NULL,        -- Part 14 Class G
    removes_walls   boolean NOT NULL,        -- Part 1 Class A works to outside walls
    summary         text NOT NULL,
    source_url      text NOT NULL,
    checked_on      date NOT NULL,
    PRIMARY KEY (organisation, reference)
);

-- Permitted development and consent rules, with the date each version applies from.
CREATE TABLE pd_rule (
    rule_id      text PRIMARY KEY,
    measure      text NOT NULL,              -- solar, heat_pump, wall_insulation, any
    clause       text NOT NULL,              -- e.g. GPDO Sch 2 Part 14 Class A, A.2(e)
    plain        text NOT NULL,              -- the rule in plain words
    applies_when text NOT NULL,              -- listed, conservation_area, article_2_3, always, not_article_2_3
    effect       text NOT NULL,              -- not_permitted, condition, consent_needed
    in_force     date NOT NULL,
    amended_by   text,
    source_url   text NOT NULL,
    checked_on   date NOT NULL
);

-- Help with cost.
CREATE TABLE grant_scheme (
    scheme_id    text PRIMARY KEY,
    measure      text NOT NULL,
    amount_gbp   integer,
    plain        text NOT NULL,
    condition    text NOT NULL,              -- any, off_gas_grid_replacing_oil_lpg_coal, ...
    valid_from   date,
    valid_to     date,
    source_url   text NOT NULL,
    checked_on   date NOT NULL
);
