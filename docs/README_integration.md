# Integrating with user applications

Although the Community Edition is optimized for more light use, one can use it also to power real applications (given
they cope with the possible service interruptions of course) by either:

* Providing a "setup finished" callback script to do "something" with the resulting VM / Postgres info
* Running in special `--connstr-only` mode
* Specifying an S3 (or compatible) bucket where to push the connect string
* Writing the connect string to a file on the engine node

PS The connect string can be outputted in following formats:

`--connstr-format = auto* | ssh | ansible | postgres`

## Pipe-friendly `--connstr-only` mode

Engine ensures VM, sets up Postgres if needed in quiet mode, prints connstr and exits. Example usage:

```
docker run --rm -e CONNSTR_ONLY=y -e REGION=eu-north-1 -e INSTANCE_NAME=pg1 -e STORAGE_MIN=100 pg-spt \
  | run_some_testing \ 
  && docker run --rm -e TEARDOWN=y -e REGION=eu-north-1 -e INSTANCE_NAME=pg1
```

## Writing the connect string to a file on the engine node

Just specify a full file path via `--connstr-output-path` or `CONNSTR_OUTPUT_PATH`, that the engine node has
write privileges to.

## Pushing connect info to S3

For convenient app integration the operator can push the connect details to S3 or S3 compatible buckets. The bucket must
be pre-existing!

Relevant input parameters / Env vars:

```
  --connstr-bucket / CONNSTR_BUCKET (Required for S3 push to work)
  --connstr-bucket-key / CONNSTR_BUCKET_KEY (Required for S3 push to work)
  --connstr-bucket-region / CONNSTR_BUCKET_REGION
  --connstr-bucket-endpoint / CONNSTR_BUCKET_ENDPOINT
  --connstr-bucket-access-key / CONNSTR_BUCKET_ACCESS_KEY
  --connstr-bucket-access-secret / CONNSTR_BUCKET_ACCESS_SECRET
```

E.g. a sample config looks something like:

```
pg_spot_operator ... --connstr-bucket app1cs --connstr-bucket-endpoint https://9e61e4.r2.cloudflarestorage.com \
  --connstr-bucket-key connstr.json --connstr-bucket-access-key aaa --connstr-bucket-access-secret bbbb
```

Format of data written into the bucket:

```
{
  "connstr": "postgresql://app1:secret@1.1.1.1:5432/postgres?sslmode=require",
  "instance_name": "app1",
  "ip_public": "1.1.1.1",
  "ip_private": "2.2.2.2",
  "admin_user": "app1",
  "admin_password": "secret",
  "app_db_name": "postgres"
}

```

## Setup finished callback file usage

Currently the callback be a self-contained executable which gets following 4 input parameters for propagations into "somewhere":

- Instance name
- Private full connect string a la `postgresql://postgres@localhost:5432/postgres`
- Public full connect string, when `public_ip_address: true` is set, else an empty string
- User provided tags as JSON, if any

PS Note that the callback execution is **limited to 30 seconds!**
Also - for `--vm-only` mode the VM IP addresses are used instead of Postgres connect strings.

Example usage:

```commandline
docker run --rm --name pg1 -e INSTANCE_NAME=pg1 -e REGION=eu-north-1 \
  -e STORAGE_MIN=100 -e STORAGE_TYPE=local -e CPU_MIN=2 \
  -e SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" \
  -e AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  -e SETUP_FINISHED_CALLBACK="/my_callback.sh" -v "$HOME/my_callback.sh":/my_callback.sh \
  pgspotops/pg-spot-operator:latest
```