import logging
import os
import boto3.session

from pg_spot_operator.cloud_impl.aws_client import get_session

logger = logging.getLogger(__name__)


def s3_clean_bucket_path_if_exists(region: str, bucket_name: str, bucket_path_to_rm: str) -> None:
    session = get_session(region)

    s3 = session.resource('s3')
    bucket = s3.Bucket(bucket_name)
    if bucket and bucket.creation_date:
        logger.info('Starting clean-up of bucket %s path %s ...', bucket_name, bucket_path_to_rm)
        bucket.objects.filter(Prefix=bucket_path_to_rm.rstrip("/") + "/").delete()
        logger.info('Delete OK')
    else:
        logger.info('Backup bucket %s not found, nothing to clean up', bucket_name)
