# Security

The defaults are geared towards user experience i.e. public access, but everything is tunable.

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
