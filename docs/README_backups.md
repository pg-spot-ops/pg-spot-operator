# Backups

If using local storage instances (`--storage-type=local`, default storage type is `network`), you don't get data persistence
by default - which is good only of course for throwaway testing/analytics etc. To support persistence there is built-in
support for `pgBackRest` with S3 storage. Backups could of course configured for network storage also, for the usual extra
safety and (manual) PITR reasons.

A typical restore takes a few minutes on network storage, and is proportional to the DB size when using
volatile instance storage + restore from S3 (via pgBackRest). A 100GB DB size S3 restore takes about 10min on lower-end
hardware.

Note though that enabling backup still means a small data loss in case of VM eviction, assuming data is constantly written.
The default average data loss window is around 1min (`backup.wal_archiving_max_interval=2min`) and for larger databases
(100GB+), restoring in case of an eviction will take 10min+ and the operational side will suffer, so network storage
with some provisioned IOPS to compensate disk latencies might be a better idea.

Relevant CLI / Env flags:
  * --backup-s3-bucket / BACKUP_S3_BUCKET (signals we want backups)
  * --backup-cipher / BACKUP_CIPHER (no encryption by default)
  * --backup-retention-days / BACKUP_RETENTION_DAYS (1d by default)
  * --backup-s3-key / BACKUP_S3_KEY
  * --backup-s3-key-secret / BACKUP_S3_KEY_SECRET

**PS** It is strongly recommended to generate a distinct key/secret for backups, with only limited S3 privileges, and not
to re-use the engine credentials, as the keys will be actually placed on the Postgres VMs for pgBackRest to work.

Also, technically non-S3 storage, or S3 outside of AWS, can be used - but in that case the user must provide full
pgBackRest configuration lines (`backup.pgbackrest.global_settings` etc) as part of the manifest.
