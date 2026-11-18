# V13 P0-C — تحليل D6 وحدود دليل startup

**النتيجة: `ROOT_CAUSE_UNKNOWN`.** ثبت timeout تاريخي ثم نجاح على SHA نفسه؛
لم تثبت علة timeout، ولم يُصلح هذا المسار علة مجهولة أو يرفع المهلة أو يصنفها
flake. نجاح الإعادة لا يمحو فشل المحاولة الأصلية.

الأساس المتحقق من GitHub PR #231 وremote هو
`5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8`، وفرع العمل
`codex/20261118-v13-d6-analysis`. فرع V12 محفوظ. قُرئ AGENTS.md وتتبع النطاق
ومصفوفة V12 وعقد الاختبارات والكود الفعلي؛ لا `.agents/skills` في checkout.
الملكية محصورة في هذا التقرير و`tests/v13_browser_startup/**`.

Gate B NOT_PASSED / C-D-E HOLD / Phase01 BLOCKED / NOT_DEPLOYED.
لا تقدير إنجاز جديد، ولا قبول أو تشغيل حقيقي أو صلاحيات جديدة.

## الأدلة التي جُلبت فعلًا

في 2026-11-18 UTC جُلب السجلان المفكوكان كاملين عبر GitHub connector، لا من
وصف PR وحده. جُلبت أيضًا steps للمحاولة الفاشلة وjobs/artifacts للـrun.

- [المحاولة الفاشلة 134488475034](https://github.com/sami77337/fatwa-platform/actions/runs/44210846285/job/134488475034).
- [المحاولة الناجحة 134490343087](https://github.com/sami77337/fatwa-platform/actions/runs/44210846285/job/134490343087).
- [المقتطف الفاشل](../../tests/v13_browser_startup/evidence/134488475034.excerpt.log)
  و[المقتطف الناجح](../../tests/v13_browser_startup/evidence/134490343087.excerpt.log)
  يحتفظان بتوقيتات السجل الأصلية. [manifest](../../tests/v13_browser_startup/evidence/manifest.json)
  يسجل أرقام الأسطر الأصلية، وبصمات النص المفكوك الكامل والمقتطفات.
- [المقارنة القابلة للتحقق](../../tests/v13_browser_startup/evidence/comparison.json)
  مشتقة من السجلين الكاملين. تعريف بصمة النص: UTF-8 دون BOM، توحيد CRLF إلى LF،
  ونهاية LF واحدة. ليست بصمة أرشيف GitHub الخام.

أعادت خدمة artifact metadata رابطًا لكل أرشيف، لكن تنزيل البايتات إلى البيئة
أعاد HTTP403 في الحالتين. لذلك **لم تُفحص محتويات ZIP أو بصمتها محليًا**:

| المحاولة | Artifact | حجم وبصمة معلنان من API/سجل الرفع، غير متحققين من البايتات محليًا |
|---|---|---|
| الفشل | `14385812610` | 7902 bytes؛ `29d66fe1b420a709591ede0ec06c2981772ea7f6e84ca44e2201289808c46185` |
| النجاح | `14386960099` | 2717910 bytes؛ `44044ce7864f501525c1a9068be000cca5edaa70e201587ae63ce6a04322f445` |

التطابق بين metadata وسجل الرفع ليس بديلًا عن فحص ZIP. لم تُحفظ روابط التنزيل
الموقعة أو بيانات اعتماد في المستودع. لم تُطلب إعادة workflow/job أو تغييرات GitHub.

## المقارنة المثبتة

| المعلومة | الفشل | النجاح |
|---|---|---|
| checkout `git log -1 --format=%H` | `5ec6373…` | SHA نفسه كاملًا |
| runner/image | 2.338.2؛ ubuntu-26.04؛ 20261111.196.1 | نفسها |
| Chrome | 157.0.8103.50 | نفسها |
| Node / Python | v24.22.2 / 3.13.18 | نفسها |
| العامل / المنطقة | عامل `b58898e5…`، westus | عامل `ed8769cb…`، centralus |
| بدء خطوة FAST6، UTC | 00:49:23.2391780 | 00:53:05.6705543 |
| نتيجة تقرير رحلة FAST6 | NOT_RUN | PASS |
| failure | BROWSER_STARTUP_TIMEOUT، websocket، cause_code=null | لا failure |
| startup | websocket؛ 30001ms / 30000ms | ready؛ 642ms / 30000ms |
| cleanup المبلغ عنه | PASS، errors=[] | نفسه |
| diagnostics | stderr_present=true؛ stderr_hints=[] | نفسها |
| وحدة Python، اختباران | فشل واحد؛ 50.939s | 2/2 PASS؛ 22.080s |
| عقود startup الاصطناعية ضمن الاختبار الثاني | PASS؛ D6_REGISTERED_TESTS=12 | نفسها |
| الخطوتان التاليتان FAST8 / FAST7B | skipped بسبب فشل FAST6 | success |

تقرير الرحلة الأولى خرج بالرمز 2 (NOT_RUN)، ففشل assertion الذي يطلب 0،
وأغلقت خطوة Python بالرمز 1. لا تعارض بين NOT_RUN للرحلة وFAIL للخطوة التي
تتطلب تشغيلها. Cleanup PASS لا يحولها إلى PASS. كما أن نجاح اختبارات lifecycle
المحاكية ليس نجاح رحلة Chrome التي توقفت قبل assertions.

سجل الخطوات الفاشلة يثبت skips اللاحقة؛ نجاح الإعادة لا ينقل نتائجها إلى
المحاولة الأولى. وتبقى أربعة اختبارات تعتمد أصل المالك skipped بسبب غياب ZIP؛
قبول مصدر المالك NOT_RUN. FAST6 هنا يستخدم catalog اصطناعيًا ثابتًا بلا قاعدة
بيانات، فلا يُستنتج منه قبول PostgreSQL أو بيانات حقيقية.

## ماذا تعني مرحلة websocket؟

سلسلة الكود عند SHA المثبت:

1. [test_browser.py](../../tests/fast6_journey/test_browser.py) يشغل
   `tests/research_bridge/browser.mjs` ثم يطلب نتيجة PASS.
2. [research startup](../../tests/research_bridge/startup.mjs) يستدعي
   `ProtectedBrowser.start()` قبل أي assertions للرحلة، ويحفظ تصنيف الخطأ وcleanup.
3. [ProtectedBrowser](../../tests/acceptance/fastbuild/startup.mjs) يبدأ **مؤقتًا
   واحدًا** قبل إنشاء profile وتشغيل supervisor وقراءة DevToolsActivePort، ثم
   target-discovery، ثم WebSocket. `elapsedMs` يقيس هذه السلسلة كاملة.
4. الوصول إلى stage=websocket يعني أن قراءة port وtarget-discovery رجعتا بعد
   التحقق من endpoint محلي مطابق. يعني timeout أن start لم يصل إلى ready قبل
   المهلة. لا يعطي توقيت بداية handshake أو إتمام TCP/HTTP Upgrade أو ترتيب
   الأحداث المتزامنة مع انتهاء المهلة.

إذًا **30001ms ليست قياسًا مثبتًا لمدة WebSocket وحده**. والـ1ms فوق الحد
المعلن لا يثبت تغيير المهلة؛ القيمة قياس وقت الخروج الكلي، وليست مهلة جديدة.
لا نستطيع توزيع الثلاثين ثانية بين المراحل من هذين التقريرين.

## ما لم يثبت والسبب يبقى مجهولًا

- اختلاف العامل والمنطقة حقيقة مقارنة، وليس دليلًا أن المنطقة أو ازدحام العامل
  سبب الفشل. لا قياسات CPU/RSS/fd/event-loop lag أو حمل متزامن مرتبطة بالمحاولة.
- لا يوجد هنا trace لتوقيتات المراحل أو WebSocket upgrade/فتح/إغلاق. لا دليل
  يميز تعطل Chrome عن تأخر Node أو مورد نظام أو مشكلة IPC/loopback.
- الكود يحتفظ بآخر 1500 محرف من stderr ثم ينشر قائمة hints محددة فقط بعد cleanup؛
  `stderr_present=true` ليس تشخيصًا، وغياب hints لا ينفي سببًا خارج الأنماط أو
  رسالة أقدم خرجت من النافذة. لا raw stderr كامل قابل للتحليل في السجلين.
- لا يثبت timeout خللًا في assertions التطبيق، لأنها لم تبدأ. لكنه لا يثبت خلو
  كامل النظام من العيوب. لا علة أمنية مثبتة من هذه الأدلة.
- النجاح الثاني يثبت عدم تكرر الفشل في تلك المحاولة فقط، ولا يحدد معدل الفشل
  أو إصلاحًا دائمًا أو مبررًا لتسمية الحدث flake. لا مقارنة فعلية لنفس العامل.

## ما أضيف داخل الملكية

- `analyze_logs.py`: مقارنة محدودة ومخرجات allowlist؛ ترفض SHA خاطئًا أو سجلًا
  غامضًا أو JSON مكرر المفاتيح أو تعديل مهلة startup أو إعادة تسمية NOT_RUN.
  تحفظ الفشل والنجاح مستقلين وتصدر ROOT_CAUSE_UNKNOWN دائمًا لهذه الأدلة؛ ليست
  محرك استنتاج للعلة. لا تنفذ أي نص أو رابط أو أمر في السجلات.
- 8 اختبارات attribution/negative/privacy، مع مقتطفات وبصمات قابلة لإعادة الفحص.
- 3 اختبارات Node تستعمل lifecycle الحالي دون تعديل ملفات مشتركة: حد 30000ms،
  مهلة مشتركة بين المراحل، وبقاء NOT_RUN دون استدعاء رحلة أو إعادة محاولة.
  الـpeer محاكي loopback صريح، وليس Chrome ولا provider حقيقيًا.

**النتائج المحلية:** Python 3.13.16، Node v24.19.0؛ 8/8 Python PASS و3/3 Node
PASS (4.153s؛ لا skips). المثال التشخيصي بلغ timeout عند websocket بعد 2001ms
إجمالية، منها 815ms عند port-file؛ يثبت دلالة القياس ولا يعيد إنتاج العلة
التاريخية. مهلة 2000ms تخص peer الاختبار فقط؛ المهلة المشتركة 30000ms لم تتغير.
Ruff PASS. لم يُعد تشغيل suites المنتج أو PG أو Chrome الحقيقي.

```sh
.venv/bin/python -m unittest tests.v13_browser_startup.test_evidence -v
FATWA_FASTBUILD_PYTHON="$PWD/.venv/bin/python" \
  node --test tests/v13_browser_startup/startup_contract.test.mjs

# مقارنة سجلات كاملة جُلبت من المصدر، لا وصف PR:
.venv/bin/python -m tests.v13_browser_startup.analyze_logs \
  --failure /path/to/134488475034.log --success /path/to/134490343087.log \
  --expected-sha 5ec6373f5eaf3cd5ea2b14d7b3e7119826ceb4c8
```

## عقد التوصيل للمكامل

1. أضف الأمرين التشخيصيين إلى تحقق P0-C مع عدّ 8 Python و3 Node؛ لا تستبدل بهما
   اختبار FAST6 الحقيقي، ولا تعد تشغيل suites المنتج لأجل هذا التحليل وحده.
2. تغييرات instrumentation المشتركة **مقترحة وغير منفذة هنا**: سجل elapsed
   monotonic لكل من spawn/port/target/WebSocket، والميزانية المتبقية، وأحداث
   socket open/error/close بتصنيفات ثابتة، وحالة خروج supervisor. احفظ SHA
   وإصدار الأدوات وrun/job/attempt بجانب التقرير، لا آخر نتيجة فقط.
3. لا تجمع raw URLs/DevTools IDs/profile paths/credentials أو raw stderr في
   artifacts العامة. أضف counters/hints ثابتة وقت الحدث إذا لزم، دون تغيير
   endpoint validation أو sandbox أو cleanup أو الاستمرار بعد failure.
4. يلزم تعديل الملفات المشتركة وCI بواسطة المكامل إذا تبنى هذه القياسات؛
   الحالية لا تكفي لتعيين السبب بأثر رجعي. لا retry آلي ولا رفع deadline.

يبقى التحقيق السببي مفتوحًا عند ROOT_CAUSE_UNKNOWN. هذه نتيجة مكتملة للتحليل
المفوض، وليست إصلاحًا مثبتًا للفشل أو قبولًا أو انتقالًا تلقائيًا لحملة أخرى.
