
# Postgres Spot Operator [Community Edition]

Maintains stateful Postgres on Spot VMs.

AWS only for now.

Not a "real" K8s operator (yet) - but does the same basically. 

# General idea

1. The user specifies a few key parameters like region, minimum CPU count and storage size
2. Specifies or mounts (Docker) the cloud credentials
3. The operator finds the cheapest Spot instance for given HW requirements and launches as VM
4. Runs Ansible to set up Postgres
5. Keeps checking the VM health and if evicted launches a new one, re-mounts the data volume and restarts Postgres   


# Usage

PS! Expects a working AWS CLI setup (~/.aws/credentials)

## Python local dev/test in a virtualenv

```bash
make virtualenv
source .venv/bin/activate
pip install -r requirements-test.txt
python3 -m pg_spot_operator --verbose --instance-name pg1 --region eu-north-1 --cpu-min 4 --storage-min 100
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
