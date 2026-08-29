"""Race events (project rule 35).

Everything that can happen to a race without being part of how a car moves:
mechanical failures, contact, spins, and the flags race control shows because
of them.  The physics core knows about none of it; the race core reacts to it.
"""

from .collision import ContactRisk, contact_probability, sample_contact, sample_spin
from .incident import (
    Incident,
    IncidentKind,
    IncidentRaised,
    IncidentSeverity,
    severity_rank,
)
from .race_control import (
    FlagChanged,
    FlagState,
    Neutralisation,
    RaceControl,
    RaceControlDecision,
)
from .reliability import SystemStress, cooling_stress, failure_probability, sample_failure

__all__ = [
    "ContactRisk",
    "FlagChanged",
    "FlagState",
    "Incident",
    "IncidentKind",
    "IncidentRaised",
    "IncidentSeverity",
    "Neutralisation",
    "RaceControl",
    "RaceControlDecision",
    "SystemStress",
    "contact_probability",
    "cooling_stress",
    "failure_probability",
    "sample_failure",
    "sample_spin",
    "severity_rank",
]
