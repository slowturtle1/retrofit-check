-- Money facts for rough costs and savings. Each row is dated and sourced; assumptions are labelled as such.
CREATE TABLE price_fact (
    fact_id      text PRIMARY KEY,
    value        double precision NOT NULL,
    unit         text NOT NULL,
    plain        text NOT NULL,
    kind         text NOT NULL,              -- official | consumer_survey | assumption
    valid_from   date,
    valid_to     date,
    source_url   text NOT NULL,
    checked_on   date NOT NULL
);

INSERT INTO price_fact VALUES
('elec_rate', 26.32, 'p/kWh', 'Electricity unit rate under the Ofgem price cap, Direct Debit average, no VAT on electricity from 1 Oct 2026 to 31 Mar 2027', 'official', '2026-10-01', '2026-12-31',
 'https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges', '2026-10-25'),
('gas_rate', 7.97, 'p/kWh', 'Gas unit rate under the Ofgem price cap, Direct Debit average, including 5% VAT', 'official', '2026-10-01', '2026-12-31',
 'https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges', '2026-10-25'),
('gas_standing', 29.68, 'p/day', 'Gas standing charge under the Ofgem price cap, Direct Debit average', 'official', '2026-10-01', '2026-12-31',
 'https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges', '2026-10-25'),
('seg_low', 6, 'p/kWh', 'Highest export rate open to everyone (ScottishPower), per Which?', 'consumer_survey', '2026-04-24', NULL,
 'https://www.which.co.uk/news/article/smart-export-guarantee-rates-the-best-and-worst-seg-tariffs-for-solar-panel-owners-azICP0i78MD8', '2026-10-25'),
('seg_high', 15, 'p/kWh', 'Export rate for customers who also buy their electricity from the supplier, per Which?', 'consumer_survey', '2026-04-24', NULL,
 'https://www.which.co.uk/news/article/smart-export-guarantee-rates-the-best-and-worst-seg-tariffs-for-solar-panel-owners-azICP0i78MD8', '2026-10-25'),
('solar_cost_gb_median', 1595.06, '£/kW', 'Median installed cost of 0 to 4 kW solar PV in Great Britain, 2025/26 (MCS data)', 'official', '2025-04-01', '2026-03-31',
 'https://www.gov.uk/government/statistics/solar-pv-cost-data', '2026-10-25'),
('solar_cost_london_mean', 2101.01, '£/kW', 'Mean installed cost of 0 to 4 kW solar PV in London, 2025/26 (MCS data)', 'official', '2025-04-01', '2026-03-31',
 'https://www.gov.uk/government/statistics/solar-pv-cost-data', '2026-10-25'),
('ashp_cost_lq', 11128, '£', 'Lower quartile cost of an air to water heat pump installed under the Boiler Upgrade Scheme, Apr to Jun 2026, before the grant', 'official', '2026-04-01', '2026-06-30',
 'https://www.gov.uk/government/statistics/boiler-upgrade-scheme-statistics-august-2026', '2026-10-25'),
('ashp_cost_median', 12908, '£', 'Median cost of an air to water heat pump installed under the Boiler Upgrade Scheme, Apr to Jun 2026, before the grant', 'official', '2026-04-01', '2026-06-30',
 'https://www.gov.uk/government/statistics/boiler-upgrade-scheme-statistics-august-2026', '2026-10-25'),
('ashp_cost_uq', 15627, '£', 'Upper quartile cost of an air to water heat pump installed under the Boiler Upgrade Scheme, Apr to Jun 2026, before the grant', 'official', '2026-04-01', '2026-06-30',
 'https://www.gov.uk/government/statistics/boiler-upgrade-scheme-statistics-august-2026', '2026-10-25'),
('self_use_low', 0.25, 'share', 'Share of solar electricity used at home without a battery, low end', 'assumption', NULL, NULL, 'assumption', '2026-10-25'),
('self_use_high', 0.5, 'share', 'Share of solar electricity used at home without a battery, high end', 'assumption', NULL, NULL, 'assumption', '2026-10-25'),
('boiler_eff', 0.85, 'share', 'Seasonal efficiency of the existing gas boiler', 'assumption', NULL, NULL, 'assumption', '2026-10-25'),
('scop_low', 2.8, 'ratio', 'Heat pump seasonal efficiency, low end', 'assumption', NULL, NULL, 'assumption', '2026-10-25'),
('scop_high', 3.5, 'ratio', 'Heat pump seasonal efficiency, high end', 'assumption', NULL, NULL, 'assumption', '2026-10-25');

INSERT INTO price_fact VALUES
('gas_boiler_cost', 3500, '£', 'Typical cost of replacing an old gas boiler with an A rated one, with thermostatic radiator valves, Great Britain', 'advice_body', '2026-05-20', NULL,
 'https://energysavingtrust.org.uk/advice/boilers/', '2026-10-25'),
('ashp_life_years', 20, 'years', 'On average an air source heat pump lasts up to 20 years', 'advice_body', NULL, NULL,
 'https://mcscertified.com/technology/air-source-heat-pump/', '2026-10-25');
