# قائمة المراجعة التحريرية المحلية

شغّل `python -m apps.editorial_queue` وافتح
<http://127.0.0.1:8014/dev/editorial-queue>.
يتجاوز المشغّل فحص الترحيلات المسبق فقط؛ تبقى حواجز Django القائمة
للبيئة المحلية والإنتاج وطرق HTTP مفعّلة. يمكن استخدام `runserver` المعتاد
مع PostgreSQL مهيأ. لا يحتاج عرض هذه العينات إلى قاعدة بيانات.

تُعاد قراءة عينات `apps.editorial_workbench.services.build_cases()` التسع كما هي:
سجل المراجعات الثابت وثمانية صفوف من Wave7. لا توجد عينات خاصة جديدة أو
مسار يستقبل حمولة أو اسم ملف. الخدمات الأصلية مسؤولة عن الاستلام والتحضير
وتشخيص الإحالات؛ يعاد استخدام `build_history` و`build_revision_audit` للقطات.

تعمل تصفية الحالة والمراجع والبحث معًا؛ يبقى ترتيب القائمة ثابتًا حسب خدمة
العينات. يحدد مفتاح السجل الرابط، مستقلًا عن المعرّف الخارجي الذي قد يتكرر
أو يغيب. السابق والتالي هما أقرب سجلين مطابقين دون التفاف عند الحدود.
يظل الرابط المباشر لسجل خارج التصفية قابلًا للفحص مع رسالة واضحة ودون جيران.
تحفظ روابط القائمة والتفاصيل التصفية؛ تفتح روابط مساحة العمل السجل ذاته
وهوية المراجعة الفعلية، بما فيها الأرقام غير المتتالية.

تُعرض بصمة الحمولة وبصمة نص الصف الخام وحدود UTF-8 دون تعديل المصدر.
سجل `history` يعرض تسلسل الاستلام الاصطناعي، وليس شريحة ملف أصلي؛ مؤشرات
مراجعه تخص أحدث لقطة ثابتة. بقية مؤشرات المراجع تخص الاستلام الأصلي.
عدم وجود مراجع يختلف عن المطابقة؛ كل نتيجة غير `verified` مؤشر غير محسوم.
المطابقة تقنية مع الفهرس الاصطناعي فقط؛ ليست توثيقًا علميًا أو قبول مصدر مالك.
تدقيق اللقطات وصفي وليس سجل أحداث موثقًا، ووسم النسبة ليس هوية مستخدم.

التحقق المركّز:

```powershell
python manage.py test tests.editorial_queue.test_services tests.editorial_queue.test_views tests.editorial_workbench.test_services tests.editorial_workbench.test_views tests.editorial_workbench.test_persisted --settings=config.settings.test
python manage.py check --settings=config.settings.development
python -m ruff check apps/editorial_queue tests/editorial_queue config/urls.py
python -m ruff format --check apps/editorial_queue tests/editorial_queue
git diff --check
```

هويات المدخلات الاصطناعية المستخدمة:

- `fixtures.synthetic_payload()`:
  `cfb2bebf24e9f11bab46787e8b5926e93627b616ce85f6457c6d3715a236c0cb`.
- `serialize_intake((REVISION_HISTORY_RECORD.intake,))`:
  `75fc9bc0ebedbac1ae3b9cbe28cfc308ab25f5eeb6813aeb50156c27be655bb0`.

لا نماذج أو ترحيلات أو تغييرات إعدادات أو صلاحيات جديدة. لا عمليات كتابة
أو انتقالات أو نشر أو اعتماد علمي. لا وصول إلى سجلات محفوظة أو تشغيل قارئها.
اختبارات `SimpleTestCase` تمنع قاعدة البيانات؛ لا تثبت قبول PostgreSQL أو
مصادر ZIP الأصلية، ولم يُجر هذا القبول ضمن المهمة.
التغيير المشترك الوحيد هو URL include واحد؛ التراجع بإزالته وملفات هذه الميزة.

Gate B NOT_PASSED; C/D/E HOLD; Phase01 BLOCKED; SCOPE_DEVIATION_HOLD;
NOT_DEPLOYED / GATES_HOLD. Draft PR للمراجعة البشرية فقط.
