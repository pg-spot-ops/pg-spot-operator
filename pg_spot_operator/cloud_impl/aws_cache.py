import glob
import json
import logging
import os
import time
import urllib
from datetime import date, datetime

import requests
from unidecode import unidecode

from pg_spot_operator.constants import DEFAULT_CONFIG_DIR
from pg_spot_operator.util import get_aws_region_code_to_name_mapping

CONFIG_DIR_PRICE_CACHE_SUBDIR = "price_cache"

logger = logging.getLogger(__name__)


def get_cached_pricing_dict(cache_file: str) -> dict:
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, CONFIG_DIR_PRICE_CACHE_SUBDIR)
    )
    cache_path = os.path.join(cache_dir, cache_file)
    if os.path.exists(cache_path):
        logger.debug("Reading cached AWS pricing file: %s", cache_path)
        try:
            with open(cache_path, "r") as f:
                return json.loads(f.read())
        except Exception:
            logger.error(
                "Failed to read cached AWS pricing file from: %s", cache_path
            )
    return {}


def write_pricing_cache_file_as_json(
    cache_file: str, pricing_info: dict
) -> None:
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, CONFIG_DIR_PRICE_CACHE_SUBDIR)
    )
    cache_path = os.path.join(cache_dir, cache_file)
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(pricing_info, f)


def get_ondemand_pricing_info_via_http(region: str) -> dict:
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

    sanitized_url = urllib.parse.quote(unidecode(url), safe=":/")
    logger.debug("requests.get: %s", sanitized_url)
    f = requests.get(
        sanitized_url, headers={"Content-Type": "application/json"}, timeout=5
    )
    if f.status_code != 200:
        logger.error(
            "Failed to retrieve AWS pricing info - retcode: %s, URL: %s",
            f.status_code,
            sanitized_url,
        )
        return {}
    return f.json()


def try_clean_up_old_pricing_cache_files(older_than_days: int) -> None:
    """Delete old per region JSON files
    ~/.pg-spot-operator/price_cache/aws_ondemand_us-east-1_20241115.json
    """
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, CONFIG_DIR_PRICE_CACHE_SUBDIR)
    )
    epoch = time.time()
    for pd in sorted(glob.glob(os.path.join(cache_dir, "aws_*"))):
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
    cached_pricing_info = get_cached_pricing_dict(cache_file)
    if cached_pricing_info:
        return cached_pricing_info

    pricing_info = get_ondemand_pricing_info_via_http(region)
    if not pricing_info:
        logger.error(
            "Failed to retrieve AWS ondemand pricing info for region %s",
            region,
        )
        return {}

    write_pricing_cache_file_as_json(cache_file, pricing_info)
    try_clean_up_old_pricing_cache_files(older_than_days=7)
    return pricing_info


def get_latest_spot_pricing_json() -> dict:
    """Return latest Spot JSON if any found.
    Location: $config-dir/$price-cache/aws_spot_{now.year}{now.month}{now.day}_{now.hour}00.json
    """
    cache_dir = os.path.expanduser(
        os.path.join(DEFAULT_CONFIG_DIR, CONFIG_DIR_PRICE_CACHE_SUBDIR)
    )
    g = glob.glob(os.path.join(cache_dir, "aws_spot_*"))
    if g:
        return json.load(open(sorted(g, reverse=True)[0]))
    return {}


def get_spot_pricing_from_public_json() -> dict:
    """Via an AWS managed 2MB S3 JSON: https://website.spot.ec2.aws.a2z.com/spot.json
    Caches locally into hourly aws_spot_* files
    Response contains all regions and looks like:
    {
      "vers": 0.01,
      "config": {
        "rate": "perhr",
        "valueColumns": [
          "linux",
          "mswin"
        ],
        "currencies": [
          "USD"
        ],
        "regions": [
          {
            "region": "us-east-1",
            "footnotes": {
              "*": "notAvailableForCCorCGPU"
            },
            "instanceTypes": [
              {
                "type": "generalCurrentGen",
                "sizes": [
                  {
                    "size": "m6i.xlarge",
                    "valueColumns": [
                      {
                        "name": "linux",
                        "prices": {
                          "USD": "0.0615"
                        }
                      },
                      {
                        "name": "mswin",
                        "prices": {
                          "USD": "0.2032"
                        }
                      }
                    ]
                  },
                  {
                    "size": "m6g.xlarge",
                    "valueColumns": [
                      {
                        "name": "linux",
                        "prices": {
                          "USD": "0.0378"
                        }
                      },
                      {
                        "name": "mswin",
                        "prices": {
                          "USD": "N/A*"
                        }
                      }
                    ]
                  },
    """
    now = datetime.now()
    cache_file = f"aws_spot_{now.year}{now.month}{now.day}_{now.hour}00.json"
    spot_pricing_info = get_cached_pricing_dict(cache_file)
    if spot_pricing_info:
        return spot_pricing_info

    url = "https://website.spot.ec2.aws.a2z.com/spot.json"
    logger.debug(
        "Fetching AWS spot pricing info from %s to %s ...", url, cache_file
    )
    r = requests.get(
        url, headers={"Content-Type": "application/json"}, timeout=5
    )
    if r.status_code != 200:
        logger.error(
            "Failed to retrieve AWS pricing info - retcode: %s, URL: %s",
            r.status_code,
            url,
        )
        latest_stored_spot_pricing_info = get_latest_spot_pricing_json()
        if latest_stored_spot_pricing_info:
            logger.warning(
                "Using possibly outdated spot pricing from: %s",
                latest_stored_spot_pricing_info,
            )
        return {}
    spot_pricing_info = r.json()

    write_pricing_cache_file_as_json(cache_file, spot_pricing_info)

    return spot_pricing_info


def get_spot_eviction_rates_from_public_json() -> dict:
    """Via an AWS managed ~1MB JSON: https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json
    Caches locally into hourly aws_eviction_rate_* files
    """
    now = datetime.now()
    cache_file = (
        f"aws_eviction_rate_{now.year}{now.month}{now.day}_{now.hour}00.json"
    )
    eviction_rate_info = get_cached_pricing_dict(cache_file)
    if eviction_rate_info:
        return eviction_rate_info

    url = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"
    logger.debug(
        "Fetching AWS spot eviction rate info from %s to %s ...",
        url,
        cache_file,
    )
    r = requests.get(
        url, headers={"Content-Type": "application/json"}, timeout=5
    )
    if r.status_code != 200:
        logger.error(
            "Failed to retrieve AWS pricing info - retcode: %s, URL: %s",
            r.status_code,
            url,
        )
        latest_stored_spot_pricing_info = get_latest_spot_pricing_json()
        if latest_stored_spot_pricing_info:
            logger.warning(
                "Using possibly outdated spot pricing from: %s",
                latest_stored_spot_pricing_info,
            )
        return {}
    eviction_rate_info = r.json()

    write_pricing_cache_file_as_json(cache_file, eviction_rate_info)

    return eviction_rate_info
