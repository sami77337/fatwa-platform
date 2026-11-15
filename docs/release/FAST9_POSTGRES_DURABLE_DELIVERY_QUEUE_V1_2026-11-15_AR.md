# FAST9 — PostgreSQL Durable Delivery Queue v1

التاريخ: 15 نوفمبر 2026.

**الحالة: بيئة اختبار PostgreSQL اصطناعية فقط. NOT_DEPLOYED / GATES_HOLD.**

## ما أضيف
- تطبيق Django مستقل `apps.delivery_queue` غير مضاف إلى إعدادات الإنتاج أو الواجهات العامة.
- مخطط PostgreSQL مستقل للاعتمادات المستهلكة، ونوايا التسليم، وإيصالات المزوّد، وأحداث التدقيق.
- `commit_approved_plan`: يستهلك الإيصال مرة واحدة ويربطه ببصمة الخطة وnonce وبصمة manifest، ويحفظ كل الأجزاء في معاملة واحدة. قفل advisory transaction-scoped يعالج سباق إنشاء صف اعتماد غير موجود.
- `claim_next`: حجز عامل عبر `SELECT FOR UPDATE SKIP LOCKED` لمنع عاملين من حجز الصف نفسه.
- `record_receipt`: حفظ إيصال المزوّد وتحديث الحالة وسجل التدقيق ذريًا، مع رفض إعادة استعمال المرجع لمحتوى مختلف.
- `quarantine_expired_leases`: تحويل الحجز المنتهي إلى NEEDS_RECONCILIATION وعدم إعادة إرساله تلقائيًا.
- `summarize_plan`: اكتمال الخطة فقط عند تسليم كل الأجزاء.

## الضوابط
- التطبيق غير مسجل في `config.settings.base` ولا `config.settings.development`.
- إعداد اختبار منفصل يرث حراسة قاعدة Wave7 الاصطناعية، ولا يفتح إعداد الإنتاج.
- migrations تضيف triggers تمنع تعديل/حذف approval claims وprovider receipts وaudit events.
- لا يوجد sender أو HTTP أو connector أو نشر.
- اختبارات PostgreSQL 17 و18 في قواعد مؤقتة معزولة، لا تستخدم قواعد خارج CI.

## الحدود
هذا نموذج durable queue داخل PostgreSQL، وليس ربطًا فعليًا بمزوّد هوية أو قناة. التحقق من الاعتماد وإيصال القناة يظل callback يجب ربطه بمصدر موثوق قبل أي تشغيل حقيقي. لا يدّعي ضمان exactly-once عند القناة الخارجية؛ المطلوب من المزوّد دعم idempotency key أو reconciliation.

