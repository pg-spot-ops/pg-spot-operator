Changelog
=========


(unreleased)
------------
- Add also hourly prices to --check-price output. [Kaarel Moppel]

  For easier comparisons with other big clouds, which mostly show hourly
  prices
- Fail early in --connstr-only if no matching SKUs found. [Kaarel
  Moppel]

  And make the error msg less ugly
- --list-instances: don't scan all AWS regions immediately when region
  not provided. [Kaarel Moppel]

  Try first to look for CMDB known regions
- Merge pull request #149 from pg-spot-ops/add-uptime-flag. [Kaarel
  Moppel]

  Add a new --list-vm-creates flag
- Add spot price + discount % to --list-vm-creates. [Kaarel Moppel]
- Show also --list-instances / --list-instances-cmdb times in local
  zone. [Kaarel Moppel]
- Do UTC conversion via stdlib and move to util.py. [Kaarel Moppel]
- Show VM created_on in local time zone. [Kaarel Moppel]
- Rename to more descriptive --list-vm-creates. [Kaarel Moppel]
- Add a new --list-creates flag. [Kaarel Moppel]
- Fix --list-instances output for instances with volumes. [Kaarel
  Moppel]
- README: --check-price doesn't require Ansible. [Kaarel Moppel]

  Plus remove enterprise version info
- Smoke testing script - add a success notify URL. [Kaarel Moppel]


0.9.54 (2025-04-21)
-------------------
- Release: version 0.9.54 🚀 [Kaarel Moppel]
- Fix leftover debug from last, breaking --connstr-only mode. [Kaarel
  Moppel]


0.9.53 (2025-04-21)
-------------------
- Release: version 0.9.53 🚀 [Kaarel Moppel]
- No retry on marker read as SSH connection validated in prev step.
  [Kaarel Moppel]

  Assume marker not there in case of errors
- Write the "setup completed" marker in Ansible instead of Py. [Kaarel
  Moppel]

  More logical / clean
- Write a "setup completed" marker file at
  /var/lib/postgresql/operator_setup_completed_marker. [Kaarel Moppel]

  To signal that Ansible run completed. Can be removed on the VM to
  re-configure postgres after some manual meddling
- Merge pull request #148 from pg-spot-ops/add-smoke-testing-script.
  [Kaarel Moppel]

  Add a script that maintains an instance and calls a webhook from URL read from ~/.pg-spot-operator-smoke-test-notify-url to notify of errors
- Ignore the "scripts" folder from CI. [Kaarel Moppel]
- Fail smoke_test.sh if yq not installed. [Kaarel Moppel]
- Daily logs, read instance name from YAML manifest. [Kaarel Moppel]
- Don't use "trap", better messages. [Kaarel Moppel]
- Add a simple smoke testing loop. [Kaarel Moppel]

  Creates an instance and keeps doing some SQL, call a webhook on failures
- Add throughput / iops to --list-instance abandoned volumes output.
  [Kaarel Moppel]
- Make --list-instances show resumable / abandoned volumes. [Kaarel
  Moppel]


0.9.52 (2025-04-16)
-------------------
- Release: version 0.9.52 🚀 [Kaarel Moppel]
- Time-box --connstr-only mode to 30min. [Kaarel Moppel]

  Something must be terminally wrong - signal test scripts etc with exit
  code 2
- Assign a new UUID to instance with same name after delete. [Kaarel
  Moppel]

  To not possibly overwrite backups
- Fix case when decreasing min_ram still recycled the existing instance.
  [Kaarel Moppel]

  with enough RAM
- Fail with exit code 0 after teardown. [Kaarel Moppel]

  Instead of 1
- README remove trailing whitespace from "docker run" example. [Kaarel
  Moppel]
- README - update the --check-price table output. [Kaarel Moppel]

  Columns had changed
- Re-licence to Apache 2.0. [Kaarel Moppel]

  And add support / sponsoring options


0.9.51 (2025-04-15)
-------------------
- Release: version 0.9.51 🚀 [Kaarel Moppel]
- Fail early on --teardown if can't determine region. [Kaarel Moppel]
- Fix an unnecessary volume remounting error. [Kaarel Moppel]


0.9.50 (2025-04-14)
-------------------
- Release: version 0.9.50 🚀 [Kaarel Moppel]
- Add a "Running" and "Last VM" columns to --list-instance-cmdb output.
  [Kaarel Moppel]

  Via a live describe_instances call
- Add --list-instances-cmdb cmdline flag. [Kaarel Moppel]

  To list all instances offline based on CMDB information
- Merge pull request #147 from pg-spot-ops/vm-only-mount-disks. [Kaarel
  Moppel]

  By default mount data disks also in `--vm-only` mode
- Add --no-mount-disks flag. [Kaarel Moppel]

  To make it possible to get the old --vm-only behaviour where data
  volumes are not automatically mounted to /var/lib/postgresql
- Mount data disks in --vm-only mode. [Kaarel Moppel]
- Don't require explicit --region input for --teardown. [Kaarel Moppel]

  Using CMDB same as for --stop / --resume
- A bit more INFO lvl logging around volume creation. [Kaarel Moppel]
- Set --stripes default value to 1. [Kaarel Moppel]

  Still means no striping. Allows for more convenient scripting
- Fix VM details like CPU, RAM not being stored to CMDB "vm" table.
  [Kaarel Moppel]


0.9.49 (2025-04-11)
-------------------
- Release: version 0.9.49 🚀 [Kaarel Moppel]
- CMDB instance.ram_min was not set. [Kaarel Moppel]

  Also sync main HW specs changes from manifest to CMDB instance tbl
- Merge pull request #146 from pg-spot-ops/stop-resume-functionality.
  [Kaarel Moppel]

  Add stop / resume functionality via `--stop` and `--resume`. Adds CLI convenience as don't need to look up the launch config, just need the instance name. `--list-instances` now also lists active and resumable instances separately
- Don't list instances not on EBS or backed up as resumable. [Kaarel
  Moppel]
- Make --list-instances aware of resumable instances. [Kaarel Moppel]
- Implement --resume. [Kaarel Moppel]

  Works based on --instance-name only. Also fix a CMDB striping leftover
  bug
- Set instance.stopped_on in CMDB on --stop. [Kaarel Moppel]
- Implement --stop / STOP. [Kaarel Moppel]

  Also don't require the region to be set - look it up from CMDB based on
  --instance-name
- Make striping volume order deterministic. [Kaarel Moppel]

  Previosly could happen that the postgres volume was effectively
  reinitialized


0.9.48 (2025-04-07)
-------------------
- Release: version 0.9.48 🚀 [Kaarel Moppel]
- Merge pull request #145 from pg-spot-ops/add-striping-support. [Kaarel
  Moppel]

  Add EBS striping support via --stripes and --stripe-size-kb
- Update docs with volume striping. [Kaarel Moppel]
- Leave out the root vol in --list-instances output if using striping.
  [Kaarel Moppel]
- Show all VolumeId-s in --list-instances. [Kaarel Moppel]
- Add EBS striping support via --stripes and --stripe-size-kb. [Kaarel
  Moppel]
- Merge pull request #144 from pg-spot-ops/max-price-flag. [Kaarel
  Moppel]

  Max price flag
- Log an info message when SKUs are removed due to --max-price. [Kaarel
  Moppel]
- Add --max-price flag cap. [Kaarel Moppel]
- Merge pull request #143 from pg-spot-ops/main-loop-refactor. [Kaarel
  Moppel]

  Main loop refactor + do a cheaper VM alive check via SSH
- First check if VM still exists via a cheaper SSH check. [Kaarel
  Moppel]

  Not to overspam the AWS API when going a lot below default 60s
  "alive check" via --main-loop-interval-s
- Refactor the main loop for better readability. [Kaarel Moppel]
- Fix GPU instances CPU arch inferring from the family name. [Kaarel
  Moppel]

  g4dn.xlarge is x86 actually although it has a "g" in family
- Set Postgres 17 as default version. [Kaarel Moppel]

  Can be considered stable now after 17.4 release
- Minimal WAL logging for the "throwaway" tuning profile. [Kaarel
  Moppel]

  Reduces WAL writing by some 10-20%


0.9.47 (2025-02-21)
-------------------
- Release: version 0.9.47 🚀 [Kaarel Moppel]
- Merge pull request #138 from pg-spot-ops/ami-caching. [Kaarel Moppel]

  Ami caching
- Remove the reading cached AWS pricing debug message. [Kaarel Moppel]

  Was too chatty
- Cache AWS OS AMIs for a week. [Kaarel Moppel]
- Allow provisioning of st1 and sc1 type (HDD) volumes. [Kaarel Moppel]

  Can save some $$ so.
  As per https://github.com/pg-spot-ops/pg-spot-operator/issues/130
- Compact --check-price output a bit. [Kaarel Moppel]

  Remove also column comparing approximate difference with RDS pricing
- Install Timescale from Timescale repos, not PGDG. [Kaarel Moppel]

  As the PGDG version has many features missing. Also auto-install the
  OS package to make it more convenient
- README Minor --list-avg-spot-savings correction. [Kaarel Moppel]


0.9.46 (2025-02-03)
-------------------
- Release: version 0.9.46 🚀 [Kaarel Moppel]
- Add a Lifecycle column to the --list-instances output. [Kaarel Moppel]

  To show if it's a spot or on-demand instance. Also show the correct
  on-demand price for the on-demand instances
- Allow VM provisioning with --ssh-private-key pointing to a PEM file.
  [Kaarel Moppel]

  Currently we checked for .pub existance
- Simplify aws ec2 authorize-security-group-ingress example. [Kaarel
  Moppel]

  To expose an SSH port for Ansible to work
- Male fail2ban less aggressive. [Kaarel Moppel]

  5 > 100 errors per 1h
- Show help again if no CLI arguments set. [Kaarel Moppel]

  Got messed up with default --vm-login-user set to pgspotops
- Fix persistent VM (--persistent-vms) price sorting. [Kaarel Moppel]

  Was random essentially
- Add a special -1 value to --storage-min handling. [Kaarel Moppel]

  Don't create / attach a data volume in that case and only run with root
  volume. Default --os-disk-size is 20GB.


0.9.45 (2025-01-28)
-------------------
- Release: version 0.9.45 🚀 [Kaarel Moppel]
- README minor correction on boolean flags. [Kaarel Moppel]
- Merge pull request #136 from pg-spot-ops/check-ssh-connectivity-after-
  vm-provisioning. [Kaarel Moppel]

  Check SSH connectivity not just wait 10s after VM provisioning and before Ansible setup, so that the first loop would always succeed
- A time based SSH connectivity check loop instead count based. [Kaarel
  Moppel]

  For better predictibility
- Check SSH connectivity after VM provisioning and before Ansible setup.
  [Kaarel Moppel]

  To avoid the occasional connectivity errors on the first loop, as
  hard-coded 10s or 15s doesn't always seem to work.

  As per https://github.com/pg-spot-ops/pg-spot-operator/issues/124
- Security README - mention current secrets handling posture /
  assumptions. [Kaarel Moppel]

  Close for now https://github.com/pg-spot-ops/pg-spot-operator/issues/62
- Merge pull request #135 from pg-spot-ops/record-app-user-password-in-
  pgpass. [Kaarel Moppel]

  Store app user password in postgres user .pgpass if set to be able to look it up later

  As per https://github.com/pg-spot-ops/pg-spot-operator/issues/129
- Formatter bycatch. [Kaarel Moppel]
- Make .pgpass setting a bit nicer. [Kaarel Moppel]

  Respect possible user modifications if any
- Store app user password in postgres user .pgpass if set. [Kaarel
  Moppel]

  To be able to look it up later. As per https://github.com/pg-spot-ops/pg-spot-operator/issues/129
- Merge pull request #134 from pg-spot-ops/enable-huge-pages-for-large-
  ram-skus. [Kaarel Moppel]

  Enable Linux huge pages for larger (>8GB) shared_buffers
- Stay on default 'huge_pages=try' for a test period still. [Kaarel
  Moppel]

  Instead of 'on' which fails if not enough huge pages available
- Enable huge pages for larger (>8GB) Shared Bufffers. [Kaarel Moppel]

  As can bring visible performance improvements.

  https://github.com/pg-spot-ops/pg-spot-operator/issues/132
- Merge pull request #133 from pg-spot-ops/disable-transparent-huge-
  pages-on-boot. [Kaarel Moppel]

  Disable Linux Transparent Huge Pages directly after boot
- Disable Linux Transparent Huge Pages directly after boot. [Kaarel
  Moppel]

  As generally negative for databases that manage their own memory
- Amend last. [Kaarel Moppel]

  Fix circular import not catched by linter
- Keep trying other instance types when Spot vCPU count exceeded.
  [Kaarel Moppel]

  As limitations could apply only to a specific instance family
- Merge pull request #131 from pg-spot-ops/add-postgres-monitoring-via-
  pgwatch. [Kaarel Moppel]

  Add postgres monitoring via pgwatch
- Ensure Grafana service started on boot. [Kaarel Moppel]
- Add some pgwatch Prom dashboards. [Kaarel Moppel]
- Add Postgres monitoring via pgwatch. [Kaarel Moppel]

  Using pgwatch 3.0 release from https://github.com/cybertec-postgresql/pgwatch/releases

  Also adding local trust auth by default so that pgwatch can already
  connect seamlessly during the setup
- Add Python versions badge. [Kaarel Moppel]


0.9.41 (2025-01-21)
-------------------
- Release: version 0.9.41 🚀 [Kaarel Moppel]
- Add a CodeCov badge. [Kaarel Moppel]
- Set CodeCov to "informational" mode. [Kaarel Moppel]
- Merge pull request #127 from pg-spot-ops/add-codecov-config. [Kaarel
  Moppel]

  Add codecov.yml
- Add codecov.yml. [Kaarel Moppel]

  Don't force quotas for now
- Run the setup finished callback also in --vm-only mode. [Kaarel
  Moppel]

  Feed VM IP addresses as input instead of PG connstr though
- Degrade instance destroy signal file path msg to debug. [Kaarel
  Moppel]
- Warn if ansible-playbook executable not found on the PATH. [Kaarel
  Moppel]

  and if full Postgres setup mode
- Don't require setting of --storage-min for --list-instances to work.
  [Kaarel Moppel]
- Connstr outputting improvements. [Kaarel Moppel]

  Add a new "auto" --connstr-format and respect "postgres" format even when --vm-only set


0.9.40 (2025-01-20)
-------------------
- Release: version 0.9.40 🚀 [Kaarel Moppel]
- Merge pull request #126 from pg-spot-ops/revert-boolean-cli-flag-
  handling. [Kaarel Moppel]

  Revert to original boolean CLI flag input handling + rename 2 flags to accomodate that

  Don't require true/yes input for booleans
- Rename --ip-floating to --static-ip-addresses. [Kaarel Moppel]

  For CLI convenience
- Rename --assign-public-ip to --private-ip-only. [Kaarel Moppel]

  So that it works better via Py CLI
- Revert ba6518633: Change CLI input flags logic - all boolean flags
  accepting values now. [Kaarel Moppel]

  As quite inconvenient and non-pythonic in practice and given most people
  will probably go for Docker usage anyways
- Some more README readability improvements. [Kaarel Moppel]
- Adjust network NVme random_page_cost to 1.25 from 1.1. [Kaarel Moppel]
- Set default_toast_compression to 'lz4' [Kaarel Moppel]

  Replacing postgres default pglz as seems to be overall better:
  https://www.timescale.com/blog/optimizing-postgresql-performance-compression-pglz-vs-lz4
- README - add a beta status label. [Kaarel Moppel]
- --list-regions - mention that not all regions might be actually
  usable. [Kaarel Moppel]

  And add an AWS CLI command to list enabled regions
- Show the monthly spot price + AZ when re-trying a launch. [Kaarel
  Moppel]

  As in case of not enough Spot capacity the the next tried price / zones can
  already be different
- Set --ram-min default to 1GB. [Kaarel Moppel]

  As 512MB instances occasionally throw OOM during Ansible setup


0.9.36 (2025-01-12)
-------------------
- Release: version 0.9.36 🚀 [Kaarel Moppel]
- Increase MAX_SKUS_FOR_SPOT_PRICE_COMPARE from 15 to 25. [Kaarel
  Moppel]

  To cover case where cheaper burstable instances did not get selected as
  they had more cores, when --allow-burstable set
- Expose the vm.allow_burstable attribute on the CLI. [Kaarel Moppel]

  As --allow-burstable. Disabled by default
- Add cloud / SKU details to Ansible inventory output. [Kaarel Moppel]

  Effective for --connstr-output-path + --connstr-format=ansible

  Outputs now smth like: cat ans1.ini
  51.92.207.184 ansible_user=pgspotops ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
  ; cloud=aws region=eu-south-2 provider_id=i-038f8779f966b8d73 sku=c6gd.medium
- Warn if no SSH access keys provided / found in real modes. [Kaarel
  Moppel]

  Proceed though as might be a test run still
- Docs - add an example date to --expiration-date. [Kaarel Moppel]

  As ISO 8601 might require googling for most people
- Consider only enabled regions by default for price check. [Kaarel
  Moppel]

  And --list-instances, if --region not set explicitly. Fall back to all
  known regions if describe_regions call fails
- README document that CLI assumes a local Ansible installation. [Kaarel
  Moppel]

  To be able to actually configure Postgres
- CLI - show help when no action params set. [Kaarel Moppel]

  Also remove the --show-help param as not needed anymore


0.9.35 (2025-01-07)
-------------------
- Release: version 0.9.35 🚀 [Kaarel Moppel]
- Merge pull request #122 from pg-spot-ops/readme-up. [Kaarel Moppel]

  Readme update - Rework TOC, move to header.
- Rework TOC. [Kaarel Moppel]
- README - highlight the AI / GPU use case. [Kaarel Moppel]

  Under Not only for Postgres
- README: mention the new --list-avg-spot-savings flag. [Kaarel Moppel]

  And tidy the --list-avg-spot-savings output a bit
- Merge pull request #121 from pg-spot-ops/regional-spot-stats-summary.
  [Kaarel Moppel]

  New flag `--list-avg-spot-savings` to show regional spot savings and eviction rate summary
- Add a Mean Time to Eviction column to --list-avg-spot-savings output.
  [Kaarel Moppel]
- Rename flag to --list-avg-spot-savings. [Kaarel Moppel]

  And leave out the avg vCPU price as hard to calculate reliably
- Show correct avg. saving rate + ljustify. [Kaarel Moppel]
- Rename new flag to --regional-spot-stats. [Kaarel Moppel]

  Plus table output
- New CLI flag to get avg Spot pricing / eviction rate stats. [Kaarel
  Moppel]

  Skel
- Random selection strategy needs an extra price sort. [Kaarel Moppel]

  Even in single region search
- New flag: --ram-max / RAM_MAX. [Kaarel Moppel]

  To limit cost for eviction-rate strategy, as lowest eviction rate
  bracket machines could get huge and expensive
- Set Ansible default root to ~/.pg-spot-operator/ansible. [Kaarel
  Moppel]

  And make dev location secondary


0.9.31 (2025-01-06)
-------------------
- Release: version 0.9.31 🚀 [Kaarel Moppel]
- Better max_parallel_workers tuning. [Kaarel Moppel]
- Respect --connstr-format=ansible for --connstr-output-path. [Kaarel
  Moppel]

  Was storing PG connstr in normal non-vm-only mode
- Fix local file connstr integration via --connstr-output-path. [Kaarel
  Moppel]
- README updates on commerical edition / features. [Kaarel Moppel]


0.9.30 (2025-01-02)
-------------------
- Release: version 0.9.30 🚀 [Kaarel Moppel]
- AWS AMIs search - ignore "daily" AMIs. [Kaarel Moppel]

  As not really test according to google
- Example manifest - remove deprecated comment about explicit NICs.
  [Kaarel Moppel]
- Don't create explicit NICs anymore. [Kaarel Moppel]

  This effectively disables persitent private IP addresses...but not a
  huge loss anyways, as this disabled moving between AZs once launced
- Fix new CLI flags handling for non-default values. [Kaarel Moppel]

  Logically false string were not set to empty
- Wait less on teardown befor deleting Elastic IPs. [Kaarel Moppel]

  60s > 10s
- Change CLI input flags logic - all boolean flags accepting values now.
  [Kaarel Moppel]

  --check-price > --check-price=yes/true/on.

  To a) be better aligned with K8s env params b) to be able to override
  e.g. public IP on the CLI without using ENV
- CLI: add --ip-floating flag. [Kaarel Moppel]

  To control Elastic IP creation
- K8s README - document how to create a K8s service for an instance.
  [Kaarel Moppel]

  To use the external VM transparently from within the K8s cluster
- Helm - set pullPolicy to IfNotPresent. [Kaarel Moppel]

  Was "Always" - but not using tags yet, meaning could get a breaking API
  change with Always
- Merge pull request #119 from pg-spot-ops/dont-retry-vm-create-on-
  quota-breach. [Kaarel Moppel]

  Dont retry vm create on Spot vCPU quota breach
- Show a nicer error when Spot quota exceeded. [Kaarel Moppel]

  As quite a common case probably for first-time users
- VM creation - don't re-try during one loop in case Spot quota reached.
  [Kaarel Moppel]
- Merge pull request #118 from pg-spot-ops/os-disk-size. [Kaarel Moppel]

  New HW attribute: --os-disk-size with 20GB default
- New HW attribute: --os-disk-size with 20GB default. [Kaarel Moppel]
- Run tests on only Python 3.12. [Kaarel Moppel]

  Faster feedback loop, linting should catch most of version differences


0.9.21 (2024-12-30)
-------------------
- Release: version 0.9.21 🚀 [Kaarel Moppel]
- Minor correct last. [Kaarel Moppel]
- Add jumpy CPU perf to common issues README. [Kaarel Moppel]
- Env input naming - get rid of the PGSO prefix. [Kaarel Moppel]

  Should be fine without it also. A bit unwieldy still
- Rename --connstr-output-only to just --connstr-only. [Kaarel Moppel]
- Merge pull request #117 from pg-spot-ops/connstr-local-file-storage.
  [Kaarel Moppel]

  New integration option: connect string storing into a local engine node file
- Don't overwrite the --connstr-output-path file if no changes. [Kaarel
  Moppel]

  to the connect string
- A new app integration flag: --connstr-output-path. [Kaarel Moppel]

  To stores the PG / VM connect string in plain text on the engine node,
  for easy readout by apps


0.9.20 (2024-12-26)
-------------------
- Release: version 0.9.20 🚀 [Kaarel Moppel]
- Add a README on Common Issues. [Kaarel Moppel]

  Like fixing the Spot Quotas and enabling non-activated regions
- Merge pull request #116 from pg-spot-ops/tuning-profiles-overhaul.
  [Kaarel Moppel]

  Tuning profiles overhaul, add "throwaway" profile. Remove standalone tuning profile files
- Add new tuning profile - throwaway. [Kaarel Moppel]

  Plus some README and refactor
- Implement non-default tuning profiles also in the new way. [Kaarel
  Moppel]
- Refactor Postgres config tuning. [Kaarel Moppel]

  Replace standalone tuning scripts with normal Python code.
  To avoid path issues and provide better testability
- Update README.md. [Evans Akai Bekoe]
- Minor logging output improvements. [Kaarel Moppel]
- Don't show the full values for detected manifest by default. [Kaarel
  Moppel]

  Show keys only in normal mode, not to leak any credentials and such
  to the console. Still show in --debug mode
- Docs - various clarifications. [Kaarel Moppel]
- Print out the input params / manifest only in --debug mode. [Kaarel
  Moppel]

  Instead of --verbose. Better for security
- Tuning profiles - int rounding for max_parallel_workers. [Kaarel
  Moppel]

  and max_parallel_maintenance_workers
- Tune postgresql.conf according to the exact HW created. [Kaarel
  Moppel]

  Previously we did it only when explicit instance types were provided
  and fell back to min HW reqs, which are normally smaller than what
  was actually resolved.

  https://github.com/pg-spot-ops/pg-spot-operator/issues/107
- README_aws_cli_basics.md - document how to list eviction events.
  [Kaarel Moppel]


0.9.15 (2024-12-17)
-------------------
- Release: version 0.9.15 🚀 [Kaarel Moppel]
- Merge pull request #115 from pg-spot-ops/persistent-vm-option. [Kaarel
  Moppel]

  Allow running on persistent VMs via the new --persistent-vms flag
- Better logging when --persistent-vms set. [Kaarel Moppel]

  Selection strategies only relevant for Spot VMs
- README document the new --persistent-vms flag. [Kaarel Moppel]
- Minor check price output table format for non-spots. [Kaarel Moppel]
- Improved ondemand sorting. [Kaarel Moppel]

  Make selection strategies spot/non-spot aware and use the according
  price when sorting. If using ondemand VMs redirect all advanced sort
  strategies to "cheapest"
- Sort by ondemand price when --persistent-vms set. [Kaarel Moppel]
- Rename --ondemand to --persistent-vms. [Kaarel Moppel]

  Should be more universally understood as ondemand is an AWS concept
- Add new --ondemand flag to run on non-Spot VMs. [Kaarel Moppel]

  Add flag and propagate to run_instances
- Add a new --debug flag. [Kaarel Moppel]

  To not clean up Ansible run config and logs, for troubleshooting and
  forensics
- Merge pull request #113 from pg-spot-ops/list-instances-improvements.
  [Kaarel Moppel]

  List instances improvements - pricing info + human readable uptime
- Hint at --list-instances in the main README. [Kaarel Moppel]
- Declare the humanize Py dependency. [Kaarel Moppel]
- Replace LaunchTime with Uptime in --list-instances. [Kaarel Moppel]

  For a nicer experience
- Remove double-printing of a region's instance count in --verbose mode.
  [Kaarel Moppel]
- Add current Spot price to --list-instances output. [Kaarel Moppel]
- List instances: make per region scanning messages debug level. [Kaarel
  Moppel]

  Show wnly the output table in normal / non-verbose mode
- Merge pull request #110 from pg-spot-ops/s3-connstr-storage. [Kaarel
  Moppel]

  New app integration feature -  connect string info pushing to S3
- Update README_env_options.md on S3 push flags. [Kaarel Moppel]
- Document the new connstr S3 pushing feature. [Kaarel Moppel]
- Better debug info around s3 connstr storage. [Kaarel Moppel]
- Rename --connstr-bucket-filename to --connstr-bucket-key. [Kaarel
  Moppel]

  As more correct
- Connect info written to s3 after a success loop. [Kaarel Moppel]

  If --connstr-bucket and --connstr-bucket-filename set
- Dummy connstr s3 writing. [Kaarel Moppel]
- Lay groundwork for new s3 connect string integration possibility.
  [Kaarel Moppel]

  New manifest section: integrations


0.9.12 (2024-12-10)
-------------------
- Release: version 0.9.12 🚀 [Kaarel Moppel]
- Show Spot and On-demand prices without decimals if > $100. [Kaarel
  Moppel]
- Set a "Name" tag on VM create automatically if not set by the user.
  [Kaarel Moppel]

  In the form of '$instance-name [pg-spot-operator]'.

  To provide better recognition in the AWS Web Console.
- Merge pull request #109 from pg-spot-ops/list-instances. [Kaarel
  Moppel]

  New CLI flag: --list-instances
- Docement the new --list-instances option. [Kaarel Moppel]
- Add some more fields to the --list-instances output table. [Kaarel
  Moppel]
- New CLI flag: --list-instances. [Kaarel Moppel]

  Show key attributes from boto3.describe_instances
- Expose --storage-speed-class manifest attribute via the CLI. [Kaarel
  Moppel]

  As sometimes actually want HDD instances for testing
- Merge pull request #108 from pg-spot-ops/ansible-connstr-output.
  [Kaarel Moppel]

  Add an option to get Ansible inventory suitable output in --connstr-output-only mode
- Don't try to download Ansible files when --vm-only set. [Kaarel
  Moppel]

  As not needed
- README - mention that one can also use the operator for non-Postgres
  tasks. [Kaarel Moppel]

  And generate an Ansible inventory file plus just run custom playbooks
- Rename --connstr-output-format to --connstr-format. [Kaarel Moppel]
- Add new --connstr-output-format CLI flag. [Kaarel Moppel]

  To get an Ansible compatible inventory string for easy custom setups,
  where --connstr-output-format=ansible given
- README update - mention idling server estimates. [Kaarel Moppel]
- README - a more complete PyPI example + mention brute-force
  protectoion. [Kaarel Moppel]
- Merge pull request #105 from pg-spot-ops/cli-list-strategies-flag.
  [Kaarel Moppel]

  A new CLI flag:  --list-strategies
- Turn instance selection strategies into string constants. [Kaarel
  Moppel]
- Bail on invalid --selection-strategy input and list available
  strategies. [Kaarel Moppel]
- Add new --list-strategies CLI flag. [Kaarel Moppel]

  To explain available strategies. Also add a hint to this new flag in the
  check price output


0.9.11 (2024-12-06)
-------------------
- Release: version 0.9.11 🚀 [Kaarel Moppel]
- README - update the Docker usage example. [Kaarel Moppel]

  Use region us-east-1 to be in sync with PyPI quickstart
- Fix EBS volumes re-mounting. [Kaarel Moppel]

  Re-attach didn't work in case device had nvme1 in name
- Merge pull request #104 from pg-spot-ops/fix-price-fetching-for-
  running-instances. [Kaarel Moppel]

  Spot price displaying of running instances was flawed
- Add small explanation why need to use boto3 pricing API when AZ set.
  [Kaarel Moppel]
- Spot price displaying of running instances was flawed. [Kaarel Moppel]

  Didn't work after an engine restart


0.9.10 (2024-12-05)
-------------------
- Release: version 0.9.10 🚀 [Kaarel Moppel]
- Ansible - fix APT cache for recently added fail2ban role. [Kaarel
  Moppel]

  1h caching for other APT updates also to speed things up a bit
- Merge pull request #103 from pg-spot-ops/exclude-previously-fast-
  failed-instance-types-from-creation. [Kaarel Moppel]

  Better uptime - create previously fast-failed instance types as last resort only
- Change short lifetime optimization strategy - just reorder. [Kaarel
  Moppel]

  Instead of actually removing instance types from the shortlist. If all
  shortlist members had evictions then re-apply eviction rate based
  sorting
- More uptime - exclude previous short lifetime instance types on
  create. [Kaarel Moppel]

  We'll go to higher priced instance types if previous ran <5min within a
  30min window
- Merge pull request #102 from pg-spot-ops/python-test-matrix. [Kaarel
  Moppel]

  CI test / lint on all modern Python versions
- Fix a Py 3.10 linter issue. [Kaarel Moppel]
- CI test / lint on all modern Python versions. [Kaarel Moppel]


0.9.9 (2024-12-04)
------------------
- Release: version 0.9.9 🚀 [Kaarel Moppel]
- Fix unterminated string literal for Python 3.10. [Kaarel Moppel]

  From last PR: approx_rds_x = f"{math.ceil(


0.9.8 (2024-12-04)
------------------
- Release: version 0.9.8 🚀 [Kaarel Moppel]
- Appease linter. [Kaarel Moppel]

  pg_spot_operator/cli.py:619: error: Argument 1 to "add_rows" of "PrettyTable" has incompatible type "list[tuple[Any, ...]]"; expected "Iterable[list[Any]]"  [arg-type]
- Merge pull request #101 from pg-spot-ops/try-next-sku-on-create-
  failure. [Kaarel Moppel]

  Better HA - try next cheapest SKU when getting InsufficientInstanceCapacity on VM create
- Fix AZ info not being set correctly on price resolving. [Kaarel
  Moppel]
- Don't need the resolved_instances manifest attribute after all.
  [Kaarel Moppel]
- Re-try with another instance type when getting
  InsufficientInstanceCapacity. [Kaarel Moppel]

  Try up to 3 instance types during one main loop
- Tune the pricing table output a bit more + README update. [Kaarel
  Moppel]
- Re-sort the price check output before display using cheapest strategy.
  [Kaarel Moppel]
- Add justification to the price output table. [Kaarel Moppel]
- Use prettytable instead of tabulate. [Kaarel Moppel]

  Add an additional sort if doing a multi-region price check
- WIP pretty printing. [Kaarel Moppel]
- Make multi-instance selection work. [Kaarel Moppel]
- Instance selection strategies now returning lists. [Kaarel Moppel]
- Add SSH brute force protection via fail2ban. [Kaarel Moppel]

  New attribute os.ssh_brute_force_protection defaulting to True. A custom
  Ansible implementation sadly as seems fail2ban doesn't work OOB on
  Debian 12
- Enable pgBackRest encryption by default. [Kaarel Moppel]

  With a dummy password though but better than none
- PgBackrest S3 backup - limit process-max to max 16 cores. [Kaarel
  Moppel]

  Doesn't seem to bring much after that
- Merge pull request #100 from pg-spot-ops/add-hba-lines-cli-flag.
  [Kaarel Moppel]

  New CLI flag --pg-hba-lines to override operator defaults
- New CLI flag --pg-hba-lines to override operator defaults. [Kaarel
  Moppel]

  Which might be too wide if SG not trimmed down.

  https://github.com/pg-spot-ops/pg-spot-operator/issues/6
- Gran non-superuser the built-in replication role. [Kaarel Moppel]

  To be able to use Logical Replication by default
- Better Ansible defaults and move some tuning settings to Ansible.
  [Kaarel Moppel]
- Remove the Docker workflow entirely as on Docker Hub. [Kaarel Moppel]

  Was commented out but that doens't play nice with GH Actions seems
- Don't validate CLI args when manifest specified explicitly. [Kaarel
  Moppel]
- Merge pull request #99 from pg-spot-ops/add-auth-delay-to-pgconf-3.
  [Kaarel Moppel]

  Major ansible restructuring - group_vars + other
- Sync monitoring section Python defaults with Ansible. [Kaarel Moppel]

  No monitoring by default. As get a bit faster to connect string
- Add back example Vault encrypted password to the example manifest.
  [Kaarel Moppel]
- Add test for merge_user_and_tuned_non_conflicting_config_params.
  [Kaarel Moppel]
- Remove vars/instance_manifest.yml as using group_vars. [Kaarel Moppel]
- Do more verbose logging also in Ansible if --verbose set. [Kaarel
  Moppel]
- Fix Ansible failing on app user privs not having a DB yet. [Kaarel
  Moppel]
- Show merged vars as 0 step for single_instance_setup.yml. [Kaarel
  Moppel]

  Add missing top sections + remove unneeded defaults from default_manifest.yml
- Space pad the instance manifest instead of plain YAML dump. [Kaarel
  Moppel]

  To preserve vault secrets
- Fix linter. [Kaarel Moppel]
- Run make fmt && make lint. [Evans Akai Bekoe]
- Rebase and fix types and references. [Evans Akai Bekoe]
- Fix misc issues. [Evans Akai Bekoe]
- Rebase on main branch. [Evans Akai Bekoe]
- Change preload-libraries to dict and dump instance-manifest correctly.
  [Evans Akai Bekoe]
- Fix postgres_cluster_name scattering. [Evans Akai Bekoe]
- Unify default, instance and engine manifests. [Evans Akai Bekoe]
- Refactor roles/merge_vars into inventory group_vars. [Evans Akai
  Bekoe]
- Rename merge_var.yml as _preprocess.yml. [Evans Akai Bekoe]
- Factor out and include pretasks. [Evans Akai Bekoe]
- Copy-paste config_lines to instance_manifest. [Evans Akai Bekoe]
- Add postgresql conf default for auth-delay. [Evans Akai Bekoe]


0.9.7 (2024-11-28)
------------------
- Release: version 0.9.7 🚀 [Kaarel Moppel]
- Don't require --region to be set in explicit VM host mode. [Kaarel
  Moppel]

  when --vm-host set
- Fix latest 0.9.6 release for Python < 3.12. [Kaarel Moppel]

  Seems e4391718de3cf9c27 hit some weird f-string handling difference not
  picked up by linter, got:

  File "/home/krl/.local/pipx/venvs/pg-spot-operator/lib/python3.10/site-packages/pg_spot_operator/cli.py", line 720
    zip_url = f"https://github.com/pg-spot-ops/pg-spot-operator/archive/refs/tags/{data["tag_name"]}.zip"


0.9.6 (2024-11-27)
------------------
- Release: version 0.9.6 🚀 [Kaarel Moppel]
- Require --storage-min set in non-price-check modes. [Kaarel Moppel]

  When not using a fixed VM or teardown modes
- Improve PyPI Ansible setup files downloading - follow tags. [Kaarel
  Moppel]

  This allows to introduce breaking Ansible changes seamlessly.

  WARNING - Old PyPI setups should clean ~/.pg-spot-operator/ansible
  to benefit from this change
- Fix static VM Ansible inventory generation. [Kaarel Moppel]

  When --vm-host / --vm-login-user set
- PyPI - a more meaningul description. [Kaarel Moppel]
- Correct 4e2122831 - don't require region for --check-price. [Kaarel
  Moppel]
- Shorten main loop message a bit when all OK. [Kaarel Moppel]
- --check-manifest: require region or availability_zone set. [Kaarel
  Moppel]

  Also move check_manifest_and_exit before check_cli_args_valid(), as most
  CLI flags are not effective in --check-manifest
- Ansible: don't add the dummy test table by default. [Kaarel Moppel]
- K8s / Helm sample deployments - add more main attributes. [Kaarel
  Moppel]

  For a more easier get-go


0.9.5 (2024-11-26)
------------------
- Release: version 0.9.5 🚀 [Kaarel Moppel]
- Merge pull request #97 from pg-spot-ops/add-instance-family-filtering.
  [Kaarel Moppel]

  Add option to select / filter suitable instances based on instance type family regex
- Reflect the new --instance-family option in the README. [Kaarel
  Moppel]
- Implement --instance-family regex based filtering if provided. [Kaarel
  Moppel]
- Add --instance-family dummy attribute. [Kaarel Moppel]
- Merge pull request #96 from pg-spot-ops/api-improvements. [Kaarel
  Moppel]

  API - attribute naming improvements
- API rename: self-terminate -> self-termination. [Kaarel Moppel]
- Admin-user-password -> admin-password. [Kaarel Moppel]
- Admin_user_password -> admin_password. [Kaarel Moppel]
- More postgresql -> postgres. [Kaarel Moppel]
- API: postgresql -> postgres. [Kaarel Moppel]

  Nobody really calls it postgresql I guess
- API: floating_ips -> ip_floating. [Kaarel Moppel]
- API: cpu_architecture -> cpu_arch. [Kaarel Moppel]

  Just a bit too cumbersome on the CLI
- Disable Github Docker workflow as using / testing Docker Hub
  integration. [Kaarel Moppel]
- Merge pull request #95 from pg-spot-ops/cli-add-volume-type-iops-
  bandwith. [Kaarel Moppel]

  CLI - add flags to set volume type, iops, bandwith
- Wire new volume params to the manifest. [Kaarel Moppel]
- Add new flags: --volume-type, --volume-iops, --volume-throughput.
  [Kaarel Moppel]


0.9.0 (2024-11-25)
------------------
- Release: version 0.9.0 🚀 [Kaarel Moppel]
- In CLI input mode infer --region automatically from --zone if not set.
  [Kaarel Moppel]

  Same as in manifest mode. Otherwise would get still a global price
  check in --check-price mode
- Merge pull request #94 from pg-spot-ops/check-price-improvements.
  [Kaarel Moppel]

  Check price improvements - don't bail when one region's price fetching fails + allow global --check-price
- README update - demo the new global price check. [Kaarel Moppel]

  In the Usage via Python section
- Allow global price check with no region set at all. [Kaarel Moppel]
- Improve CLI input validation - don't need --storage-min for EBS
  storage. [Kaarel Moppel]

  Also can have --instance-name set for --check-price mode
- Fix authenticated / boto3 price resolving. [Kaarel Moppel]
- Show a warning about regions not reached for pricing info. [Kaarel
  Moppel]

  A la:
  WARNING - failed to inquiry regions: ['ap-southeast-5', 'cn-north-1', 'cn-northwest-1']
- Logging - don't show asctime and levelname in --check-price mode.
  [Kaarel Moppel]
- Global --check-price improvements - dont bail on one region failing.
  [Kaarel Moppel]
- Improve HW reqs change handling. [Kaarel Moppel]

  Currently the running instance was terminated but due to caching the
  "ensure VM" function didn't pick up and a whole main loop passed before
  rebuild was tried
- Retries for --connstr-output-only mode. [Kaarel Moppel]

  Currently program exited on first loop errors in --connstr-output-only
  mode but no real season for that, cloud is volatile - just keep trying
- Linter Python 3.10 -> 3.12. [Kaarel Moppel]
- Fix new Ansible folder created on each main loop in case of errors.
  [Kaarel Moppel]

  Can take too much disk space in the end if left running for too long.
  Now have oa folder per action per day
- Fix explicit --instance-types input being too aggressive. [Kaarel
  Moppel]
- Merge pull request #93 from pg-spot-ops/eviction-rate-strategy.
  [Kaarel Moppel]

  Add eviction rate based and a balanced instance selection strategy
- In "cheapest" selection mode don't consider the worst eviction rate
  bracket still. [Kaarel Moppel]

  With >20% eviction rates
- README - add new eviction rate indicator to sample --check-price
  output. [Kaarel Moppel]
- Update READMEs + log hints on used strategy. [Kaarel Moppel]
- Make the new "balanced" instance selection strategy the default.
  [Kaarel Moppel]
- Add a "balanced" instance selection strategy. [Kaarel Moppel]

  Weighed average on price + eviction rate
- Add tests for instance_type_selection.py. [Kaarel Moppel]
- Rename InstanceTypeSelectionDefault to InstanceTypeSelectionCheapest.
  [Kaarel Moppel]
- Eviction rate strategy working. [Kaarel Moppel]

  Also show the expected eviction rate when we have the information
- WIP refactor selection strategy. [Kaarel Moppel]
- Add AWS public Spot eviction rate parsing. [Kaarel Moppel]

  Based on https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json
- README - reduce quickstart --check-price output a bit for readability.
  [Kaarel Moppel]

  Also hint that --region can be a regex in --help
- README - mention port 22 SG access pre-requisite in Quickstart.
  [Kaarel Moppel]

  Remove port 5432 mention as not a hard requirement for successful Ansible setup
- README - mention port 22 / 5432 SG access pre-requisite in Quickstart.
  [Kaarel Moppel]


0.8.8 (2024-11-19)
------------------
- Release: version 0.8.8 🚀 [Kaarel Moppel]
- README - mention "assume role" based authentication option. [Kaarel
  Moppel]

  Under pre-requisites to creating a DB
- Cross regional price check (#90) [Kaarel Moppel]

  * Add util to resolve fuzzy regions to real ones

  * Main flow in place - show max top 3 cheapest regions

  * Cope with parsing of NA spot prices in S3 price list files

  * Update READMEs to reflect the new --region regex + --check-price combo

  * Fail early when regex --region input used in non-check-price mode

  * Don't allow regex --region also for --teardown / --teardown-region
- New CLI flag: --list-regions (#89) [Kaarel Moppel]

  * New CLI option: --list-regions

  * Document new --list-regions in docs/README_env_options.md
- Show selected instance storage speed class also. [Kaarel Moppel]

  Or "EBS only" if no instance storage support
- Uncomment S3 privileges in sample Terraform. [Kaarel Moppel]

  As not needed for base functionality


0.8.7 (2024-11-19)
------------------
- Release: version 0.8.7 🚀 [Kaarel Moppel]
- Fix CPU arch "guessing" from instance_type name. [Kaarel Moppel]

  Was fixed to ARM. Assuming "g" always present for ARM instances
- Bump codecov/codecov-action from 4 to 5 (#87) [dependabot[bot],
  dependabot[bot]]

  Bumps [codecov/codecov-action](https://github.com/codecov/codecov-action) from 4 to 5.
  - [Release notes](https://github.com/codecov/codecov-action/releases)
  - [Changelog](https://github.com/codecov/codecov-action/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/codecov/codecov-action/compare/v4...v5)

  ---
  updated-dependencies:
  - dependency-name: codecov/codecov-action
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Non auth price check (#88) [Kaarel Moppel]

  * WIP

  * Parse ResolvedInstanceTypeInfo from AWS static ondemand pricing JSON

  Some info is not quite as explicit as from boto3 directly, like CPU
  arch, so need to do some best effort heuristics until find a better
  source for instance details

  * WIP

  * Generalize instance type info from boto3 and JSON APIs into InstanceTypeInfo

  * Linter passing

  * Fix ondemand JSON cache reading

  * Don't ugly-error when no SKUs match user HW reqs

  * Fix CPU arch filtering

  Support arm / non-arm only for now

  * Fix non-auth price fetching from sa-east-1 region

  South America (São Paulo) had to be un-accented

  * In debug mode hint if using the S3 API or boto3 calls for pricing

  * Respect --instance-types user input

  Don't consider any other SKUs then

  * Minor formatting / debug output changes

  * README - update to new output messages

  Plus add an approximate comparison to RDS prices
- Fetch price info via AWS endpoints (#67) [Evans Akai Bekoe, Kaarel
  Moppel]

  * fetch price info via AWS endpoints

  * fix linter and errors

  * provide else-clause of pricing function

  * cast price string to float

  * add logging for when pricing info is not found

  * Don't double-check the pricing manifest + os.path.join + some logging

  * Simplify on-demand price parsing + a test

  * WIP

  * Pass tests - simplify the on-demand pricing URL derivation

  * Use the old ec2.shop for fallback if AWS static info fails

  * Round on-demand AWS and fallback price using same precision

  * Clean up older than 1 week ondemand pricing files automatically

  * Don't fetch the ondemand meta files at all as not likely to change

  And we have a fallback in place

  ---------
- K8s/README_k8s.md typo. [Kaarel Moppel]
- README - add a link to the k8s sub-readme. [Kaarel Moppel]
- Add a K8s readme. [Kaarel Moppel]
- Minor k8s/example_deployment.yaml adjustment. [Kaarel Moppel]
- Helm example - set storageClass to "standard" [Kaarel Moppel]

  To make Minikube PVCs work without an explicit PV
- Add some more Docker build exclude folders. [Kaarel Moppel]
- K8s - add a sample Deployment manifest. [Kaarel Moppel]
- K8s - add a minimal Helm chart (#85) [Kaarel Moppel]

  * Add a minimal Helm chart

  * Make basic skel work

  * Add PVC for .ssh

  * Add a PV to make minikube happy

  * Silence "image has non-numeric user (nobody)" errors

  100Mi -> 10Mi SSH volume

  * Add an initContainer to deployment

  To fix /app/.ssh permissions that get set to root on volume mount. There
  must be a better way though??
- Docker - generate SSH keys properly during runtime (#84) [Kaarel
  Moppel]

  * Docker - generate SSH keys during runtime

  Add a dump-init entrypoint wrapper for that

  * Set Docker user ID to 5432 to appease PodSecurityPolicy runAsNonRoot

  Also remove some root useful extra packages

  * Create /app/.ssh during image build
- README - remove Docker examples with bind mounts. [Kaarel Moppel]

  As most probably will now run into user privilege issues after switching
  to a non-root image + safer conceptually also to feed in only what is
  required
- Docker - fix non-root user Ansible SSH access. [Kaarel Moppel]

  Seems HOME for the nobody user resolved to /nonexistent. Thus
  create a soft-link to /app

  debug1: Trying private key: /nonexistent/.ssh/id_rsa
- Ansible - do not cache SSH signatures on connect. [Kaarel Moppel]

  Better for long-term setups
- Increase SSH ConnectTimeout to 3s from 1s for the displayed SSH
  connstr. [Kaarel Moppel]
- Make --connstr-output-only --vm-only aware. [Kaarel Moppel]

  Print out the SSH "connstr" instead of Postgres connstr
- Docker - switch to a non-root image (#83) [Kaarel Moppel]

  As things seems to have matured enough
- README - replace Github release badge with PyPI release. [Kaarel
  Moppel]
- README - add a few badges. [Kaarel Moppel]
- README - fix double credentials setting in the Docker example. [Kaarel
  Moppel]
- Docker image building - point to Containerfile explicitly. [Kaarel
  Moppel]
- Automate Docker image building / publishing. [Kaarel Moppel]
- Region teardown improvement - mark all instances as deleted also in
  CMDB. [Kaarel Moppel]

  Consider any CMDB errors as non-critical though
- Fix --teardown-region - not all instances were cleaned up. [Kaarel
  Moppel]

  The describe_instances loop didn't account for multiple reservations
- VM provisioning - increase OS disk from default 8 to 20 GB. [Kaarel
  Moppel]

  Previous change wasn't effective as root device for Debian AMI is
  actually /dev/xvda not /dev/sda1
- Docs/README_development.md - link to the Resource Explorer img.
  [Kaarel Moppel]
- README_development.md - mention AWS Resource Explorer. [Kaarel Moppel]

  To track down any operator created objects if needed
- README_integration.md - note that callbacks are limited to 30 seconds
  runtime. [Kaarel Moppel]
- A new top level manifest attribute "vm_only" to skip the Postgres
  setup (#82) [Kaarel Moppel]

  * New top level manifest attribute: vm_only

  To skip the Postgres setup

  * Update the manifest in CMDB after vm_only loop also

  As in normal mode, not to get superfluous manifest diff output
- Hint that non-floating IPs take longer to recover after an eviction.
  [Kaarel Moppel]

  Due to some AWS NIC state refresh lag, can't re-attach before NIC shown
  as available again
- Teardown fixes (#81) [Kaarel Moppel]

  * Delete only explicitly created NICs on teardown

  Also only EIPs of the target instance

  * Delete NICs before EIPs also in teardown_region()

  As EIPs depend on NICs

  * Don't even try to delete backup if we don't have a bucket set
- Mention our VPC + IAM setup Terraform scripts also in the AWS CLI
  readme. [Kaarel Moppel]
- README - suggest to run the Terraform from "scripts" if no play
  account. [Kaarel Moppel]

  available for the user
- Fix last one - add missing EIP policies. [Kaarel Moppel]
- Example Terraform to create a sandbox VPC + IAM user + creds (#80)
  [Kaarel Moppel]

  IAM policies are region limited for additional play safety
- READEME - switch quickstart demo from Docker to Py as more terse.
  [Kaarel Moppel]
- New CLI flag: --aws-key-pair-name / PGSO_AWS_KEY_PAIR_NAME (#78)
  [Kaarel Moppel]

  * New CLI flag: --aws-key-pair-name / PGSO_AWS_KEY_PAIR_NAME

  To specify an existing EC2 SSH key pair to access the VM. Other SSH
  inputs also still effective

  * Don't bail when aws.key_pair_name input is invalid

  As other SSH key specification options could be valid

  * README - in Docker howto showcase the new PGSO_AWS_KEY_PAIR_NAME envvar
- README - make more clear which AWS credentials are required. [Kaarel
  Moppel]

  In the quickstart section


0.8.6 (2024-11-05)
------------------
- Release: version 0.8.6 🚀 [Kaarel Moppel]
- Don't display the main loop sleep message in dry-run mode. [Kaarel
  Moppel]
- Auto-download ansible setup scripts from GitHub if missing (#76)
  [Kaarel Moppel]

  * Auto-download the Ansible setup scripts from Github

  If not found locally and --ansible-path not set. To make pipx usage
  more user-friendly

  * More Github downloading to util.py
- Security readme - recommend a new isolated VPC for running the
  operator. [Kaarel Moppel]
- Add a separate Readme for CLI options (#70) [Kaarel Moppel]

  * Add a new help doc on CLI / ENV input parameters

  * Move to "definition list" format for readability

  * Revert "Move to "definition list" format for readability"

  This reverts commit 93397a0935e6d772b77d61ac209bae5dbf9d6850.

  As seems Github does not support Markdown definition lists yet :(

  * Fix a line
- README - mention the support for Ansible Vault secrets. [Kaarel
  Moppel]
- README - add a section on extensions usage. [Kaarel Moppel]
- README typos + minor wording. [Kaarel Moppel]

  Move the project status section to footer
- README update - more compact quickstart. [Kaarel Moppel]
- Mask long and ugly AWS API timeout errors in non-verbose mode. [Kaarel
  Moppel]

  When listing active VMs. As quite common actually on flaky network.
- README usage section - link to all options. [Kaarel Moppel]

  And add an example parameter to enable the pgvector extension
- Refactor cleanup helper (#68) [Kaarel Moppel]

  * Clean up resources region by region

  More logical so

  * Loop regions by sorted region name

  * Dont run the script without any parameters

  Show usage instead if no params given
- Remove some noise from the README. [Kaarel Moppel]

  Some sections actually linked in footer


0.8.5 (2024-10-24)
------------------
- Release: version 0.8.5 🚀 [Kaarel Moppel]
- README - remove instance name from the quickstart price check example.
  [Kaarel Moppel]

  As not required since prev commit
- Don't require --instance-name input in --check-price mode. [Kaarel
  Moppel]
- Don't store user provided secrets in plain-text in the CMDB (#64)
  [Kaarel Moppel]

  * Don't store any user secrets in the CMDB

  As per user feedack. Carries some risk still although mostly a dev tool

  * Refactor the connect string printing to a more logical place

  As per PR review https://github.com/pg-spot-ops/pg-spot-operator/pull/64

  * Rebase
- In --check-price mode show the spot price in any case. [Kaarel Moppel]

  Even if can't get the On-Demand price for a discount comparison
- Docs reorg - split the README (#66) [Kaarel Moppel]

  * Add a short primer on AWS CLI basics

  * Split main README into smaller ones by topic

  * Check linking

  * Link all sections

  * Add a note on project status

  * Make 1st lines of README more light to read

  Plus don't downplay the security posture, as still accounted for

  * AWS basics - add a link to account creation

  * Change docs base path from reorg branch to main
- Delete tmp Ansible folder after success (#65) [Kaarel Moppel]

  To lower the likelyhood of leaking any passwords
- Allow using non-default VPCs (#60) [Kaarel Moppel]

  * New manifest attribute / CLI flag --aws-vpc-id

  To be able to use non-default VPCs more conveniently. Previously once
  could already do it by specifying a Subnet ID - but this assumes also
  the AZ is set correctly by the user. Now we select the subnet according
  to the cheapest AZ found if just VPC ID specified

  * README - add information on the new --aws-vpc-id flag

  Plus move the whole Security section higher, as obviously a topic
  nowadays

  * README - recommend a new VPC for all operator instances

  * README - add example information how to create a new play VPC

  Toghether with SG rules opening up ports used by the operator

  * Rename --public-ip to --assign-public-ip

  As per PR feedback

  * Specify what a public instance means
- Increase after-VM-create sleep from 5s to 10s. [Kaarel Moppel]

  Seems reducing after-VM-create sleep from 30s to 5s was too optimistic
  still
- Update README.md. [Evans Akai Bekoe]


0.8.2 (2024-10-17)
------------------
- Release: version 0.8.2 🚀 [Kaarel Moppel]
- README - Add info on Python installation via pipx (#59) [Kaarel
  Moppel]

  * Add info on Python installation via pipx

  * Demo the newly added --ansible-path flag when running via pipx
- Make custom Ansible paths possible via --ansible-path (#58) [Kaarel
  Moppel]

  For example when wanting to do some customizations to the Postgres setup
  or when using via PyPI / pipx


0.8.1 (2024-10-17)
------------------
- Release: version 0.8.1 🚀 [Kaarel Moppel]


0.8.0 (2024-10-17)
------------------
- Release: version 0.8.0 🚀 [Kaarel Moppel]
- Faster teardown - don't sleep unnecessarily (#57) [Kaarel Moppel]

  If there are no volumes (--storage-type=local) then no reason to sleep.
  And if using floating IPs then NIC is set to DeleteOnTermination and
  don't have to do anything
- Some messages were still only about looking for the cheapest VM (#55)
  [Kaarel Moppel]

  https://github.com/pg-spot-ops/pg-spot-operator/issues/13
- Reduce after-VM-create sleep from 30s to 5s. [Kaarel Moppel]

  As already checking the instance state in ensure_vm()...but still need a
  bit of extra as "available" state doesn't mean actually that one can
  yet log in. 5s seems to work well though.

  https://github.com/pg-spot-ops/pg-spot-operator/issues/46
- Don't create a NIC in floating IP mode (#52) [Kaarel Moppel]

  As less chance of abandoned resources + faster ressurect after eviction as don't have to wait for the NIC to become "available"

  * Don't create a NIC in floating IP mode

  Rename floating_public_ip -> floating_ips

  https://github.com/pg-spot-ops/pg-spot-operator/issues/7

  * Add some comments around public IPs to the example manifest
- Merge pull request #54 from pg-spot-ops/non-default-ssh-key-option.
  [Evans Akai Bekoe]

  New flag --ssh-private-key + Ansible manifest section
- Take account --ssh-private-key when displaying the SSH connect string.
  [Kaarel Moppel]
- Check on startup that --ssh-private-key .pub file also exists. [Kaarel
  Moppel]
- New flag --ssh-private-key + Ansible manifest section. [Kaarel Moppel]

  New section as proably need to add all other Ansible connection opts
  also to support ProxyCommand etc
- Show the SSH connect string on VM create / instance setup finished
  (#53) [Kaarel Moppel]

  https://github.com/pg-spot-ops/pg-spot-operator/issues/26
- Don't show "Re-configuring Postgres" when in --vm-only mode. [Kaarel
  Moppel]
- Correct last commit typo. [Kaarel Moppel]
- Survive when public or private primary IP address of instances changes
  (#51) [Kaarel Moppel]

  Normally should not happen but possible. Re-register in CMDB then.
- Show progress messages still in --connstr-output-only mode (#50)
  [Kaarel Moppel]

  Was a bit too scary
- Detect externally set expiration tags and terminate the instance if
  needed (#47) [Kaarel Moppel]

  * Detect externally set expiration tags and shut down the engine

  To to counter the "runaway daemon" problem

  https://github.com/pg-spot-ops/pg-spot-operator/issues/33

  * Ensure the externally signalled expiry is persistent on one engine node

  By introducing a new Sqlite table "ignored_instance"

  * Don't shut down the engine after external signalling

  This reduces the chance of a resurrect-loop if running Docker with something
  like --restart=unless-stopped

  * Take into account --dry-run and custom host modes
- Proofread readme (#49) [Evans Akai Bekoe]

  * proofread readme

  * proofread readme
- Support adding extensions over the CLI (#48) [Kaarel Moppel]

  * New CLI flags --os-extra-packages and --shared-preload-libraries

  To enable non core extensions like postgis or timescaledb. By default
  only load pg_stat_statements

  * Add a new CLI / manifest attribute "extensions"

  To pre-create listed extensions as users don't have the necessary privs
  if admin_is_superuser=false

  * Fix linter

  * Improve --os-extra-packages help comment

  To be really comma separated
- Add --app-db-name / PGSO_APP_DB_NAME flag. [Kaarel Moppel]

  To create a non-postgres DB for app / user usage
- Fix non-admin user default DB and public schema privs. [Kaarel Moppel]

  Non-admin couldn't create tables effectively
- Fix tests/test_manifests.py. [Kaarel Moppel]
- New CLI flag --admin-is-superuser / PGSO_ADMIN_IS_SUPERUSER. [Kaarel
  Moppel]

  Also don't hand out the real superuser by default anymore
- README - specify that the discount rate is to normal EC2 pricing.
  [Kaarel Moppel]

  and RDS actually costs more
- README - add a Why journey to introduce the concept. [Kaarel Moppel]
- CLI - don't require --storage-min in --teardown or --teardown-region
  mode. [Kaarel Moppel]
- README - link to RDS pricing + indicate approximate uptime. [Kaarel
  Moppel]
- README - elaborate more on the input manifests. [Kaarel Moppel]
- README - move "integrating with apps" section higher. [Kaarel Moppel]

  Add a note about tags usage
- README - clarify user input options + add a VC subsection. [Kaarel
  Moppel]
- README update - fix some inconsistencies. [Kaarel Moppel]
- Add support for optional on-the-VM monitoring (#29) [Kaarel Moppel]

  * Add Ansible monitoring_setup role

  Installs prom + node_exporter if monitoring.node_exporter set

  * Grafana setup added

  * New vars structure

  Replace "lineinfile" grafana.ini with a custom ini template

  * Provision 2 dashboards - node exporter basic + node exporter full

  Slightly modified versions of:
  https://grafana.com/grafana/dashboards/13978-node-exporter-quickstart-and-dashboard/
  https://grafana.com/grafana/dashboards/1860-node-exporter-full/

  * Fix cold apt cache

  * Make node exporter quickstart dash Grafana global default

  * Rename local_only -> externally_accessible in monitoring section

  * Fix externally_accessible effect - was reversed actually

  * Add monitoring.grafana.protocol param to control TLS

  Enabled via a self-signed certificate by default

  * WIP Monitoring CLI flags + README

  * Integrate with the engine. Feature complete now

  * README minor correction

  * Fix CLI to_bool -> str_to_bool rename leftovers

  * Display the Grafana URL if enabled

  * Node exporter quickstart dash - add tooltip sort by descending

  * Make monitoring.grafana.protocol setting a bit more foolproof

  As per PR review

  * Don't rotate Grafana certs on every Ansible run
- README minor fix - Docker path location. [Kaarel Moppel]
- Reduce Cronjob chattiness in --self-terminate mode. [Kaarel Moppel]

  As Cron assumes if failed when producing output
- Cli price check mode (#32) [Kaarel Moppel]

  * Add a new CLI flag --check-price / PGSO_CHECK_PRICE env var

  Resolves HW reqs (according to the --selection-strategy in effect), displays the current Spot price and exits

  Some AWS secrets setting refactor bycatch
- README ports section - add a sample AWS CLI command to enable SSH
  access. [Kaarel Moppel]

  for the engine node IP address only
- README - add a section on relevant ports / EC2 Security Group
  permissions. [Kaarel Moppel]
- Improve the delete_all_operator_tagged_objects.sh script. [Kaarel
  Moppel]

  Scan all active regions by default for Spot Operator resources
- Postgres tuning - use SKU real CPU / RAM / disk info when available.
  [Kaarel Moppel]

  So far was using the user input, but as it's "min_cpu" etc, the real
  harware can be much more powerful
- Docker - use latest (3.12) Python base image. [Kaarel Moppel]
- CLI flags - enable custom AWS subnets and Security Groups. [Kaarel
  Moppel]

  By adding 2 new flags --aws-security-group-ids and --aws-subnet-id
- Increase AWS root volume size from default 8 to 20GB. [Kaarel Moppel]

  8 is too skimpy probably, might want to install some custom packages
  still for ad-hoc analytics etc
- Cli.py fix to_bool -> str_to_bool leftover. [Kaarel Moppel]
- Require --expiration-date when --self-terminate set. [Kaarel Moppel]
- README - add --self-terminate mode info. [Kaarel Moppel]
- New CLI flags --self-terminate --self-terminate-access-key-id --self-
  terminate-secret-access-key. [Kaarel Moppel]

  Need explicit input - not read from local AWS config as with normal --aws-access-key-id and
  --aws-secret-access-key as there are serious security implications
- Reference instance_teardown.py from root home in cron. [Kaarel Moppel]
- Roles/self_terminatio - main flow implemented. [Kaarel Moppel]

  Install a cronjob under root to check "expiration_date" every 10mins
- New feature - fire-and-forget auto-terminate mode WIP. [Kaarel Moppel]
- Validate --instance-name and --storage-type. [Kaarel Moppel]
- Update README about the new --connstr-output-only mode. [Kaarel
  Moppel]
- New feature: --connstr-output-only mode. [Kaarel Moppel]

  Ensure VM, set up Postgres, print connstr and exit. Helps with all kinds
  of integrations / pipelines
- README - mention that a setup from zero typically takes 2-3min.
  [Kaarel Moppel]
- Enable Ansible pipelining to speed up the setup. [Kaarel Moppel]

  From zero setup taking 2-3min usually now
- Show the selected zone instead of region on new instance selection.
  [Kaarel Moppel]

  To better see what zones are cheap currently
- Don't auto-add quotes to --expiration-date input. [Kaarel Moppel]

  Leave it to user as leads to confusing errors otherwise
- HW filtering - exclude burstable instance types by default. [Kaarel
  Moppel]

  As tend to get killed more often
- Refactor manifest compilation from CLI args. [Kaarel Moppel]

  Skip the intermediary text glueing - set InstanceManifest attributes
  and export to YAML in the end, as need a textual representation also
  for SQLite storage / change diffing
- Adjust CLI params. [Kaarel Moppel]
- Convert roles/open_pg_instance_access. [Kaarel Moppel]
- Convert roles/pgbackrest_restore. [Kaarel Moppel]
- Convert roles/configure_pgbackrest. [Kaarel Moppel]
- Convert roles/init_pg_instance. [Kaarel Moppel]
- Convert roles/os_setup. [Kaarel Moppel]
- Convert roles/install_os_pg_prereqs. [Kaarel Moppel]
- Convert merge_vars. [Kaarel Moppel]
- Python side moved to new manifest API. [Kaarel Moppel]
- Fix --dry-run Ansible inventory compilation. [Kaarel Moppel]
- CLI rename --selection to --selection-strategy. [Kaarel Moppel]

  Manifest field: vm.instance_selection_strategy
  Currently supported: cheapest | random
- Merge pull request #17 from pg-spot-ops/14-instance-choice-strategy.
  [Evans Akai Bekoe]

  allow random strategy for instance-type selection
- Fix misc review stuff. [Evans Akai Bekoe]
- Fix misc review comments. [Evans Akai Bekoe]
- Allow random strategy for instance-type selection. [Evans Akai Bekoe]
- Merge pull request #21 from pg-spot-ops/non-su-power. [Evans Akai
  Bekoe]

  add more roles to pg admin user
- Fix review items. [Evans Akai Bekoe]
- Add more roles to admin user. [Evans Akai Bekoe]
- WIP. [Kaarel Moppel]
- If admin_is_superuser not set, grant all built-in Postgres roles
  instead. [Kaarel Moppel]
- Fix find_cheapest_spot_region_for_instance_type.py UTC handling.
  [Kaarel Moppel]
- README update on expected eviction rates. [Kaarel Moppel]
- Generate correct inventory file in --dry-run mode for fixed host.
  [Kaarel Moppel]

  Use provided vm.host / vm.login_user instead of localhost
- Fixed vm.host / vm.login_user was ignored for manifest files. [Kaarel
  Moppel]
- README - add a section on the Enterprise Edition. [Kaarel Moppel]
- Ansible - fix unattended upgrades setup. [Kaarel Moppel]

  vm.unattended_security_upgrades input var was not actually effective.
  Also enable automatic reboot if needed
- Main loop - show backing instance type also if a VM exists. [Kaarel
  Moppel]
- Limit get_current_hourly_ondemand_price fetching completion to 5s.
  [Kaarel Moppel]
- Implement pg_config.ensure_shared_preload_libraries. [Kaarel Moppel]

  List converted to shared_preload_libraries (+ restart of Postgres when
  needed) when shared_preload_libraries not already specified by user in extra_config_lines
- Shut down when --teardown set and resource cleanup successful. [Kaarel
  Moppel]
- Clean up logs older than one week on startup. [Kaarel Moppel]

  Ansible actions leave some garbage (full roles + vars + logs) which
  might start to accumulate in long term
- Display backing instance pub / priv IP on a NoOp loop still. [Kaarel
  Moppel]
- Lower default backup.wal_archiving_max_interval to 2min. [Kaarel
  Moppel]

  So that average data loss for instance storage would be around 1min
- README - add a section on backups. [Kaarel Moppel]
- CLI - add pgbackrest s3 backups option. [Kaarel Moppel]

  With s3 cleanup by default on instance expiry. New flags:
    --backup-s3-bucket
    --backup-cipher
    --backup-retention-days
    --backup-s3-key
    --backup-s3-key-secret
- README - clarify remote "postgres" user access possibility. [Kaarel
  Moppel]

  Not enabled by default
- README - add a section "setup finished" callback hook usage. [Kaarel
  Moppel]
- Reduce Containerfile size slightly. [Kaarel Moppel]

  Via apt-clean
- README - add a Security section. [Kaarel Moppel]
- README - all more main features and and --expiration-date sample.
  [Kaarel Moppel]
- README - add a subsection on "destroy file" usage. [Kaarel Moppel]
- Relax the single-engine-process mutex a bit - make it per instance-
  name. [Kaarel Moppel]
- README - add a section on non-cloud development. [Kaarel Moppel]
- Test SSH connection in --dry-run mode when using custom VM. [Kaarel
  Moppel]
- CLI rename --vm-address / username to more clear --vm-host/--vm-login-
  user. [Kaarel Moppel]

  Also in the manifest
- CLI - don't require --region / --storage-min when using a fixed VM.
  [Kaarel Moppel]
- Fix var merging - include new setup_finished_callback. [Kaarel Moppel]
- Set --vm-address / --vm-user also as manifest attributes. [Kaarel
  Moppel]

  So that could test the full lifecycle including callback
- Add --setup-finished-callback CLI param. [Kaarel Moppel]

  Rename Ansible connstr_changed_callback role also to
  setup_finished_callback as called even when the actual connstr doesnt
  change but some other setting
- README update. [Kaarel Moppel]
- Skip 30s sleep if backing VM actually existed during ensure_vm.
  [Kaarel Moppel]
- Don't resolve HW reqs on startup when already have a backing VM.
  [Kaarel Moppel]

  Just show price info
- Containerfile - add missing tuning_profiles folder. [Kaarel Moppel]
- Add standard python3 shebang to tuning profiles. [Kaarel Moppel]
- More logging adjustments. [Kaarel Moppel]
- Reduce some logging noise. [Kaarel Moppel]
- README - switch the run examples to a cheaper 2 CPU instance. [Kaarel
  Moppel]

  Correct Docker image name also
- Add all available fields to the example manifest. [Kaarel Moppel]
- Rename admin_is_real_superuser to admin_is_superuser. [Kaarel Moppel]
- Fix get_network_interfaces, return only NICs related to given
  instance. [Kaarel Moppel]
- Fix CLI set --expiration-date instances resurrected in next loop.
  [Kaarel Moppel]
- Add quotes to --expiration-date CLI param if not already quoted.
  [Kaarel Moppel]
- Implement single instance destroy. [Kaarel Moppel]
- New CLI flag / feature: --destroy-file-base-path. [Kaarel Moppel]

  Defaults to "/tmp/destroy-". Main idea is to auto-shutdown the container
  after instance not needed anyore with something like:
  docker exec pg1 -- touch /tmp/destroy-myinstance
- Add one retry to connstr changed callback invocation. [Kaarel Moppel]
- New feature - execut a user provided callback on connect string
  change. [Kaarel Moppel]
- Implement manifest is_paused attribute. [Kaarel Moppel]

  No engine actions temporarily to perform some user maintenance / shut
  down the instance etc
- Show RAM in MiB if < 1GB instead of 0. [Kaarel Moppel]

  Fix multi-instance cheapest detection
- Support multi-instance input from user. [Kaarel Moppel]

  vm.instance_type -> vm.instance_types list
- Fix test_filter_instances. [Kaarel Moppel]
- Make admin user superuser by default. [Kaarel Moppel]

  As the whole thing geared anyways for power users
- Move single instance mutex check down a bit. [Kaarel Moppel]

  So that can still check for prices when something running
- Ansible - fix default pg_hba access. [Kaarel Moppel]
- Ansible - unused roles cleanup. [Kaarel Moppel]
- CLI add --admin-user / --admin-user-password. [Kaarel Moppel]
- Validate --user-tags on startup instead of manifest compilation.
  [Kaarel Moppel]
- Add --user-tags CLI option. [Kaarel Moppel]
- New feature - upscale / downscale on CPU / RAM requirements change.
  [Kaarel Moppel]

  Also for local instance storage
- Correct instance type filtering. [Kaarel Moppel]

  Don't leave out burstable instances
- Exit after --dry-run first loop. [Kaarel Moppel]
- Add --vm-address / --vm-user to run / test Ansible setup on custom
  host. [Kaarel Moppel]

  Good for local Vagrant testing for example
- Remove --no-recreate flag as cannot implement without a fully stateful
  CMDB. [Kaarel Moppel]
- Add --vm-only / PGSO_VM_ONLY CLI flag to skip Ansible setup. [Kaarel
  Moppel]
- Add --teardown-region CLI option. [Kaarel Moppel]

  Same as delete_all_operator_tagged_objects.sh but for Docker convenience
- CLI - infer --region from --zone if latter set. [Kaarel Moppel]
- Destroy_target_time_utc -> expiration_date leftovers. [Kaarel Moppel]
- Add ansible/v1/merge_vars.yml. [Kaarel Moppel]

  For more convenient merge testing
- Ansible engine vars merging - remove unneeded default vars. [Kaarel
  Moppel]
- Delete object script - add eu-south regions (dev-testing) [Kaarel
  Moppel]
- Don't include 1st disk device into LV when using network storage.
  [Kaarel Moppel]
- Ansible - fix mounting of EBS volumes when local storage also exists.
  [Kaarel Moppel]
- Apply some rounding to the selected instances Spot price. [Kaarel
  Moppel]
- Find_cheapest_spot_region - get rid of depracated warning. [Kaarel
  Moppel]
- Don't validate --region format in case of manifest file input. [Kaarel
  Moppel]
- Decrypt the secrets in main loop before AWS client usage. [Kaarel
  Moppel]
- Make manifest secret decryption generic. [Kaarel Moppel]

  And decrypt also aws.access_key_id / secret_access_key
- Rename ensure_app_dbname to app_db_name. [Kaarel Moppel]
- Fix instance expiry check - account for utc / non-utc inputs. [Kaarel
  Moppel]
- Rename expires_on to more standard expiration_date. [Kaarel Moppel]
- Add pg-spot-operator-expires-on tag to created VMs if set. [Kaarel
  Moppel]
- Find_cheapest_spot_region - add ondemand savings info. [Kaarel Moppel]
- Add util script to find cheapest zone for an instance type. [Kaarel
  Moppel]
- Reduce logging noise, better AMI info. [Kaarel Moppel]
- Validate --region format. [Kaarel Moppel]
- Ensure single instance of program running. [Kaarel Moppel]
- Replace override manifest with a more light session_vars dict. [Kaarel
  Moppel]

  To propagate engine interventions / overrides to ansible
- Encrypt pg.admin_user_password for the sample manifest. [Kaarel
  Moppel]
- Validate vault password decryption with --check-manifests. [Kaarel
  Moppel]
- Ansible - add more default vars. [Kaarel Moppel]

  So that can run roles without manifests in "vars" folder
- Ansible - fix Postgres port to 5432. [Kaarel Moppel]
- Ansible - rename pg.major_ver to top level postgres_version. [Kaarel
  Moppel]
- Remove --sqlite-path param. [Kaarel Moppel]

  Glue SQLITE_DBNAME to --config-dir
- Show selected SKU info only after we have the spot price. [Kaarel
  Moppel]
- Refactor boto3.get_client to a separate file. [Kaarel Moppel]
- README update - docer run with new direct SSH keys / AWS creds input.
  [Kaarel Moppel]
- Add --aws-access-key-id / --aws-secret-access-key params. [Kaarel
  Moppel]

  To not bind ~/.aws to the container
- Tuning - add a line with profile name as a comment. [Kaarel Moppel]
- Apply the "default" tuning profile by default. [Kaarel Moppel]
- Add --tuning-profile / PGSO_TUNING_PROFILE CLI parameter. [Kaarel
  Moppel]

  To be able to apply basic Postgres tuning easily
- Add standalone tuning profiles. [Kaarel Moppel]
- Add --ssh-keys / PGSO_SSH_KEYS param. [Kaarel Moppel]

  For more Docker convenience, so that don't have to bind to host .ssh for
  convenient access
- Replace PyPy instructions with local Python dev. [Kaarel Moppel]
- Add Containerfile. [Kaarel Moppel]
- Pass user_data to ec2_launch_instance. [Kaarel Moppel]
- Make ensure_vm execution less generic. [Kaarel Moppel]
- WIP. [Kaarel Moppel]
- CLI - do some basic validations before CMDB init. [Kaarel Moppel]
- Pass dry-run to ec2_launch_instance and catch ClientError. [Kaarel
  Moppel]
- Fix --dry-run. [Kaarel Moppel]
- Import operator / main loop skel. [Kaarel Moppel]
- Manifest rename - pg.major_ver to top lvl postgres_version. [Kaarel
  Moppel]
- Add SQLite CMDB for keeping instance / VM info and manifest changes.
  [Kaarel Moppel]
- Add --pg-major-version param. [Kaarel Moppel]
- Manifests - move assign_public_ip attr from VM section to root.
  [Kaarel Moppel]
- Add --cpu_architecture arg. [Kaarel Moppel]

  Rename destroy_target_time_utc -> expires_on
- CLI - impl --check-manifest. [Kaarel Moppel]
- Fix tests. [Kaarel Moppel]
- Amend last tests/test_aws_vm.py. [Kaarel Moppel]
- Add test_ensure_spot_vm. [Kaarel Moppel]
- Add a Bash script to clean up any operator created AWS resources.
  [Kaarel Moppel]

  Handy for dev testing
- AWS VM creation skel. [Kaarel Moppel]
- Remove unused imports. [Kaarel Moppel]
- Add manifests.py defining the user input YAML model. [Kaarel Moppel]
- Add AWS impl skel. [Kaarel Moppel]
- Add CLI args. [Kaarel Moppel]
- Add example_manifests/hello_aws.yaml. [Kaarel Moppel]
- Import single instance ansible from EE. [Kaarel Moppel]
- Remove .github/workflows/rename_project.yml. [Kaarel Moppel]
- Remove some template skel files. [Kaarel Moppel]
- Bump actions/checkout from 3 to 4. [dependabot[bot]]

  Bumps [actions/checkout](https://github.com/actions/checkout) from 3 to 4.
  - [Release notes](https://github.com/actions/checkout/releases)
  - [Changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/actions/checkout/compare/v3...v4)

  ---
  updated-dependencies:
  - dependency-name: actions/checkout
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Bump actions/setup-python from 4 to 5. [dependabot[bot]]

  Bumps [actions/setup-python](https://github.com/actions/setup-python) from 4 to 5.
  - [Release notes](https://github.com/actions/setup-python/releases)
  - [Commits](https://github.com/actions/setup-python/compare/v4...v5)

  ---
  updated-dependencies:
  - dependency-name: actions/setup-python
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Bump softprops/action-gh-release from 1 to 2. [dependabot[bot]]

  Bumps [softprops/action-gh-release](https://github.com/softprops/action-gh-release) from 1 to 2.
  - [Release notes](https://github.com/softprops/action-gh-release/releases)
  - [Changelog](https://github.com/softprops/action-gh-release/blob/master/CHANGELOG.md)
  - [Commits](https://github.com/softprops/action-gh-release/compare/v1...v2)

  ---
  updated-dependencies:
  - dependency-name: softprops/action-gh-release
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Bump stefanzweifel/git-auto-commit-action from 4 to 5.
  [dependabot[bot]]

  Bumps [stefanzweifel/git-auto-commit-action](https://github.com/stefanzweifel/git-auto-commit-action) from 4 to 5.
  - [Release notes](https://github.com/stefanzweifel/git-auto-commit-action/releases)
  - [Changelog](https://github.com/stefanzweifel/git-auto-commit-action/blob/master/CHANGELOG.md)
  - [Commits](https://github.com/stefanzweifel/git-auto-commit-action/compare/v4...v5)

  ---
  updated-dependencies:
  - dependency-name: stefanzweifel/git-auto-commit-action
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Bump codecov/codecov-action from 3 to 4. [dependabot[bot]]

  Bumps [codecov/codecov-action](https://github.com/codecov/codecov-action) from 3 to 4.
  - [Release notes](https://github.com/codecov/codecov-action/releases)
  - [Changelog](https://github.com/codecov/codecov-action/blob/main/CHANGELOG.md)
  - [Commits](https://github.com/codecov/codecov-action/compare/v3...v4)

  ---
  updated-dependencies:
  - dependency-name: codecov/codecov-action
    dependency-type: direct:production
    update-type: version-update:semver-major
  ...
- Python 3.9 -> 3.10. [Kaarel Moppel]

  No win / mac builds
- README update. [Kaarel Moppel]
- Change licence to Functional Source License, Version 1.1, Apache 2.0
  Future License. [Kaarel Moppel]
- ✅ Ready to clone and code. [kmoppel]
- Initial commit. [Kaarel Moppel]


