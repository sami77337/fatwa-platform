# The verifier resolves this official Python tag to its digest before the build.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG POSTGRES_MAJOR=18
ARG SOURCE_REVISION
LABEL org.opencontainers.image.source="https://github.com/sami77337/fatwa-platform" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Fatwa Platform isolated development verification"

RUN test "$POSTGRES_MAJOR" = 17 || test "$POSTGRES_MAJOR" = 18
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl --fail --silent --show-error --location \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/pgdg.asc \
    && test "$(gpg --batch --show-keys --with-colons /tmp/pgdg.asc | awk -F: '$1 == "fpr" {print $10; exit}')" = B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8 \
    && install -m 644 /tmp/pgdg.asc /usr/share/keyrings/fatwa-pgdg.asc \
    && printf 'deb [signed-by=/usr/share/keyrings/fatwa-pgdg.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main\n' > /etc/apt/sources.list.d/fatwa-pgdg.list \
    && install -d /etc/postgresql-common \
    && printf 'create_main_cluster = false\n' > /etc/postgresql-common/createcluster.conf \
    && apt-get update -qq \
    && apt-get install -y --no-install-recommends "postgresql-${POSTGRES_MAJOR}" ffmpeg \
    && rm -rf /var/lib/apt/lists/* /tmp/pgdg.asc \
    && groupadd --gid 10001 fatwa \
    && useradd --no-log-init --uid 10001 --gid 10001 --create-home fatwa

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --no-deps -r requirements.txt
COPY . /app
RUN install -d -o 10001 -g 10001 /app/.local \
    && install -o 10001 -g 10001 -m 0600 /dev/null /app/runtime-readonly-probe

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FATWA_PRODUCTION=0 \
    FATWA_CONTAINER_POSTGRES_MAJOR=${POSTGRES_MAJOR} FATWA_CONTAINER_SOURCE=${SOURCE_REVISION}
USER 10001:10001
ENTRYPOINT ["python", "infra/containers/runtime.py"]
