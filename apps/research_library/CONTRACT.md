# Typed research library: bounded synthetic development contract

An item identifies a declared source record within a case and namespace. Its
immutable versions describe a work, a particular source edition and an optional
exact digital file. A missing file is a descriptive reference, never a pretend
reader. File blobs retain original bytes independently of logical ownership.
The library accepts BOOK, DOCUMENT, IMAGE, AUDIO and VIDEO; existing lesson and
series identities remain in `scholarly_links`.

Every source version preserves the declared provenance and rights basis. Those
strings do not authenticate a source, grant use or approve a religious text.
Three distinct current scoped identities create, review and approve a version.
Approval explicitly lists permitted uses, then a separate expiring RELEASE may
make the exact approved display/file available in the synthetic public preview.
No version inherits an older version's review or rights. Newer unreviewed edits
do not silently replace a released edition. WITHDRAW denies all reads of that
version; REVOKE only ends its public lease. Historic private inspection remains
available to independently permitted editors. Public paths carry no case IDs,
source upload paths, private actor identities or unapproved provenance notes.

Native and imported writes use the same `write_material` service. `current_material`
returns stable item/version IDs, the version number/digest, the exact payload and
file pins. An update requires the exact prior number; an omitted file preserves
the prior file, and replacing/removing it requires an explicit supported request.
Inputs cannot contain imported approvals, credentials or administrative grants.
The importer preserves its own staging and decisions and never bypasses these
canonical library services.

`staff_boundary` composes under the existing owned synthetic transaction and
same-case lock. `policy_snapshot`/`assert_policy_snapshot` expose authority identity,
the pure policy generation and storage/configuration identity for composed
import, export and complete-render boundaries. Reads pin source rows and actual
bytes; all permission and identity callbacks finish before the final pure checks.

Current review limits are 64 items per case, 64 versions per item, 192000 bytes
per file, 20 selected exported/offline items, and one-hour reviewed rights/public
leases. These are bounded prototype limits, not production retention decisions.
Default flags are false; authority and identity providers are absent.
Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; NOT_DEPLOYED.
