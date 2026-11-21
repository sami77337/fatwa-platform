# Reviewed scholar materials and public lesson series

This default-off development component addresses original owner points **281**
(the scholar page displays attributed fatwas, lessons and general materials) and
**290** (the knowledge library supports lessons and series). It composes the
existing public knowledge, source library and scholarly lesson records; it does
not infer a person's identity from an author's name or publish an unreviewed
recording because its metadata is visible.

## Behavior

Staff open **مواد العلماء والدروس المنشورة** from the selected case. Each action
uses the live authenticated identity, exact case/evidence versions, CSRF and a
request key. They can select an exact published scholar profile and released
material version, select an exact reviewed lesson with an approved original
audio part, or select already released lessons in a documented series order.
The chosen public title, summary, attribution and teacher labels are separate
from internal source descriptions.

A different actor reviews each version; a third actor independently approves
it and explicitly releases it. Release expires at the earliest current source,
identity or policy deadline. Correcting an attribution or series order appends
a new version, preserves its stable public identity and requires fresh review.
Withdrawing the current released version does not revive an older release.

Anonymous pages expose only the current authorized projection. The scholar
page includes the existing attributed fatwas and lessons plus explicitly
reviewed general materials. The teaching catalogue links to series and lessons.
A series preserves the order of its exact source version; lesson pages provide
previous/next navigation without changing lesson identities. The native audio
control reads the original approved recording, including genuine bounded HTTP
byte ranges; it never autoplays or invents a transcript or timestamp. Each
range repeats all current source and actor checks. Withdrawal closes both the
lesson's bytes and a series that depends on it.

## Boundaries

`FATWA_PUBLIC_TEACHING_ENABLED` and
`FATWA_PUBLIC_TEACHING_PUBLIC_ENABLED` must be literal `True` in the isolated
synthetic environment. `FATWA_PUBLIC_TEACHING_AUTHORITY` must implement the
explicit `TeachingAuthority` contract; there is no implicit role grant.
Current permissions cover the workspace, selected resource and every source
case. `PUBLIC_LESSON_CONTENT` is independent from metadata publication and
the existing scholarly `READ_MEDIA` grant. Missing or changed policy, identity,
source version, expiry or original bytes denies the read. Source boundaries are
retained through the final response and rechecked after adapter callbacks.

Three append-only tables retain the stable item, exact versions and decisions:
`public_teaching_teachingitem`, `public_teaching_teachingversion` and
`public_teaching_teachingaction`. SQL verifies source pins, canonical payload
hashes, version/action chains, immutable identities, documented series order,
finite release deadlines and independent actors. The three functions are
`pt_source_pin(text,uuid)`, `pt_item_guard()` and `pt_history_guard()`; their
triggers are `pt_item_guard`, `pt_version_guard` and `pt_action_guard`.

The feature remains **NOT_DEPLOYED**. Gate B is **NOT_PASSED**, Gates C/D/E
remain **HOLD**, and Phase01 remains **BLOCKED**. Development fixtures do not
authorize real publication, real requester data or production migrations.

## Verification

The native PostgreSQL suites exercise exact attribution, independent decisions,
real original bytes, versioned ordering, current source/identity rights,
concurrent edits, idempotency, SQL forgery/immutability, migration reversal,
native CSRF forms, source-choice privacy and late-render rollback.

All 15 service, native HTTP and fresh-connection recovery tests passed on
fresh PostgreSQL 17 and PostgreSQL 18 clusters (153.016 and 153.950 seconds,
respectively). These runs include the populated migration reversal and
current-source permission denials; they do not replace protected browser
or hosted backup/restore evidence.

`recovery_support.populate()` creates four real items/versions and twelve
decisions across the three nonempty tables. `verify_restored()` opens the
original audio and material on a fresh connection under freshly constructed
synthetic trust, checks six current-trust denials, reopens positive reads and
asserts that canonical/source/teaching rows and bytes are unchanged. No
credentials or authority objects are serialized in the recovery pins.

The protected browser identity is
`apps.public_teaching.browser_tests.PublicTeachingBrowserTests.test_native_scholar_material_ordered_series_actual_lesson_playback_and_revocation`.
Its proof path is
`.local/qa/functional-continuation/public-teaching-browser/result.json`.
It requires actual native creation and independent decisions, public catalogue
navigation, real keyboard-started recording playback, exact downloaded
material bytes, stable previous/next links and withdrawal denial. Screenshots
cover 320/1280 pixels; all four browser contexts have traces. Local protected
Chromium is unavailable in this workspace, so only the hosted protected run
can supply browser completion evidence. The implementation and local tests
alone do not count these original points as completed.
