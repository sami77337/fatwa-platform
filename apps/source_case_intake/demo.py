"""Run with the owned PostgreSQL helper; reports no secret capabilities."""

import json

import django


def main():
    django.setup()
    from django.test import override_settings

    from . import services, simulators

    results = []
    with override_settings(FATWA_SOURCE_CASE_INTAKE_ENABLED=True):
        for source in ("telegram", "youtube", "website"):
            fixture = getattr(simulators, source)
            args = dict(context=simulators.context(source), synthetic_fixtures_only=True)
            first = services.ingest(raw=fixture(), **args)
            following = services.ingest(raw=fixture(2, parent=1), token=first["token"], **args)
            results.append(
                {
                    "source": source,
                    "root": first["status"],
                    "reply": following["status"],
                    "public_ref": first["public_ref"],
                }
            )
    print(json.dumps({"synthetic_only": True, "cases": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
