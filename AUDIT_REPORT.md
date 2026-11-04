# Pre-deployment audit — spare parts catalogue

Audit date: 2026-11-05 · Auditor: Claude (read-only run) · Catalogue audited: 9,950 products, 6 brands, 15 import batches (7 applied), local Postgres 16, local web app on :3000.

## 0. How this audit was run, and what it could not do

- **Read-only.** Code, migrations and the main database were not modified. Main-database fingerprint (md5 of `products`) was `5e5c77b3bcbb` / 9,950 rows before and after; `import_batches` stayed at 15. Everything destructive (apply, delete, resync, duplicate upload, corrupt files, RLS probing, an added `discount_pct` column) ran on a throwaway copy (`createdb -T`, database `audit_tmp`, plus an empty `audit_fresh` rebuilt from migrations) with its own copy of the stored files. Both databases and the probe role were dropped at the end.
- **"Throwaway search index".** This build has no Meilisearch. Search is Postgres-only (`product_search` table inside the database), so the throwaway copy contains its own index. Meilisearch itself has never been run live (only a fake-server test), so parity with a real index is **not verified**.
- **`PRE_DEPLOY_CHECKLIST.md` does not exist** in the repo, in `~/Downloads` or `~/Desktop`, so I could not use its item IDs. I numbered the items myself: sections **A–K**, A–J follow your ten steps in order (A=1 … J=10), K is an extra operations section. If you send the checklist I will re-map the IDs; the evidence does not change.
- **`search/tests/queries.json` does not exist** (the plan promised it; the folder is empty). Step 9 therefore used an audit-made query set (section I); I did not add it to the repo.
- Independent row counts used a different method from the parsers (PyMuPDF words/serial numbers instead of pdfplumber cell grids; a 330-dpi re-OCR for Pensol). Where a method is the same engine (Pensol/catalogue OCR) it is marked NEEDS HUMAN.
- No discount/dealer/trade/margin/net values were printed anywhere in this report. Only locations and counts.
- Disclosure: while building the product I created OCR debug dumps (`data/scratch/p1.json`, `p2.json`, images). They are part of finding **G4** below.
- Raw evidence files from this run: `/private/tmp/claude-501/-Users-ayusharora-Desktop-lifeos/af3d3a9c-d77a-4ee1-99ee-fd1235521d52/scratchpad/audit/` (`s1.py`…`s10b.txt`, `dump_data.sql` — the data-only dump, which contains catalogue data and should be deleted when you no longer need it).
- Test suite: `pytest` 50 passed (87 s), run for this audit.

Status key: **PASS** verified · **FAIL** verified problem · **NEEDS HUMAN** cannot be settled from the data alone.

---

## 1. Field coverage (A)

Percent of rows with the field filled. Cells under 100 % in **bold**. `n/a by source` means the PDF does not print it.

| Brand | rows | descr. | category | segment | make | application | mrp | hsn | moq | gst | image | cross-refs | variant | price basis known |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Car International | 4,640 | 100 | 100 | 100 | **71.7** | **60.9** | 100 | **96.8** | **0** | 100 | **0** | **0** | **1.3** | **0** |
| Fras-le | 157 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **0** | **0** (n/a: footer says taxes extra) | **0** | **0** | 100 | 100 |
| Meko | 511 | 100 | 100 | 100 | **66.5** | 100 | 100 | **0** | **0** | **0** | **44.4** | **54.2** | **0** | **0** |
| Neolite | 492 | 100 | 100 | 100 | **76.4** | 100 | 100 | **0** | **0** | **0** | **0** | **0** | **2.4** | **0** |
| Pensol | 202 | 100 | 100 | 100 | **0** | **0** | **91.1** | **0** | **0** | **0** | **0** | **0** | 100 | 100 |
| Uno Minda | 3,948 | **99.97** | **99.95** | 100 | **96.6** | 100 | 100 | 100 | 100 | 100 | **0** | **0** | **0** | **0** |

Overall: no make on 1,936 rows (19.5 %); segment is "OTHER" on 2,089 rows (21 %); `price_basis` is "unknown" on 9,591 rows.

| ID | Item | Status | Evidence |
|---|---|---|---|
| A1 | Part number and brand present on every row | PASS | 0 missing in 9,950 rows |
| A2 | Description present on every row | **FAIL** | 1 row blank: Uno Minda `SW-1622M`, page 28, serial 2921 |
| A3 | Category present on every row | **FAIL** | 2 Uno Minda rows null: `H4/H19 LED PREM 300`, `H8/H9/H11/H16 LED P` (long part number overflowed into P'GROUP; flagged `long_part_no`) |
| A4 | Segment present | PASS | 100 %, but 21 % are "OTHER" (see E-section) |
| A5 | Make filled | **FAIL** | 80.5 % overall (table above) |
| A6 | "Where it is used" (application) filled | **FAIL** | Car International 60.9 %, Pensol 0 % |
| A7 | MRP present | NEEDS HUMAN | 18 Pensol packs print "NA" (stored null by design); 100 % elsewhere. Is "no MRP" acceptable on the public site? |
| A8 | HSN filled | **FAIL** | Meko, Neolite, Pensol 0 %; Car International 96.8 % (150 bad/`#N/A`) |
| A9 | MOQ filled | **FAIL** | only Uno Minda prints it |
| A10 | GST % filled | NEEDS HUMAN | filled for Uno Minda and Car International only; Fras-le, Neolite, Meko, Pensol do not print a rate (Fras-le/Pensol state tax treatment in a footer) |
| A11 | Image filled | **FAIL** | 227 products (2.3 %), all Meko |
| A12 | Cross-references present | NEEDS HUMAN | 510 refs on 277 Meko products; no other source prints them (plan goal "OEM number as the link between brands" is unmet) |
| A13 | Variant label complete where the source has variants | NEEDS HUMAN | Fras-le 100 %; Car International 58 labels were *inferred* by the parser |
| A14 | Price basis (incl./excl. GST) known | **FAIL** | known for Fras-le (ex-tax) and Pensol (incl.) only |

---

## 2. Source vs saved (B)

Printed columns per source and what the profile does with them. **MAPPED**, **DELIBERATELY IGNORED** (never-stored rule), **POSSIBLY LOST**.

### Uno Minda "Master Price List" (39 pp; `data/pdfs/uno_minda/…` and stored batch file)
| Printed column | Disposition | Where it goes |
|---|---|---|
| S. No. | MAPPED (position only) | `source_row` |
| PART NO | MAPPED | `part_no`, `part_no_norm` |
| P'GROUP (ABR/AST/HLT…) | MAPPED (code itself not kept) | `category` via `category_map` |
| DESCRIPTION | MAPPED | `description` |
| CLASS ("4WH") | **POSSIBLY LOST** | not stored |
| SEGMENT | MAPPED | `segment` |
| PRODUCT TYPE (MECHANICAL/ELECTRICAL/COOLANT…) | **POSSIBLY LOST** | not stored |
| OEM | MAPPED | `oem_raw`, `oem_name` |
| APPLICATION | MAPPED | `application` |
| NPD STATUS (A/B/B1; yellow highlight) | **POSSIBLY LOST** | not stored |
| MOQ / GST% / HSN / MRP | MAPPED | `moq`, `gst_pct`, `hsn`, `mrp` |
| TD% W/O GST | DELIBERATELY IGNORED | characters dropped before any text lookup (test-enforced) |
| "WEF: APR'26" (effective date) | **POSSIBLY LOST** | no effective-date column exists anywhere |

### Fras-le "XTRA LIFE" (4 pp)
Sr. No. (group number) **POSSIBLY LOST** · OEM MAPPED · Segment MAPPED · New Part No MAPPED (`part_no` + `variant_label`) · Vehicle Application MAPPED · Front/Rear **POSSIBLY LOST as a field** (only inside the generated description text) · No. of pcs per set **POSSIBLY LOST as a field** (only inside the description text) · Std. packing MAPPED (`pack_qty`) · MRP MAPPED · HSN (page header) MAPPED · "w.e.f. 01-04-2026" **POSSIBLY LOST**.

### Neolite aftermarket price list (14 pp)
Product code MAPPED · Description MAPPED · Unit MAPPED · Std pkg MAPPED (`pack_qty`) · MRP till 31.03.2026 MAPPED (`mrp_prev`) · Revised MRP MAPPED (`mrp`) · section headings MAPPED into application/make/segment · "W.E.F 01-April-2026" **POSSIBLY LOST**. Neolite's second PDF (`Neo-Catelogue Design-1.pdf`: "Suitable for", bulb fitment, unit/assy, parking) is **not ingested** (see B3).

### Car International (80 pp)
PART NO, DESCRIPTION, NEW LIST (→ `mrp`), UNIT, HSN MAPPED · RATE (GST 18 %) MAPPED to `gst_pct` (it is a tax rate, not a dealer rate) · "Feb-26" **POSSIBLY LOST**. Vehicle make/model are *derived* from description keywords, not printed.

### Meko price list (32 pp)
S.No (position), PART No, MRP, application text, REF. NOS. (→ `cross_refs`) MAPPED · section titles MAPPED · "Price: …" Z-series cards MAPPED · "01/01/2026" **POSSIBLY LOST** · 6 cover/index/ad pages and the code-list page 29 not read (reported as unrecognised).

### Meko catalogue (80 pp, images)
Model code + photo MAPPED (`image_url` on 227 existing products) · application text and REF. NOS. printed on every card **not stored** (duplicates the price list) · **56 catalogue codes have no price-list product, so their photo and card data are lost** (**POSSIBLY LOST**).

### Pensol dealer list (2 scanned pp)
PRODUCT MAPPED (`part_no`, name) · spec lines MAPPED **incompletely** (finding D12) · PACKING MAPPED (`variant_label`) · MRP PER PC MAPPED · RATE DELIBERATELY IGNORED · "inclusive of all taxes" MAPPED (`price_basis`) · "01 April 2026" **POSSIBLY LOST**.

| ID | Item | Status | Evidence |
|---|---|---|---|
| B1 | Every printed column documented as mapped / ignored / lost | PASS | tables above; staging holds only the 24 whitelisted keys (no profile can emit another) |
| B2 | No POSSIBLY LOST columns | **FAIL** | Uno Minda CLASS, PRODUCT TYPE, NPD STATUS; Fras-le group no., Front/Rear and pcs-per-set as fields; every price list's effective date; 56 unmatched Meko catalogue cards |
| B3 | Every supplied PDF ingested | **FAIL** | not used: `Neo-Catelogue Design-1.pdf` (37 pp), `Automotive Dealer … (1).pdf` (byte-identical duplicate), `03_Master … -5-39.pdf` (pages 5–39 of the ingested file) |
| B4 | Stored originals match what was uploaded | PASS | 7/7 applied batches: file exists, sha256 equals `file_sha256`; no orphan files in storage |
| B5 | Staging cannot carry unlisted columns | PASS | `batch_rows.data` has 24 distinct keys, all in the whitelist; profile emitting another key aborts the parse |

---

## 3. Minimum display test (C)

Rows missing a field the public card needs.

| Brand | rows | no part no. | no description | no MRP |
|---|---|---|---|---|
| Car International | 4,640 | 0 | 0 | 0 |
| Fras-le | 157 | 0 | 0 | 0 |
| Meko | 511 | 0 | 0 | 0 |
| Neolite | 492 | 0 | 0 | 0 |
| Pensol | 202 | 0 | 0 | **18** |
| Uno Minda | 3,948 | 0 | **1** | 0 |

Brand is never null (foreign key). Examples (source file · page · row):
- Missing MRP (all Pensol, "NA" in the PDF): `PENSOL URANUS PLUS` 26 LTR BKT — *Automotive Dealer Price List…pdf* p1 #1; `PENSOL DIAMOND EX 36000 Plus` 50 LTR PLY DRM — p1 #7; `PENSOL DIAMOND EX 36000` 50 LTR PLY DRM — p1 #16; `PENSOL PLATINUM EX TURBO` 50 LTR.PLY DRM — p1 #31; `PENSOL DIAMOND SUPER PLUS` 50 LTR PLY DRM — p1 #43.
- Missing description: `SW-1622M` — *03_Master Price List…pdf* p28 #2921.
- Not in the database at all because the price could not be read or the row was a duplicate (5 rows held): Meko `M-542` (p7, MRP unreadable); Meko catalogue `M-871` (p53, duplicate); Pensol `PENSOL APLR 100000` 18 KG BKT and 10 KG BKT (p1, OCR could not read the price), Pensol `PENSOL GEAR TX 80W 90` 4X5 LTR JAR (p2, same).

| ID | Item | Status | Evidence |
|---|---|---|---|
| C1 | Part number on every row | PASS | 0 missing |
| C2 | Brand on every row | PASS | 0 missing |
| C3 | Description on every row | **FAIL** | 1 row (above) |
| C4 | MRP on every row | NEEDS HUMAN | 18 Pensol "NA" rows; decide whether to show "price on request" |
| C5 | No real product silently absent | NEEDS HUMAN | 5 held rows listed above; the reports show them, but the public site cannot |

---

## 4. Extraction accuracy (D)

### Rows per page (parser), and independent counts
| File | Pages | Parser rows | Independent method | Result |
|---|---|---|---|---|
| Uno Minda master list | 39 | 3,948 | serial-number words at x<38 (PyMuPDF), compared **as sets** | **identical set 1…3,948**, no gaps, no extras; pages 1–5 = serials 1…590 (590 rows) |
| Fras-le | 4 | 157 | count of `₹` tokens per page | 157 = 157; per page 43/45/45/24 match |
| Neolite | 14 | 492 | lines starting with a code and ending in two numbers | 673 raw rows = 492 products + 181 repeated listings merged (matches the parser's own merge note) |
| Car International | 80 | 4,640 | UNIT-column words (Pcs/Set/Kit) | 4,638 vs 4,640 — 2 rows unreconciled (p16: one row prints "UNIT" in the unit column; p48: not explained) |
| Meko price list | 32 | 512 (+1 held) | serial anchors + `Price :` cards | 512 = 512 on every recognised page |
| Pensol | 2 | 205 (202 stored) | container words (JAR/BKT/DRM) at 330 dpi | 198 vs 205 (same OCR engine; not independent enough) |
| Meko catalogue | 80 | 284 codes matched (227 products enriched, 56 unmatched, 1 duplicate) | none available | NEEDS HUMAN |

Rows per page, parser (selected): Uno Minda 120,120,120,120,110,105×23,78,**47**,60,80,81,105,99,105,106,106,76 (page 30 is thin but its serials 3084–3130 are continuous: tall wrapped rows). Fras-le 43/45/45/24. Car International 37–63 (pages 55 and 80 lowest). Meko price list: 25,32,28,31,25,29,25,26,4,10,8,18,24,26,24,8,40,37,31,28,33 on the recognised pages; the other 14 pages are brochure/index/ad pages or unrecognised layouts.

Pages listed as needing OCR: Meko price list p3, 4, 5, 16, 30 (brochure photos: text read with OCR, contain no price rows); Pensol p1, 2 (read with OCR); catalogue all pages (read with OCR). No scanned price page remains unread. Pages with unrecognised layout (reported, not guessed): Meko p1, 2, 6, 29, 31, 32.

### Flagged rows by reason (applied batches)
Car International: no_vehicle_detected 1,089 · bad_hsn 150 · mrp_outlier 143 · vehicle_guess 62 · variant_inferred 58. Fras-le: oem_guess 18. Meko: no_ref_numbers 65 · no_section 33 · duplicate 1 · bad_mrp 1. Neolite: oem_guess 33 · alt_descriptions 21 · variant_inferred 12 · mrp_decreased 2 · mrp_outlier 1. Pensol: no_mrp 18 · check_alignment 6 · low_ocr_confidence 4 · pack_decimal_fixed 3 · bad_mrp 3 · price_per_litre_outlier 1 (+ `ocr` on all 205). Uno Minda: oem_guess 141 · clipped_description 117 · mrp_outlier 95 · unknown_oem 38 · segment_guess 17 · unknown_pgroup 2 · long_part_no 2. Total 2,056 rows carry at least one flag (full list: `data/reports/flagged_all_brands.csv`).

### 10 random rows per brand to check against the PDF (seed 20261105)
(`brand | file | page #serial | part no | variant | MRP | description`)

**Uno Minda** (*03_Master Price List 4WH MAR FY 26-27.pdf*): p25 #2634 `SS-1512FR2` 2154 STRUT ELEMENT(G)FRNT RH-IND V2 · p14 #1469 `HL-5686M` 2927 HEAD LIGHT W WIRE I-10 T2-LH · p36 #3597 `S21236-000M00` 1000 PWS MAIN-THAR · p24 #2526 `GS-1007L` 414 GAS SPRING LEFT-RITZ · p5 #551 `A11613005Q01` 2539 UNIVERSAL TRACTOR SEAT BELT- RETRACTABLE · p9 #975 `TD-1122` 255 TEMPERATURE SENSOR GREY COUPLER · p4 #464 `A11102158A01` 1235 EICHER/ TMTL BACK REST 36HP, 50HP · p37 #3673 `HL-5653AMM` 3431 HL ASSY MTR SCORPIO T-2-RH · p10 #1037 `AF4114PU` 254 HYND-SNTRO · p2 #134 `MB03013017` 306 DIAPHRAGM TYPE 24

**Fras-le** (*AFF_XL_PRICE_LIST_01.04.26.pdf*): p2 `AFF/XL/AL/TP/SM/3&4` STD 3499 · p2 `AFF/XL/AL/TP/SM/1&2` STD 2884 · p1 `AFF/XL/PRIMA/12` STD 4945 · p2 `AFF/XL/AL/SM/BS6/HLP-8` OS-2 5768 · p2 `AFF/XL/AL/E-COM` STD 2729 · p2 `AFF/XL/AMW/1` OS-1 4645 · p1 `AFF/XL/WTP/2` STD 5385 · p4 `AFF/XL/NTTR/407` STD 1790 · p1 `AFF/XL/T407/1&2` OS-1 1301 · p3 `AFF/XL/MAN/RR/8` OS-1 4890

**Neolite** (*Price List w.e.f 01 April 2026.pdf*): p8 `Neo-1713` 455 · p4 `NEO-626 A` 896 · p8 `NEO-788` 350 · p13 `NEO-1358` 390 · p6 `PPI-651` 281 · p2 `NEO-207A` 674 · p12 `NEO-929 W` 524 · p7 `NEO 1485` 688 · p11 `AUX-23` 822 · p8 `PPI-197 X` 482

**Car International** (*NEW PRICE LIST 2026 WHSN.pdf*): p18 `1321` 73 RADIATOR CAP BIG TABLE LEYLAND 4018 ETC · p21 `1539` 41 DR.STRIKER TAVERA,MAXIMO,XYLO · p14 `1055` 364 DOOR LATCH ASSY ALTO REAR · p59 `22043` 247 BRAKE SHOE FRONT BAJAJ MAXIMO Z(SET OF 2 · p24 `1778` 410 W.R.ASSY INNOVA POWER REAR · p61 `30229` 1430 ORVM XCENT ADJUSTABLE · p42 `9071` 200 O.H. I-20 CHROME FRONT · p24 `1782` 138 R.C. LOCK ASSY ALTIS · p67 `30957` 15510 12 IN 1 BAGGAGE BOX INDICATOR HANDLE KIT · p44 `9516` 17 KNOB W/ROD & W/WASHER & LOCK VOLVO

**Meko** (*PRICE LIST 2026.pdf*): p7 `M-412` 6380 · p19 `M-871 X` 2860 · p21 `M-555` 2936 · p20 `M-830 F` 2250 · p27 `M-82001` 490 · p18 `M-538 A (Z)` 4160 · p14 `M-606` 2138 · p7 `M-406` 2964 · p26 `M-6815` 1375 · p14 `M-865 A` 3392

**Pensol** (*Automotive Dealer Price List…pdf*): p2 `PENSOL T.Q.X.` 20 LTR.BKT 7061 · p2 `PENSOL T.Q.X.` 4X 5 LTR JAR 1804 · p2 `PENSOL POWERTRANS WBF` 50 LTR PLY DRN (no MRP) · p2 `PENSOL 4ST SM` 20 X 900 ML JAR 480 · p2 `PENSOL PXT PRIDE` 20X 1 LTR. JAR 616 · p2 `PENSOL GEAR TX 80W 90` 50 LTR PLY DRN (no MRP) · p1 `PENSOL DIAMOND EX 36000 Plus` 6X 3 LTR JAR 1389 · p2 `PENSOL PXT ULTRA` 4X3 LTR JAR 1619 · p2 `PENSOL PXT DIESEL` 7 LTR BKT 2982 · p1 `PENSOL HDBF CRIMSON PLUS` 100 x 100 ML JAF 87

| ID | Item | Status | Evidence |
|---|---|---|---|
| D1 | Rows per page plausible; thin pages explained | PASS | thin pages: Uno Minda p30 (47, serial-continuous), Meko brochure pages |
| D2 | Uno Minda rows = PDF rows (serials 1…3,948; sample 1…590) | PASS | independent serial set identical to parser set, 0 differences |
| D3 | Fras-le = 157 | PASS | 157 = 157 per page |
| D4 | Neolite rows reconcile | PASS | 673 raw = 492 + 181 merged (**whether each merge is right is D10/NEEDS HUMAN**) |
| D5 | Car International = PDF | NEEDS HUMAN | 4,638 vs 4,640; verify pages 16 and 48 by eye |
| D6 | Meko price list = PDF | PASS | 512 = 512 on recognised pages |
| D7 | Pensol = PDF | NEEDS HUMAN | 205 parsed vs 198 estimated by a second OCR pass |
| D8 | Meko photos attached to the right product | NEEDS HUMAN | 284 matches, never checked beyond 2 products |
| D9 | Pages needing OCR identified and handled | PASS | listed above; none unread |
| D10 | Flagged rows triaged | NEEDS HUMAN | 2,056 rows; ~340 are parser guesses (192 make, 62 vehicle, 17 segment, 70 variant labels) |
| D11 | Hand verification of random rows | NEEDS HUMAN | 60 rows listed above |
| D12 | Pensol spec lines (SAE grade) attached to every pack row | **FAIL** | 116 of 202 rows lack the grade (only 24 of 44 product names carry it): the spec line is read after the first pack rows and only later rows get it. Proposed fix: attach specs to the whole group after grouping |
| D13 | No corrupted/interleaved text in descriptions | NEEDS HUMAN | an interleaving bug (multi-line Uno Minda cells) was found and fixed earlier in this project (100 rows resynced); no automated detector exists — spot-check long descriptions |

---

## 5. Data quality (E)

- **Part numbers shared across brands:** 0. **Different printed numbers normalising to the same value (same brand):** 0 (the parsers merge or label such cases before storage — see Neolite 181 merges, Car International 58 inferred labels).
- **MRP (min / median / max / rows over 10× the brand median):** Car International 2 / 277 / 18,306 / 145 · Fras-le 1,088 / 4,305 / 7,326 / 0 · Meko 61 / 2,636 / 22,000 / 0 · Neolite 21 / 551.5 / 37,429 / 3 · Pensol 18 / 1,782.5 / 13,688 / 0 · Uno Minda 3 / 762.5 / 99,345 / 140. 41 Car International rows cost under ₹5 (e.g. `W.R.HANDLE CAP` ₹2; plausible for caps, check) and Uno Minda's top prices (`H15700096A00` ₹99,345) are real LED/lamp assemblies per the list but should be eyeballed. 0 rows have MRP ≤ 0.
- **Whitespace / odd characters:** part numbers clean. `variant_label` has 2 values with a trailing space (Car International). 7 Car International descriptions contain a backslash (`W\KEY`, `L\R`, `O\M` — the PDF prints a backslash). 40 descriptions contain curly quotes/dashes (Neolite ” ×37, Car International ’ ×6, – ×2). No control characters.
- **Make names (71 distinct single makes):** inconsistent spellings of the same maker: *Leyland* vs *Ashok Leyland*; *Ford New Holland* vs *New Holland* vs *Case New Holland*; *Mitsubishi* vs *Mitsubishi Fuso*; *Massey Ferguson* vs *TAFE (Massey Ferguson)*; *Suzuki* vs *Maruti Suzuki*; *Swaraj* vs *Swaraj Mazda*; *Volvo* vs *Volvo Eicher (VECV)*. "Universal" (604 rows) is stored as a make. 274 rows hold several makes in one string ("Tata / Mahindra"), so make filtering relies on `ILIKE`. Parenthetical makes appear ("ACE (Action Construction Equipment)").
- **Category vocabulary differs by brand for the same thing:** *Mirrors* (Car Intl) vs *Rear View Mirrors* (Uno Minda); *Head Lamps* / *Head & Tail Lamps* / *Lamps*; *Sensors* vs *Switches & Sensors* vs *Switches & Clock Springs*; *Brake Linings* (2 brands) fine but *Water Pump Kits/Impellers* separate from *Water Pumps*; 48 categories overall.

| ID | Item | Status | Evidence |
|---|---|---|---|
| E1 | No unintended part-number collisions across brands | PASS | 0 |
| E2 | No two printed numbers collapse to one normalised value | PASS | 0 |
| E3 | MRP outliers explained | NEEDS HUMAN | 145 + 140 rows over 10× brand median; 41 rows under ₹5 |
| E4 | No stray whitespace / odd characters | **FAIL** | 2 trailing-space variant labels; 7 backslash descriptions; 40 curly quotes |
| E5 | One canonical name per make | **FAIL** | see list above; "Universal" counted as a make; multi-make strings |
| E6 | One category vocabulary across brands | **FAIL** | e.g. Mirrors vs Rear View Mirrors; 48 categories |
| E7 | No zero or negative prices | PASS | 0 rows MRP ≤ 0 |

---

## 6. Schema review (F)

- **Fresh rebuild:** migrations 001–004 applied to an empty database give **identical columns (119) and indexes (27)** to the live database.
- **Columns empty for every brand:** none, except `stock_status` and `status` which are constants by design (`ask`, `published`). Tables `vehicles` and `fitments` are empty (0 rows); `cross_refs` 510; `change_log` 38,093 (41 MB for ~10k products, ~4 KB per product per run).
- **Unique key:** `unique (brand_id, part_no_norm, variant_label)`. Works for Fras-le (STD/OS-1/OS-2/OS-3 = 50/50/50/7 rows, 122 part numbers carry several variants) and Pensol pack sizes. Weakness: `variant_label` is not trimmed, so `'X '` and `'X'` are different keys.
- **Indexes missing:** five foreign keys have no index — `cross_refs.product_id` (hit by every search and delete), `products.first_batch_id`, `sync_runs.batch_id`, `change_log.run_id`, `fitments.vehicle_id`. No index backs the segment/category/make filters or the substring search (all sequential scans; fine at 10k, not at 100k+).
- **Foreign-key deletes:** products → `cross_refs`, `fitments`, `product_search` CASCADE; batch history (`import_batches`, `sync_runs`, `change_log`, `audit_events`, `batch_rows`) NO ACTION (history is kept by design). Appropriate.
- **Append-only:** `UPDATE` and `DELETE` on `audit_events` and `change_log` raise an exception (tested). `TRUNCATE change_log` **succeeded** for the table owner (38,093 → 0 rows in the copy): the guard is row-level only.
- **RLS:** enabled on all 14 public tables; policies only for `products` (published), `brands`, `cross_refs`. `cross_refs` policy is `using (true)`, so refs of *hidden* products would be readable.
- **Can the schema hold the planned data without a rewriting migration?**
  - *Vehicle fitments:* tables exist (`vehicles(make, model, engine, notes)`, `fitments`) but the batch engine ignores them: `change_log` states do not include fitments, resync/delete will not restore them, no profile writes them, and `vehicles` has no year range or body fields. **No.**
  - *Multiple images:* one `image_url` text column. **No** (needs a `product_images` table and a data move).
  - *Supersession:* `cross_refs.ref_type` allows `supersession`, but there is no direction (replaces / replaced by) or validity date. **Partly.**
  - *Manual edits:* nothing marks a field as hand-edited; every resync rewrites every column from the PDF (plan phase 2 requires protection). **No.**
  - *Effective date of a price list:* no column on batches or products. **No.**

| ID | Item | Status | Evidence |
|---|---|---|---|
| F1 | Migrations rebuild the schema from scratch | PASS | fresh DB: 119 = 119 columns, 27 = 27 indexes |
| F2 | Variants (OS-n, pack sizes) handled by the unique key | PASS | Fras-le 50/50/50/7, 122 multi-variant part numbers |
| F3 | No dead columns | PASS | only constant defaults |
| F4 | Indexes adequate | **FAIL** | 5 unindexed FKs; no filter/search indexes |
| F5 | Delete behaviour of foreign keys is deliberate | PASS | list above |
| F6 | Fitments storable and reversible without a rewrite | **FAIL** | engine ignores fitments; vehicles lacks year/engine detail |
| F7 | Multiple images per product | **FAIL** | single `image_url` |
| F8 | Supersession | **FAIL** | no direction/validity |
| F9 | Manual edits survive a resync | **FAIL** | no override/lock mechanism |
| F10 | History tables truly append-only | NEEDS HUMAN | row triggers block UPDATE/DELETE; TRUNCATE allowed for the owner role |
| F11 | `change_log` growth acceptable | NEEDS HUMAN | 41 MB now (full before/after JSON per change); a 100k-product catalogue re-synced a few times will be several hundred MB |
| F12 | RLS policies leak nothing | **FAIL** | `cross_refs` readable regardless of the product's published status |

---

## 7. Never-stored rule (G)

- **Column names** (all 14 public tables): 0 names containing discount / dealer / trade / margin / net / scheme / cut / rate (except `gst_pct`) / td / cd.
- **JSON keys:** `batch_rows.data` (24 keys), `change_log.before/after` (31 keys each), `audit_events.details` (34 keys), cross-ref elements, search-index documents (16 keys) and `search/meili_settings.json`: 0 forbidden keys.
- **Data-only dump** (`pg_dump --data-only`, 49.8 MB): 0 forbidden JSON keys. Whole-word hits, counts only: `td` in 221 products/221 staging rows = part numbers that start with `TD-` (Uno Minda temperature sensors); `cut` in 7 products (e.g. "CUT-OFF VALVE"); `cd` 4; `dealer` only in the *file name* "Automotive **Dealer** Price List" (2 batch rows, 3 audit rows). Nothing resembling a discount or dealer price is stored in a catalogue table.
- **Logs and generated files:** `/tmp/*.log` and `data/reports/*.csv` clean. **`data/ocr_cache/*.json` (2 Pensol page files) and `data/scratch/p1.json`, `p2.json` each hold 202 numbers from the dealer RATE column** (the OCR output is cached *before* the RATE column is discarded). They are git-ignored but exist on disk.
- **Saved originals:** all 7 stored PDFs are unredacted (`redacted=false`); the Uno Minda file still prints the TD% column and the Pensol file the RATE column. `REDACT_ON_UPLOAD` is opt-in and off (owner deferred it).
- **The automated test** (`tests/test_never_stored.py`) exists and runs in the 50-test suite. Evidence it fails on a new column: adding `discount_pct` to the throwaway copy and running the test's own schema query listed `('products', 'discount_pct')`. Names that **would not** be caught (snake_case token list only): `cd_pct`, `ndp`, `dp`, `wholesale_price`, `purchase_price`, `landing_cost`, `cost_price`, `TDPercent`, `tradeDiscount`, `tdpct`, `dealerrate`. It does not scan stored values, files, or caches, and nothing runs it automatically (no CI).
- Positive tests that pass: the Uno Minda profile never looks up text in the TD% column; Pensol RATE-column words never reach the row builder.

| ID | Item | Status | Evidence |
|---|---|---|---|
| G1 | No forbidden column names | PASS | 0 in 14 tables |
| G2 | No forbidden JSON keys in staging / change_log / audit | PASS | 0 across 24/31/34 keys |
| G3 | Data-only dump clean | PASS | 0 keys; word hits explained (TD- part numbers, "cut-off", file name) |
| G4 | No discount / dealer-rate values in logs or generated files | **FAIL** | 202 dealer-rate numbers in `data/ocr_cache/` (2 files) and 202 in `data/scratch/p1.json`/`p2.json` |
| G5 | Search index settings and documents clean | PASS | 0 hits |
| G6 | Automated never-stored test exists | PASS | `tests/test_never_stored.py`, passing |
| G7 | Test fails if a forbidden column is added | PASS | `discount_pct` caught on the copy |
| G8 | Test covers realistic naming variants and values | **FAIL** | 11 plausible names slip through; no value/file/cache scan |
| G9 | Saved originals free of discount/dealer columns | **FAIL** | 7/7 unredacted; redaction off |
| G10 | The test runs automatically before every deploy | **FAIL** | no CI configuration anywhere |
| G11 | Pensol RATE words never reach row building (test) | PASS | `test_rate_column_words_never_reach_the_row_builder` |
| G12 | Uno Minda TD% column never read (test) | PASS | `test_profile_never_reads_the_skipped_column` |

---

## 8. Batch engine on the throwaway copy (H)

Fingerprint = md5 of `products`, `cross_refs`, `fitments` (as JSON, ordered). Copy and main were identical at the start (`5e5c77b3bcbb` / 9,950).

| Test | Result |
|---|---|
| Delete the Neolite batch, re-upload the same PDF, apply, delete again | fingerprint before apply = after delete exactly (`6e4360880e54`, 9,914 products); 36 inserted, 36 deleted |
| Duplicate upload | warning raised; 2 earlier batches with the same sha256 reported; `duplicate_file_warning` audited |
| Resync unchanged Fras-le file (with "remove missing") | preview 0 / 0 / 0, 157 unchanged; applying it left the fingerprint and `change_log` row count (38,072) unchanged |
| Resync of a modified copy of the Fras-le PDF (one price edited, one row blanked) | preview: 3 updates, 0 inserts, 0 removals (1 removal with "remove missing"). Compared with a parser-only diff of the two files: exactly 1 price change (3,474 → 3,499), 2 `application` changes on the neighbouring group rows (my edit had also removed part of the merged application cell), 1 removed row. **Engine diff = file diff.** Previewing changed nothing |
| Later conflicting batch, then delete the earlier batch | **139 of 157 products reported as conflicts instead of 1** (see H2) |
| Corrupt files | random bytes and 0-byte file: rejected at upload ("not a readable PDF"), nothing stored. Truncated PDF: accepted, parse failed cleanly (`status failed`, "Unexpected EOF"), file kept. Neolite PDF parsed with the Fras-le profile: 0 rows, all 14 pages "unrecognised", nothing guessed |
| Timeline / audit | every step present for apply→delete: `file_uploaded, duplicate_file_warning, parse_started, parse_finished, rows_flagged, batch_applied, search_reindexed, batch_delete_requested, batch_deleted, search_reindexed`; `sync_runs`: initial (+36) then delete (−36). Event type `login` (in the plan) never occurs |
| Search table vs database after all operations | 0 products with missing/stale search text, 0 orphan rows |

**Critical finding (H2).** Before cross-reference support was added, `change_log` states were written without a `cross_refs` key. Rollback compares the product's current state with the logged "after" state and treats any difference as "changed since this batch wrote it". **8,739 of 9,950 products (88 %) have such legacy states** (Car International 4,443, Uno Minda 3,701, Neolite 456, Fras-le 139). Deleting any of those four batches would skip almost every product as a "conflict" (reproduced: 139/157). Batches created since the change (Meko, Pensol, and anything re-applied) are unaffected, and the repository test for conflicts passes for them. Proposed fix (not applied): compare states ignoring a missing `cross_refs` key, or back-fill the key in `change_log`; add a regression test using a legacy-shaped log entry.

| ID | Item | Status | Evidence |
|---|---|---|---|
| H1 | Apply then delete restores the catalogue exactly | PASS | identical fingerprint (new batch) |
| H2 | …also for batches already in the database | **FAIL** | 8,739 products with legacy log states; delete would skip them |
| H3 | Resync of an unchanged file changes nothing | PASS | 0/0/0, no new `change_log` rows |
| H4 | Resync of a modified file produces exactly the right diff | PASS | engine diff = independent file diff |
| H5 | Duplicate upload warns | PASS | 2 prior batches reported |
| H6 | Deleting a batch lists and skips later conflicting changes | PASS | works for current-format batches (repo test `test_delete_skips_products_changed_by_a_later_batch`); legacy limitation is H2 |
| H7 | Corrupt files handled without damage | PASS | rejected/failed cleanly; no catalogue change |
| H8 | Timeline and audit log record every step | PASS | list above |
| H9 | Logins audited | **FAIL** | no `login` events (no admin login exists) |
| H10 | Search table matches the database after operations | PASS | 0 stale, 0 orphan |
| H11 | A real Meilisearch index matches the database | NEEDS HUMAN | never run; only a fake-server test |
| H12 | A failure half-way through an apply leaves nothing behind | NEEDS HUMAN | code runs apply in one transaction and marks the batch `failed`; no test injects a failure |

---

## 9. Search quality (I)

Run through `pgsearch.search` against the main database (read-only), 9,950 products. "Rank" = position of the first acceptable result among the top 30.

| Case | Query | Total | Rank | ms |
|---|---|---|---|---|
| part number | `MB04015028` | 1 | 1 | 66 |
| lower case | `mb04015028` | 1 | 1 | 55 |
| spaces | `MB 0401 5028` | 1 | 1 | 57 |
| dashes | `MB-0401-5028` | 1 | 1 | 56 |
| mixed | `mb 0401-5028` | 1 | 1 | 56 |
| prefix (6 / 4 chars) | `MB0401` / `MB04` | 47 / 97 | 1 / 1 | 53 / 55 |
| Neolite / Fras-le / Meko codes | `NEO-800A`, `neo800a`, `AFF/XL/TTS/1`, `aff xl tts 1`, `M-513`, `m513` | 3–6 | 1 each | 53–58 |
| OEM / cross-ref number | `3532005601` (→ M-540) | 1 | 1 | 55 |
| second half of a doubled number | `1203` (→ `141/1203`) | 6 | 1 | 52 |
| abbreviation | `DBV` | 43 | 1 | 86 |
| abbreviation | `T.L. swift` / `W.R. handle` | 35 / 102 | 1 / 1 | 90 / 145 |
| abbreviation | **`H.L. alto`** | **0** | – | 54 |
| spelled out | `window regulator handle`, `head lamp alto` | 102 / 16 | 1 / 1 | 130 / 114 |
| make + part | `tata brake valve`, `maruti door lock`, `eicher water pump`, `bolero orvm`, `tata 1612 brake lining` | 9–50 | 1 each | 58–109 |
| make alias | `tml brake valve` | 19 | **5** | 85 |
| one-letter typo | **`brake vlave`**, **`brake pd`**, **`hornn`** | **0 / 0 / 0** | – | ~50 |
| no-space two-word term | `headlamp` / **`waterpump`**, **`doorlock`**, **`brakepad`** | 176 / **0 / 0 / 0** | 1 / – | 49–86 |
| plural | `brake pads` | 209 | **12** | 51 |
| empty / spaces only | `` | 9,950 | – | 16 |
| nonsense | `qzxvbnmw`, `7731990044` | 0 | – | 48–54 |
| symbols | `%`, `_`, `'` | **9,950** | – | 19 |
| SQL-ish | `x'; drop table products;--` | 0 (no error) | – | 53 |
| 60 repeated words | `brake brake …` | 829 | 1 | **294** |

Latency over 35 mixed runs: **p50 54 ms, p95 106 ms, max 106 ms** at 9,950 products (plan target: p95 < 100 ms at 100,000). The query does a full scan with `ILIKE` on a text column, so expect roughly 10× slower at 100k.

| ID | Item | Status | Evidence |
|---|---|---|---|
| I1 | `search/tests/queries.json` regression set exists and passes | **FAIL** | file missing; `search/tests/` is empty |
| I2 | Part numbers with spaces, dashes, lower case | PASS | rank 1 in 5/5 |
| I3 | Prefix search | PASS | rank 1 for `MB0401`, `MB04` |
| I4 | OEM / cross-reference numbers | PASS | `3532005601`, `1203` rank 1 |
| I5 | Abbreviations both ways | **FAIL** | `H.L. alto` returns nothing (DBV, T.L., W.R. pass) |
| I6 | Make + part type | PASS | 5/5 rank 1; alias `tml` rank 5 |
| I7 | One-letter typos | **FAIL** | 0 results in 3/3 (no fuzzy matching) |
| I8 | No-space versions of two-word terms | **FAIL** | 3 of 4 return nothing |
| I9 | Plurals / stemming | **FAIL** | `brake pads` best hit at rank 12 |
| I10 | Empty query behaviour | NEEDS HUMAN | returns the whole catalogue (9,950) |
| I11 | Nonsense returns nothing, never errors | PASS | 0 results, no errors on 5 odd inputs |
| I12 | Symbol-only queries behave | **FAIL** | `%`, `_`, `'` return all 9,950 products |
| I13 | p95 < 100 ms | **FAIL** | 106 ms at one tenth of the target size; 294 ms for a long query |
| I14 | Behaviour and speed at 100k products with Meilisearch | NEEDS HUMAN | not built / not run |

---

## 10. Security (J)

Public web app (:3000) and the ingest API (:8765), probed anonymously. Row-level security was exercised in the throwaway copy by creating a role with the broad table grants Supabase gives `anon` by default, then issuing reads and writes as that role (the real Supabase `anon` key/bucket cannot be tested locally).

- **Public routes** (`/api/search`, `/api/product/{id}`, `/api/config`, `/img/…`, `/`) only. No batch, table or file listing routes. Paths like `/img/../batches/x`, `/img/%2e%2e/%2e%2e/data/pgdata/PG_VERSION`, `/.env`, `/.git/config` → 404. `POST/PUT/DELETE/PATCH` on the API → 405.
- **As the anonymous database role:** `products` 9,895 (published only; the one product I hid in the copy was invisible), `brands` 6, `cross_refs` 510; **0 rows** from `import_batches`, `batch_rows`, `sync_runs`, `change_log`, `audit_events`, `product_search`, `make_aliases`, `abbreviations`, `category_map`, `vehicles`, `fitments`. `INSERT` into `products`/`audit_events`: blocked by RLS; `UPDATE`/`DELETE`: 0 rows; `TRUNCATE`: denied; `DROP TABLE`: denied.
- **Stored PDFs:** the web app has no route to them; traversal attempts failed. Local storage is a plain folder; the Supabase private-bucket setting (`public=false`) is in migration 002 but untestable here.
- **`/admin`** → 404, because **no admin app or login exists** (Day 3 of the plan was not built; uploads happen by CLI).
- **Ingest API:** no header 401, wrong secret 401, right secret without actor 400, right secret with actor reaches the app (an unknown batch id returns an unhandled 500). `/docs` and `/openapi.json` are public on both apps.
- **Secrets:** 64 tracked files, 8 commits. No JWTs, API keys, private keys or assigned secrets in the tree or in `git log -p`; the one connection-string match is the placeholder in `.env.example`. No PDFs, caches or storage were ever committed.
- **Rate limiting:** none in code or config. 300 rapid anonymous requests all returned 200; an anonymous client enumerated **all 9,950 products with 100 requests in 2.8 s** (`limit` max 100, offset unbounded).

| ID | Item | Status | Evidence |
|---|---|---|---|
| J1 | Anonymous cannot read non-public tables | PASS | 0 rows from 11 tables (simulated RLS) |
| J2 | Anonymous cannot write or destroy | PASS | insert blocked, update/delete 0 rows, truncate/drop denied |
| J3 | Stored PDFs unreachable from the public app | PASS | no route; 6 traversal attempts → 404 |
| J4 | Supabase bucket is private and signed-URL only | NEEDS HUMAN | cannot test without a Supabase project |
| J5 | `/admin` requires login | **FAIL** | no admin app and no auth exist |
| J6 | Ingest API requires the shared secret | PASS | 401 / 401 / 400 as above |
| J7 | No public API docs, no stack traces | **FAIL** | `/docs`, `/openapi.json`, `/redoc` open; unhandled 500 on unknown batch |
| J8 | No secrets in the repository or history | PASS | pattern scan of 8 commits: 0 real secrets |
| J9 | Rate limiting exists | **FAIL** | none; 300/300 requests served |
| J10 | Bulk scraping of the catalogue is hard | **FAIL** | full enumeration in 2.8 s |

---

## 11. Operations (K)

| ID | Item | Status | Evidence |
|---|---|---|---|
| K1 | Automated test suite passes | PASS | 50 passed in 87 s |
| K2 | The ingest service can be built for deployment | **FAIL** | `docker-compose.yml` builds `./ingest`, but there is no `Dockerfile` |
| K3 | CI runs tests on every change | **FAIL** | no CI/pre-commit configuration |
| K4 | Backup and restore procedure exists | **FAIL** | none documented; the data directory is a local `pgdata` folder |
| K5 | Admin UI for upload / batches / audit (plan Day 3) | **FAIL** | not built; CLI only |
| K6 | Production configuration (Supabase, Meilisearch, env vars) exercised | NEEDS HUMAN | only local Postgres has ever been used |

---

## Scorecard

| Section | Items | PASS | FAIL | NEEDS HUMAN | Passed % |
|---|---|---|---|---|---|
| A Field coverage | 14 | 2 | 8 | 4 | 14 % |
| B Source vs saved | 5 | 3 | 2 | 0 | 60 % |
| C Minimum display | 5 | 2 | 1 | 2 | 40 % |
| D Extraction accuracy | 13 | 6 | 1 | 6 | 46 % |
| E Data quality | 7 | 3 | 3 | 1 | 43 % |
| F Schema | 12 | 4 | 6 | 2 | 33 % |
| G Never-stored rule | 12 | 8 | 4 | 0 | 67 % |
| H Batch engine | 12 | 8 | 2 | 2 | 67 % |
| I Search quality | 14 | 5 | 7 | 2 | 36 % |
| J Security | 10 | 5 | 4 | 1 | 50 % |
| K Operations | 6 | 1 | 4 | 1 | 17 % |
| **Total** | **110** | **47** | **42** | **21** | **42.7 %** |

(NEEDS HUMAN counted as not passed.)

## Critical items that failed or could not be verified

1. **H2** — batch delete/rollback is effectively broken for 8,739 of 9,950 products (legacy `change_log` states). The headline safety feature does not work on today's data.
2. **G4 / G9** — ~400 dealer-rate numbers sit in `data/ocr_cache` and `data/scratch`; every stored original still contains its TD%/RATE column; redaction is off.
3. **A14** — price basis (incl. or excl. GST) is unknown for 9,591 rows; the public site shows MRP without saying which.
4. **D12** — 116 of 202 Pensol rows lack the oil grade (SAE …), the most important search term for oils.
5. **B2** — columns the sources print and we drop (Uno Minda CLASS / PRODUCT TYPE / NPD STATUS, price-list effective dates, Fras-le group number, pcs-per-set as a field, Neolite bulb/fitment catalogue).
6. **J5 / K5 / J9 / J10** — no admin login or UI, no rate limiting, whole catalogue scrapable in seconds.
7. **F9 / F7 / F6** — no protection for manual edits, one image per product, fitments untracked: phase-2 features cannot be added without a migration that rewrites data.
8. **I1 / I13 / I14** — no search regression set; p95 already 106 ms at 10 % of the target size; Meilisearch untested.
9. **K2 / K3 / K4 / K6** — no Dockerfile, CI, backup procedure; production wiring untested.
10. **H11 / H12 / J4 / A7 / C4–C5** — unverified by design: live Meilisearch parity, mid-apply failure, private bucket, "NA" prices and 5 held rows.

## Top ten gaps, ordered by cost to fix after deployment (schema or data-rewriting first)

1. **Legacy `change_log` states (H2).** Fix the comparison or back-fill the `cross_refs` key *before* more batches are applied; after deployment every older batch is stuck, and back-filling an append-only log needs a controlled migration.
2. **Single `image_url` (F7).** Needs a `product_images` table and a move of existing links; costs more with every image added.
3. **No manual-edit protection (F9).** Needs a per-field override/lock structure, then every profile and the resync logic must honour it; staff edits made before this exists get overwritten.
4. **Dropped source columns and effective dates (B2).** Needs new columns (class, product type, NPD status, effective-from, group no., pcs per set) then a resync of every batch; the originals are kept so it is recoverable, but only while they are stored.
5. **Fitments, vehicles, supersession not engine-tracked (F6 / F8).** Needs schema additions (year range, engine, direction) and `change_log` states that include them; history written before that cannot be reconstructed.
6. **Unknown price basis (A14).** Needs your answer per brand, then a resync of ~9.6k rows (cheap if done before launch, a customer-visible correction after).
7. **Canonical make and category vocabularies (E5 / E6).** A mapping table plus resync; after launch, saved links, filters and bookmarks that use today's names break.
8. **Discount/dealer data on disk and in originals (G4 / G9).** Deleting the caches is trivial; redacting already-archived originals means rewriting stored files and their hashes, so turn redaction on before the next upload.
9. **Search engine (I5–I14).** Swap to Meilisearch or add trigram/full-text indexes; no data change, but it is the user-visible quality gap (typos, no-space words, plurals, speed).
10. **Admin, auth, rate limiting, packaging (J5, J9, J10, K2–K5).** Code and configuration only: login, throttling, Dockerfile, CI, backups.

## Everything that needs a human to check against the PDFs

- **Random rows (60 listed in section 4).** Check each against the page/serial given.
- **Car International** page 16 (a row printing "UNIT" in the unit column) and page 48 (one row unexplained); the 58 parser-labelled same-number variants; the 62 "VAN → Maruti Suzuki" guesses; `R.C.` and `B.O.` meanings.
- **Pensol:** the 18 "NA" packs; the 3 packs with unreadable prices (APLR 100000 18 kg and 10 kg, Gear TX 80W 90 4×5 L); the flagged blocks 4ST EXTRA / 2T SM / 2T JASO FC; whether the oil grades should be on every pack row; the 3 packs where OCR dropped a decimal point and the parser restored it from the price (7.5 L).
- **Meko:** `M-542` price; the 56 catalogue codes without a price-list product; a sample of the 227 photo matches (is each photo the right pump?); the 65 products with no REF numbers; page 29 (code-list page, unread); whether the Z-series "(Z)" products should be separate products.
- **Neolite:** the 181 merged listings (same code, same price, different section) and the 21 with alternate wording; the 12 labelled variants (e.g. NEO-800A W/P vs W/O/P); the two price drops (NEO-1641, NEO-1838); the section → make guesses (BOSS, D-CM TYTA, M-RCO P-LO, P-GIO, TT TRVLOR, Vee-ro Mhndra).
- **Uno Minda:** the 192 make guesses (`oem_guess`, e.g. TAFF = TAFE) and 38 unmapped codes; the 17 "4WH" segment rows now guessed CAR; the 117 clipped descriptions; the 95 price outliers; that the 100 rows repaired by the resync read correctly.
- **All brands:** whether MRP includes GST (A14); whether "no MRP" rows may be shown; the 2,089 rows with segment "OTHER" and the 1,936 with no make; the `H.L. alto`-style abbreviation expectations for the missing `queries.json`.
- **Deployment owner:** Supabase bucket privacy and real RLS roles, Meilisearch parity, backups, hosting.

---

# Update: pre-migration fixes and fresh-load re-test (2026-11-05, later the same day)

The catalogue loaded so far was a test run. Before the final load into Supabase everything that would be expensive to change
afterwards was fixed, and the whole load was repeated into a **fresh, empty database** (migrations 001–005 from scratch, redaction
on, all 7 sources via `load-all`, then `verify`). Old-format log entries from the test run no longer exist, so finding H2 is
re-tested on the fresh load instead of being patched.

## What changed since the audit

| Audit finding | Fix | Re-test on the fresh load |
|---|---|---|
| H2 delete/rollback broken for legacy log states | not patched (test data discarded); delete preview run on all 7 freshly loaded batches | 0 conflicts on 6 batches; the Meko price list shows 227 conflicts, which is correct (the catalogue batch changed those 227 products later) |
| G4 dealer-rate numbers cached on disk | OCR layer drops the RATE column before caching; 2 cache files and all `data/scratch` debug files deleted | 0 RATE-column words in `data/ocr_cache`; tests added |
| G9 originals unredacted | redaction on by default and fail-closed; Uno Minda strip removed in 6 s (was 60 s); Pensol scan pixels cleared and re-checked with OCR | archived Uno Minda original: 0 words in the TD% strip, 0 "TD%" headers; upload is refused if redaction cannot be proven |
| D12 Pensol oil grade missing on 116 rows | spec lines attached to every pack of a product | 125 of 202 rows carry the grade/API text (the rest are greases, coolants, brake fluids) |
| B2 dropped columns / dates | `products.attributes` (class, product type, NPD status, group no., position, pcs per set, sections …), `price_effective_from`, `import_batches.effective_from` | every priced product has its price-list date; attributes on 3,948 / 157 / 492 / 202 products |
| F7 one image | `product_images` + engine support | tested (apply, resync, delete restore exactly) |
| F6 fitments | new `fitments` table with year range and engine, tracked in change_log and restored by delete | tested |
| F8 supersession | `cross_refs.direction` | schema |
| F9 manual edits overwritten | `products.locked_fields`, honoured by resync | tested: a locked MRP survives a resync that changes it |
| F4 indexes | 6 indexes added; trigram search index created automatically on Supabase | schema rebuilt from scratch |
| F10 TRUNCATE | blocked by statement triggers | tested |
| F12 RLS | children are public only when the product is published | tested |
| E4 / E5 | variant labels trimmed (+ constraint); canonical make and category maps; "Universal" becomes a flag, not a make | 0 makes with brackets, "Leyland" merged, "Rear View Mirrors" merged |
| I1, I5, I7, I8, I9, I12 | `search/tests/queries.json` (35 cases) + test; abbreviation both ways; typo and run-together-word correction; plurals; symbol-only queries match nothing | 35/35 pass |
| J7, J9, J10 | API docs off; 90 requests/min per IP; results limited to the first 300 per query | docs → 404; 130 rapid requests → 87 × 200, 43 × 429; offset beyond 300 → 400 |
| G8 | one shared definition of forbidden names (`ingest/rules.py`) incl. `cd_pct`, `ndp`, `dp`, `wholesale_price`, camelCase | 23 bad names caught, 11 real names not flagged |
| Performance | all engine writes are set-based (one statement per page of products) | full load of 9,950 products + 510 refs + 227 photos in about 2.5 minutes locally |
| Source row with an empty description (`SW-1622M`) | shows its application text, flagged `description_from_application`; rows with no category become "Uncategorised" | A2 / A3 / C3 |
| K2 | `Dockerfile` + compose for the public app | not built here (no Docker on this Mac) |

Tests: 100 passed in the final run, plus the 35 search-regression cases (35/35 when pointed at the loaded database with `CATALOGUE_TEST_DB`).

## Items whose status changed

PASS now: A2, A3, B2, C3, D12, E4, E5, F4, F6, F7, F8, F9, F10, F12, G4, G8, G9, H2 (fresh load), I1, I5, I7, I8, I9, I12, J7, J9, J10.
Moved to NEEDS HUMAN: E6 (category granularity is a taxonomy decision), K2 (Dockerfile exists but was not built).

| Section | Items | PASS | FAIL | NEEDS HUMAN | Passed % |
|---|---|---|---|---|---|
| A Field coverage | 14 | 4 | 6 | 4 | 29 % |
| B Source vs saved | 5 | 4 | 1 | 0 | 80 % |
| C Minimum display | 5 | 3 | 0 | 2 | 60 % |
| D Extraction accuracy | 13 | 7 | 0 | 6 | 54 % |
| E Data quality | 7 | 5 | 0 | 2 | 71 % |
| F Schema | 12 | 11 | 0 | 1 | 92 % |
| G Never-stored rule | 12 | 11 | 1 | 0 | 92 % |
| H Batch engine | 12 | 9 | 1 | 2 | 75 % |
| I Search quality | 14 | 11 | 1 | 2 | 79 % |
| J Security | 10 | 8 | 1 | 1 | 80 % |
| K Operations | 6 | 1 | 3 | 2 | 17 % |
| **Total** | **110** | **74** | **14** | **22** | **67.3 %** |

(A2, A3 and C3 are fixed in the final fresh load: 0 blank descriptions, 0 null categories; F10 also passes now.)

## Still failing or open

- **A14 price basis** (9,591 products `unknown`): needs your answer per brand in `data/config/price_basis.csv`; `verify` fails until then.
- **A5, A6, A8, A9, A11** are limits of what the sources print, not bugs (no make on generic parts, no HSN in Meko/Neolite/Pensol, MOQ only from Uno Minda, photos only for 227 Meko pumps).
- **B3** `Neo-Catelogue Design-1.pdf` (bulb fitment per Neolite code) is not ingested; the `attributes` column and update-only path are ready for it.
- **G10 / K3** no CI; **H9 / J5 / K5** no admin login or screens yet (code only, no data change); **K4** backups are Supabase's own.
- **I13** p95 search latency 104 ms at 10k products on plain Postgres (target 100 ms at 100k); Supabase gets a trigram index automatically, not verifiable locally.
- **NEEDS HUMAN** (unchanged): hand-check of the random rows and all guessed makes/segments; Pensol OCR rows (203 of 205 parse; 3 prices unreadable); Meko photo matches (227) and the 56 catalogue cards with no price-list product; real Supabase bucket privacy and RLS roles; live Meilisearch (not used).
