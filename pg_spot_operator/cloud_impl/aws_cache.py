import glob
import json
import logging
import os
import time
import urllib
from datetime import date

import requests

from pg_spot_operator.constants import DEFAULT_CONFIG_DIR
from pg_spot_operator.util import get_aws_region_code_to_name_mapping

logger = logging.getLogger(__name__)


def get_cached_pricing_dict(cache_file: str) -> dict:
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, "price_cache")
    )
    cache_path = os.path.join(cache_dir, cache_file)
    if os.path.exists(cache_path):
        logger.debug(
            "Reading AWS pricing info from daily cache: %s", cache_path
        )
        try:
            with open(cache_path, "r") as f:
                return json.loads(f.read())
        except Exception:
            logger.error("Failed to read %s from AWS daily cache", cache_file)
    return {}


def cache_pricing_dict(cache_file: str, pricing_info: dict) -> None:
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, "price_cache")
    )
    cache_path = os.path.join(cache_dir, cache_file)
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(pricing_info, f)


def get_pricing_info_via_http(region: str) -> dict:
    """AWS caches pricing info for public usage in static files like:
    https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/EU%20(Stockholm)/Linux/index.json
    """
    region_location = get_aws_region_code_to_name_mapping().get(region, "")
    if not region_location:
        raise Exception(f"Could not map region code {region} to location name")
    logger.debug(
        f"Fetching AWS on-demand pricing info for region {region} ({region_location}) ..."
    )

    url = f"https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/{region_location}/Linux/index.json"

    sanitized_url = urllib.parse.quote(url, safe=":/")
    logger.debug("requests.get: %s", sanitized_url)
    f = requests.get(
        sanitized_url, headers={"Content-Type": "application/json"}, timeout=5
    )
    if f.status_code != 200:
        logger.error(
            "Failed to retrieve AWS pricing info - retcode: %s, URL: %s",
            f.status_code,
            url,
        )
        return {}
    return f.json()


def clean_up_old_ondemad_pricing_cache_files(older_than_days: int) -> None:
    """Delete old per region JSON files
    ~/.pg-spot-operator/price_cache/aws_ondemand_us-east-1_20241115.json
    """
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, "price_cache")
    )
    epoch = time.time()
    for pd in sorted(glob.glob(os.path.join(cache_dir, "aws_ondemand_*"))):
        try:
            st = os.stat(pd)
            if epoch - st.st_mtime > 3600 * 24 * older_than_days:
                os.unlink(pd)
        except Exception:
            logger.info("Failed to clean up old on-demand pricing JSON %s", pd)


def get_aws_static_ondemand_pricing_info(region: str) -> dict:
    today = date.today()
    cache_file = (
        f"aws_ondemand_{region}_{today.year}{today.month}{today.day}.json"
    )
    pricing_info = get_cached_pricing_dict(cache_file)
    if not pricing_info:
        pricing_info = get_pricing_info_via_http(region)
        if pricing_info:
            cache_pricing_dict(cache_file, pricing_info)
            clean_up_old_ondemad_pricing_cache_files(older_than_days=7)
        else:
            logger.error(
                f"Failed to retrieve AWS ondemand pricing info for region %s",
                region,
            )
            return {}
    return {}
