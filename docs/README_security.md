# Security

The defaults are geared towards user experience i.e. public access if admin user / password set, but with precautions like
brute-force protection (`auth_delay`, `fail2ban`) taken, and everything being configurable as well.

WARNING - it is very much recommended to use a new, isolated VPC for running the Spot Operator! Official AWS documentation
on creating one: https://docs.aws.amazon.com/vpc/latest/userguide/create-vpc.html#create-vpc-cli

## Security-relevant manifest attributes with defaults

```commandline
public_ip_address: true
postgres:
  admin_is_superuser: true
  admin_user: ''  # If not set only local on-the-vm access possible
  admin_password: ''
  pg_hba_lines:  # Defaults allow non-postgres world access
    - "host all postgres 0.0.0.0/0 reject"
    - "hostssl all all 0.0.0.0/0 scram-sha-256"
aws:
  security_group_ids: []  # By default VPC "default" SG is used
vault_password_file:  # Ansible Vault key file accessible on the engine, to handle encrypted secrets (if any used) 
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
MYPUBIP=$(curl -sL whatismyip.akamai.com)

aws ec2 authorize-security-group-ingress \
  --group-name default \
  --protocol tcp \
  --port 22 \
  --cidr "${MYPUBIP}/32" \
  --region eu-north-1
```

Some AWS documentation on the topic:

* https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html
* https://docs.aws.amazon.com/cli/latest/reference/ec2/authorize-security-group-ingress.html

# Secrets handling

FYI Although some precaucions are taken, currently a trusted execution environment is assumed. Meaning:

* In `--verbose` and `--debug` mode it's not guaranteed that no secrets will leak to stout / Ansible logs, like admin
  user password or AWS credentials (if explicitly fed in). Ansible logs though are deleted after successful completion
  if `--debug` not set.
* If plain text password are provided they will also land in the local SQLite config DB (`~/.pg-spot-operator/pgso.db`)
  for change detection purposes. Thus **for untrusted execution environments manifest usage + encrypting all secrets
  with Ansible Vault is recommended.**
