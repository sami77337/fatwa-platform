# PR52 review correction: serve executable assets on the actual live server

Independent Astra feedback was relayed by the coordinator. The E6 asset defect
was reproduced before changing the handler: `LiveServerTestCase` intercepted
`/assets/` and called Django static serving with `STATIC_ROOT=None`. The catalog
files exist, but every one returned HTTP 500 with `TypeError` in `safe_join`.
The missing-asset request returned 500 as well. This was an E6 test service defect,
not an E4 production defect and not a sandbox workaround.

New regression command, with the disposable PostgreSQL environment from README:

```sh
.venv/bin/python tests/acceptance/wave6/run.py --assets
```

RED before the fix: 2 test methods, 6 failure records (5 asset subtests plus the
missing-asset test). GREEN after switching the shared E6 base class to Django's
`StaticLiveServerTestCase`: 2 PASS, 0 FAIL, 0 SKIP. Five files are checked over
actual loopback HTTP (`catalog.js`, `django-api.mjs`, `tree.js`, `style.css`,
`catalog.css`). The tests require 200, JavaScript/CSS MIME and bytes equal to the
original files. The missing path requires 404. HTML fallback success cannot pass.
The browser gate uses exactly this shared server class and now additionally
checks status/MIME/bytes for all five assets before Chromium startup, recording
each actual response in `browser-result.json.asset_preflight`.

No STATIC_ROOT setting, collectstatic step, root route, dependency, E4 or E5 file
was changed. No browser sandbox or system permissions were modified.

## Prepared PR51 integration hooks

Read actual PR51 head `feb70f0fe9d0fe71765044045bc5924aa175f676` via Git fetch.
`--review-batches` adds three real HTTP tests for allowlisted `default/mixed`
batch identity, exact original text, filter/page/detail/return state via actual
links, invalid batch 400 and POST 405. These passed 3/3 against an untouched
PR51 source snapshot extracted under `/tmp/e6-pr51-source`, with only the E6
test directory overlaid. The snapshot remains separate from the E6 branch;
no E2 code was merged, cherry-picked, edited or committed here. This is PR51
HTTP hook validation, not final combined-SHA acceptance.

`--browser --review-batches` makes the tenth browser journey mandatory, using
the actual `#batch` selector, `.original-text`, repeated `SYN-P01`, `SYN-M03`
and exact query contract observed in PR51. It checks batch switching, keyboard
submit, original whitespace, duplicate-ID isolation, blocked row visibility,
filter/page/detail/return/history/reload and clear retaining the chosen batch.
Browser execution of this hook remains NOT_RUN while the protected Chromium
startup gate is blocked. Missing selectors fail instead of falling back.

E4 PR55 is reported by the coordinator to fix the baseline filter-only defect.
Its head was observed as `411965fc94329e0c206101144a788351b63e245e`. The E6 branch
still starts from the prescribed base; its baseline regression remains RED here.
The final recheck of that regression and both desktop/mobile browser journeys
must run on the coordinator's assembled SHA, later. No combined acceptance or
fresh independent approval of this correction is claimed.

The initial STATUS.md and baseline JSON retain historical first-increment
evidence. Updated clean-head results are recorded in the existing PR52 body.
Windows, PG17, real-source acceptance and final assembled browser: NOT_RUN.
NOT_DEPLOYED / GATES_HOLD / USAGE_NOT_OBSERVED.
