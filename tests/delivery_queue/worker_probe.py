"""Subprocess test probe, restricted to the runner's already-owned test database."""
import json
import sys


def main():
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections
    from apps.delivery_queue.services import claim_next
    if len(sys.argv) != 3 or sys.argv[1] != settings.WAVE7_TEST_DATABASE_NAME:
        raise RuntimeError('exact_owned_test_database_required')
    connection = connections['default']
    connection.close()
    connection.settings_dict['NAME'] = sys.argv[1]
    try:
        lease = claim_next(provider='reply-source', worker_id=sys.argv[2])
        # Never print the reservation token or connection details.
        print(json.dumps({'intent_key': lease.intent_key if lease else None}))
    finally:
        connections.close_all()


if __name__ == '__main__':
    main()
