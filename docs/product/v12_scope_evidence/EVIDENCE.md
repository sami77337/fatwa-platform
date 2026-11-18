# شواهد محددة عند P0 وطبقة P1

كل مجموعة تثبت الجزء المكتوب فقط؛ اشتراك نقاط في شاهد لا يجعلها متكافئة.

## case-original

حفظ السؤال الحرفي والمرجع المستقل؛ التعقيب والاستيضاح يغيران الأدلة؛ قرار المفتي مرتبط بإصدار جواب وأدلة محددين.

**الحد:** الشاهد يخص القضية الاصطناعية وخدماتها الحالية؛ لا يثبت كل مصادر الإنتاج أو سياسة هوية معتمدة أو اكتمال جميع أمثلة البند.

نقاط: 21, 22, 23, 26, 27, 28, 29, 31, 32, 33, 34, 36, 37, 38, 39, 40, 43, 44, 45, 46, 66, 69, 81, 82, 83, 84, 85, 86, 87, 102, 103, 104, 105, 147, 184, 434, 435, 436, 444, 445, 503, 504

- code: [apps/casework/services.py — intake_case](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L357-L425)
- code: [apps/casework/services.py — record_decision](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L537-L601)
- code: [apps/casework/services.py — add_followup](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L636-L650)
- tests: [tests/casework/test_core.py — test_two_cases_have_distinct_durable_identity_and_lossless_original](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L94-L108)
- tests: [tests/casework/test_core.py — test_followup_invalidates_previous_approval_without_erasing_history](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L152-L174)
- tests: [tests/casework/test_core.py — test_clarification_returns_same_case_then_new_human_version_is_required](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L176-L199)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203282032) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v6-casework.yml#L1-L180)

## source-intake

Adapters محلية لصيغ Telegram وYouTube والموقع تحفظ الخام وتمنع التكرار وتضع الربط الملتبس للمراجعة؛ لا دمج لتشابه الاسم.

**الحد:** محاكيات ببيانات اصطناعية؛ لا webhook عام أو Telegram/YouTube فعلي أو Meta. أحداث التعديل تحفظ للمراجعة ولا تثبت دورة تصحيح/حذف جميع المنصات.

نقاط: 12, 18, 19, 20, 21, 22, 23, 24, 41, 42, 50, 52, 53, 141, 153, 154, 155, 483, 485, 486, 532

- code: [apps/source_case_intake/services.py — capture](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/services.py#L55-L82)
- code: [apps/source_case_intake/services.py — process](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/services.py#L164-L201)
- code: [apps/source_case_intake/services.py — resolve_review](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/services.py#L231-L301)
- tests: [apps/source_case_intake/tests.py — test_identical_names_do_not_merge_senders_accounts_or_conversations](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/tests.py#L144-L167)
- tests: [apps/source_case_intake/tests.py — test_threads_edits_and_unavailable_original_are_held](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/tests.py#L169-L181)
- tests: [apps/source_case_intake/tests.py — test_raw_survives_apply_failure_and_retry_is_atomic](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_case_intake/tests.py#L218-L226)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281930) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v9-campaign.yml#L1-L116)

## requester

بوابة عربية بقضية واحدة، استيضاح وملف ذري، عرض الجواب المصرح فقط وإغلاق القديم عند تغير الوقائع؛ تأكيد الحفظ ليس قراءة.

**الحد:** سياسات الهوية والاسترداد الإنتاجية غير معتمدة؛ الهاتف والكيبورد لا يثبتان مطابقة WCAG كاملة أو كل الأجهزة.

نقاط: 29, 30, 37, 38, 39, 40, 54, 145, 146, 147, 148, 149, 150, 151, 152, 249, 250, 251, 254, 259, 399, 462, 501, 502, 503, 504

- code: [apps/requester_portal/services.py — snapshot](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/requester_portal/services.py#L49-L171)
- code: [apps/requester_portal/services.py — submit_reply](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/requester_portal/services.py#L175-L221)
- tests: [apps/requester_portal/workflow_tests.py — test_one_step_reply_file_under_external_lock_reaches_existing_mufti_workspace](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/requester_portal/workflow_tests.py#L46-L72)
- tests: [apps/requester_portal/workflow_tests.py — test_storage_failure_rolls_back_reply_evidence_and_pending_clarification](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/requester_portal/workflow_tests.py#L74-L89)
- tests: [apps/requester_portal/workflow_tests.py — test_reply_file_closes_released_answer_and_only_current_case_changes](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/requester_portal/workflow_tests.py#L106-L117)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281992) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v11_verify.py#L1-L81)

## mufti-desk

واجهة القضية تجمع الخطوة التالية والسياق والجواب والبحث والحقوق والمراجعة والإتاحة؛ تستخدم الخدمات القائمة.

**الحد:** تكامل اصطناعي وليس اعتماد رحلة إنتاج؛ لا إثبات لجميع قوائم التعيين أو التسجيل المباشر أو سياسات U03.

نقاط: 1, 2, 30, 48, 49, 50, 51, 52, 53, 54, 60, 487, 488, 489, 490, 494, 533, 542

- code: [apps/mufti_workspace/workflow.py — describe_work](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/mufti_workspace/workflow.py#L11-L187)
- tests: [apps/mufti_workspace/workflow_tests.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/mufti_workspace/workflow_tests.py#L1-L177)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281992) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v11_verify.py#L1-L81)

## answer-parts

أجزاء نص وملف وصوت مرتبة في إصدار مع اعتماد ثم إتاحة خاصة مستقلة؛ النسخ الأصلية لا تضيع عند تحرير الجواب.

**الحد:** أنواع وأحجام محدودة؛ رفع الصوت لا يثبت التسجيل المباشر أو الفيديو أو كل الوثائق؛ لا Object Storage إنتاجي.

نقاط: 25, 36, 69, 71, 72, 75, 76, 78, 80, 86, 87, 133, 272, 358, 359, 360, 376, 377, 378, 379, 380, 381, 382, 440

- code: [apps/answer_media/services.py — save_multipart_answer](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/answer_media/services.py#L158-L289)
- code: [apps/answer_media/services.py — release_private](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/answer_media/services.py#L314-L373)
- tests: [apps/answer_media/tests.py — test_text_audio_file_revision_approval_and_separate_private_release](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/answer_media/tests.py#L93-L120)
- tests: [apps/answer_media/tests.py — test_cross_editor_copy_preserves_files_but_not_approval_or_private_release](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/answer_media/tests.py#L256-L285)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## delivery

خطة أجزاء محكومة بقدرات القناة وبصمات الجواب والتوقيع؛ قبول المزود منفصل عن الإثبات، والفشل الجزئي لا يعيد الأجزاء آليًا.

**الحد:** مزود محاكى فقط؛ لا إرسال فعلي أو عقد Meta. اقتراح بديل لا يثبت تنفيذه. لا إعادة إرسال آلية بعد حالة غير محسومة.

نقاط: 106, 108, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 123, 124, 125, 126, 127, 128, 129, 130, 131, 442, 452, 481, 484, 494, 505, 506, 535

- code: [apps/composite_delivery/services.py — _prepare](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/composite_delivery/services.py#L79-L155)
- code: [apps/composite_delivery/services.py — composite_status](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/composite_delivery/services.py#L333-L385)
- tests: [apps/composite_delivery/tests.py — test_text_file_audio_signed_full_journey_and_accepted_is_not_delivered](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/composite_delivery/tests.py#L123-L148)
- tests: [apps/composite_delivery/tests.py — test_capability_kind_mime_size_text_and_receipt_gaps_block_entire_staging](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/composite_delivery/tests.py#L150-L170)
- tests: [apps/composite_delivery/tests.py — test_failure_partial_uncertainty_never_retries_completed_or_failed_parts](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/composite_delivery/tests.py#L172-L193)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281930) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v9-campaign.yml#L1-L116)

## publication

نسخة تحريرية مستقلة وموافقة نشر مستقلة؛ المكتبة التجريبية تخفي المسحوب والقديم وتعرض تصحيحات آمنة.

**الحد:** ليست إتاحة عامة فعلية؛ قوالب guard لا تثبت إزالة كل معلومة شخصية؛ لا جدولة نشر أو Telegram عام أو صلاحيات منظّم U03.

نقاط: 88, 91, 92, 121, 125, 132, 133, 134, 136, 137, 139, 140, 141, 142, 143, 144, 248, 260, 261, 265, 266, 267, 268, 269, 270, 271, 275, 276, 277, 282, 388, 419, 536, 537

- code: [apps/experimental_publication/services.py — create_edition](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/experimental_publication/services.py#L170-L218)
- code: [apps/library_preview/services.py — browse](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/library_preview/services.py#L266-L337)
- code: [apps/library_preview/services.py — read](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/library_preview/services.py#L341-L346)
- tests: [apps/library_preview/tests.py — test_anonymous_read_only_journey_has_no_private_projection_or_transcript_resolver](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/library_preview/tests.py#L85-L111)
- tests: [apps/library_preview/tests.py — test_withdrawal_and_new_facts_close_listing_details_and_source](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/library_preview/tests.py#L180-L189)
- tests: [apps/library_preview/tests.py — test_corrections_preserve_metadata_history_but_never_old_content_or_candidates](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/library_preview/tests.py#L202-L226)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## knowledge-links

علاقات بمصدر مرجعي/تفريغ مرتبط بفتوى تجريبية، اقتراح ثم مراجعة مستقلة وتاريخ تصحيح وسحب وفتح مصرح.

**الحد:** ليست موسوعة U10 ولا رسم معرفة شاملًا أو كتالوج دروس مكتملًا؛ كل معنى أوسع في البند يبقى مفتوحًا.

نقاط: 3, 4, 175, 178, 179, 180, 181, 188, 228, 274, 275, 276, 277, 283, 284, 285, 286, 287, 288, 289, 290, 329, 335, 336, 337, 342, 343, 345, 346, 347, 510, 537, 539

- code: [apps/knowledge_links/services.py — propose](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/knowledge_links/services.py#L244-L292)
- code: [apps/knowledge_links/services.py — act](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/knowledge_links/services.py#L296-L338)
- code: [apps/knowledge_links/services.py — open_material](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/knowledge_links/services.py#L506-L515)
- tests: [apps/knowledge_links/tests.py — test_real_reference_transcript_journey_with_safe_library_projection](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/knowledge_links/tests.py#L157-L186)
- tests: [apps/knowledge_links/tests.py — test_correction_preserves_history_hides_old_and_requires_new_approval](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/knowledge_links/tests.py#L208-L230)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## research

بحث عربي بمصادر مصرح بها وفتح موضع موثق والعودة وإلحاق إحالة بالجواب مع حفظ الملفات.

**الحد:** الفهرس ليس متن كتاب؛ لا Collections عامة أو Saved Search أو Compare شامل أو كل المواضع/الأنواع. لا بحث semantic/Luna مثبت.

نقاط: 4, 215, 216, 219, 221, 226, 230, 233, 234, 240, 264, 338, 339, 347, 491, 492, 543, 544, 545, 546, 549, 550, 553

- code: [apps/research_workspace/services.py — search](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/services.py#L237-L436)
- code: [apps/research_workspace/services.py — open_resource](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/services.py#L440-L498)
- code: [apps/research_workspace/services.py — add_citation](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/services.py#L502-L580)
- tests: [apps/research_workspace/tests.py — test_arabic_normalization_exact_location_and_index_not_book_text](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/tests.py#L92-L113)
- tests: [apps/research_workspace/tests.py — test_append_citation_preserves_saved_answer_audio_and_resets_approval](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/tests.py#L187-L217)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## citation-history

اختيارات من مصادر موجودة للمراجعة البشرية؛ تصحيح إحالة بإصدار جديد وتاريخ السبب والفاعل دون الكتابة الآلية للجواب.

**الحد:** D-068 سياقي أوسع من اقتراحات البحث الموجودة؛ لا نص قرآني/حديثي موثق مُورّد ولا كل طبعات/PDF/مواضع بصرية أو طباعة وتصدير مكتمل.

نقاط: 543, 544, 545, 550, 551, 552, 553, 555, 556

- code: [apps/case_citations/services.py — suggest_sources](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/case_citations/services.py#L431-L446)
- code: [apps/case_citations/services.py — save_cited_answer](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/case_citations/services.py#L249-L341)
- code: [apps/case_citations/services.py — read_citation_history](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/case_citations/services.py#L450-L525)
- tests: [apps/case_citations/research_tests.py — test_suggestions_are_existing_arabic_matches_and_never_write](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/case_citations/research_tests.py#L26-L37)
- tests: [apps/case_citations/research_tests.py — test_correction_records_previous_source_reason_actor_and_time](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/case_citations/research_tests.py#L39-L69)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281930) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v9-campaign.yml#L1-L116)

## rights

حقوق READ/CITE/RELATE/PREVIEW مستقلة، مربوطة بالمصدر والنسخة والقضية؛ تحقق بعد تجميع النتائج يمنع بقاء المنتهي.

**الحد:** إقرارات اصطناعية لا رخص حقيقية؛ لا دليل تغطية كل التصدير/التوصيل/المصادر المستقبلية. الإنشاء لا يمنح حق القراءة.

نقاط: 216, 334, 395, 554

- code: [apps/source_rights/services.py — projection_expiry_guard](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_rights/services.py#L40-L56)
- code: [apps/source_rights/services.py — permits_reference_for_locked_case](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_rights/services.py#L387-L391)
- tests: [apps/source_rights/test_strict.py — test_expiry_blocks_read_cite_relate_and_preview_with_valid_actor_and_preview_policy](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/source_rights/test_strict.py#L153-L183)
- tests: [tests/casework/test_v12_catalog_expiry.py — test_prior_item_expiry_during_later_projection](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_v12_catalog_expiry.py#L125-L134)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## private-files

أصل خاص خارج صفوف PG ببصمة وقفل ربط؛ فشل التخزين يحفظ الأصل وGC يحترم المراجع والمهلة.

**الحد:** filesystem معزول، لا مخزن سحابي إنتاجي أو ماسح malware؛ حدود الرفع لا تعني اكتمال فحص الأمان لكل صيغة.

نقاط: 25, 36, 78, 377, 378, 379, 380, 381, 382, 383, 384, 414, 424, 440, 451

- code: [apps/private_media/filesystem.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/private_media/filesystem.py#L1-L401)
- code: [apps/private_media/validation.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/private_media/validation.py#L1-L74)
- tests: [apps/private_media/filesystem_tests.py — test_durable_private_original_idempotent_and_legacy_resolver](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/private_media/filesystem_tests.py#L40-L54)
- tests: [apps/private_media/filesystem_tests.py — test_partial_write_and_fsync_failures_never_publish_partial_original](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/private_media/filesystem_tests.py#L115-L134)
- tests: [apps/private_media/filesystem_tests.py — test_gc_dry_run_grace_live_refs_corrupt_unknown_and_explicit_removal](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/private_media/filesystem_tests.py#L176-L199)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281930) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v9-campaign.yml#L1-L116)

## recovery

نسخ مشفر متزامن لقاعدة وأصول خاصة واستعادة إلى هدف معزول مع تحقق بصمات وروابط؛ منع plaintext في strict.

**الحد:** تجربة محدودة الحجم، لا PITR إنتاجي أو RPO/RTO معتمد أو KMS؛ backup ليس تصديرًا بحثيًا عامًا.

نقاط: 366, 414, 423, 424, 425, 428, 541

- code: [apps/platform_recovery/encrypted.py — snapshot](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/encrypted.py#L54-L97)
- code: [apps/platform_recovery/encrypted.py — restore](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/encrypted.py#L154-L169)
- tests: [apps/platform_recovery/v12_recovery_tests.py — test_01_plaintext_api_and_cli_are_closed_before_any_output_or_adapter_open](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/v12_recovery_tests.py#L162-L203)
- tests: [apps/platform_recovery/v12_recovery_tests.py — test_03_strict_encrypted_roundtrip_retains_originals_permissions_and_schema](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/v12_recovery_tests.py#L273-L298)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## maintenance

بوابة ACTIVE/DRAINING/FROZEN وتشغيل إدارة strict؛ منع writers المدعومين أثناء النسخ دون استئناف تلقائي.

**الحد:** حد تعاون التطبيق؛ ليس جدار صلاحيات PostgreSQL superuser أو OS ولا اعتماد تشغيل إنتاج.

نقاط: 410, 428, 541

- code: [apps/platform_recovery/admission.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/admission.py#L1-L94)
- code: [apps/platform_recovery/admin.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/admin.py#L1-L76)
- tests: [tests/casework/test_v12_administration.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_v12_administration.py#L1-L210)
- tests: [apps/platform_recovery/v12_maintenance_tests.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/platform_recovery/v12_maintenance_tests.py#L1-L328)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## identity

هوية موثوقة scoped للمفتي ورفض الأدوار المزورة/القضايا الأجنبية؛ access token قابل للإبطال؛ الأصل والقرار البشري مستقلان.

**الحد:** عدم وجود AI مفتي لا يثبت تنفيذ AI Gateway، ولا اختبار MFA تطويري سياسة هوية إنتاجية أو تفعيل إدارة U03.

نقاط: 62, 63, 84, 85, 101, 145, 146, 147, 148, 149, 150, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 402, 403, 404, 405, 406, 407, 408, 412, 415, 416, 507, 508, 510

- code: [apps/casework/services.py — _identity](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L153-L157)
- code: [apps/casework/services.py — _token_case](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L605-L626)
- code: [apps/casework_web/guard.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework_web/guard.py#L1-L139)
- tests: [tests/casework/test_core.py — test_organizer_and_foreign_case_cannot_read_or_author_ruling](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L201-L224)
- tests: [tests/casework/test_core.py — test_tokens_are_hashed_and_invalid_or_expired_tokens_denied](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L283-L295)
- tests: [tests/casework/test_http.py — test_shared_database_rate_budget_ignores_forwarded_addresses](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_http.py#L298-L308)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203282032) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v6-casework.yml#L1-L180)

## reference-import

فهرس 622 بإصدار ومصدر وصفحات وشجرة غير قابلة للطمس؛ preview وdry-run وتثبيت ذري محكوم بالبصمة.

**الحد:** مصدر كتاب واحد وليس taxonomy فتاوى عامة أو مركز استيراد لكل الصيغ؛ لا corpus حديث أو تصنيف مختصين معتمد.

نقاط: 159, 160, 164, 165, 332, 333, 334, 348, 349, 350, 351, 352, 353, 354, 355, 356

- code: [apps/reference/ingest.py — ingest_catalog](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/reference/ingest.py#L68-L128)
- tests: [tests/reference/test_catalog.py — test_commit_requires_exact_preview_and_changed_input_is_rejected](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/reference/test_catalog.py#L53-L62)
- tests: [tests/reference/test_catalog.py — test_insertion_is_atomic_even_after_a_partial_batch](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/reference/test_catalog.py#L64-L79)

STATIC_ONLY; exact test execution not established here

## search-baseline

بحث تحريري وتطبيع ومرادفات محدودة ومؤشرات تطابق؛ تقييم اصطناعي مستقل عن قبول متخصصين.

**الحد:** قراءة كود/اختبارات فقط لهذا الرابط؛ لم يثبت هنا تنفيذ كل مسار داخل run محدد. لا strict phrase/semantic/fuzzy شامل أو gold benchmark معتمد.

نقاط: 35, 192, 217, 218, 219, 220, 221, 222, 223, 229, 231, 232, 242, 245, 246, 449

- code: [apps/editorial_search/services.py — search_catalog](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/editorial_search/services.py#L229-L297)
- code: [apps/editorial_search/query_terms.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/editorial_search/query_terms.py#L1-L27)
- tests: [tests/editorial_search/test_scope.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/editorial_search/test_scope.py#L1-L233)

STATIC_ONLY; exact test execution not established here

## seo

Canonical وOpenGraph من أصل HTTPS مضبوط، private/search noindex؛ صفحات اصطناعية.

**الحد:** لا نطاق إنتاج configured أو إثبات كل SEO/sitemap/structured data؛ علاقة الاختبار بالتشغيل لم تُحسم في هذا المسار.

نقاط: 456, 457, 458

- code: [apps/public_site/views.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/public_site/views.py#L1-L265)
- tests: [tests/public_site/test_share_metadata.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/public_site/test_share_metadata.py#L1-L132)

STATIC_ONLY; exact test execution not established here

## transcript

تفريغ مشتق وربط بالقضية دون استبدال الأصل؛ المراجع العلمية تبقى تحت مراجعة بشرية.

**الحد:** لا مزود تفريغ صوتي حقيقي أو جودة transcription مثبتة؛ صلاحيات المنظم معلقة. شاهد تشغيلي عبر واجهة البحث في التفريغ فقط.

نقاط: 79, 80, 97, 273, 362, 418, 432, 441

- code: [apps/research_workspace/services.py — _transcript](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/services.py#L148-L172)
- tests: [apps/research_workspace/tests.py — test_actual_transcript_exact_text_and_independent_permission](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/research_workspace/tests.py#L135-L153)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203281971) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/infra/dev/v12_verify.py#L1-L86)

## core-without-ai

رحلة السؤال والجواب والمراجعة تعمل دون اتصال AI؛ اختبارات core تمنع اتصال الشبكة.

**الحد:** عدم الحاجة إلى AI لا يثبت fault injection لكل خدمة اختيارية أو تشغيلًا إنتاجيًا.

نقاط: 214, 429, 430

- code: [apps/casework/services.py — intake_case](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L357-L425)
- code: [apps/casework/services.py — save_answer](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/services.py#L474-L507)
- tests: [tests/casework/test_adversarial.py — test_core_journey_performs_no_python_network_connections](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_adversarial.py#L347-L371)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203282032) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v6-casework.yml#L1-L180)

## architecture

شجرة Django modular وخدمات PG وflags مغلقة؛ 22 نتيجة workflow ناجحة عند P0.

**الحد:** قراءة بنية ونجاح CI إجمالي لا يثبت اكتمال المنتج أو CD أو الاستقلال عن كل نظام خارجي أثناء التشغيل.

نقاط: 6, 8, 446, 448, 454, 455

- code: [config/settings/campaign_strict.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/config/settings/campaign_strict.py#L1-L13)
- code: [apps/casework/models.py — file](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/apps/casework/models.py#L1-L236)
- tests: [tests/casework/test_core.py — test_synthetic_ack_is_required_before_db_reads_or_writes](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/tests/casework/test_core.py#L379-L382)

REMOTE_WORKFLOW_AND_JOB_SUCCESS; test-selector linkage inspected; no per-assertion log imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44203282032) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/5aff9ba3cce35241b3ded27ed3428e0d4ecad768/.github/workflows/v6-casework.yml#L1-L180)

## p1-case-journey

تجميع الأصل والملفات والتعقيبات بحسب Evidence Version مع أساس الأجوبة في إطار القضية؛ تنقل أصلي إلى الخدمات دون إنشاء سجل مواز أو تنفيذ اعتماد ضمن التنقل.

**الحد:** عينة قضية اصطناعية، ليست كل قوائم التعيين أو كل الأجهزة؛ لا تسجيل ميكروفون أو تفعيل U03 أو تغيير سياسة موافقة.

نقاط: 29, 30, 38, 43, 44, 45, 46, 48, 49, 50, 51, 52, 53, 54, 487, 488, 489, 490, 533

- code: [apps/mufti_workspace/journey.py — evidence_history](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey.py#L4-L22)
- code: [apps/mufti_workspace/journey.py — connected_actions](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey.py#L25-L85)
- code: [apps/mufti_workspace/context.py — case_workspace](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/context.py#L142-L247)
- tests: [apps/mufti_workspace/journey_tests.py — test_evidence_history_groups_original_files_and_answer_basis_without_new_records](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey_tests.py#L44-L65)
- tests: [apps/mufti_workspace/journey_tests.py — test_actual_image_pdf_audio_previews_require_current_scope](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey_tests.py#L67-L86)
- tests: [apps/mufti_workspace/journey_tests.py — test_navigation_is_same_case_read_only_and_waiting_has_no_edit_shortcut](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey_tests.py#L177-L203)

EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/infra/dev/v12_p1_verify.py#L1-L64)

## p1-multipart-edit

فتح المحرر المركب من القضية وحفظ تعديل نصي بنموذج native ذي ملف اختياري فارغ مع بقاء الملفات والبصمات والجواب السابق؛ إصدار جديد غير معتمد، ورفض stale/CSRF/حقول ملف مزورة.

**الحد:** لا تسجيل صوت مباشر أو تحرير كل أنواع الوسائط؛ الإتاحة والاعتماد مستقلان، ونجاح إعادة التحرير لا يثبت كامل نطاق Composer.

نقاط: 69, 75, 76, 78, 81, 82, 83, 86, 87, 490, 533

- code: [apps/answer_media/views.py — _multipart](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/answer_media/views.py#L55-L83)
- code: [apps/answer_media/services.py — save_multipart_answer](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/answer_media/services.py#L158-L289)
- code: [apps/mufti_workspace/journey.py — connected_actions](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/mufti_workspace/journey.py#L25-L85)
- tests: [tests/casework/test_v12_answer_edit.py — test_returned_multipart_edit_without_new_file_preserves_originals_and_history](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_answer_edit.py#L35-L60)
- tests: [tests/casework/test_v12_answer_edit.py — test_unknown_duplicate_nonempty_and_mixed_file_fields_never_save](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_answer_edit.py#L62-L72)
- tests: [tests/casework/test_v12_answer_edit.py — test_empty_upload_edit_still_requires_csrf_and_current_scope](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_answer_edit.py#L74-L79)

EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/infra/dev/v12_p1_verify.py#L1-L64)

## p1-rights-inspector

فحص مرجع/طبعة/موضع وبصمات النسخ، مقارنة قرار حقوق بسابقه مع فصل التاريخ عن الحق الحالي؛ استعمالات READ/CITE/RELATE/PREVIEW منفصلة وFULL_TEXT/QUOTE/PUBLISH غير مدعومة ومرفوضة.

**الحد:** فحص VIEW ليس حق فتح أو اقتباس أو نشر الأصل؛ 622 فهرس فقط. لا رخص حقيقية أو مصدر قرآن/حديث مستحدث، ولا استكمال كامل البند 554 في التصدير وكل القنوات.

نقاط: 216, 334, 395, 543, 544, 545, 546, 551, 552, 554, 556

- code: [apps/source_rights/registry.py — inspect_source](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/registry.py#L163-L245)
- code: [apps/source_rights/registry.py — usage_matrix](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/registry.py#L84-L114)
- code: [apps/source_rights/registry.py — material](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/registry.py#L37-L81)
- tests: [apps/source_rights/v12_tests.py — test_toc_identity_is_exact_and_cannot_imply_text_quote_or_publication](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/v12_tests.py#L25-L51)
- tests: [apps/source_rights/v12_tests.py — test_revision_comparison_preserves_predecessor_and_never_revives_old_grant](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/v12_tests.py#L53-L74)
- tests: [apps/source_rights/v12_tests.py — test_private_transcript_has_text_identity_but_never_exposes_text_or_public_uses](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/v12_tests.py#L76-L89)
- tests: [apps/source_rights/v12_tests.py — test_identity_revocation_during_projection_denies_the_inspector](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/source_rights/v12_tests.py#L175-L186)

EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/infra/dev/v12_p1_verify.py#L1-L64)

## p1-library-roundtrip

بحث المكتبة scoped في نص التحرير وبيانات المصدر والطبعة والموضع؛ مجموعة ذات حقوق حالية واحدة للنتائج والفئات والعدد والصفحات، وعودة native تحفظ المرشحات والقضية بعد إعادة تفويضها.

**الحد:** مكتبة تجريبية لا نشر إنتاجي؛ لا بحث semantic أو شبكة معرفة كاملة. سياق العودة لا يمنح صلاحية، وانتهاء الحق أثناء التصفية يغلق الاستجابة.

نقاط: 4, 216, 219, 221, 223, 228, 230, 240, 264, 274, 275, 276, 329, 335, 343, 347, 491, 492, 536, 539, 543, 554

- code: [apps/experimental_publication/services.py — library_catalog](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/experimental_publication/services.py#L451-L457)
- code: [apps/experimental_publication/services.py — _library](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/experimental_publication/services.py#L460-L546)
- code: [apps/knowledge_links/views.py — file](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/knowledge_links/views.py#L1-L132)
- code: [apps/experimental_publication/views.py — file](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/experimental_publication/views.py#L1-L240)
- tests: [tests/casework/test_v12_library_navigation.py — test_source_metadata_search_and_collection_facets_use_current_rights](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_library_navigation.py#L40-L49)
- tests: [tests/casework/test_v12_library_navigation.py — test_one_catalog_call_and_native_material_roundtrip_keep_filters](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_library_navigation.py#L61-L86)
- tests: [tests/casework/test_v12_library_navigation.py — test_return_context_is_not_authority_and_rechecks_revoked_source](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_library_navigation.py#L88-L106)
- tests: [tests/casework/test_v12_library_navigation.py — test_clock_expiry_during_catalog_filtering_never_keeps_counts_or_facets](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_library_navigation.py#L108-L129)

EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/infra/dev/v12_p1_verify.py#L1-L64)

## p1-browser-restored

رحلة Chrome sandbox على PG17.12/18.7 من مراجعة الأصل والتوضيح والملفات إلى البحث/الحقوق/جواب text-PDF-WAV وموافقة وإتاحة مستقلة، وتسليم محاكى جزئي؛ ثم نسخ مشفر واستعادة لخادم PG ثان وعملية HTTP مستقلة تتحقق من الهدف والأصول والصلاحيات وسحبها.

**الحد:** قضية واحدة ببيانات اصطناعية. DELIVERED/FAILED_REQUIRES_REVIEW/SENT_UNCONFIRMED لا تعني تسليمًا كاملًا أو قراءة. لا إرسال خارجي أو U03 أو PITR/KMS إنتاجي أو قبول رسمي. لا ننقل عدد HTTP المحلي إلى CI دون قراءة artifact.

نقاط: 25, 29, 30, 36, 37, 38, 39, 40, 51, 54, 75, 76, 129, 130, 145, 148, 149, 150, 151, 152, 249, 251, 254, 366, 383, 414, 423, 424, 425, 428, 434, 440, 442, 501, 503, 504, 532, 533, 535, 536, 541, 542, 554

- code: [apps/platform_recovery/encrypted.py — snapshot](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/platform_recovery/encrypted.py#L54-L97)
- code: [apps/platform_recovery/encrypted.py — restore](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/platform_recovery/encrypted.py#L154-L169)
- code: [apps/composite_delivery/services.py — composite_status](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/composite_delivery/services.py#L333-L385)
- code: [apps/requester_portal/services.py — snapshot](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/apps/requester_portal/services.py#L49-L171)
- code: [tests/casework/v12_restored_browser.py — TargetProofMiddleware](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/v12_restored_browser.py#L43-L59)
- code: [tests/casework/v12_restored_browser.py — restore_and_verify](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/v12_restored_browser.py#L327-L403)
- tests: [tests/casework/test_v12_browser.py — test_one_v12_case_partial_delivery_encrypted_restore_and_target_http](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/tests/casework/test_v12_browser.py#L284-L501)

EXACT_HEAD_JOB_LOG_TEST_PASS_BOTH_MAJORS; source/test assertions inspected; artifact JSON not imported
[تشغيل SHA المثبت](https://github.com/sami77337/fatwa-platform/actions/runs/44208238581) · [محدد التشغيل](https://github.com/sami77337/fatwa-platform/blob/0055a5ab05c6dbe6d41a528666666f9db07f2fee/infra/dev/v12_p1_verify.py#L1-L64)
