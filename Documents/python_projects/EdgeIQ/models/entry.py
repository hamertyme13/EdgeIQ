from dataclasses import dataclass, field

from models.prop import Prop


@dataclass
class Entry:

    platform: str

    props: list[Prop] = field(default_factory=list)

    wager: float = 0

    payout: float = 0

    result: str = "Pending"