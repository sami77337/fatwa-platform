# FAST9 — PostgreSQL Audit Hash Chain & External Attestation v1

**الحالة: تطوير واختبار اصطناعي فقط — NOT_DEPLOYED / GATES_HOLD.**

## ما أضيف
- DeliveryAuditHead singleton لتسلسل الأحداث ورأس السلسلة.
- sequence وprevious_digest وdigest لكل DeliveryAuditEvent.
- كل كتابة تدقيق تقفل رأس السجل وتضيف الحدث وتحدّث الرأس داخل معاملة PostgreSQL نفسها.
- `verify_audit_chain` يعيد حساب كل حدث ويتحقق من التسلسل والرابط السابق والرأس.
- `PostgresAuditAttestation` بختم HMAC-SHA256 على رأس السجل باستخدام مفتاح يمرره المستدعي من خارج قاعدة البيانات.
- رفض checkpoint قديم بعد إضافة حدث، ودعم تدوير المفاتيح.
- اختبار تعديل حدث وإعادة بناء سلسلة SHA-256 المحلية؛ ينجح الفحص المحلي بعد إعادة البناء لكن checkpoint الخارجي القديم يرفض الرأس المعدّل.

## حدود الأمان
HMAC يثبت امتلاك المفتاح المشترك ولا يقدم non-repudiation. يجب حفظ المفتاح والـcheckpoint خارج قاعدة PostgreSQL والمضيف، ويفضل KMS/WORM store. لا توجد خدمة KMS أو WORM موصولة هنا. لا يثبت الختم صحة القرار الشرعي، بل يثبت تطابق رأس سجل التدقيق مع نقطة تحقق موثوقة سابقة.

لا إرسال أو نشر أو دمج.
