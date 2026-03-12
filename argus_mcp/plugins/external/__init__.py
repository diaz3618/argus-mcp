"""External safety plugins for Argus MCP.

These plugins integrate with external security services (LLMGuard, VirusTotal,
ClamAV, content moderation providers, OPA, Cedar) and are disabled by default.
Enable them in ``config.yaml`` under ``plugins.entries`` with appropriate settings.
"""

from __future__ import annotations

from argus_mcp.plugins.registry import register_plugin

from .cedar_policy import CedarPolicyPlugin
from .clamav import ClamAVPlugin
from .content_moderation import ContentModerationPlugin
from .llmguard import LLMGuardPlugin
from .opa_policy import OPAPolicyPlugin
from .unified_pdp import UnifiedPDPPlugin
from .virustotal import VirusTotalPlugin

register_plugin("llmguard", LLMGuardPlugin)
register_plugin("virustotal", VirusTotalPlugin)
register_plugin("clamav", ClamAVPlugin)
register_plugin("content_moderation", ContentModerationPlugin)
register_plugin("opa_policy", OPAPolicyPlugin)
register_plugin("cedar_policy", CedarPolicyPlugin)
register_plugin("unified_pdp", UnifiedPDPPlugin)

__all__ = [
    "CedarPolicyPlugin",
    "ClamAVPlugin",
    "ContentModerationPlugin",
    "LLMGuardPlugin",
    "OPAPolicyPlugin",
    "UnifiedPDPPlugin",
    "VirusTotalPlugin",
]
