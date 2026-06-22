from packages.common.capability import CapabilityMeta

META = CapabilityMeta(
    service="leads",
    name="AI小高线索",
    description="AI小高线索能力服务边界。",
)

from apps.leads.services import get_lead, get_summary, list_leads  # noqa: E402,F401
