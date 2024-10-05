import random
from typing import Type


class InstanceTypeSelectionStrategy:

    @classmethod
    def execute(
        cls, instance_types: list[tuple[str, str, float]]
    ) -> tuple[str, str, float]:
        raise NotImplementedError(
            f"{cls.__name__} has not implemented the execute method"
        )


class InstanceTypeSelectionDefault(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls,
        instance_types: list[tuple[str, str, float]],
    ) -> tuple[str, str, float]:
        return instance_types[0]


class InstanceTypeSelectionRandom(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(
        cls, instance_types: list[tuple[str, str, float]]
    ) -> tuple[str, str, float]:
        return random.choice(instance_types)


class InstanceType:

    @classmethod
    def get_selection_strategy(
        cls, instance_selection_strategy: str | None
    ) -> Type[InstanceTypeSelectionStrategy]:
        strategy = {
            "cheapest": InstanceTypeSelectionDefault,
            "random": InstanceTypeSelectionRandom,
        }
        return (
            strategy.get(instance_selection_strategy or "cheapest")
            or InstanceTypeSelectionDefault
        )
