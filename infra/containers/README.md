# Isolated development and test containers

This is an executable development environment for owner point453 / D-039, not a
production deployment or a claim that staging, workers and production operations
have been configured. The native application and unchanged source requirements
remain in this repository. No image is published and no existing database is used.

From a clean committed checkout on a machine with Docker:

```sh
python infra/containers/verify.py --postgres 17
python infra/containers/verify.py --postgres 18
```

The verifier pulls the official `python:3.13-slim-bookworm` image, resolves and
records its immutable repository digest, and uses that digest in the actual
build. The complete committed Git archive is the build context. Untracked files,
working changes and Git credentials cannot enter that archive. Python packages
use the existing exact runtime pins. PostgreSQL comes from the official PGDG
repository using the existing verified signing-key fingerprint. The resolved
base digest, image ID, source revision and source-archive digest are written into
each execution receipt; a moving base tag is not a reproducibility claim.

The runtime uses UID10001, a read-only root filesystem, no network interface other
than loopback, no published ports, no host directory or Docker-socket mount,
dropped capabilities and no-new-privileges. Only bounded temporary storage is
writable. Its PostgreSQL process is created, migrated and stopped by the same
owned-cluster runner as the existing test environment. Real native session
revocation, exact fresh confirmation, the credential budget and the closed
campaign composition are checked against that database. The source write probe
must fail with a read-only-filesystem error. The container is removed afterward.

`.local/qa/containers/pg17/` and `pg18/` contain the build log, runtime log and
`result.json`. A PASS requires actual image construction, inspected Docker
boundaries, four passing native/composition tests and an exact source-bound
runtime result. A syntax check or the presence of this Dockerfile cannot pass.
The independent `Isolated development containers` workflow performs both real
executions; its artifacts complement the full functional/browser/recovery suite.

There is no local Docker daemon in the recovery executor, so the first runtime
result must come from that hosted workflow. Until it succeeds, this feature is
implemented but unverified and is excluded from the 95-candidate functional
certificate. Final visual design, production TLS/storage/secrets, deployments and
live provider connections are outside this unit.

Primary format and runtime references:

- [Docker build contexts and archive input](https://docs.docker.com/build/concepts/context/)
- [Dockerfile instructions](https://docs.docker.com/reference/dockerfile/)
- [Docker runtime boundaries](https://docs.docker.com/reference/cli/docker/container/run/)
- [Official Python image](https://hub.docker.com/_/python)
- [Official PostgreSQL Debian packages](https://www.postgresql.org/download/linux/debian/)

## First inspected hosted proof

[Run44904565936](https://github.com/sami77337/fatwa-platform/actions/runs/44904565936)
passed on both PostgreSQL majors at `ad92317507375aaabfb7b22aabb958495ab8614b`.
Both ZIP artifacts were downloaded; archive, build-log and runtime-log hashes
were verified. The actual runtimes used PostgreSQL17.12 and18.7, UID10001,
network=none and read-only committed source, and each passed four native campaign
tests with the ownership-aware configured runner. The source write probe failed
as required. No image was published and no service was deployed. This validates
owner453 for this development-source checkpoint only; final-source execution is
still required. Exact IDs, hashes, runtime records and the earlier rejected
unwitnessed-database attempt are preserved in
`docs/product/functional_continuation/checkpoints/containers_ad923175.json`.
