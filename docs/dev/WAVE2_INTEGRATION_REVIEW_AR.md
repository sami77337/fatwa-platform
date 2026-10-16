# مراجعة تكامل الموجة الثانية

2026-10-16؛ الأساس: `0a858df1c135eb39b9d1c7d7e284d1779c04f1d9` مع تعديلات محلية غير ملتزمة.

الإصلاحات:
- توحيد خطأ تجاوز معاملات API إلى JSON بالحالة 400، مع تفعيل اختبار B5 السابق كاختبار نجاح مطلوب.
- إصلاح اكتشاف اختبارات B6 على Python 3.13 باستخدام مسارات المجلدات، وإدراج اختبارات API وSSR وأوامر التدقيق الجديدة. أضيف اختبار يكتشف المجموعات فعليًا دون تنفيذ اختبارات قاعدة البيانات.
- تصحيح ترتيب imports في اختبار B6 لاجتياز Ruff.

التحقق الفعلي:
- **PASS**: Node 24.16.0؛ 87 نجاحًا من 88، وSKIP واحد لغياب أرشيف المالك. الأمر: `python tools/dev/qa.py node`.
- **PASS**: Python 3.13.15 وDjango 5.2.18؛ فحص النظام `python tools/dev/qa.py system` دون فحص اتصال قاعدة البيانات.
- **PASS**: 79 اختبارًا دون قاعدة بيانات: `manage.py test tests/security tests/public_site tests/integration/api tests/integration/ui tests.integration.source.test_read_only_commands --settings=config.settings.test`. استُخدمت بيئة `tools.dev.qa.environment()` المنقاة مع منفذ PostgreSQL رقم 1؛ لا اتصال بالقاعدة الدائمة.
- **PASS**: 16 اختبارًا لأدوات التشغيل: `python -B -m unittest discover -s tests/dev -p "test_*.py" -q`.
- **PASS**: `ruff check apps config tests` و`git diff --check`.
- **FAIL**: مجموعة `tests/fiqh_import`: 82 اختبارًا، 77 نجاحًا، 4 SKIP، وخطأ واحد في `test_checked_in_fixture_identity_and_five_level_tree`. يثبت `git ls-files --eol` أن العينة الاصطناعية `synthetic-five-level.json` هي `i/lf w/crlf`؛ لا تطابق بصمتها المثبتة. لم تُغيّر العينة أو البصمة ولم يُخف الاختبار.
- **NOT_RUN**: PostgreSQL وDocker وmigrations وقبول المصدر الحقيقي ذي 11,397 عنوانًا والمتصفح الحقيقي/الجوال. لم يُشغّل مسار PostgreSQL لأنه ينفذ migrations، وهي ممنوعة في هذه المهمة.

راجعت تكامل المسارات وAPI والقوالب والبحث والتنقل والإحالات. تبقى الطبعة والناشر ومعرّفات المصدر خارج العرض العام مع حفظ metadata في API، وعنوان العمل والجزء والصفحة ظاهرة. اختبارات الواجهة تستخدم DOM محاكى؛ لا تعادل قبول لوحة مفاتيح أو متصفح حقيقي.

لم أتصل بقاعدة البيانات الدائمة، ولم أعد استيراد المصدر، ولم أغيّر حواجز سلامة S0 أو أشغّل وظائف خاصة. جميع التعديلات في INTEGRATED فقط، دون commit أو نشر أو حسابات خارجية. **NOT_DEPLOYED / GATES_HOLD**.
