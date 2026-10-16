# نتيجة Wave2 B3 — 2026-10-16

الحالة: NOT_DEPLOYED / GATES_HOLD. لا commit أو push أو merge أو نشر.

الأساس: `7a44bdf28874f9113acbe82cb6fdb64baf87da89`، مع تعديلات محلية موضحة أدناه.

## التغييرات

- توضيح أن توفر الفهرس لا يعني اعتماد حكم شرعي، وأن التحقق يكون بالرجوع إلى نص المصدر وإحالته.
- إضافة إعادة محاولة من الرئيسية وروابط مساعدة مباشرة عند غياب البيانات أو تعذر الاتصال، مع التفريق عن البحث بلا نتائج.
- فهرس روابط داخل دليل الاستخدام، وإرشادات الوصول إلى البحث، وغياب البيانات وتعدد المصادر والرابط المفقود وانقطاع اتصال الجهاز.
- توضيح أن وصف المصدر لا يثبت تحميله، وأن العمل دون اتصال غير متوفر.
- الحفاظ على HTML وSSR وروابط GET ونموذج البحث القائم دون JavaScript، والمسارات الحالية دون تغيير. لم تتغير قوالب reference أو API أو الصلاحيات.

## التحقق الفعلي

Python 3.13.15. ثُبتت المتطلبات المقيدة من requirements-dev.txt داخل بيئة محلية مهملة في apps/public_site/.venv.

الأوامر النهائية ونتائجها:

```text
apps/public_site/.venv/Scripts/python manage.py test tests.public_site.test_pages --settings=config.settings.test --verbosity=1
Ran 20 tests in 0.039s — OK
System check identified no issues (0 silenced).

apps/public_site/.venv/Scripts/python -m ruff check apps/public_site/views.py tests/public_site
All checks passed!

apps/public_site/.venv/Scripts/python -m ruff format --check tests/public_site
2 files already formatted

apps/public_site/.venv/Scripts/python manage.py check --settings=config.settings.test
System check identified no issues (0 silenced).

git diff --check
نجح دون مخرجات.
```

تشمل الاختبارات العشرين سلامة المسارات والتنقل، GET/HEAD ورفض طرق التعديل، غياب المصدر وانقطاع التخزين، عدم كشف الأخطاء، نموذج بحث GET إلى عرض الفهرس الحقيقي، مسار الفهرس الفارغ و503 دون JavaScript، أهداف روابط المساعدة ومعرّفاتها، ودلالات RTL والتركيز وترويسات الأمان. أضيفت ثلاثة اختبارات إلى الاختبارات القائمة.

محاولات سابقة: Python العام لم يتضمن Django. وبعد تثبيت المتطلبات فشل اكتشاف الحزمة باستخدام tests.public_site بسبب namespace package؛ استخدام اسم الوحدة tests.public_site.test_pages نجح. فشل اختبار جديد أولًا بسبب اختلاف «ليست» و«ليس» في النص المتوقع؛ صُحح وأعيد تشغيل المجموعة كاملة بنجاح.

## حدود الأدلة

هوية fixture القائمة: a3-public-source-summary-v1، بيانات خدمة اصطناعية فقط، مع محاكاة DatabaseError وCatalogUnavailable. لا استخدام لملفات ZIP الأصلية ولا ادعاء تحقق SHA256 لها أو قبول استيرادها. اختبارات SimpleTestCase لا تفتح PostgreSQL، ولم يجر اختبار قبول قاعدة بيانات أو متصفح فعلي أو قياس بصري للهاتف. فحوص عدم JavaScript بنيوية وطلبات SSR فعلية عبر Django Client. لم تتغير البوابات: Gate B NOT_PASSED، C/D/E HOLD، Phase01 BLOCKED، وسياسات U03/U10 ما زالت بانتظار المالك.
