import random
from typing import Type

from pg_spot_operator.cloud_impl.cloud_structs import InstanceTypeInfo


class InstanceTypeSelectionStrategy:

    @classmethod
    def execute(
        cls, qualified_instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        raise NotImplementedError(
            f"{cls.__name__} has not implemented the execute method"
        )


class InstanceTypeSelectionCheapest(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls, instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        non_zero_price = [x for x in instance_types if x.hourly_spot_price]
        if not non_zero_price:
            raise Exception(
                "No qualified instances with hourly_spot_price set"
            )
        return sorted(non_zero_price, key=lambda x: x.hourly_spot_price)[0]


class InstanceTypeSelectionRandom(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls, qualified_instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        return random.choice(qualified_instance_types)


class InstanceTypeSelectionEvictionRate(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls, instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        valid_instances = [
            x
            for x in instance_types
            if x.hourly_spot_price and x.max_eviction_rate
        ]
        if not valid_instances:
            raise Exception(
                "No qualified instances with max_eviction_rate and hourly_spot_price set"
            )
        valid_instances.sort(
            key=lambda x: (x.max_eviction_rate, x.hourly_spot_price)
        )
        return valid_instances[0]


class InstanceTypeSelectionBalanced(InstanceTypeSelectionStrategy):
    """A mix of price + eviction rate"""

    @classmethod
    def execute(
        cls, instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        valid_instances = [
            x
            for x in instance_types
            if x.hourly_spot_price and x.max_eviction_rate
        ]
        if not valid_instances:
            raise Exception(
                "No qualified instances with max_eviction_rate and hourly_spot_price set"
            )
        max_price = max([x.hourly_spot_price for x in valid_instances])
        max_eviction_rate = max([x.max_eviction_rate for x in valid_instances])
        return sorted(
            valid_instances,
            key=lambda x: x.hourly_spot_price / max_price
            + x.max_eviction_rate / max_eviction_rate,
        )[0]


class InstanceTypeSelection:

    @classmethod
    def get_selection_strategy(
        cls, instance_selection_strategy: str
    ) -> Type[InstanceTypeSelectionStrategy]:
        strategy = {
            "cheapest": InstanceTypeSelectionCheapest,
            "random": InstanceTypeSelectionRandom,
            "eviction-rate": InstanceTypeSelectionEvictionRate,
            "balanced": InstanceTypeSelectionBalanced,
        }
        return strategy.get(
            instance_selection_strategy.lower().strip(),
            InstanceTypeSelectionBalanced,
        )
