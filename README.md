
# Postgres Spot Operator [Community Edition]

Maintains stateful Postgres on AWS Spot VMs. Think of it as RDS, but at a fraction of the cost! Typical [savings](https://aws.amazon.com/ec2/spot/pricing/)
are in the ballpark of 4-5x.

Obviously for non-critical projects only, as dealing with Spot instances that can be interrupted by AWS at any time ...

Not a "real" K8s operator (yet, at least) - but based on similar concepts - user desired state manifests (optional) and
a restoration / reconciliation loop.

# General idea

* The user:
  - Specifies a few key parameters like region, minimum CPU count and storage size
  - Specifies or mounts (Docker) the cloud credentials if no default AWS CLI (~/.aws/credentials) set up
* The operator:
  - Finds the cheapest Spot instance for given HW requirements and launches a VM
  - Runs Ansible to set up Postgres
  - Keeps checking the VM health every minute and if evicted launches a new one, re-mounts the data volume and restarts Postgres

# Usage

## Python local dev/test in a virtualenv

```bash
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

## Cleanup of all operator created objects

After some work / testing one can clean up all operator created cloud resources via:

```
docker run --rm -e PGSO_TEARDOWN_REGION=y -e PGSO_REGION=eu-north-1 \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

or by running a helper script from the "scripts" folders:

```
./scripts/aws/delete_all_operator_tagged_objects.sh yes
```
