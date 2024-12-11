import logging

import boto3

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


def write_to_s3_bucket(
    data: str,
    region: str,
    bucket_name: str,
    bucket_key: str,
    endpoint: str = "",
    access_key: str = "",
    access_secret: str = "",
):
    s3_params = {
        "service_name": "s3",
        "endpoint_url": endpoint,
        "aws_access_key_id": access_key,
        "aws_secret_access_key": access_secret,
        "region_name": region,
    }
    logger.debug(
        "Updating connstr info in S3. S3 details: %s",
        {
            k: v
            for k, v in s3_params.items()
            if v and k not in ("aws_access_key_id", "aws_secret_access_key")
        },
    )
    client = boto3.client(**{k: v for k, v in s3_params.items() if v})  # type: ignore
    # https://boto3.amazonaws.com/v1/documentation/api/1.35.9/reference/services/s3.html
    client.put_object(Bucket=bucket_name, Key=bucket_key, Body=data)


def read_s3_bucket(
    region: str,
    bucket_name: str,
    bucket_filename: str,
    endpoint: str = "",
    key: str = "",
    secret: str = "",
):
    s3_params = {
        "service_name": "s3",
        "endpoint_url": endpoint,
        "aws_access_key_id": key,
        "aws_secret_access_key": secret,
        "region_name": region,
    }

    client = boto3.client(**{k: v for k, v in s3_params.items() if v})  # type: ignore
    # https://youtype.github.io/boto3_stubs_docs/mypy_boto3_s3/client/#get_object
    resp = client.get_object(
        Bucket=bucket_name,
        Key=bucket_filename,
    )
    body = resp["Body"].read()
    return body.decode("utf8")
