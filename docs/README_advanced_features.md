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
