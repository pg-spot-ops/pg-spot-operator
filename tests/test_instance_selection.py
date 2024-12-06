from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo
from pg_spot_operator.instance_type_selection import (
    InstanceTypeSelection,
    SELECTION_STRATEGY_EVICTION_RATE,
    SELECTION_STRATEGY_CHEAPEST,
    SELECTION_STRATEGY_BALANCED,
)

INSTANCE_TYPES: list[InstanceTypeInfo] = [
    InstanceTypeInfo(
        instance_type="i1",
        region="r1",
        arch="x86",
        hourly_spot_price=1.0,
        max_eviction_rate=20,
    ),
    InstanceTypeInfo(
        instance_type="i2",
        region="r1",
        arch="x86",
        hourly_spot_price=2.0,
        max_eviction_rate=5,
    ),
    InstanceTypeInfo(
        instance_type="i3",
        region="r1",
        arch="x86",
        hourly_spot_price=0,
        max_eviction_rate=5,
    ),
    InstanceTypeInfo(
        instance_type="i4",
        region="r1",
        arch="x86",
        hourly_spot_price=1.5,
        max_eviction_rate=6,
    ),
]


def test_strategy_cheapest():
    instance_selection_strategy_cls = (
        InstanceTypeSelection.get_selection_strategy(
            SELECTION_STRATEGY_CHEAPEST
        )
    )

    siti: InstanceTypeInfo = instance_selection_strategy_cls.execute(
        INSTANCE_TYPES
    )[0]
    assert siti.instance_type == "i1"


def test_strategy_eviction_rate():
    instance_selection_strategy_cls = (
        InstanceTypeSelection.get_selection_strategy(
            SELECTION_STRATEGY_EVICTION_RATE
        )
    )

    siti: InstanceTypeInfo = instance_selection_strategy_cls.execute(
        INSTANCE_TYPES
    )[0]
    assert siti.instance_type == "i2"


def test_strategy_balanced():
    instance_selection_strategy_cls = (
        InstanceTypeSelection.get_selection_strategy(
            SELECTION_STRATEGY_BALANCED
        )
    )

    siti: InstanceTypeInfo = instance_selection_strategy_cls.execute(
        INSTANCE_TYPES
    )[0]
    assert siti.instance_type == "i4"
