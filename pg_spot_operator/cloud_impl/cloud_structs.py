from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class InstanceTypeInfo:
    instance_type: str
    arch: str
    cloud: str
    region: str
    availability_zone: str = ""
    hourly_spot_price: float = 0
    monthly_spot_price: float = 0
    hourly_ondemand_price: float = 0
    monthly_ondemand_price: float = 0
    cpu: int = 0
    ram_mb: int = 0
    instance_storage: int = 0
    storage_speed_class: str = "hdd"
    is_burstable: bool = False
    provider_description: dict = field(default_factory=dict)


@dataclass
class CloudVM:
    provider_id: str
    cloud: str
    region: str
    instance_type: str
    login_user: str
    ip_private: str
    ip_public: str = ""
    availability_zone: str = ""
    provider_name: str = ""
    volume_id: str = ""
    user_tags: dict = field(default_factory=dict)
    created_on: datetime | None = None
    provider_description: dict | None = None
    volume_description: dict | None = None
