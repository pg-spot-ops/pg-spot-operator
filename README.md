
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

## Via PyPI

```bash
pip install pg-spot-operator
pg_spot_operator --instance-name pg1 --region eu-north-1 --cpu-min 4 --storage-min 100
```
 
## Via Docker

```bash
docker run --rm --name pg1 -e PGSO_CPU_MIN=4 -e PGSO_STORAGE_MIN=100 \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro \
  pg-spot-ops/pg-spot-operator:latest
```
