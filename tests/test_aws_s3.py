import os
import unittest
from random import random

from pg_spot_operator.cloud_impl.aws_s3 import (
    write_to_s3_bucket,
    read_s3_bucket,
)


@unittest.SkipTest
def test_write_to_s3_bucket():
    """Assumes local AWS CLI setup"""
    if not os.path.exists(os.path.expanduser("~/.aws/config")):
        return

    BUCKET = "somebucket"
    random_as_str = str(random())
    write_to_s3_bucket(
        data=random_as_str,
        region="",
        bucket_name=BUCKET,
        bucket_key="dummy.txt",
        endpoint="",
        access_key="",
        access_secret="",
    )

    data_out = read_s3_bucket(
        region="",
        bucket_name=BUCKET,
        bucket_filename="dummy.txt",
        endpoint="",
        key="",
        secret="",
    )

    assert random_as_str == data_out
