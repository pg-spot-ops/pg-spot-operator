
# PG Spot Operator [Community Edition]

Think of it as RDS, but at a fraction of the cost! Typical [savings](https://aws.amazon.com/ec2/spot/pricing/) are around
5x compared to [RDS](https://aws.amazon.com/rds/postgresql/pricing/).

Obviously not mean for all projects as a general RDS replacement, as utilizing Spot instances means one can be interrupted
by AWS at any time, and it takes a few minutes to restore the state.

But on the other hand - eviction rates are insanely good for the price! The average frequency of interruption is only
around 5% per month according to AWS [data](https://aws.amazon.com/ec2/spot/instance-advisor/), meaning - one **can expect
to run a few months uninterrupted**, i.e. still in the 99.9+% uptime range!

Based on concepts familiar from the Kubernetes world - user describes a desired state and there's a
reconciliation loop of sorts.

A typical Postgres setup/restore takes a few minutes on network storage, and is proportional to the DB size when using
volatile instance storage + restore from S3 (via pgBackRest).

## Project status

**Working Beta**

* Manifest API not yet fully fixed (not relevant though when using Docker or the CLI).
* No guarantees on internal configuration being kept backwards compatible - thus might need to clean up `~/.pg-spot-operator`
  if getting weird errors after a version update.

# Quickstart

Let's say we're Data Scientists (sexiest job of 21st century, remember?) and need to perform some advanced ad-hoc
exploration/analytics on a medium-size dataset of a few hundred GB.

Although we have a new and shiny MacBook Pro, it still has only 16GB of RAM and our data exploration quest might not
exactly be a lot of fun...what about tapping into the power of cloud instead? Let's check how much a day of fast SSD-backed
analytics would cost our company, given we want at least 128GB of RAM for feedback to remain interactive:

```
docker run --rm -e PGSO_REGION=eu-north-1 -e PGSO_CHECK_PRICE=y \
  -e PGSO_RAM_MIN=128 -e PGSO_STORAGE_MIN=500 -e PGSO_STORAGE_TYPE=local \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro \
  pgspotops/pg-spot-operator:latest

2024-10-14 14:32:57,530 INFO Resolving HW requirements to actual instance types / prices ...
2024-10-14 14:33:01,408 INFO Cheapest instance type found: r6gd.4xlarge (arm)
2024-10-14 14:33:01,409 INFO Main specs - vCPU: 16, RAM: 128 GB, instance storage: 950
2024-10-14 14:33:01,730 INFO Current Spot discount rate in AZ eu-north-1b: -70.7% (spot $205.2 vs on-demand $700.4)
```

Incredible, an 8h work day will cost us less than a cup of coffee, specifically $2.3 - let's go for it!

PS Note that the displayed 3.4x discount is calculated from the normal on-demand EC2 instance cost, RDS adds a ~50%
premium on top of that + EBS storage costs.

```
docker run --rm -e PGSO_INSTANCE_NAME=analytics -e PGSO_REGION=eu-north-1 \
  -e PGSO_RAM_MIN=128 -e PGSO_STORAGE_MIN=500 -e PGSO_STORAGE_TYPE=local -e PGSO_CONNSTR_OUTPUT_ONLY=y \
  -e PGSO_ADMIN_USER=pgspotops -e PGSO_ADMIN_USER_PASSWORD=topsecret123 \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro pgspotops/pg-spot-operator:latest
...
postgresql://pgspotops:topsecret123@13.60.208.195:5432/postgres?sslmode=require
```

Nice, we have our instance, let's load up the dataset and get to work...
PS Note that the instance is tuned according to the hardware already!

```
$ psql "postgresql://pgspotops:topsecret123@13.60.208.195:5432/postgres?sslmode=require"

postgres=# show shared_buffers ;
 shared_buffers
----------------
 26214MB
(1 row)

postgres=# \i my_dataset.sql

postgres=# SELECT ...
```

Wow, that went smooth, other people's computers can be really useful sometimes...OK time to call it a day and shut down
the instance ...

```
docker run --rm -e PGSO_INSTANCE_NAME=analytics -e PGSO_REGION=eu-north-1 -e PGSO_REGION=eu-north-1 -e PGSO_TEARDOWN=y \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro \
  pgspotops/pg-spot-operator:latest

...
2024-10-14 14:57:03,201 INFO Destroying cloud resources if any for instance analytics ...
...
2024-10-14 14:59:09,293 INFO OK - cloud resources for instance analytics cleaned-up
```

# General idea

* The user:
  - Specifies a set of few key parameters like region, minimum CPUs/RAM and storage size and type (network EBS volumes
    or local volatile storage) and maybe also the Postgres version (defaults to latest stable). User input can come in 3 forms:
    - CLI/Env parameters a la `--instance-name`, `--region`, `--cpu-min`, `--storage-min`. Note that in CLI mode not all
      features can be configured and some common choices are made for the user
    - A YAML manifest as literal text via `--manifest`/`PGSO_MANIFEST`
    - A YAML manifest file via `--manifest-path`/`PGSO_MANIFEST_PATH`. To get an idea of all possible options/features
      one could take a look at an example manifest [here](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/example_manifests/hello_aws.yaml)
  - Specifies or mounts (Docker) the cloud credentials if no default AWS CLI (`~/.aws/credentials`) set up
  - Can optionally specify also a callback (executable file) to do something/integrate with the resulting connect
    string (just displayed by default) or just run in `--connstr-output-only` mode to be pipe-friendly
* The operator:
  - Finds the cheapest (the default strategy) Spot instance for given HW requirements and launches a VM
  - Runs Ansible to set up Postgres
  - Keeps checking the VM health every minute (configurable) and if evicted, launches a new one, re-mounts the data
    volume and resurrects Postgres

# Usage

## Via Docker

```bash
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -v ~/.aws:/root/.aws:ro -v ~/.ssh:/root/.ssh:ro \
  pgspotops/pg-spot-operator:latest
```

or passing the AWS credentials and the default SSH pubkey explicitly:

```bash
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -e PGSO_SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

PS The SSH key is optional, to access the VM directly for potential troubleshooting etc.

## Via Python

```bash
git clone https://github.com/pg-spot-ops/pg-spot-operator.git /tmp/pg-spot-operator
# PS Assuming local AWS CLI is configured!
python3 -m pg_spot_operator --region=eu-north-1 --ram-min=16 --storage-min=1000 --storage-type=local \
  --instance-name pg1 --check-price
```

PS One could also install via PyPI, a la `pipx install pg-spot-operator`, but currently the project must be still cloned
since the Ansible files have not been uploaded to PyPY. If not in the project directory use `--ansible-path` to point to
the "ansible" folder.

# Integrating with user applications

Although the Community Edition is designed for more light use, one can use it also to power real applications (given
they cope with the possible service interruptions of course) by either providing a "setup finished" callback hook or just
running in special pipe-friendly `--connstr-output-only` mode. More details [here](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md).

PS Real usage assumes that the engine is kept running on a single node only by the user, as there's by design no global
synchronization / consensus store to keep things simple.

# Enterprise Edition

Although the Community Edition works and is free to use also for businesses, it's taking the simplest approach to persistent Spot
instances really, so that some aspects of the solution are "best-efforty" and one could do much more to ensure better
uptimes.

If you'd be interested in massive cost saving also for more critical Postgres databases, please register your email address
via this form [https://tinyurl.com/pgspotops](https://tinyurl.com/pgspotops) to get notified once the upcoming Enterprise Edition
is released.

Most import features of the Enterprise Edition:

  * HA / multi-node setups
  * GCP and Azure Spot instances support
  * Advanced eviction rate heuristics for better uptimes
  * Volume auto-growth
  * Temporary fallbacks to regular non-spot VMs once uptime budget burned
  * Major version upgrades
  * Stop / sleep schedules for even more savings
  * Better integration with typical DevOps flows
  * More security, e.g. certificate access
  * A CLI for ad-hoc DBA operations

## VC inquiries

As crazy as it might sound, the math and initial interviewings indicate that, such a solution (in a more polished form)
would be commercially very much viable, and we're going to give it a try. To speed up the development though, we'd also
be interested in VC dollars - thus feel free to reach out to info@pgspotops.com if you happen to possess some and find
the niche interesting.

# Other topics

* [Features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_features.md)
* [Integrating with user applications](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md)
* [Security](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_security.md)
* [Monitoring](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_monitoring.md)
* [Backups](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_backups.md)
* [Development](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_development.md)
* [Advanced features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_advanced_features.md)
* [AWS CLI basics](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_aws_cli_basics.md)
