# نتيجة D3 — جسر الهوية الصريح

تاريخ التنفيذ: 2026-10-16. الأساس الفعلي HEAD:
`cf877ab6d0abadbeafe15efa8ef9c286e7795b23` (Wave3 PR #39).

تم تنفيذ `resolve_prepared_pointers(raw, config, catalog)` وتصديره من
`apps.reference_links`. المدخل ظرف JSON bytes بالعقد `fatwa.prepared-intake.v1`،
والنتيجة tuple من RowResult لكل صف وPointerResult لكل مؤشر. يحفظ
`original_pointer` أزواج الحقول النصية الأصلية وترتيبها دون تحويل أو تطبيع؛
يمكن استعادتها بواسطة `dict(result.original_pointer)`.
لا تظهر evidence أو citation إلا للحالة verified. الصف بلا مراجع يعيد tuple فارغًا.
الأخطاء البنيوية ترفع ValueError؛ المؤشرات النصية غير المطابقة تبقى unverified.

## إعداد بشري صريح وثابت

```python
from apps.reference_links import (
    SourceIdentity, EditionMap, HeadingMap, BridgeConfig,
    resolve_prepared_pointers,
)

# قيم اصطناعية فقط، لا تمثل مصدر المالك أو إصدار قاعدة بيانات حقيقيًا.
identity = SourceIdentity(
    'synthetic-only', '622', 'human-edition-A', 'a' * 64, 'b' * 64,
)
config = BridgeConfig(
    EditionMap(identity, 41),
    (HeadingMap('source-X', 'heading-Y', 'row-Z', 73),),
)
```

SourceIdentity يثبت namespace وbook=622 وedition_key وSHA الأرشيف وSHA المدخل.
EditionMap يربط هذه الهوية بإصدار رقمي يختاره الإنسان صراحة.
HeadingMap يربط زوج C1 النصي بمعرف C2 النصي وصف الفهرس الرقمي صراحة.
C2 يقارن حقوله الستة كاملة: حقول الهوية الخمسة وsource_id.
تُرفض تكرارات مفاتيح C1 أو C2 أو الصف الرقمي حتى لو كانت القيم متطابقة.
ترفض الأرقام النصية وbool في مواضع الأرقام. كل نسخ المؤشر المكرر داخل الصف
تبقى unverified. يسمح بمرجع مشترك بين صفوف تحريرية مختلفة.

الإعداد تفويض وثقة بشرية مقدمة من المستدعي؛ صحة تركيب SHA ليست إثبات أصالة.
يجب على الإنسان مراجعة الأرشيف والمدخل والإصدار وجدول العناوين قبل تقديم الإعداد.
لا توجد خريطة افتراضية أو اكتشاف إصدار أو استنتاج من نص السؤال.
الجسر يقارن دليل الكتالوج مع namespace وbook وSHA المدخل بالإضافة إلى الإصدار
والصف الرقميين. C3 لا يعرض archive SHA أو edition_key؛ لذلك مصدرهما هو الخريطة
البشرية الموثوقة، ولا يدّعي الجسر فحص ملف الأرشيف أو إثبات أصالته مستقلاً.
يمكن تمرير DjangoCatalog اختيارياً من `apps.reference_links.django_adapter`؛
لا يستورده الجسر ولا ينشئ اتصالاً ضمنياً. SnapshotCatalog هو البديل المعزول للعرض.

## التشغيل والنتائج الفعلية

```text
python -m unittest discover -s tests/reference_links -v
Ran 37 tests in 0.383s
OK

python -m unittest discover -s tests/reference_links -q
Ran 37 tests in 0.267s
OK

python -m apps.reference_links.demo
synthetic-1: verified (edition 41, row 73)
synthetic-2: unverified / explicit_mapping_missing

git diff --check
exit 0
```

مخرجات العرض الفعلية JSON إلى stdout؛ السطران أعلاه تلخيص حالتيه.
هوية fixture: `apps.reference_links.demo.fixtures`، namespace=synthetic-only،
book=622، edition_key=human-edition-A، archive SHA=`a` مكرر 64، input SHA=`b`
مكرر 64. هذه pins اصطناعية وليست SHA ملفات المالك.

الإحالة الناتجة:
«إحالة إلى عنوان في فهرس كشاف القناع — مثال اصطناعي: كتاب الطهارة / باب الطهارة،
ج الأول، ص 12 (عنوان فهرس، وليس نص فتوى).»
تُهرب علامات HTML والاقتباسات بواسطة html.escape؛ لا تُضاف المفاتيح الداخلية أو
الإصدار أو الناشر إلى النص العام. النتيجة الداخلية تحتوي أصل المؤشر ودليل الهوية،
وليست حمولة عامة للنشر. استخدام HTML يحتاج مراعاة عدم تكرار escaping.

أضيف 21 اختبارًا للجسر، مع 16 اختبارًا سابقًا: أشكال C1/C2 الحقيقية، جميع pins،
SHA الكتالوج، غياب الخريطة والمراجع، اصطدام الخرائط وتكرار المؤشرات، عزل الإصدار،
اختيار إصدار بشري مختلف، نقص الموقع، غموض الكتالوج، ثبات الإعداد، النص العربي
وحقن markup. اختبار الحظر يعطل builtins.open وsocket.socket أثناء الحل والعرض؛
لا يستخدم الاختبار قاعدة بيانات. العرض لا يستورد Django ولا يستخدم DjangoCatalog.

PostgreSQL والملفات الأصلية: NOT_RUN. لا استيراد أو ترحيل أو نشر أو حسابات أو
صلاحيات أو معالجة فيديو أو شبكة. لا commit أو push. NOT_DEPLOYED / GATES_HOLD؛
Gate B NOT_PASSED، C/D/E HOLD، Phase01 BLOCKED. التحقق يثبت تطابق هوية
مرجع الفهرس ضمن حدود المصدر المقدم، ولا يعتمد فتوى أو ملاءمتها للسؤال أو نشرها.
