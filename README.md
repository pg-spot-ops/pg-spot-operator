[![Release](https://img.shields.io/pypi/v/pg-spot-operator)](https://github.com/pg-spot-ops/pg-spot-operator/releases)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
[![Docker Pulls](https://img.shields.io/docker/pulls/pgspotops/pg-spot-operator)](https://hub.docker.com/r/pgspotops/pg-spot-operator)
[![Tests passing](https://github.com/pg-spot-ops/pg-spot-operator/actions/workflows/main.yml/badge.svg)](https://github.com/pg-spot-ops/pg-spot-operator/actions)
[![Status](https://img.shields.io/badge/status-beta-orange)](https://img.shields.io/badge/status-beta-orange)
[![codecov](https://codecov.io/gh/pg-spot-ops/pg-spot-operator/graph/badge.svg?token=DVAAIQXKFO)](https://codecov.io/gh/pg-spot-ops/pg-spot-operator)

# PG Spot Operator

According to various estimates 30-40% of cloud servers are idling - why not to make good use of them, and save some money in the process?

Main use case of the utility is to provide a **one-liner RDS experience, but at a fraction of the cost** - for those who don't
have multi-year Savings Plans, or run lots of irregular workloads. Typical [savings](https://aws.amazon.com/ec2/spot/pricing/)
of running self-managed EC2 Spot instances are around 5x compared to [RDS](https://aws.amazon.com/rds/postgresql/pricing/).

Obviously not meant for all projects as a general RDS replacement, as Spot could mean more service interruptions for longer
term setups. Data remains persistent though!

On the other hand - Spot eviction rates are insanely good for the price! The average frequency of interruption is only
around 10% per month according to AWS [data](https://aws.amazon.com/ec2/spot/instance-advisor/), meaning - one **can expect to run a few months uninterrupted**, i.e.
still in the 99.9+% uptime range!

Based on concepts familiar from the Kubernetes world - user describes a desired state (min. hardware specs, Postgres version,
extensions, admin user password etc) and there's a reconciliation loop of sorts.

## Topics

* [Quickstart](#quickstart)
* [Non-Postgres Use Cases](#not-only-for-postgres)
* [Using normal persistent VMs](#persistent-vm-mode)
* [General idea](#general-idea)
* [Usage](#usage)
* [Integrating with user applications](#integrating-with-user-applications)
* [Features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_features.md)
* [CLI/ENV parameters](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_env_options.md)
* [Security](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_security.md)
* [Extensions](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_extensions.md)
* [Monitoring](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_monitoring.md)
* [Backups](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_backups.md)
* [Development](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_development.md)
* [Advanced features](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_advanced_features.md)
* [AWS CLI basics](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_aws_cli_basics.md)
* [Running on K8s](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/k8s/README_k8s.md)
* [Common issues](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_common_issues.md)


# Quickstart (Python)

Let's say we're Data Scientists (sexiest job of 21st century, remember?) and need to perform some advanced ad-hoc
exploration/analytics on a medium-size dataset of a few hundred GB. Sadly all the available development DBs are not much
better than our shiny new MacBook Pro - seems our data exploration quest might not exactly be a lot of fun...

Wait, what about tapping into the power of cloud instead? Let's just spin up a private high-end analytics DB for an
as-low-as-it-gets cost!

Just in case let's check the pricing beforehand, though - in most cases it will be much better than 3 year Reserved Instances!
```
# Step 0 - ensure Python CLI prerequsites (not needed for Docker)
pipx install pg-spot-operator
pipx install --include-deps ansible  # If Ansible not yet installed

# Resolve user requirements to actual EC2 instance types and show the best (cheap and with good eviction rates) instance types.
# Here we only consider North American regions, assuming were located there and want good latencies as well.
pg_spot_operator --check-price \
  --region='^(us|ca)' --ram-min=128 \
  --storage-min=500 --storage-type=local

Resolving HW requirements to actual instance types / prices using --selection-strategy=balanced ...
Regions in consideration based on --region='^(us|ca)' input: ['ca-central-1', 'ca-west-1', 'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
Top 10 cheapest instances found for strategy 'balanced':
+-----------+--------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
|   Region  |     SKU      | Arch | vCPU |  RAM   | Instance storage | Spot $ (Mo) | On-Demand $ (Mo) | EC2 discount | Approx. RDS win | Evic. rate (Mo) |
+-----------+--------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
| us-east-1 | x2gd.4xlarge | arm  |  16  | 256 GB |   950 GB ssd     |    195.6    |      961.9       |     -80%     |        8x       |      10-15%     |
| us-east-1 | i4g.4xlarge  | arm  |  16  | 128 GB |   3750 GB ssd    |    218.4    |      889.6       |     -75%     |        7x       |       <5%       |
| us-west-2 | i4g.4xlarge  | arm  |  16  | 128 GB |   3750 GB ssd    |    245.7    |      889.6       |     -72%     |        6x       |      5-10%      |
| us-west-2 | x2gd.4xlarge | arm  |  16  | 256 GB |   950 GB ssd     |    259.5    |      961.9       |     -73%     |        6x       |       <5%       |
| us-east-2 | r5d.4xlarge  | x86  |  16  | 128 GB |   600 GB nvme    |    264.1    |      829.4       |     -68%     |        5x       |      5-10%      |
| us-east-2 | r5ad.4xlarge | x86  |  16  | 128 GB |   600 GB nvme    |    264.7    |      754.6       |     -65%     |        5x       |      5-10%      |
| us-west-1 | r6gd.4xlarge | arm  |  16  | 128 GB |   950 GB nvme    |    267.6    |      748.8       |     -64%     |        5x       |      10-15%     |
| us-east-1 | g6e.4xlarge  | arm  |  16  | 128 GB |   600 GB nvme    |    269.7    |      2163.1      |     -88%     |       13x       |       <5%       |
| us-east-2 | i4g.4xlarge  | arm  |  16  | 128 GB |   3750 GB ssd    |    295.0    |      889.6       |     -67%     |        5x       |       <5%       |
| us-west-1 | r7gd.4xlarge | arm  |  16  | 128 GB |   950 GB nvme    |    300.0    |      881.8       |     -66%     |        5x       |       <5%       |
+-----------+--------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
```

Ok seems `us-east-1` is best for us currently with some incredible pricing, as hinted in the log output - **a full work
day on a very powerful instance will cost us a mere $2.2** - less than a cup of coffee!


For actually launching any AWS instances we of course need a working CLI (`~/.aws/credentials`) or have some
[privileged enough](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/scripts/terraform/create-iam-user-and-credentials/create_region_limited_user.tf#L22)
access key and secret available or some transparent "assume role" based scheme set up on the operator host + minimally SSH
port 22 access from the operator node to the used Security Group (defaults to the "default" SG). More info on Security
Groups and ports can be found in the [Security](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_security.md) section.

If you don't yet have a safe AWS playground / credentials - start with a bit of Terraform [here](https://github.com/pg-spot-ops/pg-spot-operator/tree/main/scripts/terraform)
and feed the output into `--aws-vpc-id`, `--aws-access-key-id` and `--aws-secret-access-key` params.

Also note that in case of launching high vCPU (>16) Spot for the first time, you might need to first increase the Spot Quotas -
see the [Common issues](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_common_issues.md) section for details.

```
# In --connstr-only mode we can land right into `psql`!
psql $(pg_spot_operator --region=us-east-1 --ram-min=128 \
  --storage-min=500 --storage-type=local \
  --instance-name=analytics --connstr-only \
  --admin-user=pgspotops --admin-password=topsecret123
)

2024-11-19 11:47:32,362 INFO Processing manifest for instance 'analytics' set via CLI / ENV ...
...
2024-11-19 11:47:40,778 INFO Launching a new spot instance of type x2gd.4xlarge in region us-east-1 ...
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
 65536MB
(1 row)

postgres=# \i my_dataset.sql

postgres=# SELECT ...
```

PS for more important or long-term purposes you would go with the default `--storage-type=network`, i.e. EBS, but for our
work day or even week it's highly unlikely that the instance will get interrupted, and we rather want speed.

Also note that the instance is tuned according to the hardware already!

Wow, that task went smooth, other people's computers can be really useful sometimes...OK time to call it a day and shut down
the instance ...

```
pg_spot_operator --region=us-east-1 --instance-name=analytics --teardown

2024-11-19 11:48:04,251 INFO Destroying cloud resources if any for instance analytics ...
...
2024-11-19 11:48:04,251 INFO OK - cloud resources for instance analytics cleaned-up
```

Let's double-check that nothing is left hanging from previous experiments:

```
pg_spot_operator --region='^(us|ca)' --list-instances

+---------------+----+------------+--------------+------+----------+----------+--------+------------------+-----------------+-------+-----------------+
| Instance name | AZ | InstanceId | InstanceType | vCPU | $ (Mon.) | VolumeId | Uptime | PrivateIpAddress | PublicIpAddress | VpcId | Expiration Date |
+---------------+----+------------+--------------+------+----------+----------+--------+------------------+-----------------+-------+-----------------+
+---------------+----+------------+--------------+------+----------+----------+--------+------------------+-----------------+-------+-----------------+
```

## Not only for Postgres

Spot Operator can also be used to "just" provision and sustain VMs for any custom workloads in need of cheap VMs. Relevant
flags: `--vm-only`, `--connstr-only` or `--connstr-output-path` + `--connstr-format=ssh|ansible`.

For example to run your custom Ansible scripted verification of some large multi-TB backups on fast local storage for
peanuts, one could go:

```
pg_spot_operator --vm-only=y --connstr-only=y --connstr-output-path=inventory.ini --connstr-format=ansible \
  --region=us-east-1 --cpu-min=8 --ram-min=32 --storage-min=5000 --storage-type=local --instance-name=custom
...
INFO SKU i7ie.2xlarge main specs - vCPU: 8, RAM: 64 GB, instance storage: 5000 GB ssd
INFO Current Spot vs Ondemand discount rate: -88.4% ($86.7 vs $748.5), approx. 13x to non-HA RDS
INFO Current expected monthly eviction rate range: <5%
...

ansible-playbook -i inventory.ini mycustom_verification.yml && report_success.sh

pg_spot_operator --teardown --region=us-east-1 --instance-name custom
```

Or add the `--instance-family` flag get some cheap (well, cheapish) Tensor cores for your next AI project:

```
pg_spot_operator --region=us-west --check-price --instance-family=^p

+-----------+---------------+------+------+---------+------------------+-------------+------------------+--------------+-----------------+-----------------+
|   Region  |      SKU      | Arch | vCPU |   RAM   | Instance storage | Spot $ (Mo) | On-Demand $ (Mo) | EC2 discount | Approx. RDS win | Evic. rate (Mo) |
+-----------+---------------+------+------+---------+------------------+-------------+------------------+--------------+-----------------+-----------------+
| us-west-2 | p4d.24xlarge  | x86  |  96  | 1152 GB |  8000 GB ssd     |     8387    |      23596       |     -64%     |        5x       |       <5%       |
| us-west-2 | p5en.48xlarge | x86  | 192  | 2048 GB |  30720 GB nvme   |    13064    |      61056       |     -79%     |        8x       |      15-20%     |
| us-west-1 | p5.48xlarge   | x86  | 192  | 2048 GB |  30720 GB ssd    |    17360    |      88488       |     -80%     |        8x       |      5-10%      |
+-----------+---------------+------+------+---------+------------------+-------------+------------------+--------------+-----------------+-----------------+
```

## Persistent VM mode

There's also a `--persistent-vms` flag to use normal, non-Spot, VMs for some hardware specs.

PS To avoid too many evictions for Spots one can also use the `--list-avg-spot-savings / LIST_AVG_SPOT_SAVINGS` flag to
look for regions with low average eviction rates. E.g.:

```
pg_spot_operator --list-avg-spot-savings yes --region ^eu

2025-01-07 16:23:46,760 INFO Regions in consideration based on --region='^eu' input: ['eu-central-1', 'eu-central-2', 'eu-north-1', 'eu-south-1', 'eu-south-2', 'eu-west-1', 'eu-west-2', 'eu-west-3']
+--------------+------------------------+-----------------------------+----------------------------+
|    Region    | Avg. Spot EC2 Discount | Expected Eviction Rate (Mo) | Mean Time to Eviction (Mo) |
+--------------+------------------------+-----------------------------+----------------------------+
| eu-south-1   |         -72.6%         |            10-15%           |             4              |
| eu-south-2   |         -69.4%         |            10-15%           |             4              |
| eu-north-1   |         -68.2%         |            5-10%            |             7              |
| eu-central-2 |         -66.8%         |            10-15%           |             4              |
| eu-central-1 |         -66.5%         |            10-15%           |             4              |
| eu-west-3    |         -63.0%         |            5-10%            |             7              |
| eu-west-2    |         -62.5%         |            10-15%           |             4              |
| eu-west-1    |         -54.1%         |            5-10%            |             7              |
+--------------+------------------------+-----------------------------+----------------------------+
```

# General idea

* The user:
  - Specifies a few key parameters like region (required), and optionally some minimum hardware specs - CPU, RAM, target instance
  families / generations, or a list of suitable instance types explicitly and for local storage also the min. storage size, and maybe also
  the Postgres version (v15+ supported, defaults to latest stable) and some addon extensions. User input can come in 3 forms:
    - CLI/Env parameters a la `--region`, `--instance-name`, `--ram-min`, `--private-ip-only`. Note that in CLI mode not all
      features can be configured and some common choices are made for the user
    - A YAML manifest as literal text via `--manifest`/`MANIFEST`
    - A YAML manifest file via `--manifest-path`/`MANIFEST_PATH`. To get an idea of all possible options/features
      one could take a look at an example manifest [here](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/example_manifests/hello_aws.yaml)
  - Specifies AWS credentials if no default AWS CLI (`~/.aws/credentials`) set up or if using Docker
  - Optionally specifies how to propagate the resulting connect string to the user / app - just displayed by default. See
    the [Integrating with user applications](#integrating-with-user-applications) section for options
* The operator:
  - Finds the cheapest Spot instance with OK eviction rate (the default "balanced" `--selection-strategy`) for given HW
    requirements and launches a VM
  - Runs Ansible to set up Postgres
  - Keeps checking the VM health every minute (configurable via `--main-loop-interval-s`) and if eviction detected, launches
    a new VM, re-mounts the data volume or does a PITR restore from S3 (if `--storage-type=local` + S3 creds set) and resurrects Postgres

# Usage

There are a [lot](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_env_options.md) of parameters one
can specify, to shape the look of hardware and Postgres instance. Common usage though might look something like below.
Note that by default we're in "daemon mode" - checking continuously for the instance health and re-building if needed.

## Via Docker

An example Postgres v17 instance for a near in-memory feel with persistent EBS volumes (the default), a 5d lifetime and
pgvector AI extension enabled.

```bash
# Let's check the price first
docker run --rm -e CHECK_PRICE=y \
  -e RAM_MIN=128 -e REGION=us-east-1 \
  pgspotops/pg-spot-operator:latest
...
+-----------+---------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
|   Region  |      SKU      | Arch | vCPU |  RAM   | Instance storage | Spot $ (Mo) | On-Demand $ (Mo) | EC2 discount | Approx. RDS win | Evic. rate (Mo) |
+-----------+---------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
| us-east-1 | x2iedn.xlarge | x86  |  4   | 128 GB |   118 GB nvme    |     85.5    |      600.2       |     -86%     |       11x       |      5-10%      |
+-----------+---------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
...

# Actually create the instance for private direct SQL access from our IP address
docker run --name pg1 -e INSTANCE_NAME=pg1 -e REGION=us-east-1 \
  -e STORAGE_MIN=200 -e RAM_MIN=128 \
  -e EXTENSIONS=vector,pg_stat_statements -e OS_EXTRA_PACKAGES=postgresql-17-pgvector \
  -e SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" -e POSTGRES_VERSION=17 \
  -e PG_HBA_LINES="host all all $(curl -s whatismyip.akamai.com)/32 scram-sha-256" \
  -e EXPIRATION_DATE=$(date --utc --date="+5 day" +%Y-%m-%d) \
  -e AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  -e ADMIN_USER=mypostgres -e ADMIN_PASSWORD=supersecret123 \  
  pgspotops/pg-spot-operator:latest
```

PS The SSH key is optional, to be able to access the cloud VM directly from your workstations for potential troubleshooting etc.

## Via Python

```bash
# Install the pg-spot-operator package via pip/pipx, with pipx recommended nowadays:
pipx install pg-spot-operator
# When actually launching Postgres instaces a local Ansible installation is also assumed!
# (not needed for price checking or creating vanilla VMs with the --vm-only flag)
pipx install --include-deps ansible
# Or follow the offical Ansible docs at:
# https://docs.ansible.com/ansible/2.9/installation_guide/intro_installation.html#installing-ansible

# Let's check prices for some in-memory analytics on our 200GB dataset in all North American regions to get some great $$ value
# PS in default persistent storage mode (--storage-type=network) we though still pay list price for the EBS volumes (~$0.09/GB)
pg_spot_operator --check-price --ram-min=256 --region='^(us|ca)'

Resolving HW requirements to actual instance types / prices using --selection-strategy=balanced ...
Regions in consideration based on --region='^(us|ca)' input: ['ca-central-1', 'ca-west-1', 'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
Resolving HW requirements in region '^(us|ca)' using --selection-strategy=balanced ...
Top cheapest instances found for strategy 'balanced' (to list available strategies run --list-strategies / LIST_STRATEGIES=y):
+--------------+----------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
|    Region    |      SKU       | Arch | vCPU |  RAM   | Instance storage | Spot $ (Mo) | On-Demand $ (Mo) | EC2 discount | Approx. RDS win | Evic. rate (Mo) |
+--------------+----------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+
| us-west-2    | x8g.4xlarge    | arm  |  16  | 256 GB |   EBS only       |    170.7    |      1125.5      |     -85%     |       10x       |       <5%       |
| us-east-1    | x2gd.4xlarge   | arm  |  16  | 256 GB |   950 GB ssd     |    214.2    |      961.9       |     -78%     |        7x       |      10-15%     |
| us-west-2    | x2iezn.2xlarge | x86  |  8   | 256 GB |   EBS only       |    226.7    |      1201.0      |     -81%     |        8x       |       <5%       |
| us-west-2    | x2iedn.2xlarge | x86  |  8   | 256 GB |   237 GB nvme    |    230.5    |      1200.4      |     -81%     |        8x       |       <5%       |
| us-east-1    | x8g.4xlarge    | arm  |  16  | 256 GB |   EBS only       |    237.0    |      1125.5      |     -79%     |        8x       |       <5%       |
| us-east-1    | i4g.8xlarge    | arm  |  32  | 256 GB |   7500 GB ssd    |    261.8    |      1779.1      |     -85%     |       11x       |       <5%       |
+--------------+----------------+------+------+--------+------------------+-------------+------------------+--------------+-----------------+-----------------+

# Now to actually create the instance two mandatory flags `--region` and `--instance-name` are required. Plus all other
# optional ones like passwords, pg_hba.conf rules, etc. Run `--help` for all flags or look at README_env_options.md.
# Note that when installing from PyPI, on first real setup run the Ansible setup files are downloaded
# from Github into ~/.pg-spot-operator/ansible. If this seems too fishy, one can also pre-download.
pg_spot_operator --ram-min=256 --region=us-west-2 --storage-min 300 \
  --instance-name pg1 --postgres-version=17 --tuning-profile=analytics \
  --extensions=vector,pg_stat_statements --os-extra-packages=postgresql-17-pgvector \
  --pg-hba-lines="host all all $(curl -s whatismyip.akamai.com)/32 scram-sha-256" \
  --admin-user=mypostgres --admin-password=supersecret123
```

# Integrating with user applications

One can use the Spot Operator also to power real applications, given they cope with the slightly reduced uptimes of course,
by either:

* Providing a "setup finished" callback script to propagate Postgres / VM connect data somewhere
* Running in a special pipe-friendly `--connstr-only` mode
* Specifying an S3 (or compatible) bucket where to push the connect string
* Writing the connect string to a file on the engine node

* More details in [README_integration.md](https://github.com/pg-spot-ops/pg-spot-operator/blob/main/docs/README_integration.md).

PS Real usage assumes that the engine is kept running on a single node only by the user, as there's by design no global
synchronization / consensus store to keep things simple.

# Enterprise Edition

Although the Community Edition works and is free to use also for all non-compete business purposes, it's taking the simplest
approach to persistent Spot instances really, so that some aspects of the solution are "best-efforty" and one could do
much more to ensure better uptimes and usability.

If you'd be interested in massive cost saving also for more critical Postgres databases, please register your email address
via this form [https://tinyurl.com/pgspotops](https://tinyurl.com/pgspotops) to get notified once the upcoming Enterprise Edition is released.

Most import features of the Enterprise Edition:

  * Hybrid-provisioning - fall back to regular non-spot VMs once downtime budget burned
  * HA / multi-node setups
  * GCP and Azure Spot instances support
  * Volume auto-growth
  * Stop / sleep schedules for even more savings
  * More security, e.g. certificate access
  * A CLI for ad-hoc DBA operations
  * Native K8s integration

## Sustainable Open Source / VC info

As crazy as it might sound, we believe that such a solution in a more polished, Enterprise-friendly form would be a great
addition to the Postgres ecosystem and make Postgres even more accessible. To speed up the development we'd be interested
in VC dollars - thus feel free to reach out to info@pgspotops.com if you happen to possess some and find the niche interesting.

# Project status

**Working Beta**

* Manifest API not yet fully fixed (not relevant though when using Docker or the CLI).
* No guarantees on internal configuration being kept backwards compatible - thus might need to remove `~/.pg-spot-operator`
  if getting weird errors after a version update.
