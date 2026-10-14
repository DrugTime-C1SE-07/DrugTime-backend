from dataclasses import dataclass


@dataclass(frozen=True)
class Condition:
    id: int
    name: str
