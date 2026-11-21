"""Bind additional original points to fresh exact-commit native/browser/recovery proof."""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PLAN = Path("docs/product/functional_continuation/scope_plan.json")
PRIOR_TABLES = (
    "case_assignments_assignmentevent",
    "case_organization_organizationrevision",
    "content_reports_contentreport",
    "content_reports_reportevent",
    "research_workspace_researchcollection",
    "research_workspace_researchitem",
    "research_workspace_savedresearchsearch",
    "research_workspace_researchcollectionevent",
    "scholarly_links_lessoncategory",
    "scholarly_links_lessonseries",
    "scholarly_links_seriesversion",
    "scholarly_links_lesson",
    "scholarly_links_lessonversion",
    "scholarly_links_caserelation",
    "scholarly_links_caselessonlink",
    "scholarly_links_linkdecision",
    "public_knowledge_publicseries",
    "public_knowledge_publicrevision",
    "public_knowledge_publicaction",
    "selected_exports_exportjob",
    "selected_exports_exportevent",
    "selected_exports_exportartifact",
)
PRIOR_WORKFLOWS = (
    "apps.scholarly_links.recovery_support",
    "apps.public_knowledge.recovery_support",
    "apps.selected_exports.recovery_support",
)
NEW_WORKFLOWS = {
    "apps.research_library.recovery_support": (
        "research_library_libraryblob",
        "research_library_libraryitem",
        "research_library_libraryversion",
        "research_library_librarydecision",
    ),
    "apps.material_import.recovery_support": (
        "material_import_importbatch",
        "material_import_mappingrevision",
        "material_import_importplan",
        "material_import_importdecision",
        "material_import_groupresult",
        "material_import_importevent",
        "material_import_roundtripreceipt",
    ),
    "apps.public_collections.recovery_support": (
        "public_collections_collectionseries",
        "public_collections_collectionrevision",
        "public_collections_collectionaction",
    ),
    "apps.case_lifecycle.recovery_support": ("case_lifecycle_lifecycleevent",),
    "apps.canonical_search.recovery_support": (
        "canonical_search_searchgeneration",
        "canonical_search_searchdocument",
    ),
    "apps.canonical_search.match_recovery_support": (),
    "apps.public_answer_media.recovery_support": (
        "public_answer_media_recordingtranscript",
        "public_answer_media_transcriptaction",
        "public_answer_media_publicmediaedition",
        "public_answer_media_publicmediaaction",
    ),
    "apps.precise_citations.recovery_support": (
        "precise_citations_citationset",
        "precise_citations_citationanchor",
        "precise_citations_citationreview",
    ),
    "apps.case_attachments.video_recovery": ("case_attachments_caseattachment",),
    "apps.answer_media.youtube_recovery_support": (
        "answer_media_answermanifest",
        "answer_media_answerpart",
        "answer_media_privateanswerrelease",
    ),
    "apps.identity_registry.recovery_support": (
        "identity_registry_platformidentity",
        "identity_registry_identityobservation",
        "identity_registry_person",
        "identity_registry_linkproposal",
        "identity_registry_registryoperation",
        "identity_registry_identitymembership",
    ),
    "apps.public_reader_tools.recovery_support": (),
    "apps.material_api.recovery_support": (),
    "apps.publication_schedules.recovery_support": (
        "publication_schedules_publicationschedule",
        "publication_schedules_scheduleoutcome",
    ),
    "apps.publication_destinations.recovery_support": (
        "publication_destinations_destinationrecord",
        "publication_destinations_destinationversion",
        "publication_destinations_destinationevent",
    ),
    "apps.composite_delivery.selection_recovery": (),
    "apps.development_taxonomy.recovery_support": (
        "development_taxonomy_developmenttree",
        "development_taxonomy_concept",
        "development_taxonomy_treeversion",
        "development_taxonomy_humanreview",
        "development_taxonomy_migrationplan",
        "development_taxonomy_migrationexecution",
        "development_taxonomy_caseclassification",
    ),
    "apps.canonical_search.governance_recovery_support": (
        "canonical_search_synonymrevision",
        "canonical_search_synonympreview",
        "canonical_search_synonymdecision",
        "canonical_search_shadowcomparison",
    ),
    "apps.public_teaching.recovery_support": (
        "public_teaching_teachingitem",
        "public_teaching_teachingversion",
        "public_teaching_teachingaction",
    ),
    "apps.composite_delivery.retry_recovery": ("composite_delivery_compositeretry",),
    "apps.library_preview.reference_recovery": (),
    "apps.operational_workspace.recovery_support": (),
    "apps.operational_workspace.notes_recovery_support": (),
    "apps.arabic_search_eval.benchmark_recovery_support": (
        "arabic_search_eval_evaluationrevision",
        "arabic_search_eval_evaluationdecision",
        "arabic_search_eval_canonicalbenchmarkrun",
        "arabic_search_eval_canonicalbenchmarkdecision",
    ),
    "apps.operational_workspace.metadata_recovery_support": (),
    "apps.operational_workspace.lesson_recovery_support": (),
    "apps.operational_workspace.coordination_recovery_support": ("case_assignments_priorityevent",),
    "apps.ai_gateway.recovery_support": (
        "ai_gateway_gatewayrun",
        "ai_gateway_gatewayoutcome",
        "ai_gateway_candidatebatch",
    ),
    "apps.private_media.recovery_support": (),
    "apps.operational_workspace.transcript_recovery_support": (),
    "apps.operational_workspace.publication_recovery_support": (),
    "apps.staff_sessions.recovery_support": (
        "staff_sessions_session",
        "staff_sessions_sessionrevocation",
        "staff_sessions_freshproof",
        "staff_sessions_proofuse",
    ),
    "apps.data_privacy.recovery_support": ("data_privacy_classificationrevision",),
    "apps.permission_sets.recovery_support": ("permission_sets_permissionrevision",),
    "apps.upload_security.recovery_support": (
        "upload_security_quarantinedfile",
        "upload_security_uploadadmission",
        "upload_security_scanattempt",
    ),
    "apps.staff_mfa.recovery_support": (
        "staff_mfa_account",
        "staff_mfa_challenge",
        "staff_mfa_factor",
        "staff_mfa_proof",
        "staff_mfa_attempt",
        "staff_mfa_recoverycode",
        "staff_mfa_factorrevocation",
        "staff_mfa_recoveryuse",
        "staff_mfa_sessionassurance",
    ),
    "apps.record_suppression.recovery_support": ("record_suppression_suppressionevent",),
    "apps.media_derivatives.recovery_support": (
        "media_derivatives_derivativejob",
        "media_derivatives_derivativeevent",
        "media_derivatives_derivedoutput",
    ),
    "apps.derived_maintenance.recovery_support": (
        "derived_maintenance_derivativeclear",
        "derived_maintenance_derivativerebuild",
    ),
}
RESTORED_DENIAL_CHECKS = {
    "apps.research_library.recovery_support": {
        "missing_authority": 3,
        "missing_identity_provider": 3,
        "revoked_current_reader": 2,
        "revoked_public_release_actor": 1,
    },
    "apps.case_lifecycle.recovery_support": {
        "missing_authority": 3,
        "missing_identity_provider": 3,
        "revoked_current_reader": 3,
    },
    "apps.canonical_search.recovery_support": {"missing_authority": 1, "inactive_identity": 1},
    "apps.canonical_search.match_recovery_support": {
        "disabled_search": 1,
        "missing_authority": 1,
        "missing_identity": 1,
        "revoked_open": 1,
        "revoked_search": 1,
        "revoked_case_scope": 1,
    },
    "apps.public_answer_media.recovery_support": {
        "missing_authority": 2,
        "missing_identity_provider": 2,
        "missing_media_rights": 2,
        "revoked_current_reader": 2,
        "revoked_public_release_actor": 1,
    },
    "apps.precise_citations.recovery_support": {"missing_authority": 1, "withdrawn_source_cite": 1},
    "apps.case_attachments.video_recovery": {
        "revoked_requester": 2,
        "revoked_current_reader": 2,
        "disabled_feature": 2,
    },
    "apps.answer_media.youtube_recovery_support": {"missing_authority": 1, "inactive_identity": 1},
    "apps.identity_registry.recovery_support": {
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "revoked_current_reader": 1,
    },
    "apps.public_reader_tools.recovery_support": {
        "missing_tool_authority": 1,
        "missing_current_directory": 1,
        "missing_publication_grant": 1,
        "revoked_current_authorizer": 1,
        "missing_save_reference": 1,
        "missing_share_link": 1,
        "missing_print": 1,
        "missing_download_text": 1,
    },
    "apps.material_api.recovery_support": {
        "disabled_api": 1,
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "revoked_release_actor": 1,
    },
    "apps.publication_schedules.recovery_support": {
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "revoked_current_reader": 1,
    },
    "apps.publication_destinations.recovery_support": {
        "missing_destination_authority": 1,
        "missing_current_identity": 1,
        "missing_source_publication_authority": 1,
        "missing_signature_trust": 1,
        "revoked_current_reader_grant": 1,
        "changed_original_publisher_epoch": 1,
        "revoked_simulator_key": 1,
        "changed_exact_destination_profile": 1,
        "unavailable_current_source_rights": 1,
    },
    "apps.composite_delivery.selection_recovery": {
        "disabled_choices": 1,
        "missing_identity_provider": 1,
        "missing_capabilities": 1,
        "revoked_current_reader": 1,
    },
    "apps.development_taxonomy.recovery_support": {
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "revoked_current_reader": 1,
        "revoked_mapping_authority": 1,
    },
    "apps.canonical_search.governance_recovery_support": {
        "missing_authority": 2,
        "missing_identity_provider": 2,
        "disabled_feature": 2,
        "revoked_current_reader": 2,
    },
    "apps.public_teaching.recovery_support": {
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "missing_source_authority": 1,
        "revoked_current_release_actor": 1,
        "missing_public_content_right": 1,
        "missing_attributed_material_right": 1,
    },
    "apps.composite_delivery.retry_recovery": {
        "disabled_retry": 1,
        "missing_identity_provider": 1,
        "missing_provider_verifier": 1,
        "missing_capabilities": 1,
        "revoked_current_reader": 1,
        "revoked_failure_verification_key": 1,
    },
    "apps.library_preview.reference_recovery": {
        "disabled_feature": 1,
        "missing_reference_policy": 1,
        "missing_identity_provider": 1,
        "missing_publication_grant": 1,
        "missing_source_rights": 1,
        "revoked_current_publisher": 1,
    },
    "apps.operational_workspace.recovery_support": {
        "disabled_workspace": 1,
        "missing_authority": 1,
        "missing_identity_provider": 1,
        "revoked_current_identity": 1,
        "revoked_case_read": 1,
        "revoked_transcript_read": 1,
        "expired_operational_grant": 1,
    },
    "apps.operational_workspace.notes_recovery_support": {
        "disabled_note_feature": 1,
        "disabled_metadata": 1,
        "missing_identity_provider": 1,
        "missing_authority": 1,
        "revoked_current_identity": 1,
        "revoked_case_read": 1,
        "revoked_note_actions": 1,
    },
    "apps.arabic_search_eval.benchmark_recovery_support": {
        "missing_benchmark_authority": 2,
        "missing_identity_provider": 2,
        "disabled_feature": 2,
        "missing_source_search_authority": 2,
        "revoked_read_action": 2,
        "revoked_current_reader": 2,
    },
    "apps.operational_workspace.metadata_recovery_support": {
        "disabled_metadata_feature": 1,
        "disabled_organization": 1,
        "disabled_workspace": 1,
        "missing_directory": 1,
        "missing_operational_authority": 1,
        "missing_taxonomy_authority": 1,
        "revoked_current_identity": 1,
        "revoked_read_case": 1,
        "revoked_read_metadata": 1,
        "revoked_exact_classification_read": 1,
    },
    "apps.operational_workspace.lesson_recovery_support": {
        "disabled_lesson_feature": 1,
        "disabled_scholarly_links": 1,
        "missing_directory": 1,
        "missing_operational_authority": 1,
        "missing_lesson_authority": 1,
        "revoked_current_identity": 1,
        "revoked_read_case": 1,
        "revoked_read_lesson_links": 1,
        "revoked_target_case_read": 1,
        "revoked_read_operational_lesson": 1,
        "revoked_read_lesson_link": 1,
        "revoked_domain_lesson_read": 1,
    },
    "apps.operational_workspace.coordination_recovery_support": {
        "disabled_coordination": 1,
        "disabled_assignments": 1,
        "missing_identity_provider": 1,
        "missing_operational_authority": 1,
        "missing_candidate_policy": 1,
        "missing_priority_policy": 1,
        "revoked_current_actor": 1,
        "revoked_coordination_read": 1,
        "expired_current_grant": 1,
    },
    "apps.ai_gateway.recovery_support": {
        "gateway_disabled": 1,
        "task_disabled": 1,
        "missing_gateway_authority": 1,
        "missing_identity_directory": 1,
        "missing_provider": 1,
        "killed_provider": 1,
        "revoked_source_processing": 1,
        "revoked_fragment_processing": 1,
        "revoked_source_read": 1,
        "revoked_source_cite": 1,
        "revoked_case_scope": 1,
        "cross_actor": 1,
    },
    "apps.private_media.recovery_support": {
        "unsigned_private_url": 2,
        "same_actor_different_browser": 2,
        "missing_signing_key": 2,
        "rotated_link_epoch": 2,
        "missing_current_identity": 2,
        "revoked_current_identity": 2,
        "revoked_current_read": 2,
        "revoked_current_download": 2,
        "cross_purpose_ticket": 2,
    },
    "apps.operational_workspace.transcript_recovery_support": {
        "disabled_transcript_editor": 1,
        "disabled_recording": 1,
        "missing_directory": 1,
        "missing_operational_authority": 1,
        "missing_transcript_authority": 1,
        "missing_media_rights": 1,
        "revoked_current_editor": 1,
        "revoked_read_case": 1,
        "revoked_read_transcript_editor": 1,
        "revoked_exact_transcript_read": 1,
        "revoked_exact_audio_read": 1,
        "revoked_domain_transcript_read": 1,
        "revoked_current_media_right": 1,
    },
    "apps.operational_workspace.publication_recovery_support": {
        "disabled_publication_manager": 1,
        "disabled_publication": 1,
        "missing_directory": 1,
        "missing_operational_authority": 1,
        "missing_domain_authority": 1,
        "unversioned_domain_authority": 1,
        "revoked_current_identity": 1,
        "revoked_read_case": 1,
        "revoked_read_publication_manager": 1,
        "revoked_exact_edition_read": 1,
        "revoked_domain_read": 1,
        "expired_current_operational_grants": 1,
        "removed_current_case_scope": 1,
    },
    "apps.staff_sessions.recovery_support": {
        "sessions_disabled": 1,
        "missing_authority": 1,
        "missing_directory": 1,
        "missing_runtime_epoch": 1,
        "revoked_audit_grant": 1,
        "cross_actor_audit": 1,
        "inactive_actor": 1,
        "restored_session_runtime": 1,
    },
    "apps.data_privacy.recovery_support": {
        "privacy_disabled": 1,
        "missing_authority": 1,
        "missing_directory": 1,
        "revoked_read": 1,
        "wrong_classification_level": 1,
        "revoked_case_scope": 1,
        "public_restricted_source": 1,
        "search_not_inherited": 1,
        "export_not_inherited": 1,
        "publication_not_inherited": 1,
        "ai_not_inherited": 1,
        "classification_management_not_inherited": 1,
        "unclassified_source": 1,
    },
    "apps.permission_sets.recovery_support": {
        "feature_disabled": 1,
        "runtime_adapter_absent": 1,
        "directory_absent": 1,
        "target_inactive": 1,
        "target_auth_epoch_changed": 1,
        "target_case_scope_changed": 1,
        "management_authority_absent": 1,
        "management_mandate_revoked": 1,
        "self_grant_rejected": 1,
        "scientific_override_rejected": 1,
        "stored_individual_deny": 1,
        "disabled_template_binding": 1,
    },
    "apps.upload_security.recovery_support": {
        "disabled_saved_quarantine": 1,
        "missing_scan_policy": 1,
        "missing_scanner": 1,
        "synthetic_fixture_disallowed": 1,
        "changed_engine": 1,
        "changed_signatures": 1,
        "changed_scan_policy": 1,
        "expired_scan_receipt": 1,
        "blocked_exact_bytes": 1,
        "unscanned_exact_bytes": 1,
        "wrong_exact_size": 1,
        "omitted_app_with_saved_quarantine": 1,
        "missing_current_staff": 1,
        "foreign_case_staff": 1,
    },
    "apps.staff_mfa.recovery_support": {
        "mfa_disabled": 1,
        "missing_key": 1,
        "missing_authority": 1,
        "missing_directory": 1,
        "session_registry_disabled": 1,
        "missing_runtime_epoch": 1,
        "revoked_audit_grant": 1,
        "cross_actor_audit": 1,
        "inactive_actor": 1,
        "restored_primary_challenge": 1,
        "restored_session_assurance": 1,
        "restored_factor_login": 1,
        "restored_legacy_factor_veto": 1,
        "restored_legacy_missing_app": 1,
    },
    "apps.record_suppression.recovery_support": {
        "feature_disabled": 1,
        "journal_absent": 1,
        "floor_stale": 1,
        "floor_missing": 1,
        "directory_absent": 1,
        "management_mandate_revoked": 1,
        "restored_deleted_answer": 1,
        "late_projection_change": 1,
        "newer_floor_blocks_old_sql": 1,
        "reapplied_current_deletion": 1,
    },
    "apps.media_derivatives.recovery_support": {
        "derivatives_disabled": 1,
        "missing_derivative_authority": 1,
        "missing_current_directory": 1,
        "revoked_derivative_read": 1,
        "revoked_original_read": 1,
        "missing_current_scanner": 1,
        "changed_scan_signatures": 1,
        "disabled_scan_with_saved_original": 1,
        "expired_current_identity": 1,
        "foreign_case_identity": 1,
        "cross_actor": 1,
        "wrong_job": 1,
        "cancelled_not_ready": 1,
        "unavailable_not_ready": 1,
    },
    "apps.derived_maintenance.recovery_support": {
        "feature_disabled": 1,
        "journal_absent": 1,
        "floor_stale": 1,
        "floor_missing": 1,
        "directory_absent": 1,
        "management_mandate_revoked": 1,
        "cleared_search_identifier": 1,
        "cleared_ai_identifier": 1,
        "search_permission_revoked": 1,
        "source_read_revoked": 1,
        "source_processing_revoked": 1,
        "provider_absent": 1,
        "late_projection_floor_change": 1,
        "newer_floor_blocks_old_sql": 1,
        "reconciled_identifier_remains_cleared": 1,
    },
}

# Keep the exact executed identities, including the assignment class's inherited
# journey. An unrelated replacement test must not satisfy the aggregate count.
# Legacy proofs retain their actual formats; the audio test emits only its test
# result in the aggregate log, not a fabricated JSON result or trace.
PRIOR_BROWSER_JOURNEYS = (
    (
        "tests.casework.test_functional_completion_browser.FunctionalCompletionBrowserTests."
        "test_same_case_claim_metadata_collect_compare_report_and_human_resolution",
        ".local/qa/functional-completion/browser/result.json",
        "modern",
    ),
    (
        "apps.case_assignments.browser_tests.AssignmentBrowserTests."
        "test_claim_mine_shared_release_on_mobile_and_desktop",
        ".local/qa/case-assignments/browser/assignments.json",
        "assignments",
    ),
    (
        "apps.case_assignments.browser_tests.AssignmentBrowserTests."
        "test_two_case_browser_journey_and_revoked_capabilities",
        ".local/qa/v6-casework/browser/evidence.json",
        "casework",
    ),
    (
        "apps.browser_audio.test_browser.BrowserAudioTests."
        "test_pause_resume_preserves_one_recording_and_excludes_paused_time",
        None,
        "execution_log",
    ),
    (
        "apps.scholarly_links.browser_tests.ScholarlyBrowserTests."
        "test_native_series_lessons_typed_links_review_and_filters",
        ".local/qa/functional-completion/scholarly-browser/result.json",
        "modern",
    ),
    (
        "apps.public_knowledge.browser_tests.PublicKnowledgeBrowserTests."
        "test_native_reviewed_profile_translation_release_and_revocation",
        ".local/qa/functional-completion/public-browser/result.json",
        "modern",
    ),
    (
        "apps.selected_exports.browser_tests.SelectedExportBrowserTests."
        "test_select_preview_queue_build_download_then_current_grant_revokes_retrieval",
        ".local/qa/functional-completion/export-browser/result.json",
        "modern",
    ),
    (
        "apps.data_quality.browser_tests.QualityBrowserTests."
        "test_current_diagnostic_refresh_and_operator_restore_preserve_case",
        ".local/qa/functional-completion/quality-browser/result.json",
        "quality",
    ),
)
NEW_BROWSER_JOURNEYS = (
    (
        "apps.canonical_search.browser_matches.SearchMatchBrowserTests.test_native_exact_question_answer_matches_previous_next_and_current_denials",
        ".local/qa/functional-continuation/search-match-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_notes.OperationalNotesBrowserTests.test_native_organizer_notes_preserve_source_and_remain_hidden_from_requester",
        ".local/qa/functional-continuation/operational-notes-browser/result.json",
        "modern",
    ),
    (
        "apps.publication_destinations.browser_tests.PublicationDestinationsBrowserTests.test_native_distinct_destination_versions_signed_outcomes_correction_and_withdrawal_isolation",
        ".local/qa/functional-continuation/publication-destinations-browser/result.json",
        "modern",
    ),
    (
        "apps.research_library.browser_tests.LibraryBrowserTests.test_native_external_video_rights_versions_and_public_revocation",
        ".local/qa/functional-continuation/library-browser/result.json",
        "modern",
    ),
    (
        "apps.research_library.offline_browser_tests.OfflineLibraryBrowserTests.test_native_pwa_selection_offline_bytes_revocation_and_shortened_expiry",
        ".local/qa/functional-continuation/offline-browser/result.json",
        "modern",
    ),
    (
        "apps.material_import.browser_tests.MaterialImportBrowserTests.test_native_independent_import_to_actual_library_version",
        ".local/qa/library-operations/import-browser/result.json",
        "modern",
    ),
    (
        "apps.public_collections.browser_tests.PublicCollectionsBrowserTests.test_cross_case_native_curation_order_review_release_and_revocation",
        ".local/qa/functional-continuation/collections-browser/result.json",
        "modern",
    ),
    (
        "apps.case_lifecycle.browser_tests.LifecycleBrowserTests.test_native_close_archive_restore_reopen_and_requester_followup",
        ".local/qa/functional-completion/lifecycle-browser/result.json",
        "modern",
    ),
    (
        "apps.canonical_search.browser_tests.CanonicalSearchBrowserTests.test_native_literal_fts_fuzzy_exact_source_stale_rebuild_and_current_revocation",
        ".local/qa/functional-continuation/canonical-search-browser/result.json",
        "modern",
    ),
    (
        "apps.canonical_search.browser_recordings.RecordingSearchBrowserTests.test_actual_fts_result_opens_reviewed_original_at_pinned_segment",
        ".local/qa/functional-continuation/search-recording-browser/result.json",
        "modern",
    ),
    (
        "apps.public_answer_media.browser_tests.PublicAnswerMediaBrowserTests.test_native_transcript_revision_review_public_playback_seek_and_withdrawal",
        ".local/qa/functional-continuation/public-answer-media-browser/result.json",
        "modern",
    ),
    (
        "apps.precise_citations.browser_tests.PreciseCitationBrowserTests.test_native_exact_phrase_review_original_export_and_withdrawal",
        ".local/qa/functional-continuation/citations-browser/result.json",
        "modern",
    ),
    (
        "apps.case_attachments.video_browser_tests.RequesterVideoBrowserTests.test_native_requester_upload_playback_original_download_and_revocation",
        ".local/qa/functional-continuation/requester-video-browser/result.json",
        "modern",
    ),
    (
        "apps.staff_shell.browser_tests.StaffPWABrowserTests.test_installable_staff_scope_requires_live_authorization_and_never_caches_cases",
        ".local/qa/functional-continuation/staff-pwa-browser/result.json",
        "modern",
    ),
    (
        "apps.staff_shell.browser_tests.DarkModeBrowserTests.test_system_theme_switch_preserves_published_content_with_readable_dark_surfaces",
        ".local/qa/functional-continuation/dark-mode-browser/result.json",
        "modern",
    ),
    (
        "apps.answer_media.browser_youtube.YouTubeAnswerBrowserTests.test_native_external_link_save_approve_release_and_current_requester_access",
        ".local/qa/functional-continuation/youtube-answer-browser/result.json",
        "modern",
    ),
    (
        "apps.answer_media.browser_related.RelatedMaterialBrowserTests.test_actual_side_panel_preserves_draft_file_and_link_until_explicit_save",
        ".local/qa/functional-continuation/answer-related-browser/result.json",
        "modern",
    ),
    (
        "apps.identity_registry.browser_tests.IdentityRegistryBrowserTests.test_native_independent_identity_states_and_reviewable_merge_split",
        ".local/qa/functional-continuation/identities-browser/result.json",
        "modern",
    ),
    (
        "apps.public_reader_tools.browser_tests.ReaderToolsBrowserTests.test_native_local_reference_share_print_download_and_current_withdrawal",
        ".local/qa/functional-continuation/reader-tools-browser/result.json",
        "modern",
    ),
    (
        "apps.material_api.browser_tests.MaterialAPIBrowserTests.test_native_developer_search_exact_json_original_and_current_revocation",
        ".local/qa/functional-continuation/material-api-browser/result.json",
        "modern",
    ),
    (
        "apps.publication_schedules.browser_tests.PublicationScheduleBrowserTests.test_native_exact_future_schedule_cancel_due_publication_and_changed_authority_hold",
        ".local/qa/functional-continuation/publication-schedules-browser/result.json",
        "modern",
    ),
    (
        "apps.composite_delivery.browser_selection.CompositeChoiceBrowserTests.test_native_explicit_text_selection_preserves_audio_and_requires_independent_signed_plan",
        ".local/qa/functional-continuation/composite-choice-browser/result.json",
        "modern",
    ),
    (
        "apps.development_taxonomy.browser_tests.DevelopmentTaxonomyBrowserTests.test_native_multilevel_ids_primary_additional_reviewed_migrations_and_rollback",
        ".local/qa/functional-continuation/taxonomy-browser/result.json",
        "modern",
    ),
    (
        "apps.canonical_search.browser_governance.SearchGovernanceBrowserTests.test_native_versioned_dictionary_independent_review_actual_fts_shadow_and_retirement",
        ".local/qa/functional-continuation/search-governance-browser/result.json",
        "modern",
    ),
    (
        "apps.public_teaching.browser_tests.PublicTeachingBrowserTests.test_native_scholar_material_ordered_series_actual_lesson_playback_and_revocation",
        ".local/qa/functional-continuation/public-teaching-browser/result.json",
        "modern",
    ),
    (
        "apps.composite_delivery.browser_retry.CompositeRetryBrowserTests.test_native_failed_part_fresh_signed_bounded_retry_keeps_original_failure_and_no_duplicates",
        ".local/qa/functional-continuation/composite-retry-browser/result.json",
        "modern",
    ),
    (
        "apps.library_preview.browser_references.FatwaReferenceBrowserTests.test_native_exact_ft_lookup_scoped_staff_open_explicit_public_number_and_withdrawal",
        ".local/qa/functional-continuation/fatwa-reference-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_tests.OperationalWorkspaceBrowserTests.test_actual_organizer_queue_filters_and_scoped_details_without_scholarly_authority",
        ".local/qa/functional-continuation/operational-browser/result.json",
        "modern",
    ),
    (
        "apps.arabic_search_eval.browser_benchmark.CanonicalBenchmarkBrowserTests.test_native_authored_judgments_actual_metrics_independent_decisions_and_current_denials",
        ".local/qa/functional-continuation/search-benchmark-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_metadata.OperationalMetadataBrowserTests.test_native_organizer_tags_types_and_reviewed_classification_preserve_originals",
        ".local/qa/functional-continuation/operational-metadata-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_lessons.OperationalLessonsBrowserTests.test_native_organizer_lesson_proposal_admin_review_and_withdrawal_preserve_sources",
        ".local/qa/functional-continuation/operational-lessons-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_coordination.OperationalCoordinationBrowserTests.test_native_organizer_priority_assignment_shared_queue_and_current_revocation",
        ".local/qa/functional-continuation/operational-coordination-browser/result.json",
        "modern",
    ),
    (
        "apps.ai_gateway.browser_tests.CitationGatewayBrowserTests.test_native_candidates_original_human_handoff_failure_revocation_and_manual_citation",
        ".local/qa/functional-continuation/ai-citation-browser/result.json",
        "modern",
    ),
    (
        "apps.private_media.browser_tests.PrivateOriginalLinksBrowserTests.test_native_requester_and_staff_media_urls_downloads_and_browser_isolation",
        ".local/qa/functional-continuation/private-media-links-browser/originals/result.json",
        "modern",
    ),
    (
        "apps.private_media.browser_tests.PrivateLibraryLinksBrowserTests.test_native_library_playback_download_and_current_download_revocation",
        ".local/qa/functional-continuation/private-media-links-browser/library/result.json",
        "modern",
    ),
    (
        "apps.private_media.browser_tests.PrivateRecordingLinksBrowserTests.test_native_recording_and_reviewed_segment_playback_then_current_rights_denial",
        ".local/qa/functional-continuation/private-media-links-browser/recordings/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_transcripts.OperationalTranscriptsBrowserTests.test_native_organizer_transcript_admin_review_and_mufti_meaning_approval_keep_original",
        ".local/qa/functional-continuation/operational-transcripts-browser/result.json",
        "modern",
    ),
    (
        "apps.operational_workspace.browser_publication.OperationalPublicationBrowserTests.test_native_organizer_publication_review_admin_approval_and_withdrawal_preserve_source",
        ".local/qa/functional-continuation/operational-publication-browser/result.json",
        "modern",
    ),
    (
        "apps.staff_sessions.browser_tests.StaffSessionsBrowserTests.test_native_mufti_and_admin_fresh_confirmation_revoke_only_exact_session",
        ".local/qa/functional-continuation/staff-sessions-browser/result.json",
        "modern",
    ),
    (
        "apps.data_privacy.browser_tests.DataPrivacyBrowserTests.test_native_four_levels_two_roles_independent_read_and_current_revocation",
        ".local/qa/functional-continuation/data-privacy-browser/result.json",
        "modern",
    ),
    (
        "apps.data_privacy.browser_work.PrivateUnclassifiedWorkBrowserTests.test_native_draft_approval_without_classification_and_current_work_revocation",
        ".local/qa/functional-continuation/private-unclassified-work-browser/result.json",
        "modern",
    ),
    (
        "apps.permission_sets.browser_tests.PermissionSetsBrowserTests.test_native_templates_individual_denial_audit_disable_and_revert",
        ".local/qa/functional-continuation/permission-sets-browser/result.json",
        "modern",
    ),
    (
        "apps.upload_security.browser_tests.UploadSecurityBrowserTests.test_native_atomic_reply_quarantine_retry_original_download_and_scan_revocation",
        ".local/qa/functional-continuation/upload-security-browser/result.json",
        "modern",
    ),
    (
        "apps.staff_mfa.browser_tests.StaffMfaBrowserTests.test_native_two_roles_real_totp_factor_revocation_and_one_use_recovery",
        ".local/qa/functional-continuation/staff-mfa-browser/result.json",
        "modern",
    ),
    (
        "apps.record_suppression.browser_tests.RecordSuppressionBrowserTests.test_native_preview_soft_delete_current_denials_and_audited_restore",
        ".local/qa/functional-continuation/record-suppression-browser/result.json",
        "modern",
    ),
    (
        "apps.media_derivatives.browser_tests.MediaDerivativeBrowserTests.test_native_queue_retry_original_playback_download_cancel_and_revocation",
        ".local/qa/functional-continuation/media-derivatives-browser/result.json",
        "modern",
    ),
    (
        "apps.derived_maintenance.browser_tests.DerivedMaintenanceBrowserTests.test_native_clear_regenerate_current_sources_and_preserved_human_approval",
        ".local/qa/functional-continuation/derived-maintenance-browser/result.json",
        "modern",
    ),
)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path, started):
    path = Path(path)
    require(
        path.is_file() and path.stat().st_mtime >= started, "Missing or stale execution artifact"
    )
    return {"path": str(path), "sha256": sha(path.read_bytes()), "size": path.stat().st_size}


def test_class_exists(name):
    module, class_name = name.rsplit(".", 1)
    path = Path(module.replace(".", "/") + ".py")
    require(path.is_file(), "Declared test module is absent")
    require(
        any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in ast.parse(path.read_text()).body
        ),
        "Declared test class is absent",
    )


def actual_upload_engine_proof(head):
    """Synthetic control-flow success cannot substitute for actual AV evidence."""
    # This verifier is invoked as `python infra/dev/functional_verify.py`.
    # Python puts infra/dev, not the checked-out project root, in sys.path.
    # Resolve the application package from this immutable source checkout,
    # never from PYTHONPATH or the caller's working directory.
    project_root = Path(__file__).resolve().parents[2]
    require(
        project_root == Path.cwd().resolve()
        and (project_root / "apps/upload_security/acceptance.py").is_file(),
        "Upload scanner acceptance source is outside the checked-out project",
    )
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from apps.upload_security.acceptance import BENIGN, EICAR

    path = Path(".local/qa/upload-security-engine/result.json")
    require(path.is_file(), "Actual upload engine evidence is absent")
    evidence = json.loads(path.read_text())
    require(
        evidence.get("schema") == "fatwa.upload-security.clamav-acceptance.v1"
        and evidence.get("status") == "PASSED"
        and evidence.get("real_engine_verified") is True
        and evidence.get("tested_sha") == head
        and evidence.get("failure_stage") is None
        and evidence.get("production_changed") is False
        and evidence.get("domain_rows_written") is False
        and evidence.get("main_merged") is False
        and evidence.get("deployment") == "NOT_DEPLOYED",
        "Actual upload engine did not pass on this exact source",
    )
    require(
        bool(os.environ.get("GITHUB_RUN_ID"))
        and evidence.get("workflow_run_id") == os.environ["GITHUB_RUN_ID"]
        and evidence.get("workflow_run_attempt") == os.environ.get("GITHUB_RUN_ATTEMPT"),
        "Actual upload engine proof belongs to another workflow execution",
    )
    scanner = evidence.get("scanner", {})
    require(
        scanner.get("mode") == "CONFIGURED"
        and "synthetic" not in scanner.get("engine_version", "").lower()
        and bool(scanner.get("engine_version"))
        and re.fullmatch(r"[0-9a-f]{64}", evidence.get("executable_sha256", ""))
        and evidence.get("signature_source_reported_by_operator") == "https://database.clamav.net"
        and {"--official-db-only=yes", "--bytecode-unsigned=no"}
        <= set(evidence.get("profile", [])),
        "Actual scanner or official signature provenance is missing",
    )
    databases = evidence.get("databases", [])
    require(
        len(databases) == 3
        and {row.get("name") for row in databases} == {"main.cvd", "daily.cvd", "bytecode.cvd"}
        and all(
            re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
            and type(row.get("size")) is int
            and row["size"] > 0
            and type(row.get("declared_signatures")) is int
            and row["declared_signatures"] > 0
            for row in databases
        ),
        "Actual official database snapshot is incomplete",
    )
    expected = (
        ("BENIGN_SYNTHETIC", BENIGN, "CLEAN"),
        ("EICAR_STANDARD_68_BYTES", EICAR, "BLOCKED"),
    )
    samples = evidence.get("samples", [])
    require(len(samples) == 2, "Actual scanner samples are incomplete")
    for sample, (name, raw, status) in zip(samples, expected, strict=True):
        require(
            sample.get("name") == name
            and sample.get("expected") == sample.get("status") == status
            and sample.get("sha256") == sha(raw)
            and sample.get("size") == len(raw)
            and sample.get("complete") is True
            and type(sample.get("scanned_files")) is int
            and sample["scanned_files"] == 1
            and type(sample.get("loaded_signatures")) is int
            and sample["loaded_signatures"] > 0
            and sample.get("spec") == scanner,
            "Actual scanner did not establish complete benign and EICAR outcomes",
        )
    reports = evidence.get("reports", [])
    require(
        len(reports) == 2
        and [row.get("return_code") for row in reports] == [0, 1]
        and all(
            type(row.get("report")) is str
            and bool(row["report"])
            and row.get("report_sha256") == sha(row["report"].encode())
            for row in reports
        ),
        "Actual scanner process diagnostics are absent or changed",
    )
    # This prerequisite job runs before the aggregate starts. Run identity and
    # exact SHA, rather than a later stage's mtime, bind its downloaded artifact.
    return {**pin(path, 0), "tested_sha": head, "workflow_run_id": evidence["workflow_run_id"]}


def group_browser_journeys(group):
    primary = group["browser"]
    additional = primary.get("additional_journeys", [])
    require(
        isinstance(additional, list) and all(isinstance(row, dict) for row in additional),
        "Additional required browser journeys must be explicit records",
    )
    return [primary, *additional]


def require_browser_journeys(log):
    require(
        "\nOK\n" in log and not re.search(r"\.\.\. skipped|OK \(skipped=", log),
        "Protected browser journeys were skipped or failed",
    )
    require(
        re.findall(r"^Ran (\d+) tests? in [^\n]+$", log, re.MULTILINE) == ["55"],
        "Exactly 55 protected browser journeys must complete",
    )
    # Output from HTTP handlers or Django startup may appear between a verbose
    # test header and its status. The one complete OK summary establishes success;
    # these headers establish which exact journeys made up that execution.
    observed = re.findall(r"^test_\w+ \(([\w.]+)\)", log, re.MULTILINE)
    expected = {row[0] for row in (*PRIOR_BROWSER_JOURNEYS, *NEW_BROWSER_JOURNEYS)}
    require(
        len(observed) == len(set(observed)) == len(expected) == 55 and set(observed) == expected,
        "A required protected browser journey was omitted or replaced",
    )
    return sorted(observed)


def browser_proof(journey, *, started, log_pin, family):
    test_id, path, schema = journey
    common = {"test_id": test_id, "family": family, "execution_log": log_pin}
    if schema == "execution_log":
        return {**common, "evidence_kind": "execution_log"}
    record = pin(path, started)
    proof = json.loads(Path(path).read_text())
    require(proof.get("status") == "PASS", "Protected browser proof did not pass")
    if schema == "casework":
        views = proof.get("views", [])
        require(
            {view.get("width") for view in views} == {320, 1280}
            and all(view.get("rtl") is True and view.get("no_overflow") is True for view in views)
            and proof.get("tests_run") == 1
            and proof.get("unsafe_url_requests") == 0,
            "Legacy casework responsive journey did not pass",
        )
        # This legacy source launches with chromium_sandbox=True; its JSON predates
        # a sandbox field. The exact executed test and protected invocation are
        # required, rather than adding an assertion the original proof never made.
    else:
        sandbox_field = "browser_sandbox" if schema == "assignments" else "sandbox"
        require(
            proof.get(sandbox_field) is True and set(proof.get("widths", [])) == {320, 1280},
            "Protected responsive journey did not pass",
        )
    error_field = "browser_errors" if schema == "quality" else "page_errors"
    for field in (error_field, "external_requests"):
        value = proof.get(field)
        require(
            value == [] or (type(value) is int and value == 0),
            "Browser error or unexpected external request",
        )
    folder = Path(path).parent
    screenshots = sorted(folder.glob("*.png"))
    traces = sorted(folder.glob("*trace*.zip"))
    require(
        all(any(p.name.endswith(f"-{width}.png") for p in screenshots) for width in (320, 1280)),
        "Responsive browser screenshot is absent",
    )
    if schema not in {"assignments", "casework"}:
        require(traces, "Protected browser trace is absent")
    artifacts = [pin(p, started) for p in [*screenshots, *traces]]
    for trace in traces:
        with zipfile.ZipFile(trace) as archive:
            require(
                archive.testzip() is None
                and any(name.endswith(".trace") for name in archive.namelist()),
                "Protected browser trace is invalid",
            )
    return {**common, **record, "evidence_kind": "json_and_execution_log", "artifacts": artifacts}


def write_continuation_receipt(execution, log_root, *, labels, browser_labels):
    plan = json.loads(PLAN.read_text())
    inventory = plan["source_inventory"]
    raw = Path(inventory["path"]).read_bytes()
    require(sha(raw) == inventory["sha256"], "Original requirement inventory changed")
    original = json.loads(raw)
    index = {row["original_id"]: row for row in original}
    require(
        len(index) == len(original) == inventory["denominator"] == 556,
        "Original denominator changed",
    )
    for prefix in ("specification", "decision"):
        require(
            sha(Path(inventory[prefix + "_path"]).read_bytes()) == inventory[prefix + "_sha256"],
            "Referenced source document changed",
        )
    previous = plan["previous_batch"]
    previous_raw = Path(previous["scope_plan_path"]).read_bytes()
    require(sha(previous_raw) == previous["scope_plan_sha256"], "Historical completed plan changed")
    previous_ids = {
        p["original_id"] for g in json.loads(previous_raw)["groups"] for p in g["points"]
    }
    require(
        previous_ids == set(previous["original_ids"])
        and len(previous_ids) == previous["credited_by_coordinator"] == 57,
        "Historical credited IDs changed",
    )
    groups = plan["groups"]
    points = [point for group in groups for point in group["points"]]
    identifiers = [point["original_id"] for point in points]
    require(
        len(set(identifiers)) == len(identifiers) == plan["candidate_count"],
        "Additional candidate count or uniqueness mismatch",
    )
    require(not set(identifiers) & previous_ids, "Previously credited points counted twice")
    require(
        not set(identifiers) & {point["original_id"] for point in plan["explicit_exclusions"]},
        "An excluded point was counted",
    )
    for point in points:
        require(
            all(
                point[key] == index[point["original_id"]][key]
                for key in ("original_text", "direct_spec_ids")
            ),
            "Original requirement was paraphrased or changed",
        )
    for group in groups:
        require(
            "PLANNED" not in group["implementation_state"],
            "An unimplemented planned group cannot be certified",
        )
        require(Path(group["contract"]).is_file(), "Functional contract is absent")
        require(
            group["service_test_labels"] and set(group["service_test_labels"]) <= set(labels),
            "A required service test family was not executed",
        )
        require(not group["pending_service_test_labels"], "Required test implementation is pending")
        for name in group["service_test_classes"]:
            test_class_exists(name)
        for browser in group_browser_journeys(group):
            test_class_exists(browser["test_class"])
            require(
                browser["test_class"].rsplit(".", 1)[0] in browser_labels,
                "Required browser journey is not registered",
            )
    require(
        {browser["result_path"] for group in groups for browser in group_browser_journeys(group)}
        == {row[1] for row in NEW_BROWSER_JOURNEYS},
        "The continuation browser proof family changed",
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    require(head == execution["tested_sha"], "Accounting commit differs from the tested commit")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], text=True
        ).strip(),
        "Accounting source is not clean",
    )
    major = execution["postgres"].split()[2].split(".")[0]
    require(major in {"17", "18"}, "Unsupported PostgreSQL evidence")
    stages = {stage["name"]: stage for stage in execution["stages"]}
    require(
        {
            "system",
            "migrations",
            "recording",
            "recording_player",
            "offline_client",
            "affected",
            "recovery",
        }
        <= stages.keys(),
        "Mandatory aggregate stage is missing",
    )
    logs = []
    for name, stage in stages.items():
        require(stage["exit_code"] == 0, "A failed stage cannot count completion")
        value = pin(log_root / (name + ".log"), execution["started_at_epoch"])
        require(value["sha256"] == stage["log_sha256"], "Stage log bytes changed")
        logs.append({**value, "stage": name, "command": stage["command"]})
    affected = (log_root / "affected.log").read_text()
    require(
        "\nOK\n" in affected and not re.search(r"\.\.\. skipped|OK \(skipped=", affected),
        "Service evidence failed or skipped required work",
    )
    test_count = re.search(r"Ran (\d+) tests? in", affected)
    require(test_count, "Real service test result is absent")
    recovery_path = Path(".local/qa/functional-continuation") / f"recovery-pg{major}.json"
    recovery_pin = pin(recovery_path, execution["started_at_epoch"])
    recovery = json.loads(recovery_path.read_text())
    require(
        recovery["tested_sha"] == head
        and recovery["status"] == "PASS"
        and recovery["postgres_major"] == int(major),
        "Recovery proof does not match this exact execution",
    )
    for field in (
        "source_unchanged",
        "source_frozen",
        "fresh_process_readers",
        "restored_private_storage_used",
        "restored_unchanged_after_readers",
        "all_restored_originals_verified_after_readers",
        "source_originals_unchanged",
        "encrypted",
    ):
        require(recovery[field] is True, "Incomplete encrypted recovery proof")
    require(recovery["plaintext_dump_present"] is False, "Plaintext database dump was retained")
    expected_workflows = {*PRIOR_WORKFLOWS, *NEW_WORKFLOWS}
    require(
        set(recovery["additional_workflows"]) == expected_workflows
        and len(recovery["additional_workflows"]) == len(expected_workflows),
        "A prior or new workflow was omitted from recovery",
    )
    new_tables = sorted(name for names in NEW_WORKFLOWS.values() for name in names)
    expected_tables = {*PRIOR_TABLES, *new_tables}
    require(
        len(PRIOR_TABLES) == 22
        and len(new_tables) == 86
        and len(expected_tables) == 108
        and set(recovery["tables"]) == expected_tables,
        "Exactly the 108 prior and new recovery tables are required",
    )
    require(
        all(
            type(recovery["tables"][name]["rows"]) is int and recovery["tables"][name]["rows"] > 0
            for name in expected_tables
        ),
        "An empty prior or new table cannot prove restore",
    )
    restored_results = recovery.get("restored_workflow_results")
    require(
        isinstance(restored_results, dict)
        and set(restored_results) == expected_workflows
        and all(isinstance(value, dict) and value for value in restored_results.values()),
        "All forty-two fresh-process workflow result records are required",
    )
    for helper, expected in RESTORED_DENIAL_CHECKS.items():
        result = restored_results[helper]
        require(
            result.get("denial_checks") == expected
            and all(type(value) is int for value in result["denial_checks"].values())
            and type(result.get("denied_read_count")) is int
            and result["denied_read_count"] == sum(expected.values())
            and result.get("positive_reads_after_denial") is True,
            "Restored current-access denial proof is incomplete or changed",
        )
    require(
        any(
            ref["table"] == "research_library_libraryblob"
            and ref["backend"] == "private-filesystem-v1"
            for ref in recovery["durable_original_references"]
        ),
        "External library originals were omitted from recovery",
    )
    complete = execution["status"] == "PASS" and execution["browser_requested"] is True
    upload_engine_proof = actual_upload_engine_proof(head) if complete else None
    browser_proofs = []
    browser_test_ids = []
    if complete:
        require("browser" in stages, "Protected browser stage was not executed")
        require(
            os.environ.get("FATWA_BROWSER_SANDBOX") == "1",
            "Protected browser accounting requires sandboxed execution",
        )
        browser_log = (log_root / "browser.log").read_text()
        browser_test_ids = require_browser_journeys(browser_log)
        log_pin = pin(log_root / "browser.log", execution["started_at_epoch"])
        for family, journeys in (
            ("prior", PRIOR_BROWSER_JOURNEYS),
            ("additional", NEW_BROWSER_JOURNEYS),
        ):
            for journey in journeys:
                browser_proofs.append(
                    browser_proof(
                        journey,
                        started=execution["started_at_epoch"],
                        log_pin=log_pin,
                        family=family,
                    )
                )
    count = len(identifiers) if complete else 0
    result = {
        "schema": "fatwa.functional-continuation-scope-receipt.v1",
        "status": "PASS" if complete else "PENDING_PROTECTED_BROWSER",
        "tested_sha": head,
        "scope_plan_sha256": sha(PLAN.read_bytes()),
        "source_inventory": inventory,
        "claim_boundary": plan["claim_boundary"],
        "denominator": len(index),
        "previous_credited_count": len(previous_ids),
        "candidate_count": len(identifiers),
        "completed_additional_original_ids": sorted(identifiers, key=int) if complete else [],
        "completed_additional_original_owner_points": count,
        "completed_additional_percentage": round(100 * count / len(index), 6),
        "overlap_with_previous_ids": [],
        "requested_10_to_12_percent_met": 10 <= 100 * count / len(index) <= 12,
        "postgres_major": int(major),
        "executed_test_labels": labels,
        "affected_tests": int(test_count[1]),
        "protected_browser_tests": len(browser_test_ids),
        "protected_browser_test_ids": browser_test_ids,
        "prior_browser_journeys": len(PRIOR_BROWSER_JOURNEYS) if complete else 0,
        "additional_browser_journeys": len(NEW_BROWSER_JOURNEYS) if complete else 0,
        "browser_json_proofs": sum("path" in proof for proof in browser_proofs),
        "browser_log_only_proofs": sum("path" not in proof for proof in browser_proofs),
        "stage_receipts": logs,
        "browser_proofs": browser_proofs,
        "actual_upload_engine_proof": upload_engine_proof,
        "encrypted_recovery_proof": {
            **recovery_pin,
            "prior_nonempty_tables": sorted(PRIOR_TABLES),
            "prior_nonempty_table_count": len(PRIOR_TABLES),
            "new_nonempty_tables": new_tables,
            "new_nonempty_table_count": len(new_tables),
            "total_nonempty_tables": len(recovery["tables"]),
            "restored_workflow_results": restored_results,
            "fresh_process_denied_reads": sum(
                restored_results[helper]["denied_read_count"] for helper in RESTORED_DENIAL_CHECKS
            ),
        },
        "groups": [
            {
                "id": g["id"],
                "title_ar": g["title_ar"],
                "additional_original_ids": [p["original_id"] for p in g["points"]],
                "completed": complete,
            }
            for g in groups
        ],
        "release_state": plan["release_state"],
    }
    output = Path(".local/qa/functional-continuation") / ("pg" + major)
    output.mkdir(parents=True, exist_ok=True)
    (output / "scope-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result
