from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Person:
    person_id: str
    name: str
    phone_number: str
    role: str  # primary role
    unit: str
    secondary_roles: List[str] = field(default_factory=list)

    def can_fill_role(self, role: str) -> bool:
        """Check if person can fill a role (primary or secondary)."""
        return self.role == role or role in self.secondary_roles


@dataclass
class Vacation:
    """A scheduled vacation day for a person."""
    person_id: str
    date: dt.date
    description: str = ""


@dataclass
class Preference:
    """A preference for a person that affects scheduling."""
    person_id: str
    type: str  # rest_multiplier, pair_with, avoid_person, prefer_mission, etc.
    target: str  # type-specific value
    priority: str = "medium"  # low, medium, high
    expires: Optional[dt.date] = None

    def is_active(self, on_date: dt.date) -> bool:
        """Check if preference is active on a given date."""
        if self.expires is None:
            return True
        return on_date <= self.expires

    def priority_weight(self) -> float:
        """Return numeric weight for priority."""
        weights = {"low": 0.5, "medium": 1.0, "high": 2.0}
        return weights.get(self.priority, 1.0)


@dataclass
class Mission:
    """A mission with role requirements and assignments."""
    mission_id: str
    name: str
    start: dt.datetime
    end: dt.datetime
    roles_required: Dict[str, int]  # e.g., {"commander": 1, "soldier": 2}
    status: str = "planned"  # planned, started, completed
    assignments: Dict[str, List[str]] = field(default_factory=dict)  # e.g., {"commander": ["john"], "soldier": ["mike", "sarah"]}
    continuous: bool = False  # If true, assignments carry over to next day automatically

    def duration_hours(self) -> float:
        """Return mission duration in hours."""
        return (self.end - self.start).total_seconds() / 3600

    def is_filled(self) -> bool:
        """Check if all role requirements are met."""
        for role, count in self.roles_required.items():
            assigned = self.assignments.get(role, [])
            if len(assigned) < count:
                return False
        return True

    def unfilled_roles(self) -> Dict[str, int]:
        """Return roles that still need people."""
        unfilled = {}
        for role, count in self.roles_required.items():
            assigned = len(self.assignments.get(role, []))
            remaining = count - assigned
            if remaining > 0:
                unfilled[role] = remaining
        return unfilled

    def all_assigned_people(self) -> List[str]:
        """Return list of all person IDs assigned to this mission."""
        people = []
        for person_list in self.assignments.values():
            people.extend(person_list)
        return people

    def assign_person(self, role: str, person_id: str) -> None:
        """Assign a person to a role in this mission."""
        if role not in self.assignments:
            self.assignments[role] = []
        if person_id not in self.assignments[role]:
            self.assignments[role].append(person_id)

    def unassign_person(self, person_id: str) -> None:
        """Remove a person from all roles in this mission."""
        for role in self.assignments:
            if person_id in self.assignments[role]:
                self.assignments[role].remove(person_id)


@dataclass
class MissionTemplate:
    """Template/metadata for a mission type."""
    template_id: str
    name: str
    start_time: dt.time  # When the mission starts each day
    duration_hours: float
    roles_required: Dict[str, int]
    continuous: bool = False  # If true, assignments carry over day to day
    instances: int = 1  # How many instances run simultaneously
    notes: str = ""


@dataclass
class Campaign:
    """Campaign metadata."""
    name: str
    start_date: dt.date
    end_date: dt.date
    on_duty_estimates: Dict[str, int]  # minimum staff per role on-site
    rest_cap_hours: int = 12


# Utility functions

def parse_datetime(value: str) -> dt.datetime:
    """Parse ISO datetime string."""
    return dt.datetime.fromisoformat(value)


def parse_date(value: str) -> dt.date:
    """Parse ISO date string."""
    return dt.date.fromisoformat(value)


def parse_json_dict(value: str) -> Dict:
    """Parse JSON string to dict."""
    if not value or value.strip() == "":
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {value}") from exc


def parse_roles_json(value: str) -> Dict[str, int]:
    """Parse roles JSON to dict with int values."""
    parsed = parse_json_dict(value)
    return {role: int(count) for role, count in parsed.items()}


def parse_assignments_json(value: str) -> Dict[str, List[str]]:
    """Parse assignments JSON to dict with list values."""
    parsed = parse_json_dict(value)
    return {role: list(people) for role, people in parsed.items()}
