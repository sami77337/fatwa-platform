"""Bound complete human mappings to the native request budget on upgrade too."""

from importlib import import_module

from django.db import migrations

_PREVIOUS = import_module("apps.development_taxonomy.migrations.0002_integrity").SQL
_REVERSE = _PREVIOUS.split("CREATE TRIGGER dt_tree_guard", 1)[0].replace(
    "CREATE FUNCTION development_taxonomy_guard()",
    "CREATE OR REPLACE FUNCTION development_taxonomy_guard()",
    1,
)
_MARKER = "  old_ids:=ARRAY(SELECT value->>'id' FROM jsonb_array_elements(oldv.nodes));"
_BUDGET = """  IF (SELECT coalesce(sum(jsonb_array_length(value->'targets')),0)
      FROM jsonb_array_elements(NEW.mapping))>256
  THEN RAISE EXCEPTION 'taxonomy mapping edge budget exceeded' USING ERRCODE='23514'; END IF;
"""
assert _REVERSE.count(_MARKER) == 1
_FORWARD = _REVERSE.replace(_MARKER, _BUDGET + _MARKER, 1)


class Migration(migrations.Migration):
    dependencies = [("development_taxonomy", "0002_integrity")]
    operations = [migrations.RunSQL(_FORWARD, _REVERSE)]
