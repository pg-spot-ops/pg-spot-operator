[![Release](https://img.shields.io/pypi/v/pg-spot-operator)](https://github.com/pg-spot-ops/pg-spot-operator/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/pgspotops/pg-spot-operator)](https://hub.docker.com/r/pgspotops/pg-spot-operator)
[![Tests passing](https://github.com/pg-spot-ops/pg-spot-operator/actions/workflows/main.yml/badge.svg)](https://github.com/pg-spot-ops/pg-spot-operator/actions)

# PG Spot Operator [Community Edition]

Think of it as one-liner RDS, but at a fraction of the cost! Typical [savings](https://aws.amazon.com/ec2/spot/pricing/)
of running self-managed EC2 Spot instances are around 5x compared to [RDS](https://aws.amazon.com/rds/postgresql/pricing/).

Obviously not meant for all projects as a general RDS replacement, as utilizing Spot instances means one can be interrupted
by AWS at any time, and it takes a few minutes to restore the state.

On the other hand - Spot eviction rates are insanely good for the price! The average frequency of interruption is only
around 5% per month according to AWS [data](https://aws.amazon.com/ec2/spot/instance-advisor/), meaning - one **can expect to run a few months uninterrupted**, i.e.
still in the 99.9+% uptime range!

Based on concepts familiar from the Kubernetes world - user describes a desired state (min. hardware specs, Postgres version,
extensions, admin user password etc) and there's a reconciliation loop of sorts.

# Quickstart

Let's say we're a Data Scientists (sexiest job of 21st century, remember?) and need to perform some advanced ad-hoc
exploration/analytics on a medium-size dataset of a few hundred GB. Sadly all the available development DBs are not much
better than our shiny new MacBook Pro - seems our data exploration quest might not exactly be a lot of fun...

Wait, what about tapping into the power of cloud instead? Let's just spin up a private high-end analytics DB for an
as-low-as-it-gets cost!

Just in case let's check the pricing beforehand, though - in most cases it will be much better than 3 year Reserved Instances!
```
# Step 0 - install the pg-spot-operator package via pip/pipx:
pipx install pg-spot-operator

# Resolve user requirements to actual EC2 instance types and pick the cheapest (by default)
# according to the current Spot prices in some region:
pg_spot_operator --check-price \
  --region=eu-south-2 --ram-min=128 \
  --storage-min=500 --storage-type=local

2024-11-19 11:47:18,838 INFO Resolving HW requirements to actual instance types / prices using --selection-strategy=cheapest ...
2024-11-19 11:47:20,849 INFO Instance type selected: gr6.4xlarge (arm)
2024-11-19 11:47:20,849 INFO Main specs - vCPU: 16, RAM: 128 GB, instance storage: 600
2024-11-19 11:47:20,849 INFO Current monthly Spot price for gr6.4xlarge in region eu-south-2: $155.7
2024-11-19 11:47:20,849 INFO Current Spot vs Ondemand discount rate: -86.7% ($155.7 vs $1167.7), approx. 12x to non-HA RDS

```
PS for more important or long-term purposes you would go with the default `--storage-type=network`, i.e. EBS, but for our
work day or even week it's highly unlikely that the instance will get interrupted, and we rather want speed.

For actually launching any AWS instances we of course need a working CLI (`~/.aws/credentials`) setup or just have some
[privileged enough](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/scripts/terraform/create-iam-user-and-credentials/create_region_limited_user.tf#L22)
access key + secret available.
```
# In --connstr-output-only mode we can land right into `psql`!
psql $(pg_spot_operator --region=eu-south-2 --ram-min=128 \
  --storage-min=500 --storage-type=local \
  --instance-name=analytics --connstr-output-only \
  --admin-user=pgspotops --admin-user-password=topsecret123
)

2024-11-19 11:47:32,362 INFO Processing manifest for instance 'analytics' set via CLI / ENV ...
...
2024-11-19 11:47:40,778 INFO Launching a new spot instance of type gr6.4xlarge in region eu-south-2 ...
2024-11-19 11:47:54,250 INFO OK - aws VM i-07058e08fae07e50d registered for 'instance' analytics (ip_public = 51.92.44.224 , ip_private = 172.31.43.230)
2024-11-19 11:48:04,251 INFO Applying Postgres tuning profile 'default' to given hardware ...
...
2024-11-19 11:49:58,620 INFO Instance analytics setup completed

psql (17.1 (Ubuntu 17.1-1.pgdg24.04+1), server 16.5 (Debian 16.5-1.pgdg120+1))
SSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384, compression: off, ALPN: none)
Type "help" for help.

postgres=# show shared_buffers ;
 shared_buffers
----------------
 26214MB
(1 row)

postgres=# \i my_dataset.sql

postgres=# SELECT ...
```

Incredible, as hinted in the log output - **an 8h work day will cost us $1.7** - less than a cup of coffee!

Also note that the instance is tuned according to the hardware already!

Wow, that task went smooth, other people's computers can be really useful sometimes...OK time to call it a day and shut down
the instance ...

```
pg_spot_operator --region=eu-south-2 --instance-name=analytics --teardown

2024-11-19 11:48:04,251 INFO Destroying cloud resources if any for instance analytics ...
...
2024-11-19 11:48:04,251 INFO OK - cloud resources for instance analytics cleaned-up
```

PS If you don't yet have a safe AWS playground / credentials - start with a bit of Terraform [here](https://github.com/pg-spot-ops/pg-spot-operator/tree/main/scripts/terraform)
and feed the output into `--aws-vpc-id`, `--aws-access-key-id` and `--aws-secret-access-key` CLI params.

# General idea

* The user:
  - Specifies a few key parameters like region, minimum CPUs/RAM and storage size and type (network EBS volumes
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

There are a [lot](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_env_options.md) of parameters one
can specify, to shape the look of hardware and Postgres instance. Common usage though might look something like below.
Note that by default we're in "daemon mode" - checking continuously for the instance health and re-building if needed.

## Via Docker

An example Postgres v16 instance with a 1d lifetime and some extensions enabled:

```bash
docker run --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_EXPIRATION_DATE=$(date --utc --date="+1 day" +%Y-%m-%d) \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -e PGSO_EXTENSIONS=vector,pg_stat_statements -e PGSO_OS_EXTRA_PACKAGES=postgresql-16-pgvector \
  -e PGSO_SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" -e PGSO_POSTGRESQL_VERSION=16 \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

PS The SSH key is optional, to be able to access the cloud VM directly from your workstations for potential troubleshooting etc.

## Via Python

```bash
pipx install pg-spot-operator
# PS Assuming local AWS CLI is configured!
pg_spot_operator --region=eu-north-1 --ram-min=16 --storage-min=1000 --storage-type=local --check-price
```

# Integrating with user applications

Although the Community Edition is designed for more light use, one can use it also to power real applications (given
they cope with the possible service interruptions of course) by either providing a "setup finished" callback hook or just
running in special pipe-friendly `--connstr-output-only` mode. More details [here](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md).

PS Real usage assumes that the engine is kept running on a single node only by the user, as there's by design no global
synchronization / consensus store to keep things simple.

# Enterprise Edition

Although the Community Edition works and is free to use also for all non-compete business purposes, it's taking the simplest
approach to persistent Spot instances really, so that some aspects of the solution are "best-efforty" and one could do
much more to ensure better uptimes and usability.

If you'd be interested in massive cost saving also for more critical Postgres databases, please register your email address
via this form [https://tinyurl.com/pgspotops](https://tinyurl.com/pgspotops) to get notified once the upcoming Enterprise Edition is released.

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

## Sustainable Open Source / VC info

As crazy as it might sound, we believe that such a solution (in a more polished form) would be a great addition to the
Postgres ecosystem and also commercially viable, so we're going to give it a try. To speed up the development though,
we'd also be interested in VC dollars - thus feel free to reach out to info@pgspotops.com if you happen to possess some
and find the niche interesting.

# Project status

**Working Beta**

* Manifest API not yet fully fixed (not relevant though when using Docker or the CLI).
* No guarantees on internal configuration being kept backwards compatible - thus might need to clean up `~/.pg-spot-operator`
  if getting weird errors after a version update.

# Other topics

* [Features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_features.md)
* [Integrating with user applications](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md)
* [CLI/ENV parameters](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_env_options.md)
* [Security](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_security.md)
* [Extensions](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_extensions.md)
* [Monitoring](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_monitoring.md)
* [Backups](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_backups.md)
* [Development](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_development.md)
* [Advanced features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_advanced_features.md)
* [AWS CLI basics](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_aws_cli_basics.md)
* [Running on K8s](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/k8s/README_k8s.md)
