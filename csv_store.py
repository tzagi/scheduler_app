import csv
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .data_models import (
    Campaign,
    Mission,
    MissionTemplate,
    Person,
    Preference,
    Vacation,
    parse_assignments_json,
    parse_datetime,
    parse_roles_json,
)


# ============================================================================
# Campaign
# ============================================================================

def load_campaign(path: Path) -> Campaign:
    """Load campaign from CSV file."""
    with path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("campaign.csv is empty")
    row = rows[0]
    estimates = parse_roles_json(row["on_duty_estimates"])
    return Campaign(
        name=row["name"],
        start_date=dt.date.fromisoformat(row["start_date"]),
        end_date=dt.date.fromisoformat(row["end_date"]),
        on_duty_estimates=estimates,
        rest_cap_hours=int(row.get("rest_cap_hours", 12)),
    )


def save_campaign(path: Path, campaign: Campaign) -> None:
    """Save campaign to CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["name", "start_date", "end_date", "on_duty_estimates", "rest_cap_hours"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "name": campaign.name,
            "start_date": campaign.start_date.isoformat(),
            "end_date": campaign.end_date.isoformat(),
            "on_duty_estimates": json.dumps(campaign.on_duty_estimates),
            "rest_cap_hours": campaign.rest_cap_hours,
        })


# ============================================================================
# People
# ============================================================================

def load_people(path: Path) -> List[Person]:
    """Load people from CSV file."""
    if not path.exists():
        _create_empty_csv(path, ["id", "name", "phone_number", "role", "unit", "secondary_roles"])
        return []
    
    people: List[Person] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            secondary_roles = [
                r.strip() for r in row.get("secondary_roles", "").split(",") if r.strip()
            ]
            people.append(Person(
                person_id=row["id"],
                name=row["name"],
                phone_number=row.get("phone_number", ""),
                role=row["role"],
                unit=row["unit"],
                secondary_roles=secondary_roles,
            ))
    return people


def save_people(path: Path, people: List[Person]) -> None:
    """Save people to CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "name", "phone_number", "role", "unit", "secondary_roles"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for person in people:
            writer.writerow({
                "id": person.person_id,
                "name": person.name,
                "phone_number": person.phone_number,
                "role": person.role,
                "unit": person.unit,
                "secondary_roles": ",".join(person.secondary_roles),
            })


def get_person_by_id(people: List[Person], person_id: str) -> Optional[Person]:
    """Find person by ID."""
    for person in people:
        if person.person_id == person_id:
            return person
    return None


def get_person_by_name(people: List[Person], name: str) -> Optional[Person]:
    """Find person by name (case-insensitive partial match)."""
    name_lower = name.lower()
    for person in people:
        if name_lower in person.name.lower():
            return person
    return None


# ============================================================================
# Missions
# ============================================================================

def load_missions(path: Path, templates: Optional[List[MissionTemplate]] = None) -> List[Mission]:
    """
    Load missions from CSV file.
    
    If templates are provided, mission data is enriched from templates.
    """
    if not path.exists():
        _create_empty_csv(path, ["id", "template_id", "start", "end", "assignments"])
        return []
    
    # Build template lookup
    template_by_id: Dict[str, MissionTemplate] = {}
    if templates:
        for t in templates:
            template_by_id[t.template_id] = t
    
    missions: List[Mission] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            assignments = parse_assignments_json(row.get("assignments", "{}"))
            template_id = row.get("template_id", "")
            template = template_by_id.get(template_id) if template_id else None
            
            # Parse start/end timestamps
            start_datetime = parse_datetime(row["start"])
            end_datetime = parse_datetime(row["end"])
            
            if template:
                # Use template for roles and other metadata
                missions.append(Mission(
                    mission_id=row["id"],
                    name=f"{template.name} - {start_datetime.date()}",
                    start=start_datetime,
                    end=end_datetime,
                    roles_required=template.roles_required.copy(),
                    status="planned",
                    assignments=assignments,
                    continuous=template.continuous,
                ))
            else:
                # No template - use defaults or legacy data
                roles_required = parse_roles_json(row.get("roles_required", "{}")) if row.get("roles_required") else {}
                continuous = row.get("continuous", "").lower() in ("true", "1", "yes")
                missions.append(Mission(
                    mission_id=row["id"],
                    name=row.get("name", row["id"]),
                    start=start_datetime,
                    end=end_datetime,
                    roles_required=roles_required,
                    status=row.get("status", "planned"),
                    assignments=assignments,
                    continuous=continuous,
                ))
    return missions


def save_missions(path: Path, missions: List[Mission]) -> None:
    """Save missions to CSV file with template reference and timestamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    fieldnames = ["id", "template_id", "start", "end", "assignments"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for mission in missions:
            # Extract template_id from mission_id (e.g., "patrol1_morning_day1" -> "patrol1_morning")
            parts = mission.mission_id.rsplit("_day", 1)
            template_id = parts[0] if len(parts) > 1 else mission.mission_id
            
            writer.writerow({
                "id": mission.mission_id,
                "template_id": template_id,
                "start": mission.start.isoformat(),
                "end": mission.end.isoformat(),
                "assignments": json.dumps(mission.assignments),
            })


def get_mission_by_id(missions: List[Mission], mission_id: str) -> Optional[Mission]:
    """Find mission by ID."""
    for mission in missions:
        if mission.mission_id == mission_id:
            return mission
    return None


# ============================================================================
# Mission Templates (Metadata)
# ============================================================================

def load_mission_templates(path: Path) -> List[MissionTemplate]:
    """Load mission templates from CSV file."""
    if not path.exists():
        _create_empty_csv(path, ["id", "name", "start_time", "duration_hours", "roles_required", "continuous", "instances", "notes"])
        return []
    
    templates: List[MissionTemplate] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse start_time
            time_str = row.get("start_time", "00:00")
            start_time = dt.datetime.strptime(time_str, "%H:%M").time()
            
            continuous = row.get("continuous", "").lower() in ("true", "1", "yes")
            instances = int(row.get("instances", 1) or 1)
            
            templates.append(MissionTemplate(
                template_id=row["id"],
                name=row["name"],
                start_time=start_time,
                duration_hours=float(row["duration_hours"]),
                roles_required=parse_roles_json(row["roles_required"]),
                continuous=continuous,
                instances=instances,
                notes=row.get("notes", ""),
            ))
    return templates


def save_mission_templates(path: Path, templates: List[MissionTemplate]) -> None:
    """Save mission templates to CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "name", "start_time", "duration_hours", "roles_required", "continuous", "instances", "notes"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for template in templates:
            writer.writerow({
                "id": template.template_id,
                "name": template.name,
                "start_time": template.start_time.strftime("%H:%M"),
                "duration_hours": template.duration_hours,
                "roles_required": json.dumps(template.roles_required),
                "continuous": str(template.continuous),
                "instances": template.instances,
                "notes": template.notes,
            })


def get_missions_for_date(missions: List[Mission], date: dt.date) -> List[Mission]:
    """Get all missions that occur on a given date."""
    return [m for m in missions if m.start.date() == date]


def get_missions_for_person(missions: List[Mission], person_id: str) -> List[Mission]:
    """Get all missions where a person is assigned."""
    result = []
    for mission in missions:
        if person_id in mission.all_assigned_people():
            result.append(mission)
    return result


# ============================================================================
# Vacations
# ============================================================================

def load_vacations(path: Path) -> List[Vacation]:
    """Load vacations from CSV file."""
    if not path.exists():
        _create_empty_csv(path, ["person_id", "date", "description"])
        return []
    
    vacations: List[Vacation] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            vacations.append(Vacation(
                person_id=row["person_id"],
                date=dt.date.fromisoformat(row["date"]),
                description=row.get("description", ""),
            ))
    return vacations


def save_vacations(path: Path, vacations: List[Vacation]) -> None:
    """Save vacations to CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["person_id", "date", "description"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for vacation in vacations:
            writer.writerow({
                "person_id": vacation.person_id,
                "date": vacation.date.isoformat(),
                "description": vacation.description,
            })


def add_vacation(vacations: List[Vacation], person_id: str, date: dt.date, description: str = "") -> List[Vacation]:
    """Add a vacation, replacing if exists for same person/date."""
    # Remove existing vacation for same person/date
    vacations = [v for v in vacations if not (v.person_id == person_id and v.date == date)]
    vacations.append(Vacation(person_id=person_id, date=date, description=description))
    return vacations


def remove_vacation(vacations: List[Vacation], person_id: str, date: dt.date) -> List[Vacation]:
    """Remove a vacation for person on date."""
    return [v for v in vacations if not (v.person_id == person_id and v.date == date)]


def get_vacations_for_person(vacations: List[Vacation], person_id: str) -> List[Vacation]:
    """Get all vacations for a person."""
    return [v for v in vacations if v.person_id == person_id]


def get_vacations_for_date(vacations: List[Vacation], date: dt.date) -> List[Vacation]:
    """Get all vacations on a date."""
    return [v for v in vacations if v.date == date]


def is_on_vacation(vacations: List[Vacation], person_id: str, date: dt.date) -> bool:
    """Check if person is on vacation on a date."""
    return any(v.person_id == person_id and v.date == date for v in vacations)


# ============================================================================
# Preferences
# ============================================================================

def load_preferences(path: Path) -> List[Preference]:
    """Load preferences from CSV file."""
    if not path.exists():
        _create_empty_csv(path, ["person_id", "type", "target", "priority", "expires"])
        return []
    
    preferences: List[Preference] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            expires = None
            if row.get("expires"):
                expires = dt.date.fromisoformat(row["expires"])
            preferences.append(Preference(
                person_id=row["person_id"],
                type=row["type"],
                target=row.get("target", ""),
                priority=row.get("priority", "medium"),
                expires=expires,
            ))
    return preferences


def save_preferences(path: Path, preferences: List[Preference]) -> None:
    """Save preferences to CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["person_id", "type", "target", "priority", "expires"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pref in preferences:
            writer.writerow({
                "person_id": pref.person_id,
                "type": pref.type,
                "target": pref.target,
                "priority": pref.priority,
                "expires": pref.expires.isoformat() if pref.expires else "",
            })


def add_preference(preferences: List[Preference], pref: Preference) -> List[Preference]:
    """Add a preference. Allows multiple preferences per person."""
    preferences.append(pref)
    return preferences


def remove_preference(preferences: List[Preference], person_id: str, pref_type: str, target: str = "") -> List[Preference]:
    """Remove preferences matching person_id, type, and optionally target."""
    if target:
        return [p for p in preferences if not (p.person_id == person_id and p.type == pref_type and p.target == target)]
    return [p for p in preferences if not (p.person_id == person_id and p.type == pref_type)]


def get_preferences_for_person(preferences: List[Preference], person_id: str, on_date: Optional[dt.date] = None) -> List[Preference]:
    """Get active preferences for a person, optionally filtered by date."""
    result = [p for p in preferences if p.person_id == person_id]
    if on_date:
        result = [p for p in result if p.is_active(on_date)]
    return result


def get_preferences_by_type(preferences: List[Preference], pref_type: str) -> List[Preference]:
    """Get all preferences of a specific type."""
    return [p for p in preferences if p.type == pref_type]


# ============================================================================
# Utility
# ============================================================================

def _create_empty_csv(path: Path, fieldnames: List[str]) -> None:
    """Create an empty CSV file with headers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
