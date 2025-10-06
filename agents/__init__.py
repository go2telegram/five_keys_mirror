"""Agent collaboration package."""

from .protocol import AgentMessage, MessageKind, ConsensusOutcome, ConsensusState, AgentPeer
from .network import AgentNetwork, create_default_executor

__all__ = [
    "AgentMessage",
    "MessageKind",
    "ConsensusOutcome",
    "ConsensusState",
    "AgentPeer",
    "AgentNetwork",
    "create_default_executor",
]
