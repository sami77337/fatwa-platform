# V13 — أدلة محدودة منفصلة عن الترشيح

[أدلة V12 التاريخية](../v12_scope_evidence/EVIDENCE.md) محفوظة برؤوسها؛ الترشيح التالي ليس إثبات تنفيذ.

## browser-audio

الحالة: **VERIFIED_BOUNDED**

الهدف المحدد: تسجيل متصفح اصطناعي بإذن صريح وربط الأصل المحقق بالوقائع أو إصدار الجواب، مع معاينة وإلغاء.

الحدود: PCM16LE mono8000Hz حتى10ثوان/160044بايت؛ لا resume أو ضمان كل الأجهزة، ولا ASR/تفريغ أو ادعاء معالجة عطل Transcription. 533 وصول قضايا MUFTI المصرح بها فقط؛ لا U03. لا إكمال كامل لأي بند واسع.

النقاط المرشحة: 25, 36, 44, 46, 70, 75, 77, 78, 80, 81, 82, 432, 533

النقاط التي أضيف لها دليل مثبت: 25, 36, 44, 46, 70, 75, 77, 78, 81, 82, 533

المثبت فقط: رحلة Chrome اصطناعية بإذن ميكروفون صريح ورفض/إلغاء قبل الحفظ ثم بدء/إيقاف/معاينة؛ WAV متحقق خاص مرتبط بالقضية الواحدة وإصدار الوقائع، ثم تسجيل جزء جواب ضمن الإصدار والمراجعة البشرية. ليست تسجيلات مستخدمين حقيقيين.

الرأس: `cd22cbd265db4b57124a1f091a041fd5200637b8`

### code

- [apps/browser_audio/static/browser_audio/capture.js — file](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/browser_audio/static/browser_audio/capture.js#L1-L136)
- [apps/browser_audio/static/browser_audio/worklet.js — file](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/browser_audio/static/browser_audio/worklet.js#L1-L25)
- [apps/browser_audio/context.py — capture](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/browser_audio/context.py#L8-L12)
- [apps/casework_web/requester_intake.py — submit_intake](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/casework_web/requester_intake.py#L80-L119)

### positive_tests

- [tests/casework/test_v13_audio_wiring.py — InitialAudioTests.test_one_native_case_private_original_and_exact_replay_no_second_upload](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_audio_wiring.py#L77-L107)
- [tests/casework/test_v13_audio_wiring.py — InitialAudioTests.test_existing_requester_and_mufti_forms_render_scoped_recorders](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_audio_wiring.py#L109-L126)

### negative_tests

- [tests/casework/test_v13_audio_wiring.py — InitialAudioTests.test_disk_failure_rolls_back_case_source_evidence_and_retry_succeeds](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_audio_wiring.py#L135-L141)
- [tests/casework/test_v13_audio_wiring.py — InitialAudioTests.test_invalid_consent_proof_csrf_or_content_never_creates_case](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_audio_wiring.py#L143-L148)
- [tests/casework/test_v13_audio_wiring.py — RecorderPolicyTests.test_only_trusted_html_recorder_receives_permission_not_bytes_or_escaped_text](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_audio_wiring.py#L172-L185)

### Protected connected browser

- [tests/casework/test_v13_browser.py — V13ConnectedBrowserTests.test_one_v13_recorded_case_partial_delivery_encrypted_restore_and_target_http](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_browser.py#L407-L646)
- The receipt must contain actual sandbox=true and exact tested SHA; an environment flag alone is insufficient.
- [PG17 job134526633973](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526633973) — exact-head PASS
- [PG18 job134526634232](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526634232) — exact-head PASS

## timed-citations

الحالة: **VERIFIED_BOUNDED**

الهدف المحدد: موضع بداية/نهاية ضمن مدة أصل ثابت وبصمة ونسخة محددة، مع تاريخ تصحيح وحقوق حالية.

الحدود: الصوت الخاص فقط؛ لا corpus دروس/فيديو كامل أو إحالة عامة/تصدير/طباعة. #t تنقل داخل الأصل المصرح لا قص بايتات أو Range. لا توليد قول أو توقيت، ولا نقل تلقائي. 543 لا يثبت تحديد عبارة داخل المحرر؛556 يثبت التاريخ ولا يثبت العرض في التصدير.

النقاط المرشحة: 179, 346, 543, 544, 549, 551, 552, 553, 554, 555, 556

النقاط التي أضيف لها دليل مثبت: 179, 346, 543, 549, 551, 552, 554, 556

المثبت فقط: اختيار أصل صوتي خاص ثابت وموضع بداية/نهاية ضمن مدته المحققة، تأكيد بشري وتصحيح محفوظ بلا نقل تلقائي، وفحص الصلاحية والانتهاء في الاعتماد والاستخدام اللاحق. يشمل رفض سحب الهوية أو CITE في آخر callback بعد إصلاح الفشل التاريخي.

الرأس: `cd22cbd265db4b57124a1f091a041fd5200637b8`

### code

- [apps/timed_citations/services.py — propose](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/services.py#L206-L286)
- [apps/timed_citations/services.py — act](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/services.py#L290-L323)
- [apps/timed_citations/services.py — open_audio](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/services.py#L327-L361)
- [apps/timed_citations/services.py — for_locked_answer](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/services.py#L365-L395)
- [apps/casework/services.py — _answer_timed](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/casework/services.py#L80-L127)
- [apps/casework/services.py — _answer_use_boundary](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/casework/services.py#L131-L142)
- [apps/experimental_publication/services.py — _require_publication_sources](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/experimental_publication/services.py#L105-L130)

### positive_tests

- [apps/timed_citations/tests.py — TimedTests.test_exact_duration_human_confirmation_and_original_bytes](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/tests.py#L138-L160)
- [apps/timed_citations/tests.py — TimedTests.test_correction_is_append_only_and_previous_revision_cannot_open](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/tests.py#L205-L234)
- [tests/casework/test_v13_timed_bindings.py — TimedBindingsTests.test_confirmed_attachment_and_answer_media_allow_real_approval_and_private_bytes](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_timed_bindings.py#L149-L157)

### negative_tests

- [apps/timed_citations/tests.py — TimedTests.test_invalid_times_and_forged_duration_version_digest_are_denied](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/tests.py#L162-L184)
- [apps/timed_citations/tests.py — TimedTests.test_old_answer_does_not_inherit_citation_and_exact_old_recording_never_redirects](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/timed_citations/tests.py#L186-L203)
- [tests/casework/test_v13_timed_bindings.py — TimedBindingsTests.test_approved_then_expired_blocks_private_release_files_delivery_and_publication](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_timed_bindings.py#L179-L215)
- [tests/casework/test_v13_timed_bindings.py — TimedBindingsTests.test_collection_rechecks_timed_expiry_after_later_legacy_result_projection](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_timed_bindings.py#L269-L311)
- [tests/v13_integration_security/test_boundaries.py — TimedFinalCallbackTests.test_staff_revocation_in_final_deadline_callback_denies_private_bytes](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/v13_integration_security/test_boundaries.py#L29-L54)
- [tests/v13_integration_security/test_boundaries.py — TimedFinalCallbackTests.test_cite_revocation_in_final_deadline_callback_denies_requester_bytes](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/v13_integration_security/test_boundaries.py#L56-L77)
- [tests/v13_integration_security/test_boundaries.py — TimedFinalCallbackTests.test_no_policy_deadline_callback_after_validated_hook_returns](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/v13_integration_security/test_boundaries.py#L79-L108)

### Protected connected browser

- [tests/casework/test_v13_browser.py — V13ConnectedBrowserTests.test_one_v13_recorded_case_partial_delivery_encrypted_restore_and_target_http](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_browser.py#L407-L646)
- The receipt must contain actual sandbox=true and exact tested SHA; an environment flag alone is insufficient.
- [PG17 job134526633973](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526633973) — exact-head PASS
- [PG18 job134526634232](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526634232) — exact-head PASS

## measured-arabic-search

الحالة: **VERIFIED_BOUNDED**

الهدف المحدد: مقارنة baseline/after عربية قابلة للتكرار على نطاق مصرح مع قياسات وحدود ظاهرة.

الحدود: TOC_METADATA_ONLY ونافذة20 عنوانًا؛ لا بحث متن أو corpus كامل أو semantic، ولا stem/synonyms أو ادعاء تسريع. fixture42 حكمًا اصطناعيًا لمؤلف الاختبار وليست gold مستقلة؛243/244 وتحكيم المختصين ما زالت فجوة. 622 فهرس فقط.

النقاط المرشحة: 215, 216, 219, 221, 231, 242, 245, 246

النقاط التي أضيف لها دليل مثبت: 216, 221, 231, 242, 245, 246

المثبت فقط: ترتيب كلمات وأرقام عربية لعناوين أول20 نتيجة مرجعية مصرح بها؛ قياس baseline/after اصطناعي، مع حفظ الموضع والطبعة والعودة وسبب الترتيب ورفض الحقوق المسحوبة أو المنتهية. يعرض حد النافذة وحالة المراجعة البشرية PENDING.

الرأس: `cd22cbd265db4b57124a1f091a041fd5200637b8`

### code

- [apps/arabic_search_eval/ranking.py — rank_titles](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/ranking.py#L45-L78)
- [apps/arabic_search_eval/services.py — search_reference_titles](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/services.py#L17-L86)
- [apps/arabic_search_eval/evaluation.py — evaluate](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/evaluation.py#L72-L142)
- [apps/research_workspace/views.py — _search](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/research_workspace/views.py#L49-L60)

### positive_tests

- [apps/arabic_search_eval/test_services.py — AdapterTests.test_real_baseline_vs_digit_and_boundary_ranking_preserves_source_and_open_pins](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/test_services.py#L85-L114)
- [apps/arabic_search_eval/test_ranking.py — RankingTests.test_explicit_fixture_expectations_and_negative_queries](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/test_ranking.py#L11-L23)
- [tests/casework/test_v13_search_ui.py — SearchUiTests.test_ranked_search_open_back_preserves_scope_filters_and_canonical_answer](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_search_ui.py#L55-L72)

### negative_tests

- [apps/arabic_search_eval/test_services.py — AdapterTests.test_rights_expiry_during_rank_closes_response_even_if_no_hits_selected](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/test_services.py#L154-L171)
- [apps/arabic_search_eval/test_ranking.py — RankingTests.test_pending_stale_incomplete_and_altered_review_are_not_approval](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/arabic_search_eval/test_ranking.py#L68-L86)
- [tests/casework/test_v13_search_ui.py — SearchUiTests.test_flag_strict_kind_and_revoked_source_do_not_fallback](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_search_ui.py#L74-L88)

### Protected connected browser

- [tests/casework/test_v13_browser.py — V13ConnectedBrowserTests.test_one_v13_recorded_case_partial_delivery_encrypted_restore_and_target_http](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_browser.py#L407-L646)
- The receipt must contain actual sandbox=true and exact tested SHA; an environment flag alone is insufficient.
- [PG17 job134526633973](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526633973) — exact-head PASS
- [PG18 job134526634232](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526634232) — exact-head PASS

## human-classification

الحالة: **VERIFIED_BOUNDED**

الهدف المحدد: اقتراح تصنيف مفسر المصدر ومراجعة قبول/رفض بشرية وتاريخ دون تغيير وقائع السؤال.

الحدود: ليس سجل Taxonomy أو تصنيفًا رئيسيًا/إضافيًا أو Tags رسمية، ولا نقل فئة المنشور. 161/162/164/169/170 غير منسوبة لهذه المجموعة. لا AI classifier أو صلاحية U03 أو علاقة علمية مستنتجة؛622 فهرس كتاب فقط.

النقاط المرشحة: 47, 161, 162, 163, 164, 169, 170, 417

النقاط التي أضيف لها دليل مثبت: 47, 417

المثبت فقط: سجل اقتراح تسمية تجريبية خاصة مبني على علاقة مرجعية معتمدة ومثبتة النسخة؛ قبول/رفض بشري مستقل وتاريخ تصحيح وسحب؛ لا يغيّر Evidence أو تصنيف النسخة المنشورة. هذا دليل على عدم تبديل الوقائع وتسجيل المراجعة فقط.

الرأس: `cd22cbd265db4b57124a1f091a041fd5200637b8`

### code

- [apps/classification_review/services.py — propose](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/services.py#L122-L167)
- [apps/classification_review/services.py — act](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/services.py#L171-L212)
- [apps/classification_review/services.py — desk](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/services.py#L216-L300)

### positive_tests

- [apps/classification_review/tests.py — ClassificationTests.test_proposed_until_independent_human_no_canonical_mutation](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/tests.py#L77-L95)
- [apps/classification_review/tests.py — ClassificationTests.test_reject_correction_and_withdrawal_never_reapprove](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/tests.py#L127-L143)
- [tests/casework/test_v13_classification_wiring.py — ClassificationWiringTests.test_native_navigation_scope_and_independent_pending_state](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_classification_wiring.py#L65-L82)

### negative_tests

- [apps/classification_review/tests.py — ClassificationTests.test_database_append_only_self_review_and_exclusive_decision](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/tests.py#L217-L248)
- [apps/classification_review/tests.py — ClassificationTests.test_real_rights_expiry_revocation_and_redacted_history](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/apps/classification_review/tests.py#L349-L399)
- [tests/casework/test_v13_classification_wiring.py — ClassificationWiringTests.test_freeze_blocks_shared_http_and_service_without_insert](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_classification_wiring.py#L84-L91)

### Protected connected browser

- [tests/casework/test_v13_browser.py — V13ConnectedBrowserTests.test_one_v13_recorded_case_partial_delivery_encrypted_restore_and_target_http](https://github.com/sami77337/fatwa-platform/blob/cd22cbd265db4b57124a1f091a041fd5200637b8/tests/casework/test_v13_browser.py#L407-L646)
- The receipt must contain actual sandbox=true and exact tested SHA; an environment flag alone is insufficient.
- [PG17 job134526633973](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526633973) — exact-head PASS
- [PG18 job134526634232](https://github.com/sami77337/fatwa-platform/actions/runs/44222224904/job/134526634232) — exact-head PASS

## connected-recovery

الحالة: **SUSPENDED_SECURITY**

الهدف المحدد: رحلة واحدة تربط الصوت والإحالة والبحث والجواب والنشر المستقل ثم استعادة مشفرة وHTTP لهدف جديد وسحب صلاحيات.

الحدود: SEC13-01 BLOCKED: تطبيع مخطط الاستعادة يغيّر نصوص SQL المقتبسة فيجعل predicates مختلفة متساوية البصمة ويقبل هدفًا متلاعبًا READY. الدليل السابق محفوظ في suspended_recovery_evidence.json، لكن تعليق إسناد المجموعة مستمر حتى الإصلاح والمراجعة المستقلة. لا نجاح متصفح مستقل من ENVIRONMENT_ERROR.

النقاط المرشحة: 30, 43, 44, 46, 75, 76, 82, 406, 408, 412, 414, 415, 419, 423, 424, 425, 428, 434, 435

النقاط التي أضيف لها دليل مثبت: لا شيء بعد
