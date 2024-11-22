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
        cls, qualified_instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        non_zero_price = [
            x for x in qualified_instance_types if x.hourly_spot_price
        ]
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
        cls, qualified_instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        non_zero_price = [
            x for x in qualified_instance_types if x.hourly_spot_price
        ]
        if not non_zero_price:
            raise Exception(
                "No qualified instances with max_eviction_rate and hourly_spot_price set"
            )
        non_zero_price.sort(
            key=lambda x: (x.max_eviction_rate, x.hourly_spot_price)
        )
        return non_zero_price[0]


class InstanceTypeSelection:

    @classmethod
    def get_selection_strategy(
        cls, instance_selection_strategy: str
    ) -> Type[InstanceTypeSelectionStrategy]:
        strategy = {
            "cheapest": InstanceTypeSelectionCheapest,
            "random": InstanceTypeSelectionRandom,
            "eviction-rate": InstanceTypeSelectionEvictionRate,
        }
        return strategy.get(
            instance_selection_strategy.lower().strip(),
            InstanceTypeSelectionCheapest,
        )
