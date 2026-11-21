"""Set resource limits in a separate process, then exec only the configured scanner.

Never use preexec_fn in the threaded web process. This script has no Django or
database imports and receives no credentials or user-controlled command options.
"""

import json
import os
import resource
import sys


def main():
    request = json.loads(sys.argv[1])
    memory = request["memory_bytes"]
    cpu = request["cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (768000, 768000))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    command = request["command"]
    os.execve(command[0], command, dict(os.environ))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError):
        # Distinguish a wrapper/exec failure from ClamAV's detection status 1.
        sys.exit(70)
