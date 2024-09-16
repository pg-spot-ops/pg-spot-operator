Role Name
=========

Add pgBackRest S3 to an otherwise configured Postgres instance

Requirements
------------



Role Variables
--------------

Defaults are in `defaults/main.yml`. Minimally PG cluster info + S3 access vars must be overridden in calling playbooks:

- stanza_name
- backup_encryption
- backup_s3_bucket
- backup_s3_endpoint
- backup_s3_region
- backup.s3_key
- backup.s3_key_secret

Dependencies
------------

None
