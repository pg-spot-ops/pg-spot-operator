
# Postgres Spot Operator [Community Edition]

Maintains stateful Postgres on AWS Spot VMs. Think of it as RDS, but at a fraction of the cost! Typical [savings](https://aws.amazon.com/ec2/spot/pricing/)
are in the ballpark of 3-5x.

Obviously for non-critical projects only, as utilizing Spot instances means one can be interrupted by AWS at any time,
and it takes a few minutes to restore the state. But at the same time - the Spot eviction rates are insanely good for the price!
The average frequency of interruption across all Regions and instance types is ~5% per month according to AWS [data](https://aws.amazon.com/ec2/spot/instance-advisor/).
Meaning one can expect to run a few months uninterrupted.

Not a "real" K8s operator (yet, at least) - but based on similar concepts - user describes a desired state (manifests)
and there's a reconciliation loop of sorts.

A typical Postgres setup from zero takes about 2-3 minutes.

# General idea

* The user:
  - Specifies a set of few key parameters like region, minimum CPUs / RAM and storage size and type (network EBS volumes or local volatile storage)
  - Specifies or mounts (Docker) the cloud credentials if no default AWS CLI (~/.aws/credentials) set up
  - Can optionally specify also a callback (executable file) to do something / integrate with the resulting connect string (just displayed by default)
* The operator:
  - Finds the cheapest Spot instance for given HW requirements and launches a VM
  - Runs Ansible to set up Postgres
  - Keeps checking the VM health every minute (configurable) and if evicted, launches a new one, re-mounts the data volume and resurrects Postgres

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

* Uses cheap (3-10x) AWS Spot VMs to run Postgres
* Installs Postgres from official PGDG repos, meaning you get instant minor version updates
* Allows also to explicitly specify the target instance types
* Uses Debian-12 base images / AMI-s
* Allows override of ALL *postgresql.conf* settings if user wishes so
* Built-in basic tuning profiles for most common workloads (default, oltp, analytics, web)
* Maintains a single instance per daemon to KISS
* Supports a single EBS volume or all local / volatile instance disks in a volume group
* Supports block level S3 backups / restores via pgBackRest, meaning acceptable RPO possible even with instance storage
* Can up/down-size the CPU / RAM requests
* Can time-limit the instance lifetime via *--expiration-date "2024-10-22 00:00+03"*, after which it auto-terminates
  given the daemon is running
* Fire-and-forget / self-terminating mode for the VM to expire itself automatically on expiration date
* Tunable EBS volume performance via paid IOPS / throughput

## Non-features

* No automated major version upgrades (stop the engine, do some magic, update the manifest `postgres_version`)
* No persistent state keeping by default - relying on a local SQLite DB file. User can solve that though by setting
  `--config-dir` to some persistent volume for example. Without that some superfluous work will be performed and
  instance / state change history lost, in case of a daemon node loss.
* No automatic volume growth (can do manually still)
* DNS integration - all communication happening over IP for now

## Cleanup of all operator created objects

After some work / testing one can clean up all operator created cloud resources or only a single instance via
PGSO_TEARDOWN_REGION or PGSO_TEARDOWN.

```
docker run --rm --name pg1 -e PGSO_TEARDOWN_REGION=y -e PGSO_REGION=eu-north-1 \
  -e PGSO_AWS_ACCESS_KEY_ID="$(grep -m1 aws_access_key_id ~/.aws/credentials | sed 's/aws_access_key_id = //')" \
  -e PGSO_AWS_SECRET_ACCESS_KEY="$(grep -m1 aws_secret_access_key ~/.aws/credentials | sed 's/aws_secret_access_key = //')" \
  pgspotops/pg-spot-operator:latest
```

or by running a helper script from the "scripts" folders (by default just lists the resources):

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

# Security

By default, security is not super trimmed down, as main use case if for non-critical or temporary workloads. Everything
is tunable though.

## Security-relevant manifest attributes with defaults

```commandline
public_ip_address: true
pg:
  admin_is_superuser: true
  admin_user: ''  # Meaning only local access possible
  admin_user_password: ''
access:
  pg_hba:  # Defaults allow non-postgres world access
    - "host all postgres 0.0.0.0/0 reject"
    - "hostssl all all 0.0.0.0/0 scram-sha-256"
aws:
  security_group_ids: []  # By default VPC "default" SG is used
```

PS! Note that if no *admin_user* is set, there will be also no public connect string generated as remote "postgres" user
access is forbidden by default. One can enable remote "postgres" access (but can't be recommended of course) by setting
the *admin_user* accordingly + specifying custom *pg_hba* rules.

## Relevant ports / EC2 Security Group permissions

* **22** - SSH. For direct Ansible SSH access to set up Postgres.
* **5432** - Postgres. For client / app access.
* **3000** - Grafana. Relevant if *monitoring.grafana.externally_accessible* set
* **9100** - VM Prometheus node_exporter. Relevant if *monitoring.prometheus_node_exporter.externally_accessible* set

For non-public (*public_ip_address=false*) instances, which are also launched from within the SG, default SG inbound rules
are enough. But for public access, one needs to open up the listed ports, at least for SSH and Postgres. 

PS Ports are not changeable in the Community Edition! And changing ports to non-defaults doesn't provide any real security
anyways ...

# Integrating with user applications

Although the Community Edition is optimized for more light use, one can use it also to power real applications (given
they cope with the possible service interruptions of course) by either providing a "setup finished" callback hook or just
running in special *--connstr-output-only* mode.

## Pipe-friendly *--connstr-output-only* mode

Engine ensures VM, sets up Postgres if needed in quiet mode, prints connstr and exits. Example usage:

```
docker run --rm -e PGSO_CONNSTR_OUTPUT_ONLY=y -e PGSO_REGION=eu-north-1 -e PGSO_INSTANCE_NAME=pg1 \
  | run_some_testing \ 
  && docker run --rm -e PGSO_TEARDOWN=y -e PGSO_REGION=eu-north-1 -e PGSO_INSTANCE_NAME=pg1
```

## Setup finished callback file usage

Currently the callback be a self-contained executable which gets following 4 input parameters for propagations into "somewhere":

- Instance name
- Private full connect string a la 'postgresql://postgres@localhost:5432/postgres'
- Public full connect string, when *public_ip_address: true* is set, else an empty string
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

# Backups

If using local storage instances (*--storage-type=local*, default storage type is *network*), you don't get data persistence
by default - which is good only of course for throwaway testing / analytics etc. To support persistence there is built-in
support for pgBackRest with S3 storage. Backups could of course configured for network storage also, for usual extra
safety and (manual) PITR options.

Note though that enabling backup still means a small data loss in case of VM eviction, assuming data is constantly written.
The default average data loss window is around 1min (backup.wal_archiving_max_interval=2min) and for larger databases
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
pgBackRest configuration lines (backup.pgbackrest.global_settings etc) as part of the manifest.

# Fire-and-forget mode

In the self-terminating mode the VM will expire itself automatically after the *--expiration-date*, meaning the engine
daemon doesn't have to be kept running in the background, which is great for automation / integration. 

It works by installing a Cronjob at the end of the Ansible setup (under "root"), which runs the `instance_teardown.py`
script that checks if we've passed the *expiration_date*, and if so - cleans up any volumes, elastic IPs and finally
terminates itself.

Relevant CLI / Env flags:

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

# Enterprise Edition

Although the Community Edition works and is free to use also for businesses, it's taking the simplest approach to Spot
instances really, so that some aspects of the solution are "best-efforty" and one could do much more to ensure better
uptimes.

If you'd be interested in massive cost saving also for more critical Postgres databases, please register your email address
via this form [https://tinyurl.com/pgspotops](https://tinyurl.com/pgspotops) to get notified once the upcoming Enterprise Edition
is released.

Most import features of the Enterprise Edition:

  * HA / multi-node setups
  * GCP and Azure support
  * Advanced eviction rate heuristics
  * Volume auto-growth
  * Temporary fallbacks to regular non-spot VMs once uptime budget burned
  * Major version upgrades
  * Stop / sleep schedules for even more savings
  * Better integration with typical DevOps flows
  * A CLI for ad-hoc DBA operations
