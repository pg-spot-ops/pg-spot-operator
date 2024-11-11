# AWS CLI quick-start

Generally if planning to do a bit of real work with the PG Spot Operator, some command line visibility into the cloud becomes
really handy - so here some basics to get you started.

## Prerequisites

* Creating an AWS account - https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-creating.html
* Installing the CLI - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
* User / credentials setup - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html

As IAM / authentication is a fairly complex topic with many options for various levels of security, we won't re-write the
docs here - we just assume that the CLI just works transparently.

For an example VPC + IAM user + credentials Terraform setup one could look [here](https://github.com/pg-spot-ops/pg-spot-operator/tree/main/scripts/terraform) though.

## Listing all operator VMs

PS If working with a non-default region add `--region=X` to all commands.

```commandline
aws ec2 describe-instances --filters Name=tag-key,Values=pg-spot-operator-instance
```
or more shortly
```commandline
PAGER= aws ec2 describe-instances \
  --filters Name=instance-state-name,Values=running,pending Name=tag-key,Values=pg-spot-operator-instance \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,LaunchTime,State.Name,InstanceLifecycle,Placement.AvailabilityZone,PrivateIpAddress,PublicIpAddress,Tags]' \
  --output text
i-0b48a8383cae957f1	c6gd.medium	2024-10-21T08:41:29+00:00	running	spot	eu-north-1c	172.31.13.5	13.49.134.204
pg-spot-operator-instance	pg1
```

## Listing all operator EBS Volumes

```commandline
aws ec2 describe-volumes   --filters Name=tag-key,Values=pg-spot-operator-instance
```
or more shortly
```commandline
PAGER= aws ec2 describe-volumes   --filters Name=tag-key,Values=pg-spot-operator-instance \
  --query "Volumes[*].[VolumeId,AvailabilityZone,State,Size,VolumeType,Iops,Throughput,Tags]" --output text
vol-0776fbc66e4e6a901	eu-north-1b	in-use	10	gp3	3000	125
pg-spot-operator-instance	pg1
```

## Terminating an instance manually

For example to simulate an eviction:

```commandline
PAGER= aws ec2 terminate-instances --instance-ids i-0b3922618ebe2528b
```

PS For the actual Spot Operator managed instances teardown / cleanup it's recommended to still run in the special
`--teardown` or `--teardown-region` modes, or the Bash script from the "scripts" folder.

PS2 The `--teardown-region` mode is only safe to use when the account is not a shared / organization one!
