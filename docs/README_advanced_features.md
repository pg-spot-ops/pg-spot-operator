# Fire-and-forget mode

In the self-terminating mode the VM will expire itself automatically after the `--expiration-date`, meaning the engine
daemon doesn't have to be kept running in the background, which is great for automation/integration. 

It works by installing a Cronjob at the end of the Ansible setup (under "root"), which runs the `instance_teardown.py`
script that checks if we've passed the `expiration_date`, and if so - cleans up any volumes, elastic IPs and finally
terminates itself.

Relevant CLI/Env flags:

  * --self-termination / PGSO_SELF_TERMINATION
  * --self-termination-access-key-id / PGSO_SELF_TERMINATION_ACCESS_KEY_ID
  * --self-termination-secret-access-key / PGSO_SELF_TERMINATION_SECRET_ACCESS_KEY

**PS** It is strongly recommended to generate separate AWS credentials for self-termination, only with limited EC2 privileges
as the keys will be actually placed on the VMs to be able to work self-sufficiently. Also for public IP instances one should
take care to configure Security Groups and `pg_hba.conf` rules accordingly.

Also note that not all resources are guaranteed to be auto-expired:
  * Backups (if enabled) - as a security measure
  * In case of non-floating IPs (by default IPs are floating) custom NICs also cannot be cleaned up as still attached to the VM
    at time of calling terminate on itself. Thus if using this feature with public IPs, to get rid of any left-over resources
    it's recommend to run the `delete_all_operator_tagged_objects.sh` script occasionally. Hanging NICs don't cost extra though.


## Minimum AWS EC2 privileges for feature to work

```
"ec2:TerminateInstances",
"ec2:DisassociateAddress",
"ec2:ReleaseAddress",
"ec2:DescribeVolume*",
"ec2:DetachVolume",
"ec2:DeleteVolume",
```
