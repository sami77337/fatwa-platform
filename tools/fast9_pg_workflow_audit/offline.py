"""Fixed offline collection with inherited credential/DB variables removed."""

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--affected", action="store_true")
    args = parser.parse_args()
    from tools.dev.qa import environment

    clean = environment()
    os.environ.clear()
    os.environ.update(clean)
    import django

    django.setup()
    from django.test.runner import DiscoverRunner

    class NoDatabaseRunner(DiscoverRunner):
        def setup_databases(self, **kwargs):
            raise RuntimeError("Offline suite must never request database setup")

        def run_tests(self, test_labels, **kwargs):
            self.setup_test_environment()
            try:
                suite = self.build_suite(test_labels)
                if suite.countTestCases() < 1:
                    raise RuntimeError("Empty offline collection")
                self.run_checks(databases=[])
                result = self.run_suite(suite)
                return int(
                    not result.wasSuccessful()
                    or bool(result.skipped)
                    or bool(result.expectedFailures)
                )
            finally:
                self.teardown_test_environment()

    return NoDatabaseRunner(verbosity=2, interactive=False).run_tests(
        [
            "tests.editorial_demo.test_workflow_audit",
            "tests.editorial_demo.test_audit_provenance_projection",
            "tests.editorial_demo.test_audit_export_contract",
        ]
        if args.affected
        else [
            "tests.fast9_pg_workflow_audit.test_adapter",
            "tests.fast9_pg_workflow_audit.test_cli",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
