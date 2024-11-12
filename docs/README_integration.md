# Integrating with user applications

Although the Community Edition is optimized for more light use, one can use it also to power real applications (given
they cope with the possible service interruptions of course) by either providing a "setup finished" callback hook or just
running in special `--connstr-output-only` mode.

## Pipe-friendly `--connstr-output-only` mode

Engine ensures VM, sets up Postgres if needed in quiet mode, prints connstr and exits. Example usage:

```
docker run --rm -e PGSO_CONNSTR_OUTPUT_ONLY=y -e PGSO_REGION=eu-north-1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_STORAGE_MIN=100 pg-spt \
  | run_some_testing \ 
  && docker run --rm -e PGSO_TEARDOWN=y -e PGSO_REGION=eu-north-1 -e PGSO_INSTANCE_NAME=pg1
```

## Setup finished callback file usage

Currently the callback be a self-contained executable which gets following 4 input parameters for propagations into "somewhere":

- Instance name
- Private full connect string a la `postgresql://postgres@localhost:5432/postgres`
- Public full connect string, when `public_ip_address: true` is set, else an empty string
- User provided tags as JSON, if any

PS Note that the callback execution is **limited to 30 seconds!**

Example usage:

```commandline
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -e PGSO_SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  -e PGSO_SETUP_FINISHED_CALLBACK="/my_callback.sh" -v "$HOME/my_callback.sh":/my_callback.sh \
  pgspotops/pg-spot-operator:latest
```