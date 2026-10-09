-- FleetSheet compliance pack seed (idempotent: INSERT OR IGNORE).
-- Executed by engine.init_db() after schema.sql.
-- Policy (2026-09-24): standard-mandated intervals as stated; manufacturer
-- items follow the manufacturer manual; standard-silent calibrations default
-- to per job / pre-mobilization with a configurable deployed backstop
-- (suggested 6 months, company policy, never a standard). basis: standard |
-- manufacturer | company. trigger: per_job | per_shift | calendar | event |
-- manufacturer.

INSERT OR IGNORE INTO compliance_packs (pack_id, name, blurb) VALUES
('offshore-cabin', 'Offshore temporary pressurized cabin / living quarter',
 'IEC 60079-13 pressurization, IEC 60079-17 inspection tiers, DNV 2.7-1 lifting-set checks.'),
('analyzer-shelter', 'Analyzer shelter / pressurized control building',
 'IEC TR 61831 ventilation, NFPA 496 purge, IEC 60079-17 inspection tiers.'),
('mining-refuge', 'Mining refuge chamber / alternative',
 'MSHA preshift examinations, manufacturer maintenance, 96-hour sustainment.'),
('operator-cab', 'Pressurized operator cab',
 'Daily pressure, seal and filter checks per MSHA & NIOSH guidance; ISO 10263-4 type-test values.'),
('welding-habitat', 'Hot-work welding habitat',
 'Pre-start checklist, pressure and gas-detection monitoring, fire watch, supplier re-certification.'),
('tunnel-refuge', 'Tunnel refuge chamber',
 'EN 16191 Annex D capacity and breathing supply, loss-of-air warning.'),
('shop-tools', 'Shop tool calibration',
 'Meters, gauges, torque wrenches, vacuum equipment. Annual shop defaults; the manufacturer manual governs where it states an interval.');

-- Pack A: offshore-cabin
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('offshore-cabin', 'Minimum pressure-differential test', 'event', NULL, NULL,
 'Differential maintained per design; doors self-close and latch',
 'Test record', 'IEC 60079-13', 'standard',
 'At commissioning and after relocation or repair.', 10),
('offshore-cabin', 'Purging test', 'event', NULL, NULL,
 'Purge volume per design completed before energization; no dead spaces',
 'Test record', 'IEC 60079-13', 'standard',
 'At commissioning and after modification.', 20),
('offshore-cabin', 'Supply air from unclassified location', 'event', NULL, NULL,
 'Intake in unclassified area; dehumidified air recommended',
 'Design record', 'API RP 14F', 'standard',
 'Continuous condition; verified at commissioning.', 30),
('offshore-cabin', 'Loss-of-pressurization alarm functional test', 'calendar', 1, NULL,
 'Audible + visual alarm at monitored control point within 30 s of pressure loss',
 'Test log', 'Canada-NL Offshore Framework Regs s.114 (alarm <=30 s)', 'company',
 'The <=30 s alarm is regulatory; the monthly test interval is a company default - the standard is silent on test frequency.', 40),
('offshore-cabin', 'Gas detector calibration', 'per_job', NULL, 6,
 'Alarm 25% LEL; shut-in 60% LEL; higher-level systems manually reset',
 'Calibration record', 'BSEE/30 CFR; API RP 14G', 'company',
 'Setpoints are regulatory. Calibration per job / pre-mobilization is the shop default where the standard is silent; the 6-month deployed backstop is company policy.', 50),
('offshore-cabin', 'Detailed Ex inspection - frequently opened enclosures', 'calendar', 6, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard', NULL, 60),
('offshore-cabin', 'Close Ex inspection - movable equipment', 'calendar', 12, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard', NULL, 70),
('offshore-cabin', 'Periodic Ex inspection', 'calendar', 36, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard',
 'Maximum interval without expert advice.', 80),
('offshore-cabin', 'Lifting-set visual inspection (DNV 2.7-1)', 'calendar', 12, NULL,
 'No deformation or cracks; certification plate current',
 'Cert plate + report', 'DNV 2.7-1 (now DNV-ST-E271)', 'standard', NULL, 90),
('offshore-cabin', 'Lifting-set NDE + visual (DNV 2.7-1)', 'calendar', 48, NULL,
 'NDE + visual; certification plate current',
 'Cert plate + report', 'DNV 2.7-1 (now DNV-ST-E271)', 'standard', NULL, 100),
('offshore-cabin', 'Proof-load test after substantial repair (DNV 2.7-1)', 'event', NULL, NULL,
 'Proof-load + NDE + visual after substantial repair',
 'Test report', 'DNV 2.7-1 (now DNV-ST-E271)', 'standard', NULL, 110),
('offshore-cabin', 'Pre-mobilization inspection if idle past due date', 'per_job', NULL, NULL,
 'Inspected before taken into use when idle past periodic date',
 'Inspection report', 'DNV 2.7-1 (now DNV-ST-E271)', 'standard', NULL, 120),
('offshore-cabin', 'Hazardous-area protection method (LR-classed units)', 'event', NULL, NULL,
 'Pressurized enclosure complying with IEC 60079-2 where pressurization is the protection method',
 'Type approval / class certificate', 'Lloyd''s Register Offshore Units Rules (2014 ed.)', 'standard',
 'Verify against the rule edition the unit is classed under.', 130),
('offshore-cabin', 'Gas detection at cabin ventilation intake (LR-classed units)', 'per_job', NULL, NULL,
 'Fixed automatic combustible-gas detection + alarm at intake; function-tested',
 'Detector record', 'Lloyd''s Register Offshore Units Rules (2023 ed.)', 'standard',
 'Verify against the rule edition the unit is classed under.', 140);

-- Pack B: analyzer-shelter
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('analyzer-shelter', 'Ventilation rate verification', 'event', NULL, NULL,
 '>=10 ACH (minimum 5 per IEC 61285); release diluted to <20% LEL, toxics below OEL',
 'Commissioning record; smoke-test record', 'IEC TR 61831', 'standard',
 'Verified at commissioning; air distribution confirmed by smoke tests.', 10),
('analyzer-shelter', 'Overpressure alarm functional test', 'calendar', 1, NULL,
 'Overpressure >=25 Pa maintained; alarm on loss',
 'Pressure log / alarm test log', 'IEC TR 61831 (>=25 Pa)', 'company',
 'The >=25 Pa value is standard; the monthly test interval is a company default - the standard is silent on test frequency.', 20),
('analyzer-shelter', 'Purge before energization', 'per_job', NULL, NULL,
 '4 enclosure volumes before energization (10 for rotating machinery); >=25 Pa during purge',
 'Start-up log', 'NFPA 496', 'standard',
 'At each start-up.', 30),
('analyzer-shelter', 'Gas/toxic/O2/smoke/heat detector calibration', 'manufacturer', NULL, 6,
 'Per manufacturer manual; O2-deficiency warning 19.5%',
 'Calibration certificate', 'Manufacturer manual', 'manufacturer',
 'Follow the manufacturer manual. Per-job/pre-mob check is the shop default where the manual is silent; the 6-month deployed backstop is company policy.', 40),
('analyzer-shelter', 'Detailed Ex inspection - frequently opened enclosures', 'calendar', 6, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard', NULL, 50),
('analyzer-shelter', 'Close Ex inspection - movable equipment', 'calendar', 12, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard', NULL, 60),
('analyzer-shelter', 'Periodic Ex inspection', 'calendar', 36, NULL,
 'Per IEC 60079-17 inspection tables',
 'Inspection record', 'IEC 60079-17', 'standard',
 'Maximum interval without expert advice.', 70),
('analyzer-shelter', 'Ventilation entry verification', 'per_shift', NULL, NULL,
 'Ventilation confirmed without entry; fan, gas detector and pressurization status indicated outside',
 'Entry log', 'Company guidance (GP-31-04 style)', 'company',
 'Treat as confined space after ventilation failure.', 80);

-- Pack C: mining-refuge
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('mining-refuge', 'Preshift examination (coal)', 'per_shift', NULL, NULL,
 'No damage; tamper-evident seals intact; deployment mechanisms functional; compressed O2 and air available',
 'Secure-book record (retain >=1 yr)', '30 CFR 75.360; MSHA compliance guide', 'standard', NULL, 10),
('mining-refuge', 'Manufacturer scheduled maintenance', 'manufacturer', NULL, NULL,
 'Per manufacturer manual - mandatory',
 'Maintenance record', 'MSHA compliance guide', 'standard',
 'Manufacturer-specified maintenance is mandatory under MSHA guidance.', 20),
('mining-refuge', 'Breathable-air compressor/fan check', 'per_shift', NULL, NULL,
 'Compressor/fan supplying breathable air operable',
 'Secure-book record', 'MSHA compliance guide', 'standard', NULL, 30),
('mining-refuge', '96-hour sustainment inventory', 'per_shift', NULL, NULL,
 '2,000 calories + 2.25 qt potable water per person per day x 96 hr',
 'Inventory record', 'MSHA compliance guide', 'standard',
 'Verify inventory each preshift; full count per schedule.', 40),
('mining-refuge', 'Refuge training currency verified', 'calendar', 3, NULL,
 'Quarterly training completed; annual hands-on expectations training',
 'Training record', 'MSHA compliance guide', 'standard',
 'Unit-level currency check only - FleetSheet does not track individual personnel or their certifications.', 50),
('mining-refuge', 'Refuge chamber construction (MNM)', 'event', NULL, NULL,
 'Fire-resistant construction; gastight; compressed-air and water lines; voice comms to surface independent of mine power',
 'Design record', '30 CFR 57.11059', 'standard',
 'Design/commissioning verification for metal/nonmetal refuge chambers.', 60);

-- Pack D: operator-cab
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('operator-cab', 'Cab pressure-gauge check', 'per_shift', NULL, NULL,
 'Positive pressure confirmed on gauge; monitored through the shift',
 'Daily checklist', 'MSHA silica guide; NIOSH', 'company',
 'Guidance only - no source found stating an explicit MSHA numerical mandate. Observed effective range 0.01-0.40 in. w.c.; ineffective below 0.04 in. w.c.', 10),
('operator-cab', 'Cab seals, doors and windows inspection', 'per_shift', NULL, NULL,
 'No holes, gaps or cracks; door and window seals in good condition',
 'Daily checklist', 'MSHA silica guide; CPWR/NIOSH', 'company',
 'Guidance only - see pressure-gauge check note.', 20),
('operator-cab', 'Cab filter inspection / replacement', 'manufacturer', NULL, NULL,
 'No filter damage or bypass; >=95% intake filtration; replaced per manufacturer',
 'Filter record', 'MSHA silica guide; NIOSH', 'manufacturer',
 'Inspect before work; replace per manufacturer manual.', 30),
('operator-cab', 'Cab type-test performance (design)', 'event', NULL, NULL,
 '50-200 Pa maintained; >=43 m3/h filtered fresh air',
 'Type-test report', 'ISO 10263-4', 'standard',
 'Design/type-approval verification.', 40);

-- Pack E: welding-habitat
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('welding-habitat', 'Pre-start checklist + gas test', 'per_job', NULL, NULL,
 'Per supplier manual; positive pressure confirmed before hot work',
 'Job checklist', 'Supplier manual', 'company',
 'Every deployment / shift.', 10),
('welding-habitat', 'Positive-pressure differential monitoring', 'per_job', NULL, NULL,
 'Differential per vendor manual (typical 25-50 Pa, alarm below 25 Pa); continuous monitoring while deployed',
 'Pressure log', 'Vendor manual', 'company',
 'Setpoints are vendor-specific, not universal regulatory values.', 20),
('welding-habitat', 'Gas sensor calibration + shutdown-logic test', 'per_job', NULL, 6,
 'Per vendor manual; HC/H2S triggers airflow cut-off and welding shutdown per client cause-and-effect',
 'Calibration record; cause-effect matrix', 'Vendor manual + client permit', 'manufacturer',
 'Cause-and-effect logic is client/vendor-specific. The 6-month deployed backstop is company policy.', 30),
('welding-habitat', 'Fire watchers posted', 'per_job', NULL, NULL,
 'Fire watchers posted inside and outside; briefed',
 'Permit log', 'Vendor manual', 'company',
 'During all hot work.', 40),
('welding-habitat', 'Supplier re-certification', 'calendar', 12, NULL,
 'Unit re-certified by supplier',
 'Supplier certificate', 'Supplier', 'company',
 'Annual is the shop default - supplier interval governs where stated.', 50);

-- Pack F: tunnel-refuge
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('tunnel-refuge', 'Capacity and geometry verification', 'event', NULL, NULL,
 '>=0.75 m2 floor area/person; >=1.6 m headroom; >=1.5 m3 volume/person',
 'Design record', 'EN 16191 Annex D', 'standard',
 'Design/commissioning verification.', 10),
('tunnel-refuge', 'Emergency breathing supply service', 'manufacturer', NULL, NULL,
 'Independent 4-hour supply at 40 L/min/person; serviced per manufacturer',
 'Design + service record', 'EN 16191 Annex D', 'manufacturer',
 'Design values are standard; service interval per manufacturer manual.', 20),
('tunnel-refuge', 'Loss-of-external-air warning functional test', 'calendar', 1, NULL,
 'Audible + visual warning outside on loss of external air',
 'Test log', 'EN 16191 Annex D', 'company',
 'The warning is standard; the monthly test interval is a company default - the standard is silent on test frequency.', 30),
('tunnel-refuge', 'Secure-area pressurization (NZ)', 'event', NULL, NULL,
 'Compressed-air line providing pressurized atmosphere; barriers withstand 14 kPa overpressure',
 'Design record', 'NZ WorkSafe code', 'standard',
 'Design verification; NZ regulation.', 40);

-- Pack G: shop-tools (added 2026-09-24 at Jason's direction)
INSERT OR IGNORE INTO compliance_requirements
(pack_id, name, trigger, interval_months, deployed_backstop_months, criterion, evidence, source, basis, note, sort_order) VALUES
('shop-tools', 'Multimeter / clamp meter calibration', 'calendar', 12, NULL,
 'Calibrated against traceable reference; certificate on file',
 'Calibration certificate', 'Manufacturer manual', 'company',
 'Annual is the shop default; follow the manufacturer manual where it states an interval.', 10),
('shop-tools', 'Pressure / test gauge calibration', 'calendar', 12, NULL,
 'Calibrated against traceable reference; certificate on file',
 'Calibration certificate', 'Manufacturer manual', 'company',
 'Annual is the shop default; follow the manufacturer manual where it states an interval.', 20),
('shop-tools', 'Torque wrench calibration', 'calendar', 12, NULL,
 'Calibrated against traceable reference; certificate on file',
 'Calibration certificate', 'Manufacturer manual', 'company',
 'Annual is the shop default; follow the manufacturer manual where it states an interval.', 30),
('shop-tools', 'Vacuum gauge / pump function check', 'per_job', NULL, 6,
 'Function-checked before each job; calibrated per manufacturer manual',
 'Check record', 'Manufacturer manual', 'company',
 'Per-job check is the shop default; the 6-month deployed backstop is company policy.', 40),
('shop-tools', 'Calibration reference standards current', 'calendar', 12, NULL,
 'Shop''s master references hold current traceable calibration from an external lab',
 'External calibration certificates', 'Company policy', 'company',
 'The references everything else is checked against.', 50);
