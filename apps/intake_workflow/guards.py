"""Sole Wave7 write/ownership guard. No caller-supplied scope or connection config."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import re

from django.conf import settings
from django.db import DatabaseError, connections, transaction
from .contracts import CONTRACT_VERSION, DATABASE_ROLE, SOURCE_CONFIG_ID, SYNTHETIC_SCOPE

OWNERSHIP_TABLE = 'wave7_synthetic_ownership'
WRITE_TAG = SYNTHETIC_SCOPE + '/' + SOURCE_CONFIG_ID


class SyntheticWriteDenied(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # fixed codes only; never a DSN, payload or credential


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    using: str
    database_name: str
    base_name: str
    test_name: str
    scope: str = SYNTHETIC_SCOPE
    source_config_id: str = SOURCE_CONFIG_ID


@dataclass(frozen=True, slots=True)
class WriteContext:
    using: str
    database_name: str
    database_oid: int
    scope: str = SYNTHETIC_SCOPE
    source_config_id: str = SOURCE_CONFIG_ID


def _require(condition, code):
    if not condition:
        raise SyntheticWriteDenied(code)


def validate_write_configuration(*, synthetic_fixtures_only: bool = False,
                                 using: str = 'default') -> DatabaseTarget:
    _require(synthetic_fixtures_only is True, 'SYNTHETIC_ACK_REQUIRED')
    _require(os.environ.get('FATWA_WAVE7_SYNTHETIC_WRITES') == '1', 'WRITES_DISABLED')
    _require(os.environ.get('FATWA_PRODUCTION') == '0', 'PRODUCTION_FLAG_REQUIRED')
    _require(using == 'default', 'UNSAFE_DATABASE_ALIAS')
    _require(getattr(settings, 'WAVE7_SCOPE', None) == SYNTHETIC_SCOPE
             and getattr(settings, 'WAVE7_SOURCE_CONFIG_ID', None) == SOURCE_CONFIG_ID,
             'UNTRUSTED_SCOPE_OR_SOURCE_CONFIG')
    _require(not any(os.environ.get(key) for key in ('DATABASE_URL','PGSERVICE',
        'PGSERVICEFILE','PGHOSTADDR','PGPASSFILE','PGOPTIONS')), 'UNSAFE_CONNECTION_OVERRIDE')
    db = settings.DATABASES.get('default', {})
    base = getattr(settings, 'WAVE7_BASE_DATABASE_NAME', '')
    test = getattr(settings, 'WAVE7_TEST_DATABASE_NAME', '')
    _require(isinstance(base, str) and re.fullmatch(r'wave7_synthetic_[a-z0-9_]{1,40}', base)
             and test == 'test_' + base, 'UNSAFE_DATABASE_NAMES')
    _require(db.get('ENGINE') == 'django.db.backends.postgresql'
             and db.get('HOST') == '127.0.0.1' and db.get('USER') == DATABASE_ROLE
             and db.get('NAME') in (base, test) and db.get('TEST', {}).get('NAME') == test,
             'UNSAFE_DATABASE')
    port = str(db.get('PORT', ''))
    _require(re.fullmatch('[0-9]{1,5}', port) and 1 <= int(port) <= 65535, 'UNSAFE_DATABASE_PORT')
    return DatabaseTarget(using, db['NAME'], base, test)


def _connection(target):
    return connections[target.using]


def _outside_transaction(connection):
    _require(not connection.in_atomic_block and connection.get_autocommit(),
             'GUARD_BEFORE_TRANSACTION_REQUIRED')


def _metadata(connection, target):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, current_setting('server_version_num')::int, "
                       "(SELECT oid FROM pg_database WHERE datname = current_database())")
        name, role, version, oid = cursor.fetchone()
    _require(name == target.database_name and role == DATABASE_ROLE and version // 10000 in (17, 18),
             'ACTUAL_DATABASE_IDENTITY_MISMATCH')
    return int(oid)


def _owned_context(connection, target, oid):
    with connection.cursor() as cursor:
        cursor.execute("SELECT c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c "
                       "JOIN pg_namespace n ON n.oid=c.relnamespace "
                       "WHERE n.nspname='public' AND c.relname=%s", [OWNERSHIP_TABLE])
        _require(cursor.fetchone() == ('r', DATABASE_ROLE), 'DATABASE_OWNERSHIP_REQUIRED')
        cursor.execute('SELECT scope, source_config_id, contract_version, database_name, database_oid '
                       'FROM public.wave7_synthetic_ownership')
        rows = cursor.fetchmany(2)
    _require(rows == [(SYNTHETIC_SCOPE, SOURCE_CONFIG_ID, CONTRACT_VERSION, target.database_name, oid)],
             'DATABASE_OWNERSHIP_MISMATCH')
    return WriteContext(target.using, target.database_name, oid)


def require_owned_database(*, synthetic_fixtures_only: bool = False,
                            using: str = 'default') -> WriteContext:
    target = validate_write_configuration(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    try:
        connection = _connection(target)
        _outside_transaction(connection)
        return _owned_context(connection, target, _metadata(connection, target))
    except DatabaseError:
        raise SyntheticWriteDenied('DATABASE_UNAVAILABLE_OR_UNTRUSTED') from None


def require_synthetic_write(*, synthetic_fixtures_only: bool = False,
                            using: str = 'default') -> WriteContext:
    context = require_owned_database(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                       "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                       "AND t.tgname='w7_00_synthetic_write_guard' AND NOT t.tgisinternal "
                       "AND t.tgenabled IN ('O','A') AND c.relname = ANY(%s)",
                       [['intake_workflow_'+name for name in ('intakebatch','intakeitem','intakereference','reviewevent')]])
        _require(cursor.fetchone()[0] == 4, 'WORKFLOW_SCHEMA_NOT_READY')
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                       "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                       "AND c.relname='intake_workflow_intakebatch' AND NOT t.tgisinternal "
                       "AND t.tgname='w7_15_unique_json_keys' AND t.tgenabled IN ('O','A'))")
        _require(cursor.fetchone()[0], 'WORKFLOW_SCHEMA_NOT_READY')
    return context


def initialize_synthetic_database(*, synthetic_fixtures_only: bool = False,
                                  using: str = 'default') -> WriteContext:
    """Explicit empty-DB claim; existing owned data is checked and never reset."""
    target = validate_write_configuration(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    connection = _connection(target)
    locked = False
    try:
        _outside_transaction(connection)
        oid = _metadata(connection, target)
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(73907, 1705)')
            locked = True
            cursor.execute("SELECT to_regclass('public.wave7_synthetic_ownership')")
            if cursor.fetchone()[0] is not None:
                return _owned_context(connection, target, oid)
            # Only PostgreSQL's actual system/temporary schemas are exempt. LIKE
            # 'pg_%' also hides ordinary names such as pgxforeign ('_' is a wildcard).
            cursor.execute("SELECT oid,nspname FROM pg_namespace WHERE nspname NOT IN "
                           "('pg_catalog','pg_toast','information_schema') "
                           "AND nspname !~ '^pg_(toast_)?temp_[0-9]+$'")
            namespaces = cursor.fetchall()
            _require(all(name == 'public' for _,name in namespaces), 'UNKNOWN_NONEMPTY_DATABASE')
            user_oids = [oid for oid,_ in namespaces]
            # Relations/functions alone miss standalone enum/domain types and
            # other user metadata. These fixed catalog/column names are internal.
            for catalog,column in (
                ('pg_class','relnamespace'), ('pg_proc','pronamespace'),
                ('pg_type','typnamespace'), ('pg_collation','collnamespace'),
                ('pg_conversion','connamespace'), ('pg_operator','oprnamespace'),
                ('pg_opclass','opcnamespace'), ('pg_opfamily','opfnamespace'),
                ('pg_ts_config','cfgnamespace'), ('pg_ts_dict','dictnamespace'),
                ('pg_ts_parser','prsnamespace'), ('pg_ts_template','tmplnamespace'),
                ('pg_statistic_ext','stxnamespace'), ('pg_extension','extnamespace'),
            ):
                cursor.execute(f'SELECT EXISTS (SELECT 1 FROM pg_catalog.{catalog} '
                               f'WHERE {column} = ANY(%s))', [user_oids])
                _require(not cursor.fetchone()[0], 'UNKNOWN_NONEMPTY_DATABASE')
        # All rejecting preflight checks above run before atomic()/DDL.
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE public.wave7_synthetic_ownership ('
                    'singleton smallint PRIMARY KEY CHECK(singleton=1), scope text NOT NULL, '
                    'source_config_id text NOT NULL, contract_version text NOT NULL, '
                    'database_name text NOT NULL, database_oid bigint NOT NULL)')
                cursor.execute('INSERT INTO public.wave7_synthetic_ownership VALUES (1,%s,%s,%s,%s,%s)',
                    [SYNTHETIC_SCOPE, SOURCE_CONFIG_ID, CONTRACT_VERSION, target.database_name, oid])
                cursor.execute("""CREATE FUNCTION public.wave7_ownership_immutable() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Wave7 ownership is immutable'
                    USING ERRCODE='23514'; END; $$;
                    CREATE TRIGGER wave7_ownership_immutable BEFORE UPDATE OR DELETE
                    ON public.wave7_synthetic_ownership FOR EACH ROW
                    EXECUTE FUNCTION public.wave7_ownership_immutable();""")
        return _owned_context(connection, target, oid)
    except DatabaseError:
        raise SyntheticWriteDenied('DATABASE_UNAVAILABLE_OR_UNTRUSTED') from None
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(73907, 1705)')


@contextmanager
def synthetic_atomic(*, synthetic_fixtures_only: bool = False, using: str = 'default'):
    """Canonical E1/E2/E3 unit of work: sole guard BEFORE transaction.atomic()."""
    context = require_synthetic_write(synthetic_fixtures_only=synthetic_fixtures_only, using=using)
    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            # Transaction-local application tag, not a role/server/security setting.
            cursor.execute("SELECT set_config('fatwa.wave7_synthetic_write', %s, true)", [WRITE_TAG])
        yield context


def require_owned_migration(sender, using, **kwargs):
    """Registered only when the separate Wave7 dev/test app is installed."""
    require_owned_database(synthetic_fixtures_only=True, using=using)
