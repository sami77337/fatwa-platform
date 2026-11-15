# FAST9 — Ed25519 MUFTI Approval to PostgreSQL Queue Bridge v1

**الحالة: تطوير واختبار اصطناعي فقط — NOT_DEPLOYED / GATES_HOLD.**

## الهدف
ربط حد التحقق Ed25519 الموجود في FAST9 بحد الاستهلاك الذري للاعتماد في PostgreSQL، بدل تمرير حقول اعتماد قابلة للتشكيل يدويًا إلى خدمة الطابور.

## ما أضيف
- `commit_signed_approved_plan` يستقبل SignedApprovalReceipt وCurrentEvidence وPlan ومدقق هوية موثوق.
- يستدعي `require_return_approval` أولًا؛ يتحقق من التوقيع والهوية النشطة ودور MUFTI والقرار والنسخة وبصمات السؤال والمصدر والرد وبصمة الخطة الدقيقة.
- يشتق plan fingerprint من الخطة نفسها، ويستعمل step idempotency keys الموقعة كهوية لكل جزء.
- بعد التحقق فقط، يمرر ApprovedForReturn إلى `commit_approved_plan` ليستهلك receipt_id وnonce ويحفظ جميع intents في معاملة PostgreSQL واحدة.
- لا يقبل ApprovalReceipt غير الموقّع أو مفتيًا ملغى/غير نشط أو خطة معدّلة.
- اختبارات Ed25519 بمفاتيح مؤقتة، دون مفاتيح أو هويات إنتاجية.

## حدود
لا موفر هوية حي ولا KMS ولا sender. مدقق الهوية يظل adapter يمرره التطبيق من مصدر موثوق. المفاتيح الاختبارية مؤقتة. لا إرسال أو نشر أو دمج.
