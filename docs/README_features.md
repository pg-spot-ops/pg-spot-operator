# Main features

* Uses cheap (3-10x compared to on-demand pricing) AWS Spot VMs to run Postgres
* Can also use normal on-demand VMs via the `--persistent-vms` flag
* Can just provision the VMs without Postgres setup via `--vm-only`
* Supports 3 connect string propagation integrations - a generic callback script, writing to S3, pipe mode
* Installs Postgres from official PGDG repos, meaning you get instant minor version updates
* Supports Postgres versions v14-v17 (defaults to v16 currently if not specified)
* Supports all extensions available from the official repos
* Four instance selection strategies - "balanced" (def.), "cheapest", "eviction-rate", "random"
* Allows also to explicitly specify a list of preferred instance types and cheapest used
* Uses Debian 12 base images / AMI-s
* Allows override of ALL `postgresql.conf` settings if user wishes so
* Built-in basic Postgres tuning profiles for most common workloads (default, oltp, analytics, web, throwaway)
* Maintains a single instance per daemon to keep things simple
* Supports a single EBS volume or all local/volatile instance disks in a volume group
* Tunable EBS volume performance via paid IOPS/throughput
* Supports block level S3 backups/restores via pgBackRest, meaning acceptable RPO possible even with instance storage
* Can up/down-size the CPU/RAM requests
* Can time-limit the instance lifetime via `--expiration-date "2024-10-22 00:00+03"`, after which it auto-terminates
  given the daemon is running
* Fire-and-forget/self-terminating mode for the VM to expire itself automatically on expiration date
* Optional on-the-VM detailed hardware monitoring support via node_exporter + Grafana
* Supports Ansible Vault encrypted secrets in the manifests

## Non-features

* No automated major version upgrades (stop the engine, do some magic, update the manifest `postgres.version`)
* No persistent state keeping by default - relying on a local SQLite DB file. User can solve that though by setting
  `--config-dir` to some persistent volume for example. Without that some superfluous work will be performed and
  instance state change and pricing history will be lost, in case of the engine node loss.
* No automatic EBS volume growth (can do manually still)
* DNS integration - all communication happening over IP for now
* No full railguards regarding user input - undefined behaviour for example if user changes region or zone after 1st init

## General recommendations

* Cheaper instance types are usually in more danger of being overbooked / used and have a higher eviction rate - for that
  reason burstable instances are not recommended at all for real work.
* If possible do not specify an Availability Zone, as there are huge differences in pricing and eviction rates within a region.
