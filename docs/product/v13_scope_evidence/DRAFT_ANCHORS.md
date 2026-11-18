# V13 static code anchors — execution pending

Read SHA: `be40a352e17f9a03d1f2d2c1c52182f6116c13fb`. **STATIC_CODE_REVIEW_ONLY; PENDING execution.**

These exact code/test symbols were read and resolved at this SHA. Their existence is
not an executed PASS, independent security review or credited scope point. All original
556 classifications and prior evidence remain unchanged. Final execution evidence must
name its own actual SHA and both PostgreSQL majors plus protected Chrome.

Source-byte attribution remains in [SOURCE_BYTES.md](SOURCE_BYTES.md): parent-local
attestation, not original XLSX byte verification in this Cloud environment.

## browser-audio

Explicit synthetic microphone start/stop/listen/cancel; accepted WAV enters existing private evidence or answer-part persistence. Atomic initial intake preserves one case and idempotency.

Candidate points retain original SPEC links; none is credited here:

- 25: الصور، الملفات، الصوتيات والفيديوهات تحفظ كأصول مستقلة مرتبطة بالقضية. — SPEC: SPEC-U01-004, SPEC-U11-006, SPEC-U11-009, SPEC-U03-007, SPEC-U03-034, SPEC-U08-006, SPEC-U08-009, SPEC-U11-007, SPEC-U16-010
- 36: التسجيل أو الصورة أو الملف الأصلي يبقى هو الأصل المرجعي. — SPEC: SPEC-U11-009, SPEC-U03-008, SPEC-U06-012
- 44: كل إضافة تغير الوقائع التي يعتمد عليها الشيخ ترفع Evidence Version. — SPEC: SPEC-U01-012, SPEC-U07-016, SPEC-U08-015
- 46: لا يسمح النظام باعتماد جواب مبني على Evidence قديمة دون أن يقر الشيخ بأنه رأى التحديث الجديد. — SPEC: SPEC-U01-013, SPEC-U02-010, SPEC-U07-016, SPEC-U08-015
- 70: يمكنه تسجيل جواب صوتي مباشرة من الواجهة. — SPEC: SPEC-U02-013, SPEC-U01-016
- 75: يمكن للجواب الواحد أن يحتوي عدة أجزاء بترتيب محدد. — SPEC: SPEC-U02-012, SPEC-U01-016, SPEC-U07-006, SPEC-U08-017, SPEC-U16-010
- 77: يستطيع الشيخ بدء التسجيل وإيقافه واستكماله والاستماع إليه قبل الاعتماد. — SPEC: SPEC-U02-013, SPEC-U08-017, SPEC-U16-010
- 78: التسجيل الأصلي للشيخ يبقى محفوظًا ولا يُستبدل بالتفريغ. — SPEC: SPEC-U02-014, SPEC-U07-008, SPEC-U08-017, SPEC-U16-010
- 80: التفريغ ليس إجباريًا لكل تسجيل. — SPEC: SPEC-U11-013, SPEC-U07-008, SPEC-U07-026, SPEC-U08-017, SPEC-U11-005, SPEC-U11-014, SPEC-U11-022, SPEC-U16-010
- 81: يمكن للشيخ حفظ الجواب كمسودة. — SPEC: SPEC-U01-017, SPEC-U02-015
- 82: Saved لا تعني Approved. — SPEC: SPEC-U02-016, SPEC-U05-011, SPEC-U11-016, SPEC-U15-003
- 432: إذا تعطلت خدمة Transcription يبقى التسجيل الأصلي. — SPEC: SPEC-U15-013, SPEC-U11-025, SPEC-U15-001
- 533: الشيخ يرى كل القضايا في Mufti Workspace واحدة ويجيب منها بالنص أو الصوت أو الوسائط. — SPEC: SPEC-U02-001, SPEC-U02-011, SPEC-U02-013, SPEC-U16-002, SPEC-U16-027, SPEC-U16-028

### code

- [apps/browser_audio/static/browser_audio/capture.js](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/browser_audio/static/browser_audio/capture.js#L1-L136)
- [apps/browser_audio/static/browser_audio/worklet.js](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/browser_audio/static/browser_audio/worklet.js#L1-L25)
- [apps/browser_audio/context.py#capture](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/browser_audio/context.py#L8-L12)
- [apps/casework_web/requester_intake.py#submit_intake](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/casework_web/requester_intake.py#L80-L119)

### positive_tests

- [tests/casework/test_v13_audio_wiring.py#InitialAudioTests.test_one_native_case_private_original_and_exact_replay_no_second_upload](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_audio_wiring.py#L77-L107)
- [tests/casework/test_v13_audio_wiring.py#InitialAudioTests.test_existing_requester_and_mufti_forms_render_scoped_recorders](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_audio_wiring.py#L109-L126)

### negative_tests

- [tests/casework/test_v13_audio_wiring.py#InitialAudioTests.test_disk_failure_rolls_back_case_source_evidence_and_retry_succeeds](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_audio_wiring.py#L135-L141)
- [tests/casework/test_v13_audio_wiring.py#InitialAudioTests.test_invalid_consent_proof_csrf_or_content_never_creates_case](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_audio_wiring.py#L143-L148)
- [tests/casework/test_v13_audio_wiring.py#RecorderPolicyTests.test_only_trusted_html_recorder_receives_permission_not_bytes_or_escaped_text](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_audio_wiring.py#L172-L185)

### browser_candidates

- [apps/browser_audio/test_browser.py#BrowserAudioTests.test_capture_native_private_attachment_and_answer_revision](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/browser_audio/test_browser.py#L242-L337)
- [apps/browser_audio/test_browser.py#BrowserAudioTests.test_permission_denial_cancel_late_grant_limits_and_cleanup](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/browser_audio/test_browser.py#L339-L404)

### Remaining limits

- Capture is PCM16LE mono 8000Hz, at most 10 seconds/160044 bytes; no resume or cross-device compatibility claim for point77.
- Original means retained browser-generated WAV, not physical microphone signal without conversion.
- No ASR/transcription service exists here; point432 transcription-outage handling cannot be credited from recording alone.
- Point533 is scoped MUFTI case access; this does not prove every case is visible or authorize U03.

## timed-citations

Human-confirmed bounded locator pins private attachment/answer media owner, immutable version/hash/parser metadata and measured duration; canonical approval and downstream uses recheck current rights.

Candidate points retain original SPEC links; none is credited here:

- 179: يمكن تحديد Timestamp داخل الدرس أو التسجيل. — SPEC: SPEC-U04-016, SPEC-U11-028, SPEC-U09-016, SPEC-U11-004, SPEC-U11-021, SPEC-U11-023
- 346: رابط مباشر إلى Timestamp في صوت أو فيديو. — SPEC: SPEC-U06-014, SPEC-U06-016, SPEC-U06-017, SPEC-U05-014, SPEC-U12-009
- 543: يوجد نظام استدلال وإحالات دقيقة يمكّن الشيخ أو الباحث من ربط عبارة في الفتوى أو مادة علمية بأصل محدد وموضع معين قابل للفتح مباشرة، لا بمجرد عنوان كتاب أو نتيجة بحث عامة. — SPEC: SPEC-U06-001, SPEC-U02-023, SPEC-U02-028, SPEC-U04-017, SPEC-U05-028, SPEC-U10-012, SPEC-U16-002, SPEC-U16-023
- 544: يستطيع الشيخ تحديد عبارة في جوابه أو إضافة بطاقة مصدر مستقلة، ثم اختيار المصدر والنسخة والموضع ومعاينة ما سيفتحه الرابط قبل تثبيت الإحالة، دون فقد مسودة جوابه. — SPEC: SPEC-U06-006, SPEC-U06-008, SPEC-U02-023, SPEC-U02-029, SPEC-U05-020, SPEC-U10-012, SPEC-U16-002, SPEC-U16-023
- 549: يمكن توجيه الإحالة إلى درس أو تسجيل صوتي أو فيديو بموضع زمني محدد، كدقيقة وثانية أو بداية ونهاية مقطع، ويرتبط التوقيت بنسخة التسجيل نفسها ولا ينتقل تلقائيًا إلى نسخة أخرى. — SPEC: SPEC-U06-016, SPEC-U02-027, SPEC-U04-017, SPEC-U11-021, SPEC-U16-002, SPEC-U16-010, SPEC-U16-023
- 551: تستند الإحالة إلى معرف ثابت للمصدر ونسخته وموضعه، لا إلى ترتيب مؤقت في نتائج البحث أو وصف غامض مثل «الكتاب الثاني»؛ وعند الغموض يُطلب تحديد المقصود بدل تخمينه. — SPEC: SPEC-U06-007, SPEC-U16-002, SPEC-U16-023
- 552: إذا أضيفت طبعة أو ملف أو تسجيل جديد فلا تنتقل الإحالة القديمة إليه بصمت؛ تظل مرتبطة بالنسخة التي اختارها صاحب الاستدلال مع حفظ التوثيق وتاريخ التصحيحات. — SPEC: SPEC-U06-022, SPEC-U06-026, SPEC-U16-002, SPEC-U16-023
- 553: إذا تعذر فتح الفقرة أو الموضع الدقيق تقنيًا، يُفتح أقرب موضع موثق مع بيان حدود الدقة، ولا يُختلق رقم صفحة أو رابط أو مقتطف غير متحقق؛ ويمكن الاحتفاظ بمرجع وصفي عندما لا تتوفر نسخة رقمية. — SPEC: SPEC-U06-004, SPEC-U06-018, SPEC-U06-028, SPEC-U04-017, SPEC-U10-012, SPEC-U16-002, SPEC-U16-023
- 554: تخضع الإحالات لحقوق المصدر وصلاحيات الوصول وقت الإنشاء والفتح والتوصيل والنشر والتصدير؛ لا يكشف الربط بمصدر داخلي محتواه أو ملفاته لجمهور غير مخوّل، ولا يحوّل القضية الخاصة إلى مادة عامة. — SPEC: SPEC-U06-019, SPEC-U06-020, SPEC-U06-021, SPEC-U06-027, SPEC-U02-030, SPEC-U03-035, SPEC-U04-022, SPEC-U07-006, SPEC-U08-018, SPEC-U12-010, SPEC-U12-021, SPEC-U16-002, SPEC-U16-023
- 555: تبقى الإحالة والاقتباس والنص الأصلي للشيخ ومخرجات البحث الذكي طبقات متميزة؛ يمكن لـLuna اقتراح مواضع محتملة موثقة للمراجعة، لكنها لا تثبّت دليلًا في جواب الشيخ ولا تختار وجه الاستدلال أو تتولى اعتماده. — SPEC: SPEC-U06-009, SPEC-U06-024, SPEC-U06-025, SPEC-U04-018, SPEC-U12-006, SPEC-U16-002, SPEC-U16-023
- 556: يسجل النظام من أضاف الإحالة وراجعها وصححها وموضعها وإصدارها؛ ويظهر في الطباعة والتصدير مرجع مقروء يتضمن المصدر والنسخة والموضع المتاح، ولا يسمح التصحيح التقني بتبديل الحجة أو المصدر المقصود دون مراجعة الشيخ. — SPEC: SPEC-U06-023, SPEC-U06-026, SPEC-U06-027, SPEC-U03-035, SPEC-U16-002, SPEC-U16-023

### code

- [apps/timed_citations/services.py#propose](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/services.py#L200-L280)
- [apps/timed_citations/services.py#act](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/services.py#L284-L317)
- [apps/timed_citations/services.py#open_audio](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/services.py#L321-L355)
- [apps/timed_citations/services.py#for_locked_answer](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/services.py#L359-L389)
- [apps/casework/services.py#_answer_timed](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/casework/services.py#L80-L141)
- [apps/casework/services.py#_answer_use_boundary](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/casework/services.py#L145-L156)
- [apps/experimental_publication/services.py#_require_publication_sources](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/experimental_publication/services.py#L105-L130)

### positive_tests

- [apps/timed_citations/tests.py#TimedTests.test_exact_duration_human_confirmation_and_original_bytes](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/tests.py#L138-L160)
- [apps/timed_citations/tests.py#TimedTests.test_correction_is_append_only_and_previous_revision_cannot_open](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/tests.py#L205-L234)
- [tests/casework/test_v13_timed_bindings.py#TimedBindingsTests.test_confirmed_attachment_and_answer_media_allow_real_approval_and_private_bytes](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_timed_bindings.py#L149-L157)

### negative_tests

- [apps/timed_citations/tests.py#TimedTests.test_invalid_times_and_forged_duration_version_digest_are_denied](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/tests.py#L162-L184)
- [apps/timed_citations/tests.py#TimedTests.test_old_answer_does_not_inherit_citation_and_exact_old_recording_never_redirects](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/tests.py#L186-L203)
- [tests/casework/test_v13_timed_bindings.py#TimedBindingsTests.test_approved_then_expired_blocks_private_release_files_delivery_and_publication](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_timed_bindings.py#L179-L215)
- [tests/casework/test_v13_timed_bindings.py#TimedBindingsTests.test_collection_rechecks_timed_expiry_after_later_legacy_result_projection](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_timed_bindings.py#L269-L311)

### browser_candidates

- [apps/timed_citations/browser_tests.py#TimedBrowserTests.test_native_audio_locator_and_withdrawal](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/timed_citations/browser_tests.py#L15-L91)

### Remaining limits

- Private audio only: no lesson/video corpus support is established by this slice; points179/346/549 remain broader.
- Time fragment is navigation in the authorized original, not byte clipping, HTTP Range or interval-only authorization.
- No new public/requester timed-citation projection, print/export or automatic source-version migration.
- Point553 nearest documented fallback is not proved by an exact private audio locator.

## measured-arabic-search

Explicit digit/word title ranking within the first20 authorized reference metadata candidates; original title/location and open/return binding preserved; synthetic baseline/after metrics and review status displayed.

Candidate points retain original SPEC links; none is credited here:

- 215: البحث من أهم مكونات المشروع. — SPEC: SPEC-U05-001, SPEC-U05-027, SPEC-U05-002, SPEC-U05-018, SPEC-U05-028, SPEC-U09-008
- 216: يبدأ Authorization أولًا قبل Retrieval؛ لا يجب أن يبحث المستخدم في بيانات لا يحق له رؤيتها. — SPEC: SPEC-U05-003, SPEC-U04-022, SPEC-U05-026, SPEC-U05-028, SPEC-U11-022, SPEC-U12-010, SPEC-U14-025, SPEC-U16-024
- 219: يدعم Full-Text Arabic Search. — SPEC: SPEC-U05-006, SPEC-U05-007, SPEC-U05-027, SPEC-U05-028, SPEC-U10-003
- 221: يدعم Arabic Normalization مشتقة دون تغيير الأصل. — SPEC: SPEC-U05-007, SPEC-U05-028
- 231: النظام يوضح سبب ظهورها. — SPEC: SPEC-U05-013, SPEC-U05-028
- 242: لا نقيس البحث بالانطباع فقط. — SPEC: SPEC-U05-027, SPEC-U15-009, SPEC-U16-023
- 245: نقيس Recall وPrecision وجودة Ranking وCoverage. — SPEC: SPEC-U05-027, SPEC-U15-009, SPEC-U16-023
- 246: تغييرات كبيرة في Ranking أو Embeddings أو Normalization تمر باختبارات Regression. — SPEC: SPEC-U05-027, SPEC-U15-009, SPEC-U16-023

### code

- [apps/arabic_search_eval/ranking.py#rank_titles](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/ranking.py#L45-L78)
- [apps/arabic_search_eval/services.py#search_reference_titles](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/services.py#L17-L86)
- [apps/arabic_search_eval/evaluation.py#evaluate](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/evaluation.py#L72-L142)
- [apps/research_workspace/views.py#_search](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/research_workspace/views.py#L49-L60)

### positive_tests

- [apps/arabic_search_eval/test_services.py#AdapterTests.test_real_baseline_vs_digit_and_boundary_ranking_preserves_source_and_open_pins](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/test_services.py#L85-L114)
- [apps/arabic_search_eval/test_ranking.py#RankingTests.test_explicit_fixture_expectations_and_negative_queries](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/test_ranking.py#L11-L23)
- [tests/casework/test_v13_search_ui.py#SearchUiTests.test_ranked_search_open_back_preserves_scope_filters_and_canonical_answer](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_search_ui.py#L55-L72)

### negative_tests

- [apps/arabic_search_eval/test_services.py#AdapterTests.test_rights_expiry_during_rank_closes_response_even_if_no_hits_selected](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/test_services.py#L154-L171)
- [apps/arabic_search_eval/test_ranking.py#RankingTests.test_pending_stale_incomplete_and_altered_review_are_not_approval](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/arabic_search_eval/test_ranking.py#L68-L86)
- [tests/casework/test_v13_search_ui.py#SearchUiTests.test_flag_strict_kind_and_revoked_source_do_not_fallback](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_search_ui.py#L74-L88)

### browser_candidates

Pending integrated anchor; no execution claim.

### Remaining limits

- No full-text/whole-corpus/semantic retrieval; point219 full text is not established.
- 42 authored synthetic judgements over28 metadata titles are AUTHOR_PROPOSED_REVIEW_PENDING; no held-out real Arabic gold or specialist review for243/244.
- No latency improvement or production SLO is claimed; inherited rights checks dominate observed adapter cost.
- Protected integrated search browser test has not been supplied at this read SHA.

## human-classification

Private experimental label proposal with pinned independently approved reference relation, separate human review/withdrawal and append-only history, without changing canonical case Evidence or publication category.

Candidate points retain original SPEC links; none is credited here:

- 47: تعديل Metadata مثل Tag أو تصنيف لا يرفع Evidence Version لأنه لا يغير وقائع السؤال. — SPEC: SPEC-U01-014, SPEC-U04-021
- 161: الفتوى يمكن أن تنتمي لأكثر من باب. — SPEC: SPEC-U04-004, SPEC-U04-023, SPEC-U04-024
- 162: يمكن تحديد Primary Category وتصنيفات إضافية. — SPEC: SPEC-U04-004, SPEC-U04-023, SPEC-U04-024
- 163: Luna لا تخترع أبوابًا جديدة من تلقاء نفسها. — SPEC: SPEC-U04-010, SPEC-U04-012, SPEC-U03-014, SPEC-U04-023, SPEC-U04-024, SPEC-U12-014
- 164: كل Category لها ID ثابت مستقل عن اسمها الظاهر. — SPEC: SPEC-U04-013, SPEC-U04-014, SPEC-U04-023, SPEC-U04-024
- 169: الإنسان يستطيع قبولها أو رفضها أو تعديلها. — SPEC: SPEC-U04-011, SPEC-U03-013, SPEC-U04-023, SPEC-U04-024
- 170: Luna لا تنشئ Tag جديدًا مباشرة في النظام الرسمي. — SPEC: SPEC-U04-007, SPEC-U03-014, SPEC-U04-023, SPEC-U04-024
- 417: تغيير التصنيف مسجل. — SPEC: SPEC-U04-011, SPEC-U04-013, SPEC-U03-043, SPEC-U15-016

### code

- [apps/classification_review/services.py#propose](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/services.py#L122-L167)
- [apps/classification_review/services.py#act](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/services.py#L171-L212)
- [apps/classification_review/services.py#desk](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/services.py#L216-L300)

### positive_tests

- [apps/classification_review/tests.py#ClassificationTests.test_proposed_until_independent_human_no_canonical_mutation](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/tests.py#L77-L95)
- [apps/classification_review/tests.py#ClassificationTests.test_reject_correction_and_withdrawal_never_reapprove](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/tests.py#L127-L143)
- [tests/casework/test_v13_classification_wiring.py#ClassificationWiringTests.test_native_navigation_scope_and_independent_pending_state](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_classification_wiring.py#L65-L82)

### negative_tests

- [apps/classification_review/tests.py#ClassificationTests.test_database_append_only_self_review_and_exclusive_decision](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/tests.py#L217-L248)
- [apps/classification_review/tests.py#ClassificationTests.test_real_rights_expiry_revocation_and_redacted_history](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/tests.py#L349-L399)
- [tests/casework/test_v13_classification_wiring.py#ClassificationWiringTests.test_freeze_blocks_shared_http_and_service_without_insert](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/tests/casework/test_v13_classification_wiring.py#L84-L91)

### browser_candidates

- [apps/classification_review/browser_tests.py#ClassificationBrowserTests.test_native_propose_independent_review_withdraw_rtl](https://github.com/sami77337/fatwa-platform/blob/be40a352e17f9a03d1f2d2c1c52182f6116c13fb/apps/classification_review/browser_tests.py#L21-L127)

### Remaining limits

- No formal taxonomy registry, taxonomy version mapping or primary/additional category assignment: do not credit161/162/164 from a review ledger.
- Point169 refers to Tags in its original section; generic experimental label review is related partial evidence only, not a complete Tag system.
- No AI classifier is present. Absence of AI writes is not a tested AI suggestion/review implementation for163/170.
- 622 is a book TOC only; no inferred scientific relationship or general taxonomy; nothing private projects to public library.

## connected-recovery

Pending final single-case integrated browser journey and encrypted backup/restored-target HTTP, bytes and revocation checks.

Candidate points retain original SPEC links; none is credited here:

- 30: تشمل القضية: السؤال، المرفقات، التعقيبات، أجوبة الشيخ، حالة القضية، الشيخ أو الشيوخ المرتبطين بها، التصنيفات، الدروس، العلاقات، Delivery، Publication، وسجل التدقيق. — SPEC: SPEC-U01-010, SPEC-U14-012, SPEC-U04-002, SPEC-U07-003, SPEC-U01-030
- 43: للقضية مفهوم مستقل اسمه Evidence Version. — SPEC: SPEC-U01-012, SPEC-U07-016
- 44: كل إضافة تغير الوقائع التي يعتمد عليها الشيخ ترفع Evidence Version. — SPEC: SPEC-U01-012, SPEC-U07-016, SPEC-U08-015
- 46: لا يسمح النظام باعتماد جواب مبني على Evidence قديمة دون أن يقر الشيخ بأنه رأى التحديث الجديد. — SPEC: SPEC-U01-013, SPEC-U02-010, SPEC-U07-016, SPEC-U08-015
- 75: يمكن للجواب الواحد أن يحتوي عدة أجزاء بترتيب محدد. — SPEC: SPEC-U02-012, SPEC-U01-016, SPEC-U07-006, SPEC-U08-017, SPEC-U16-010
- 76: كل الأجزاء تعتبر Logical Reply واحدة مع الحفاظ على ترتيبها. — SPEC: SPEC-U02-012, SPEC-U01-016, SPEC-U07-006, SPEC-U07-008, SPEC-U08-017, SPEC-U16-010
- 82: Saved لا تعني Approved. — SPEC: SPEC-U02-016, SPEC-U05-011, SPEC-U11-016, SPEC-U15-003
- 406: Sessions قابلة للإلغاء. — SPEC: SPEC-U14-014, SPEC-U14-028, SPEC-U15-024, SPEC-U16-024
- 408: السياسة Default Deny. — SPEC: SPEC-U14-011, SPEC-U13-024, SPEC-U14-026, SPEC-U14-028, SPEC-U16-024
- 412: Rate Limiting موجود. — SPEC: SPEC-U08-027, SPEC-U14-028, SPEC-U16-024
- 414: تخزين البيانات الحساسة يطبق الحماية المناسبة. — SPEC: SPEC-U14-018, SPEC-U14-028, SPEC-U16-024
- 415: العمليات المهمة تسجل: من، ماذا، متى. — SPEC: SPEC-U14-019, SPEC-U03-043, SPEC-U15-016
- 419: النشر وإلغاء النشر مسجل. — SPEC: SPEC-U14-019, SPEC-U03-043, SPEC-U15-016
- 423: PostgreSQL له Backup/PITR بحسب إعدادات الإنتاج النهائية. — SPEC: SPEC-U15-020, SPEC-U13-002, SPEC-U15-001, SPEC-U15-021
- 424: Object Storage له Versioning/Backup مناسب. — SPEC: SPEC-U15-020, SPEC-U13-002, SPEC-U15-001, SPEC-U15-021
- 425: توجد Restore Drills. — SPEC: SPEC-U15-023, SPEC-U13-002, SPEC-U15-001, SPEC-U15-021, SPEC-U15-024, SPEC-U16-025
- 428: توجد Runbooks للأعطال. — SPEC: SPEC-U15-017, SPEC-U15-001
- 434: Fatwa Case هي مركز النموذج. — SPEC: SPEC-U01-005, SPEC-U01-010
- 435: Messages وMessage Parts مرتبة. — SPEC: SPEC-U01-004, SPEC-U02-012

### code

Pending integrated anchor; no execution claim.

### positive_tests

Pending integrated anchor; no execution claim.

### negative_tests

Pending integrated anchor; no execution claim.

### browser_candidates

Pending integrated anchor; no execution claim.

### Remaining limits

- Restore schema partial-index cast normalization fix remains in progress at this static read SHA.
- No final combined PG17/18 run, protected Chrome result or independent V13 security verdict supplied.
- D6 root cause remains ROOT_CAUSE_UNKNOWN; prior V12 security PASS does not review V13.
- No PITR/KMS production validation, privileged SQL protection, actual external send or read confirmation.
