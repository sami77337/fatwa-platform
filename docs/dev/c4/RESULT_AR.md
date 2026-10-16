# نتيجة Wave3 C4 — مرشحات البحث في عناوين الفهرس

التاريخ: 2026-10-16. الفرع: `codex/20261016-wave3-platform-c4`.
SHA الأساس: `72079aee096500f398b7536b2c1beb819cbb0cee`، والنتائج أدناه تخص التعديلات المحلية غير الملتزم بها فوقه.

## التنفيذ

أضيف إلى `GET /api/v1/fiqh/search` مرشحان اختياريان:

- `depth`: عدد صحيح ضمن 1–5، باستخدام قواعد الأعداد المحدودة الحالية (أرقام ASCII فقط).
- `has_children`: يقبل حصراً `true` أو `false` بحروف صغيرة؛ يختبر وجود طفل مباشر من الطبعة نفسها، بصرف النظر عن مطابقة عنوان الطفل لنص البحث.

مثال: `/api/v1/fiqh/search?q=كتاب&depth=2&has_children=false&root=1&limit=20`.
المعاملات المشوهة والمجهولة والمكررة ترجع JSON بالحالة 400 و`error=invalid_query` قبل الوصول إلى قاعدة البيانات.
تتحقق طبقة الخدمة أيضاً من أنواع وقيم المرشحين عند الاستدعاء المباشر، حتى مع فهرس فارغ.

تطبق المرشحات قبل العد والتقسيم إلى الصفحات. يستخدم وجود الأطفال `EXISTS` أو `NOT EXISTS` مقيداً بمعرف الطبعة ومعرف الأب الداخلي؛ لا يضيف ربطاً يكرر صفوف النتائج. بقي الترتيب `source_order, source_row_id` وحقول JSON والعناوين الأصلية وأوضاع `normalized/exact/literal` ونطاق الجذر كما هي. لا تغيير في واجهة SSR أو محددات الطبعات والناشرين أو المسارات.

## التحقق المنفذ

البيئة: Python 3.13.15، Django 5.2.18، psycopg 3.3.6، django-htmx 1.29.0، Ruff 0.17.0.

| الأمر | النتيجة الفعلية |
|---|---|
| `python -B tests/integration/api/run_isolated.py` | PASS: 29 اختباراً؛ حظر فتح اتصالات قاعدة البيانات، مع توليد SQL عبر backend PostgreSQL وصفوف مؤشرات اصطناعية |
| `python -B tests/integration/api/run_c4_synthetic.py` | PASS: 5 اختبارات؛ تنفيذ ORM وHTTP على SQLite مؤقتة داخل الذاكرة فقط |
| `python -m ruff check apps/reference/query.py apps/reference/services.py apps/reference/views.py tests/integration/api/test_c4_filters.py tests/integration/api/run_c4_synthetic.py tests/integration/api/synthetic_c4.py` | PASS |
| `python -m ruff format --check apps/reference/query.py apps/reference/services.py apps/reference/views.py tests/integration/api/test_c4_filters.py tests/integration/api/run_c4_synthetic.py tests/integration/api/synthetic_c4.py` | PASS: 6 ملفات |
| `git diff --check` | PASS |

هوية بيانات الاختبار: `c4-synthetic-v1` في `tests/integration/api/synthetic_c4.py`؛ طبعتان اصطناعيتان، في كل منهما سبعة عناوين تتكرر معرفاتها المصدرية، وشجرة حتى العمق الخامس مع اختلاف علاقة طفل بين الطبعتين.
SHA256 لملف تعريف البيانات والاختبارات: `c4452399b7b73e7b24ebb7b9caef89475b026e8ec53bb1985102b6be12b2ea77`.
الاختبارات المعزولة تستخدم أيضاً `a2-cursor-rows-v1` من أدوات الاختبار الموجودة، وليست المصدر الأصلي.

التغطية: تركيب المرشحين مع الأوضاع الثلاثة والتطبيع العربي، الأعماق الخمسة، وجود الأطفال وعدمه، نطاق الجذر شاملاً الجذر، رفض الجذر غير الجذري والمفقود حتى مع بحث فارغ، إجماليات دقيقة وصفحات مستقرة، عزل الطبعات ذات المعرفات المتكررة، فهرس فارغ ونتائج فارغة، واستمرار عقد JSON.

## حدود النتائج وحالة التسليم

- PostgreSQL 17/18 execution acceptance: **NOT_RUN**؛ لم يجر الاتصال بخادم PostgreSQL أو بيانات المالك. نجاح توليد SQL لا يثبت التنفيذ أو خطة الأداء على PostgreSQL.
- اختبارات المصدر الأصلي ذي 11,397 عنواناً وقياسات أدائه: **NOT_RUN**؛ لم تستخدم ZIP أو تعاد استيراد البيانات، ولا ادعاء بقبول المصدر.
- قاعدة الذاكرة تخلق مخططاً وبيانات اصطناعية خاصة بالاختبار دون تشغيل migrations؛ ليست بديلاً لإعدادات PostgreSQL في المشروع. لم تعدل إعدادات المشروع أو تبعياته أو مخططه أو بياناته الدائمة.
- لم تضف عمليات كتابة للمنتج، حسابات أو صلاحيات أو نشر أو إجابات آلية أو معالجة فيديو. هذه عناوين فهرس مرجعي أصلية، وليست فتاوى منشورة.
- تركت التعديلات في working tree دون commit أو push أو رفع PR، ليتولى الناشر المراجعة والتسليم.

**NOT_DEPLOYED / GATES_HOLD**. Gate B: **NOT_PASSED**؛ Gates C/D/E: **HOLD**؛ Phase01: **غير مأذون بها**.
