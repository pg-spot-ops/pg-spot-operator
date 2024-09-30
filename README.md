
# Postgres Spot Operator [Community Edition]

Maintains stateful Postgres on AWS Spot VMs. Think of it as RDS, but at a fraction of the cost! Typical [savings](https://aws.amazon.com/ec2/spot/pricing/)
are in the ballpark of 4-5x.

Obviously for non-critical projects only, as utilizing Spot instances means can be interrupted by AWS at any time ...

Not a "real" K8s operator (yet, at least) - but based on similar concepts - user desired state manifests (optional) and
a restoration / reconciliation loop.

# General idea

* The user:
  - Specifies a set of few key parameters like region, minimum CPUs / RAM and storage size and type (network EBS volumes or local volatile storage)
  - Specifies or mounts (Docker) the cloud credentials if no default AWS CLI (~/.aws/credentials) set up
* The operator:
  - Finds the cheapest Spot instance for given HW requirements and launches a VM
  - Runs Ansible to set up Postgres
  - Keeps checking the VM health every minute and if evicted launches a new one, re-mounts the data volume and restarts Postgres

# Usage

## Python local dev/test in a virtualenv

```bash
git clone git@github.com:pg-spot-ops/pg-spot-operator.git
cd pg-spot-operator
make virtualenv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pg_spot_operator --verbose --instance-name pg1 --region eu-north-1 --cpu-min 2 --storage-min 100
```

## Via Docker

```bash
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro \
  pg-spot-ops/pg-spot-operator:latest
```

or more securely only passing the needed AWS secrets / public keys:

```bash
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -e PGSO_SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

# Technical details

## Main features

* Allows also to explicitly specify the target instance types
* Uses Debian-12 base images / AMI-s
* Installs Postgres from official PGDG repos, meaning you get instant minor version updates
* Allows override of ALL *postgresql.conf* settings if user wishes so
* Built-in basic tuning profiles for most common workloads (default, oltp, analytics, web)
* Maintains a single instance per daemon to KISS
* Supports only a single EBS volume
* Supports block level S3 backups / restores via pgBackRest, meaning acceptable RPO possible even with instance storage
* Can up/down-size the hardware requests

## Non-features

* No automated major version upgrades (stop the engine, do some magic, update the manifest `postgres_version`)
* No persistent state keeping by default - relying on a local SQLite DB file. User can solve that though by setting
  `--config-dir` to some persistent volume for example. Without that some superfluous work will be performed and
  instance / state change history lost, in case of a daemon node loss.

## Cleanup of all operator created objects

After some work / testing one can clean up all operator created cloud resources or only a single instance via
*PGSO_TEARDOWN_REGION* or *PGSO_TEARDOWN*.

```
docker run --rm --name pg1 -e PGSO_TEARDOWN_REGION=y -e PGSO_REGION=eu-north-1 \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

or by running a helper script from the "scripts" folders:

PS! You need to update the list of regions to your "operational area" first in the header.

```
./scripts/aws/delete_all_operator_tagged_objects.sh yes
```

A third option for local Docker convenience, to avoid a restart with different env inputs, is to create a dummy "destroy
file" in the container that signals instance shutdown:

```commandline
docker run ...
# Note the destroy file path from the log
2024-09-30 10:49:38,973 INFO Instance destroy signal file path: /tmp/destroy-pg1
...
docker exec -it pg1 touch /tmp/destroy-pg1
# On the next loop the resources will be cleaned up and the container shuts down
```


# Local non-cloud development

For Postgres setup testing, plus manifest handling etc, one can get by with local Virtualbox / Vagrant VMs, by using
according flags

```bash
git clone git@github.com:pg-spot-ops/pg-spot-operator.git
cd pg-spot-operator
make virtualenv
source .venv/bin/activate
pip install -r requirements-test.txt

vagrant up && vagrant ssh -c 'hostname -I'  #  Or similar, add dev machine SSH keys ...

# Dev / test stuff
python3 -m pg_spot_operator --verbose --instance-name pg1 --vm-host 192.168.121.182 --vm-login-user vagrant
# If changing Python code

make fmt && make lint && make test

git commit
```
