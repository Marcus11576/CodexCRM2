# Contact Import Precheck (2026-03-22)

_Generated at 2026-03-22T14:06:18.294873+00:00_

## Sources Compared

- Previous version source: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\backups\pre_chatbot_reset_20260318T091210Z.db`
- Current live source: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\crm.db`

## Contact Count Comparison

- Previous active contacts: **293**
- Current active contacts: **294**
- Only in previous: **0**
- Only in current: **1**
- Current-only IDs: `dup-smoke-e8a827c6`

## Field Coverage (Previous vs Current)

| Field | Previous | Current |
| --- | ---: | ---: |
| phone_primary | 163 | 163 |
| career_summary | 119 | 120 |
| employment_history | 147 | 148 |
| email_primary | 199 | 199 |
| title_current | 242 | 242 |
| company_name_raw | 256 | 256 |
| cat | 293 | 293 |
| env | 243 | 243 |
| disc | 246 | 246 |
| linkedin_url | 152 | 153 |

## Top Tags In Previous Dataset

### Top `env` values
- Consultant: 111
- Other: 44
- Main Contractor: 23
- Developer - Private: 21
- Developer - Gov: 19
- Developer - Semi-Gov: 13
- Chartership: 6
- Architect: 2
- Developer - Gov, Developer - Private: 1
- Management Consultant: 1

### Top `cat` values
- OBE M: 234
- GEN: 49
- TGT: 3
- EXT: 1
- EXT, OBE T: 1
- OBE M, EXT: 1
- OBE M, OBE T: 1
- OBE T: 1
- OBE Target: 1
- OBE Target, OBE T: 1

## Sample Contacts (Previous Dataset)

| person_id | full_name | company | title | phone_primary | cat | env |
| --- | --- | --- | --- | --- | --- | --- |
| 71a6078189df | Kevin C. | Stantec | Regional Director - Buildings MENA | 971566888124 | OBE Target, OBE T | Consultant |
| 6202b029ecf0 | Steve Flint | BuiltWell Project Management | Founder | 971557227586 | OBE M | Main Contractor |
| add184b70172 | Simon Coope | sarcc | Executive Director - Head of PMO | 971-559-523327 | OBE M | Developer - Gov |
| 682f87e87843 | Sean Doherty | Khatib and Alami | VP | +971585936784 | OBE M | Consultant |
| 77d70182ddbe | Matt Squires | SSH Design | Chief Executive Officer, SSH Design | +971538601129 | OBE M | Consultant |
| b209c5921621 | Daniel Croysdale | MACE | Ops Director Cost Management |  | OBE M | Consultant |
| 00449722db88 | Ian McGauley | WSP in the Middle East | Managing Director - Project Management Services, Middle East | +971564106089 | OBE Target | Consultant |
| bc18f91b1dee | Iustina Blidarlu | MottMac | Head of Talent & Wellbeing Lead Middle East | +971505808463 | OBE M |  |
| 70e3ac1d5fc8 | James Allan | JLL | Chief Exec Officer | +971524106637 | OBE M, OBE T | Consultant |
| abd76be60e8a | Matthew Neild | NV5 | Executive Director Infrastructure |  | OBE M | Other |
| 91c5d197958c | Rick Hopper | Mott MacDonald | Managing Director |  | OBE M | Consultant |
| e1fba6769147 | Eugene Mcclusky | Palm | Global HR and Talent Executive | +971559499710 | OBE M, EXT | Main Contractor |
| e44ffeb573af | Matra Glavez | Jacobs | Advisor - Project Management |  | OBE M | Consultant |
| 330b6b8bd189 | Michael Belton | Mered | CEO | 971553467190 | OBE M | Developer - Private |
| 277d62ee2f62 | Alasdair Leven | Turner & Townsend | Director |  | OBE M | Consultant |
| b8c043004fc0 | Yannic Leveque | Acciona Cultura | VP | +971526445413 | OBE M | Main Contractor |
| 7c4168496347 | Scott Coombes | AESG | Founder | +971508855312 | OBE M | Consultant |
| live-mobile-steve-flint | Steve Flint | BuiltWell | Founder @ BuiltWell
Project Management | +971501245220 | OBE M | Main Contractor |
| 56471ab963ed | Nathan Hones | Carter Hones | Chief Operating Officer & Partner | +971501245220 | OBE M | Consultant |
| e92fbb72-efad-41dc-a6e6-1e5a0924c6bd | Omar Rahman | Blue Stone Holdings | Delivery Manager | +971501112226 | GEN | Main Contractor |

## Import Readiness

- Raw import from this previous source is currently **not required** because all previous contacts already exist in `crm.db`.
- Recommended action: run a **targeted enrichment merge** only if you want to restore specific fields or historical artifacts from backups.