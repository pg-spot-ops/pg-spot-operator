
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

or more securely only passing the needed AWS secrets/public keys:

```bash
docker run --rm --name pg1 -e PGSO_INSTANCE_NAME=pg1 -e PGSO_REGION=eu-north-1 \
  -e PGSO_STORAGE_MIN=100 -e PGSO_STORAGE_TYPE=local -e PGSO_CPU_MIN=2 \
  -e PGSO_SSH_KEYS="$(cat ~/.ssh/id_rsa.pub)" \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

## Python

```bash
pipx install pg-spot-operator
pipx ensurepath
# The project must be cloned since the Ansible files have not been uploaded to PyPY
git clone https://github.com/pg-spot-ops/pg-spot-operator.git /tmp/pg-spot-operator
# Assuming local AWS CLI is configured
pg_spot_operator --region=eu-north-1 --ram-min=16 --storage-min=1000 --storage-type=local --instance-name pg1 \
  --check-price --ansible-path /tmp/pg-spot-operator/ansible
```

# Technical details

## Main features

* Uses cheap (3-10x compared to on-demand pricing) AWS Spot VMs to run Postgres
* Installs Postgres from official PGDG repos, meaning you get instant minor version updates
* Supports Postgres versions v14-v17 (defaults to v16 currently if not specified)
* Two instance selection strategies - "cheapest" and "random"
  - Note that `--selection-strategy=random` can produce better eviction rates as cheaper instance types are in more danger
  of being overbooked. For the same reason burstable instances are not recommended at all for real work.
* Allows also to explicitly specify a list of preferred instance types and cheapest used
* Uses Debian 12 base images / AMI-s
* Allows override of ALL `postgresql.conf` settings if user wishes so
* Built-in basic Postgres tuning profiles for most common workloads (default, oltp, analytics, web)
* Maintains a single instance per daemon to keep things simple
* Supports a single EBS volume or all local/volatile instance disks in a volume group
* Tunable EBS volume performance via paid IOPS/throughput
* Supports block level S3 backups/restores via pgBackRest, meaning acceptable RPO possible even with instance storage
* Can up/down-size the CPU/RAM requests
* Can time-limit the instance lifetime via `--expiration-date "2024-10-22 00:00+03"`, after which it auto-terminates
  given the daemon is running
* Fire-and-forget/self-terminating mode for the VM to expire itself automatically on expiration date
* Optional on-the-VM detailed hardware monitoring support via node_exporter + Grafana

## Non-features

* No automated major version upgrades (stop the engine, do some magic, update the manifest `postgresql.version`)
* No persistent state keeping by default - relying on a local SQLite DB file. User can solve that though by setting
  `--config-dir` to some persistent volume for example. Without that some superfluous work will be performed and
  instance state change and pricing history will be lost, in case of the engine node loss.
* No automatic EBS volume growth (can do manually still)
* DNS integration - all communication happening over IP for now
* No full railguards regarding user input - undefined behaviour for example if user changes region or zone after 1st init

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

## Cleanup of all operator created objects

After some work/testing one can clean up all operator created cloud resources via `PGSO_TEARDOWN_REGION` or only a
single instance via the `PGSO_TEARDOWN` flag.

```
docker run --rm --name pg1 -e PGSO_TEARDOWN_REGION=y -e PGSO_REGION=eu-north-1 \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

or by running a helper script from the "scripts" folders (by default just lists the resources, need to add a parameter):

```
./scripts/aws/delete_all_operator_tagged_objects.sh yes
```

A third option for local Docker convenience, to avoid a restart with different env. inputs, is to create a dummy "destroy
file" in the container that signals instance shutdown:

```commandline
docker run ...
# Note the destroy file path from the log
2024-09-30 10:49:38,973 INFO Instance destroy signal file path: /tmp/destroy-pg1
...
docker exec -it pg1 touch /tmp/destroy-pg1
# On the next loop the resources will be cleaned up and the container shuts down
```

PS The operator tags all created object with special `pg-spot-operator-\*` tags, thus uses those also for the cleanup.

# Local non-cloud development

For Postgres setup testing, manifest handling etc, one can get by with local Virtualbox/Vagrant VMs, by using
according flags:

```bash
git clone git@github.com:pg-spot-ops/pg-spot-operator.git
cd pg-spot-operator
make virtualenv
source .venv/bin/activate
pip install -r requirements-test.txt

vagrant up && vagrant ssh -c 'hostname -I'  #  Or similar, add dev machine SSH keys ...

# Dev/test stuff

python3 -m pg_spot_operator --verbose --instance-name pg1 --vm-host 192.168.121.182 --vm-login-user vagrant

# If changing Python code

make fmt && make lint && make test

git commit
```

# Security

By default, security is not super trimmed down, as main use case if for non-critical or temporary workloads. Everything
is tunable though.

## Security-relevant manifest attributes with defaults

```commandline
public_ip_address: true
postgresql:
  admin_is_superuser: true
  admin_user: ''  # Meaning only local access possible
  admin_user_password: ''
  pg_hba_lines:  # Defaults allow non-postgres world access
    - "host all postgres 0.0.0.0/0 reject"
    - "hostssl all all 0.0.0.0/0 scram-sha-256"
aws:
  security_group_ids: []  # By default VPC "default" SG is used
```

PS! Note that if no `admin_user` is set, there will be also no public connect string generated as remote `postgres` user
access is forbidden by default. One can enable remote "postgres" access (but can't be recommended of course) by setting
the `admin_user` accordingly + specifying custom `pg_hba` rules.

## Relevant ports / EC2 Security Group permissions

* **22** - SSH. For direct Ansible SSH access to set up Postgres.
* **5432** - Postgres. For client / app access.
* **3000** - Grafana. Relevant if `monitoring.grafana.externally_accessible` set
* **9100** - VM Prometheus node_exporter. Relevant if `monitoring.prometheus_node_exporter.externally_accessible` set

For non-public (`public_ip_address=false`) instances, which are also launched from within the SG, default SG inbound rules
are enough. But for public access, one needs to open up the listed ports, at least for SSH and Postgres. 

PS Ports are not changeable in the Community Edition! And changing ports to non-defaults doesn't provide any real security
anyways ...

PS Note that for Ansible SSH access to work the default SSH key on the engine node is expected to be passwordless!

## Opening up a port via the AWS CLI

To open port 22 for the engine node/workstation IP only, for Ansible setup to work, one could run:

```
MYPUBIP=$(curl -s whatismyip.akamai.com)

aws ec2 authorize-security-group-ingress \
  --group-name default \
  --ip-permissions IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges="[{CidrIp=${MYPUBIP}/32}]" \
  --region eu-north-1
```

Some AWS documentation on the topic:

* https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html
* https://docs.aws.amazon.com/cli/latest/reference/ec2/authorize-security-group-ingress.html

# Backups

If using local storage instances (`--storage-type=local`, default storage type is `network`), you don't get data persistence
by default - which is good only of course for throwaway testing/analytics etc. To support persistence there is built-in
support for `pgBackRest` with S3 storage. Backups could of course configured for network storage also, for the usual extra
safety and (manual) PITR reasons.

Note though that enabling backup still means a small data loss in case of VM eviction, assuming data is constantly written.
The default average data loss window is around 1min (`backup.wal_archiving_max_interval=2min`) and for larger databases
(100GB+), restoring in case of an eviction will take 10min+ and the operational side will suffer, so network storage
with some provisioned IOPS to compensate disk latencies might be a better idea.

Relevant CLI / Env flags:
  * --backup-s3-bucket / PGSO_BACKUP_S3_BUCKET (signals we want backups)
  * --backup-cipher / PGSO_BACKUP_CIPHER (no encryption by default)
  * --backup-retention-days / PGSO_BACKUP_RETENTION_DAYS (1d by default)
  * --backup-s3-key / PGSO_BACKUP_S3_KEY
  * --backup-s3-key-secret / PGSO_BACKUP_S3_KEY_SECRET

**PS** It is strongly recommended to generate a distinct key/secret for backups, with only limited S3 privileges, and not
to re-use the engine credentials, as the keys will be actually placed on the Postgres VMs for pgBackRest to work.

Also, technically non-S3 storage, or S3 outside of AWS, can be used - but in that case the user must provide full
pgBackRest configuration lines (`backup.pgbackrest.global_settings` etc) as part of the manifest.

# Fire-and-forget mode

In the self-terminating mode the VM will expire itself automatically after the `--expiration-date`, meaning the engine
daemon doesn't have to be kept running in the background, which is great for automation/integration. 

It works by installing a Cronjob at the end of the Ansible setup (under "root"), which runs the `instance_teardown.py`
script that checks if we've passed the `expiration_date`, and if so - cleans up any volumes, elastic IPs and finally
terminates itself.

Relevant CLI/Env flags:

  * --self-terminate / PGSO_SELF_TERMINATE
  * --self-terminate-access-key-id / PGSO_SELF_TERMINATE_ACCESS_KEY_ID
  * --self-terminate-secret-access-key / PGSO_SELF_TERMINATE_SECRET_ACCESS_KEY

**PS** It is strongly recommended to generate a distinct key/secret for self-termination, only with limited EC2 privileges, and
not to re-use the engine credentials, as the keys will be actually placed on the Postgres VMs to be able to work self-sufficiently.
This in combination with world-public Postgres access + a weak password could lead to disastrous outcomes.  

Also note that not all resources are guaranteed to be auto-expired:
  * Backups (if enabled) - are never expired as a security measure
  * In case of non-floating IPs (by default floating) custom NICs also cannot be cleaned up as still attached to the VM
    at time of calling terminate on itself. Thus if using this feature with public IPs, to get rid of any left-over resources
    it's recommend to run the `delete_all_operator_tagged_objects.sh` script occasionally.

# Monitoring

By default, there's no out-of-the-box monitoring besides AWS instance level metrics that you get automatically, whereby
better (1min) resolution can be enabled (default is 5min) via `vm.detailed_monitoring` for an extra cost.

For additional high-frequency metrics overload one could though enable Prometheus + [node_exporter](https://github.com/prometheus/node_exporter)
and make it accessible via Grafana, using self-signed certificates or plain http.

PS Beware - when setting `monitoring.grafana.enabled` admin password is automatically set to equal the instance name
for convenience by default, if `monitoring.grafana.admin_password` not set!

PS2 Note that for public Grafana access to work, your Security Group of choice needs to have port 3000 open.

Relevant manifest attributes/defaults:

```
monitoring:
  prometheus_node_exporter:
    enabled: false
    externally_accessible: false
  grafana:
    enabled: false
    externally_accessible: true
    admin_user: pgspotops
    admin_password: "{{ instance_name }}"
    anonymous_access: true
    protocol: https
```

Relevant CLI flags:

```
--monitoring
--grafana-externally-accessible
--grafana-anonymous
```

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
