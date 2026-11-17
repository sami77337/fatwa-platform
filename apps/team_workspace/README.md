# مساحة الشيخ والفريق — شريحة مكتب القضايا الدائمة

Base inspected: PR #209, `e000cdc22c1a0dfd1e0e38eb8fd7cfbfc392487e` on
`codex/20261117-v6-durable-case-integration`. PR #207/#208 functionality is inherited,
not recreated. No existing shared files are modified by this slice.

## الوظيفة

- قائمة القضايا المخوّلة، بحث برقم القضية، وتصفية حسب الحاجة لمسودة أو انتظار
  الاستيضاح أو جاهزية المراجعة أو الإعادة أو اكتمال المراجعة. العدادات ضمن نطاق
  الهوية والبحث فقط، ولا تظهر مقتطفات أسئلة قضايا أخرى في القائمة.
- السؤال الأصلي والتعقيبات والاستيضاحات بجانب محرر أحدث جواب بشري. الحفظ ينشئ
  إصدارًا جديدًا عبر الخدمة الموجودة؛ تبقى النسخ السابقة محفوظة.
- الاعتماد والإعادة يخصان أحدث إصدار متصل بالوقائع الحالية فقط. سبب الإعادة مطلوب،
  ويظهر بعد إعادة فتح القضية في سجل الإجراءات. لا أزرار اعتماد للإصدارات القديمة
  أو المعادة أو أثناء انتظار الاستيضاح؛ يبقى رفض الأوامر المزورة في خدمة القضية.
- تغير الوقائع يوضح أن المسودة قديمة. فشل حفظ نموذج قديم يعرض نص المحاولة في حقل
  استرجاع مستقل، دون إعادة ربطه خفية بالوقائع الجديدة أو استبدال الجواب المحفوظ.
- عرض الحالة وسجل الإجراءات وإدارة رموز الوصول باستخدام resolver الموثوق القائم
  فقط. لا حالة موازية، ولا جداول أو migrations أو صلاحيات جديدة.

## الصلاحيات وحدود التكامل

مكتب القضايا الدائمة الحالي يقبل `MUFTI` فقط، مع scope للقضايا ونسخة صلاحيات
`auth_epoch`. يحتفظ هذا التغيير بالحد نفسه. أدوار author/reviewer/operator الموجودة
في المكتب التدريبي المستقل لا تُحوّل إلى MUFTI ولا تُربط بالسجل الدائم ضمن هذه
الشريحة. لا منح صلاحيات ORGANIZER أو ORGANIZER_ADMIN ولا اعتماد آلي.

الحماية القائمة باقية: معطل افتراضيًا، loopback فقط، POST وCSRF، no-store/noindex،
قيود الأحجام ومعدل الطلبات، وتحقق الهوية داخل عملية القضية. اعتماد الجواب لا يثبت
تسليمه أو قراءة السائل. بيانات الاختبار اصطناعية فقط.

## موضع الربط لمسؤول التكامل

1. استخدم `ROOT_URLCONF = "apps.team_workspace.urls"` في بروفايل التدريب المحلي،
   أو استورد منه `urlpatterns`. يعيد استخدام جميع مسارات casework القائمة ويستبدل
   **مسار staff وشاشة CSS فقط**. الروابط ونطاق cookies وCSRF وguard لا تتغير.
2. البروفايل الاختياري `apps.team_workspace.settings` يرث
   `config.settings.casework_review` ويغير ROOT_URLCONF فقط. إعداد موفر الهوية
   والاسترداد الموثوقين يظل مسؤولية الخادم كما في #209. لا تفعّل المسار في الإنتاج.
3. `presentation.read_workspace_case` يستخدم حد القراءة المقفلة الموجود
   `services._staff_case` و`services._staff` ليضيف سجل الإجراءات وأسباب القرارات.
   هذا اعتماد صريح على واجهتين داخليتين، مع اختبارات؛ يمكن لمسؤول التكامل ترقيته
   لاحقًا إلى public read API. لا قراءة ORM غير مخوّلة ولا تعديل لملفات core.
4. workflow مستقل `team-workspace.yml` يشغّل الاختبارات على PG17/18 وChrome؛
   لم نعدّل workflow #209 أو اختبارات/ملفات الفريق المشتركة.

## التحقق

ببيئة Python 3.13 واعتماديات المشروع، على قاعدة PostgreSQL اصطناعية جديدة مملوكة:

```sh
python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 -- python manage.py test apps.team_workspace.tests tests.casework.test_core tests.casework.test_adversarial --noinput
FATWA_FASTBUILD_BROWSER=/usr/bin/google-chrome python infra/dev/with_casework_postgres.py --pg-bin /path/to/postgresql/17/bin --major 17 -- python manage.py test apps.team_workspace.browser_tests --noinput
ruff check apps/team_workspace
git diff --check
```

نتيجة محلية: **54/54** اختبار PostgreSQL 17.11 نجح، منها **22** عقدًا للواجهة
الجديدة (14 عقدًا موروثًا مع إعادة توجيه اختبار تبديل epoch إلى موضعه الجديد،
و8 اختبارات مركزة جديدة)، و32 اختبار core/adversarial قائمًا.

اختبارات المتصفح تستخدم عقد الرحلة القائم لقضيتين، وتضيف اختبار البحث والتصفية
والإعادة والتعديل والاعتماد على الهاتف والحاسوب. ملفات الدليل في
`.local/qa/team-workspace/browser/`. تشغيل Chromium المحلي يستخدم wrapper خارج
المستودع بـ`--no-sandbox` لأن sandbox المتصفح غير متاح في هذه الحاوية؛ لا يغير
هذا إعداد التطبيق أو اختبار CI الذي يحتفظ بـ`chromium_sandbox=True`.
لا تُعد نتيجة المتصفح المحلي إثباتًا لبيئة sandbox؛ نتيجة CI تُبلّغ منفصلة.

**NOT_DEPLOYED / GATES_HOLD / ACCEPTANCE_HOLD.** لا دمج إلى main، لا نشر تطبيق،
لا إرسال رسائل أو تشغيل قنوات فعلية، ولا بيانات مستخدمين حقيقية.
