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


class InstanceTypeSelectionDefault(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls, qualified_instance_types: list[InstanceTypeInfo]
    ) -> InstanceTypeInfo:
        return sorted(
            qualified_instance_types, key=lambda x: x.hourly_spot_price
        )[0]


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

        qualified_instance_types.sort(
            key=lambda x: (x.max_eviction_rate, x.hourly_spot_price)
        )
        return qualified_instance_types[0]


class InstanceTypeSelection:

    @classmethod
    def get_selection_strategy(
        cls, instance_selection_strategy: str
    ) -> Type[InstanceTypeSelectionStrategy]:
        strategy = {
            "cheapest": InstanceTypeSelectionDefault,
            "random": InstanceTypeSelectionRandom,
            "eviction-rate": InstanceTypeSelectionEvictionRate,
        }
        return (
            strategy.get(
                instance_selection_strategy.lower().strip() or "cheapest"
            )
            or InstanceTypeSelectionDefault
        )
