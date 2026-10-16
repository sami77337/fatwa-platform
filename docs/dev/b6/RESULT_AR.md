# نتيجة B6 — تشغيل وفحص التكامل

التاريخ: 2026-10-16. أساس الشيفرة: `7a44bdf28874f9113acbe82cb6fdb64baf87da89`.
تعديلات B6 محلية غير ملتزمة؛ لا يعرّف SHA وحده هذه الأدوات الجديدة. لم يحدث commit أو push أو merge أو deploy.
الحالة: **NOT_DEPLOYED / GATES_HOLD**؛ Gate B NOT_PASSED، وC/D/E HOLD، وPhase01 BLOCKED.

## التشغيل على Windows

من جذر هذه النسخة، جهّز البيئة مرة واحدة في PowerShell:

```powershell
python -m venv tools/dev/.local/venv
& '.\tools\dev\.local\venv\Scripts\python.exe' -m pip install -r requirements.txt
```

يجب أن يكون Python بالإصدار 3.13 وNode بالإصدار 24، وأن يعمل Docker Desktop بمحرك Linux محلي لاختبارات PostgreSQL. تثبيت الحزم لا ينشئ قاعدة بيانات.

الأزرار الموجودة `tools/dev/START_LOCAL.cmd` و`STATUS_LOCAL.cmd` و`HEALTHCHECK_LOCAL.cmd` باقية كما هي: تشغيل الحاوية الموجودة فقط بعد التحقق من ربط هذه النسخة للقراءة فقط، وفحص HTTP عبر `127.0.0.1:8000`. لا تُنشئ حاويات بديلة ولا تبدأ قاعدة البيانات ولا تستورد المصدر. إذا كانت الحاوية مربوطة بنسخة أخرى يتوقف التشغيل؛ لا تعِد ربطها تلقائيًا. زر `TEST_LOCAL.cmd` القديم يختبر أدوات التشغيل فقط، وزر `TEST_DATABASE.cmd` القديم يبقى محظورًا لحماية القاعدة الحية.

الزر الجديد **`tools/dev/QA_LOCAL.cmd`** يشغّل الفئات الثلاث منفصلة، ويطبع تقرير JSON. يرجع رمزًا غير صفري إذا فشل فحص أو تعذر Docker، حتى لو نجحت الفئات الأخرى. لا يفترض توفر Docker من مجرد وجود الأمر `docker`.

للتشغيل المنفصل:

```powershell
& '.\tools\dev\.local\venv\Scripts\python.exe' tools/dev/qa.py system
& '.\tools\dev\.local\venv\Scripts\python.exe' tools/dev/qa.py postgres --postgres 18
& '.\tools\dev\.local\venv\Scripts\python.exe' tools/dev/qa.py postgres --postgres 17
& '.\tools\dev\.local\venv\Scripts\python.exe' tools/dev/qa.py node
python -m unittest discover -s tests/dev -p 'test_*.py' -v
```

الاستدعاءات الداخلية قوائم معاملات مع `shell=False`، دون أوامر PowerShell مركبة أو `Invoke-Expression`؛ المسافات وعلامات `&` في المسارات لا تتحول إلى شيفرة shell. تُزال متغيرات الاتصال والأسرار الموروثة. لا تُطبع بيانات Docker الخام عند تعذر التشغيل.

## عزل PostgreSQL وفخ الشبكة الداخلية

يبني الفاحص صورة Python 3.13 من `requirements.txt` المثبتة الإصدارات **قبل** تشغيلها داخل الشبكة الداخلية. سياق البناء المؤقت لا يحتوي إلا ملف المتطلبات وDockerfile؛ لا يحتوي المصدر أو الأسرار. يحتاج البناء الأول إلى الإنترنت وصور Docker؛ لا يوجد ادعاء بأنه يعمل دون اتصال.

لكل تشغيل شبكة `--internal` وحاويتا PostgreSQL وPython بأسماء UUID مستقلة. لا يوجد نشر منافذ، ولا ربط أسرار حية، ولا volume دائم. بيانات PostgreSQL في tmpfs تحت `/var/lib/postgresql` مع PGDATA صريح يصلح للإصدارين 18 و17. مصادقة trust تخص هذه الشبكة المؤقتة فقط. القاعدة الحية `fatwa_reference` وvolume الخاص بها لا يُستهدفان بأي أمر.

بعد التحقق من الإصدار وخلو العنقود من قواعد أخرى، ينفذ العامل `check --database default`، وفحص تغييرات migrations، ثم migrations فعلية وفحص اكتمالها، ثم اختبارات `tests.reference` و`tests.public_site` و`tests.security` و`tests.integration.test_site`. يشمل ذلك ORM وHTTP داخل Django وقواعد سلامة البيانات على PostgreSQL حقيقي. تُنشأ قاعدة اختبار Django وتُحذف في العنقود المؤقت وحده؛ لا يوجد `--keepdb` أو SQLite أو إعادة استخدام للعنقود الحي.

تُحذف الحاويات والشبكة والصورة ذات الأسماء المولدة فقط عند الخروج، دون prune أو إزالة volumes. يظهر فشل التنظيف كفشل. عند قتل العملية قسرًا قد تبقى موارد بأسماء `fatwa-b6-*`؛ افحصها يدويًا، ولا تستخدم تنظيفًا عامًا. لا يُعَد نجاح الاختبارات الاصطناعية قبولًا للمصدر الأصلي ذي 11,397 عنوانًا.

## CI والنتائج الفعلية

`b6-integration.yml` يمنح `contents: read` فقط، ويعطّل الاحتفاظ ببيانات اعتماد checkout. الوظائف منفصلة: فحص Django على Python 3.13، ومصفوفة PostgreSQL 18/17، واختبارات Node وأدوات التشغيل. يرفض الفاحص تشغيل CI إذا كان checkout متغيرًا أو يحتوي ملفات غير متتبعة. لا يتضمن نشرًا أو كتابة إلى GitHub أو استيراد مصدر. لا توجد نتيجة CI فعلية لهذه التعديلات لأنها لم تُلتزم أو تُدفع.

| الفئة | النتيجة على هذه الآلة |
|---|---|
| Python | 3.13.15؛ تثبيت requirements نجح في بيئة محلية معزولة |
| Django system check الفعلي | PASS، Django 5.2.18، دون مشكلات؛ لا يثبت اتصال PostgreSQL |
| اختبارات Python لأدوات التشغيل | 16 PASS؛ تشمل 10 اختبارات B6 إيجابية وسلبية |
| Node 24.16.0 | 86 إجماليًا، 85 PASS، صفر فشل، 1 SKIP؛ تشمل mocks وDOM harness |
| PostgreSQL 18 | NOT_RUN: محرك Docker غير متاح؛ migrations واختبارات DB لم تنفذ |
| PostgreSQL 17 | NOT_RUN: السبب نفسه |
| حالة الموقع الحي | FAIL: Docker غير متاح وHTTP المحلي غير متاح |
| متصفح حقيقي / جوال / لوحة مفاتيح | NOT_RUN؛ لا تُستبدل باختبارات Node |
| قبول ZIP الأصلي أو مقارنة كامل المصدر | NOT_RUN؛ لم يُستورد أي مصدر |

تشمل اختبارات B6 رفض Docker البعيد وحقن الأسطر، وتنقية الأسرار، ورفض checkout غير الملتزم في CI، وحفظ المسارات كمعاملات مستقلة، ورفض PostgreSQL غير المدعوم قبل أي إجراء، وتأكيد عدم نشر منافذ أو تركيب volumes، وترتيب البناء قبل الشبكة الداخلية، والتوقف قبل أي تغيير عند غياب Docker. هذه اختبارات للمنسق وليست دليل تشغيل PostgreSQL؛ مصفوفة CI هي التي تنفذ التطبيق فعليًا عند توفر المحرك.
