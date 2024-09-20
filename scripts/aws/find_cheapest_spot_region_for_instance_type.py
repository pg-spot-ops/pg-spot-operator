#!/usr/bin/env python3
import argparse
from collections import defaultdict
from datetime import timedelta, datetime
from statistics import mean

import boto3
import requests

PRICE_LOOKBACK_DAYS = 2


def get_all_active_regions() -> list[str]:
    client = boto3.client('account')
    paginator = client.get_paginator("list_regions")
    page_iterator = paginator.paginate()

    regs = []
    for page in page_iterator:
        regs.extend(page.get("Regions"))
    return [r["RegionName"] for r in regs if r["RegionOptStatus"].upper().startswith("ENABLED")]


def get_spot_pricing_data_for_skus_over_period(
    instance_types: list[str],
    region: str,
    lookback_period: timedelta,
    az: str | None = None,
) -> list[dict]:
    """
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_spot_price_history.html
    Response: [
    {'AvailabilityZone': 'eu-north-1b', 'InstanceType': 'g5.2xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.576800', 'Timestamp': datetime.datetime(2024, 5, 8, 8, 16, 35, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1b', 'InstanceType': 'm7gd.xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.041700', 'Timestamp': datetime.datetime(2024, 5, 8, 7, 1, 35, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1c', 'InstanceType': 'g5.2xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.562100', 'Timestamp': datetime.datetime(2024, 5, 8, 6, 32, 22, tzinfo=tzutc())},
    {'AvailabilityZone': 'eu-north-1c', 'InstanceType': 'm7gd.xlarge', 'ProductDescription': 'Linux/UNIX', 'SpotPrice': '0.048800', 'Timestamp': datetime.datetime(2024, 5, 8, 6, 1, 45, tzinfo=tzutc())}
    ]
    """
    client = boto3.client("ec2", region)
    filters = [
        {"Name": "instance-type", "Values": instance_types},
        {"Name": "product-description", "Values": ["Linux/UNIX"]},
    ]
    kwargs = {}
    if az:
        kwargs["AvailabilityZone"] = az

    paginator = client.get_paginator("describe_spot_price_history")
    page_iterator = paginator.paginate(
        Filters=filters,
        StartTime=(datetime.utcnow() - lookback_period),
        **kwargs,
    )
    pricing_data = []
    for page in page_iterator:
        pricing_data.extend(page["SpotPriceHistory"])
    return pricing_data


def get_avg_spot_price_from_pricing_history_data_by_sku_and_az(
    pricing_data: list[dict],
) -> list[tuple[str, str, float]]:
    """Returns [('t4g.small', 'eu-north-1c', 0.005700), ...], cheapest first
    Expects describe_spot_price_history input data
    """

    per_sku_az_hist: dict[str, dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    ret: list[tuple[str, str, float]] = []

    for pd in pricing_data:
        per_sku_az_hist[pd["InstanceType"]][pd["AvailabilityZone"]].append(
            float(pd["SpotPrice"])
        )
    for sku, az_dict in per_sku_az_hist.items():
        for az, price_data in az_dict.items():
            avg_price = mean(price_data)
            ret.append((sku, az, round(avg_price, 6)))

    return sorted(ret, key=lambda x: x[2])



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Checks Spot price for given Instance Types in all active regions', add_help=True)

    parser.add_argument('region_prefix', metavar='REGION_PREFIX', help='* for no filtering')
    parser.add_argument('instance_types', nargs='+', type=str, metavar='INSTANCE_TYPE')

    args = parser.parse_args()

    region_prefix: str = args.region_prefix.lower()
    instance_types: list[str] = args.instance_types

    print("Fetching all enabled regions ...")
    active_regions = get_all_active_regions()
    # print("Got:", active_regions)

    filtered_regions = active_regions
    if region_prefix != "*":
        filtered_regions = [r for r in active_regions if r.startswith(region_prefix)]
    filtered_regions.sort()
    print("Regions in selection after filtering:", filtered_regions)
    print(f"Instance types input: {instance_types}")
    print("Price history lookback days:", PRICE_LOOKBACK_DAYS)

    region_best = []
    region_worst = []

    for reg in filtered_regions:
        print(f"\nLooking for best price in REGION {reg} ...")
        try:
            pd_raw = get_spot_pricing_data_for_skus_over_period(instance_types, reg, timedelta(days=PRICE_LOOKBACK_DAYS))
            # print("Got:", pd_raw)
            if not pd_raw:
                print('No pricing data, skipping region ...')
                continue

            by_price = get_avg_spot_price_from_pricing_history_data_by_sku_and_az(pd_raw)
            # print(by_price)

            sku = by_price[0][0]
            az = by_price[0][1]
            price = round(by_price[0][2] * 24 * 30, 1)

            print('Cheapest instance, az, monthly price:', sku, az, price)
            region_best.append((reg, sku, az, price))
            region_worst.append((reg, by_price[-1][0], by_price[-1][1], round(by_price[-1][2] * 24 * 30, 1)))
        except Exception as e:
            print('Failed to fetch price:', str(e))

    if not region_best:
        print("No results")
        exit(1)

    region_best.sort(key=lambda x: x[3])  # (reg, sku, az, price)
    region_worst.sort(key=lambda x: x[3], reverse=True)  # (reg, sku, az, price)

    print("\n*** TOP 3 WORST PRICES ***\n")
    for rb in region_worst[:3]:
        reg = rb[0]
        sku = rb[1]
        az = rb[2]
        price = rb[3]
        print(f"REGION: {reg} INSTANCE_TYPE: {sku} ZONE: {az} PRICE: {price}")

    print("\n*** TOP 3 BEST PRICES ***\n")
    for rb in region_best[:3]:
        reg = rb[0]
        sku = rb[1]
        az = rb[2]
        price = rb[3]
        price_od = 0
        try:
            r = requests.get(f'https://ec2.shop?filter={sku}&region={reg}', headers={'Accept': 'application/json'})
            if r and r.status_code == 200:
                price_od = r.json()["Prices"][0]["MonthlyPrice"]
        except:
            pass
        print(f"REGION: {reg} INSTANCE_TYPE: {sku} ZONE: {az} SPOT PRICE: {price} ONDEMAND PRICE: {price_od} DIFFERENCE {round(price_od / price, 1)}x")
