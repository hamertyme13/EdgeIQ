from dataclasses import dataclass, field

from models.platform import Platform
from models.prop import Prop


@dataclass
class Entry:
    platform: Platform
    props: list[Prop] = field(default_factory=list)

    def add_prop(self, prop: Prop) -> None:
        self.props.append(prop)

    @property
    def prop_count(self) -> int:
        return len(self.props)

    @property
    def average_confidence(self) -> float:
        if not self.props:
            return 0.0

        return sum(
            prop.confidence
            for prop in self.props
        ) / len(self.props)

    @property
    def average_edge(self) -> float:
        if not self.props:
            return 0.0

        return sum(
            prop.edge
            for prop in self.props
        ) / len(self.props)
    
    @property
    def is_empty(self) -> bool:
        return len(self.props) == 0