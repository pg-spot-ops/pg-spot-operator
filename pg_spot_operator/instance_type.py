import random
from pg_spot_operator.manifests import InstanceManifest



class InstanceTypeSelectionStrategy:

    @classmethod
    def execute(cls, instance_types: list[tuple[str, str, float]]) -> tuple[str, str, float] | None:
        raise NotImplementedError(f"{cls.__name__} has not implemented the execute method")


class InstanceTypeSelectionDefault(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(cls, instance_types: list[tuple[str, str, float]]) -> tuple[str, str, float] | None:
        return instance_types[0] if len(instance_types) > 0 else None


class InstanceTypeSelectionRandom(InstanceTypeSelectionStrategy):

    @classmethod
    def execute(cls, instance_types: list[tuple[str, str, float]]) -> tuple[str, str, float]:
        return random.choice(instance_types)


class InstanceType:

    @classmethod
    def get_selection_strategy(cls, m: InstanceManifest) -> InstanceTypeSelectionStrategy:
        strategy = {
            'default': InstanceTypeSelectionDefault,
            'random': InstanceTypeSelectionRandom
        }
        return strategy.get(m.vm.instance_selection_strategy) or InstanceTypeSelectionDefault
