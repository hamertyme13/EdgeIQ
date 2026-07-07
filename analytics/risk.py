from enum import Enum

from dataclasses import dataclass

class EntryRisk(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"

@dataclass
class EntryRiskResult:
    risk: EntryRisk
    average_confidence: float
    average_edge: float
    prop_count: int


def calculate_entry_risk(props):
    """
    Determine the overall risk of an entry.

    Inputs:
        props -> list[Prop]

    Returns:
        EntryRisk
    """

    average_confidence = (
        sum(prop.confidence for prop in props)
        / len(props)
    )

    average_edge = (
        sum(prop.edge for prop in props)
        / len(props)
    )

    prop_count = len(props)

    if (
        average_confidence >= 75
        and average_edge >= 2
        and prop_count <= 2
    ):
        return EntryRiskResult(
            risk=EntryRisk.LOW,
            average_confidence=average_confidence,
            average_edge=average_edge,
            prop_count=prop_count
        )

    elif (
        average_confidence >= 60
        and average_edge >= 0
        and prop_count <= 4
    ):
        return EntryRiskResult(
            risk=EntryRisk.MEDIUM,
            average_confidence=average_confidence,
            average_edge=average_edge,
            prop_count=prop_count,
        )

    return EntryRiskResult(
        risk=EntryRisk.HIGH,
        average_confidence=average_confidence,
        average_edge=average_edge,
        prop_count=prop_count,
    )