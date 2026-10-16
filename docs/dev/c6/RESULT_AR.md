# نتيجة C6 — فحوص Wave3 للمنصة

التاريخ: 2026-10-16. الفرع: `codex/20261016-wave3-platform-c6`.
SHA الأساسي: `72079aee096500f398b7536b2c1beb819cbb0cee`.
النتائج تخص هذا الأساس مع تعديلات C6 غير الملتزم بها؛ ليست نتائج GitHub Actions.

أضيف مشغّل `tools/dev/TEST_WAVE3_LOCAL.cmd` وفاحص Python مستقل، مع اكتشاف
unittest يرفض صفر اختبارات، ووظيفة GitHub Actions على Windows وUbuntu.
الوظيفة الجديدة تختبر نسخة checkout الخاصة بالحدث، وتشترط وجود حزم C1/C2/C3
بعد جمع الفروع. ملف B6 الحالي، بما فيه PostgreSQL 17/18 وDjango وNode، لم يتغير.

## النتائج المنفذة

البيئة: Windows، Python 3.13.15، Node v24.16.0. ثُبتت متطلبات
`requirements.txt` المقيدة في بيئة محلية معزولة داخل
`tools/dev/.local/c6-venv`، دون تثبيت عام أو اتصال بقاعدة بيانات المالك.

شُغّل الأمر `cmd /d /c tools\dev\TEST_WAVE3_LOCAL.cmd` مع
`FATWA_PYTHON` يشير إلى تلك البيئة و`FATWA_NO_PAUSE=1`، وكانت النتيجة:

| الفحص | النتيجة الفعلية |
|---|---|
| unittest discovery داخل tests/dev | PASS: 26 اختبارًا، دون تجاوز |
| Django check بإعدادات الاختبار | PASS: لا مشكلات، 0 silenced |
| Node dispatcher الحالي | 88 اختبارًا: 87 PASS، 0 FAIL، 1 SKIPPED |
| رمز خروج المشغّل المحلي | 0، مع تصريح واضح بالحزم الغائبة |
| tests/content_intake | NOT_RUN: الحزمة غائبة في هذا الفرع |
| tests/fatwa_drafts | NOT_RUN: الحزمة غائبة في هذا الفرع |
| tests/reference_links | NOT_RUN: الحزمة غائبة في هذا الفرع |

اختبار Node المتجاوز هو `real supplied archive identity matches pin` بسبب
`Owner archive unavailable`؛ لا يمثل نجاحًا ولا تحقق متصفح فعلي.
السجل المحلي الكامل في `tools/dev/.local/c6-local.log`
ملف مولّد مستثنى من Git.

شُغّل أيضًا `python tools/dev/wave3_qa.py --standalone --require-integrated`:
رمز الخروج 1 كما هو متوقع، مع NOT_RUN للحزم الثلاث الغائبة؛ لذلك لا يوجد ادعاء
بنجاح التكامل. اختبارات المشغّل تستخدم أمثلة مصطنعة فقط، بما فيها مسار عربي
بمسافات ورمز `&`، فشل dependency، subprocess فاشل، Python غير 3.13،
checkout مرفوض، واكتشاف صفري. اختبارات B6 القائمة تتحقق من checkout نظيف
ومن رفض نسخة CI المتسخة وإزالة بيانات الاتصال الموروثة.

## حدود التحقق وحماية المصدر

- GitHub Actions على Windows/Ubuntu: NOT_RUN محليًا؛ يلزم تشغيل الناشر بعد الدمج.
- تكامل PostgreSQL 17/18: NOT_RUN في هذه المهمة؛ لم تُشغّل ترحيلات أو إعادة استيراد.
- قبول المصدر الحقيقي ذي 11,397 عنوانًا: NOT_RUN؛ لا ZIP أصلي أو fixture حقيقي
  استُخدم، ولا ادعاء بفحص SHA للمصدر أو مقارنة محتوى قاعدة بيانات المالك.
- لم تتغير ملفات التطبيقات أو الإعدادات أو القوالب أو اختبارات المرجع أو أدوات
  الاستيراد أو CI السابق. التوافق القرائي محقق على مستوى المشغّل وفحوصه؛
  لا يدّعي هذا فحص سلامة بيانات المالك مباشرة.
- لا معالجة فيديو أو قص أو تفريغ أو اقتباسات أو خرائط مصدر أو موافقات مختلقة.

بقيت التعديلات ضمن مسارات C6. لم يُنشأ commit أو push أو PR؛ يتولاها الناشر.
NOT_DEPLOYED / GATES_HOLD. Gate B NOT_PASSED؛ C/D/E HOLD؛ Phase01 BLOCKED.
