from dataclasses import dataclass, field


@dataclass
class ResolvedSkuInfo:
    sku: str
    arch: str
    cloud: str
    region: str
    availability_zone: str = ""
    monthly_spot_price: float = 0
    monthly_ondemand_price: float = 0
    cpu: int = 0
    ram: int = 0
    instance_storage: int = 0
    provider_description: dict = field(default_factory=dict)
