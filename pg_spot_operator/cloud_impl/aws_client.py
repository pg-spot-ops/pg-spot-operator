import boto3

AWS_PROFILE: str = ""
AWS_ACCESS_KEY_ID: str = ""
AWS_SECRET_ACCESS_KEY: str = ""


def get_client(
    service: str, region: str
):  # TODO reuse / cache sessions for a while
    if AWS_PROFILE:
        session = boto3.session.Session(
            profile_name=AWS_PROFILE,
            region_name=region,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    else:
        session = boto3.session.Session(
            region_name=region,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    return session.client(service)


def get_session(region: str) -> boto3.session.Session:
    return boto3.session.Session(
        region_name=region,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
