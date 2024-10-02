import logging

from pg_spot_operator.cloud_impl.aws_client import get_client, get_session

logger = logging.getLogger(__name__)


def s3_try_create_bucket_if_not_exists(region: str, bucket_name: str) -> None:
    client = get_client("s3", region)

    buckets = client.list_buckets()
    if buckets and buckets.get("Buckets"):
        if bucket_name in [b["Name"] for b in buckets.get("Buckets")]:
            logger.debug(
                "OK - bucket %s already exists in region %s",
                bucket_name,
                region,
            )
            return
    logger.info(
        "Trying to create bucket %s in region %s ...", bucket_name, region
    )
    client.create_bucket(
        Bucket=bucket_name,
        CreateBucketConfiguration={"LocationConstraint": region},
    )
    logger.info("OK - bucket created")


def s3_clean_bucket_path_if_exists(
    region: str, bucket_name: str, bucket_path_to_rm: str
) -> None:
    session = get_session(region)

    s3 = session.resource("s3")
    bucket = s3.Bucket(bucket_name)
    if bucket and bucket.creation_date:
        logger.info(
            "Starting clean-up of bucket %s path %s ...",
            bucket_name,
            bucket_path_to_rm,
        )
        bucket.objects.filter(
            Prefix=bucket_path_to_rm.rstrip("/") + "/"
        ).delete()
        logger.info("Delete OK")
    else:
        logger.info(
            "Backup bucket %s not found, nothing to clean up", bucket_name
        )
