import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from .csv_store import (
    add_vacation,
    get_missions_for_date,
    get_person_by_id,
    get_person_by_name,
    get_vacations_for_date,
    is_on_vacation,
    load_campaign,
    load_missions,
    load_mission_templates,
    load_people,
    load_preferences,
    load_vacations,
    remove_vacation,
    save_campaign,
    save_missions,
    save_preferences,
    save_vacations,
    add_preference,
)
from .data_models import Campaign, Mission, MissionTemplate, Person, Preference
from .scheduler import Scheduler, suggest_vacations


def load_missions_with_templates(data_dir: Path):
    """Helper to load missions with template data."""
    templates = load_mission_templates(data_dir / "mission_meta.csv")
    missions = load_missions(data_dir / "missions.csv", templates)
    return missions, templates


def init_campaign(data_dir: Path, name: str) -> None:
    """Initialize campaign directory and create missing files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    
    is_new = not (data_dir / "campaign.csv").exists()
    
    if is_new:
        print(f"Starting new campaign: {name}")
        print(f"Data directory: {data_dir}")
        print()
    else:
        print(f"Campaign: {name}")
        print(f"Data directory: {data_dir}")
        print()
    
    # Ensure campaign.csv exists
    campaign = ensure_campaign(data_dir, name)
    print(f"  Campaign: {campaign.start_date} to {campaign.end_date}")
    print(f"  On-duty estimates: {campaign.on_duty_estimates}")
    print(f"  Rest cap: {campaign.rest_cap_hours} hours")
    
    # Ensure people.csv exists
    people_path = data_dir / "people.csv"
    people = load_people(people_path)
    print(f"  People: {len(people)}")
    
    # Ensure missions.csv exists
    missions_path = data_dir / "missions.csv"
    missions = load_missions(missions_path)
    print(f"  Missions: {len(missions)}")
    
    # Ensure vacations.csv exists
    vacations_path = data_dir / "vacations.csv"
    vacations = load_vacations(vacations_path)
    print(f"  Vacations: {len(vacations)}")
    
    # Ensure preferences.csv exists
    preferences_path = data_dir / "preferences.csv"
    preferences = load_preferences(preferences_path)
    print(f"  Preferences: {len(preferences)}")
    
    print()
    if is_new:
        print("Campaign created! Next steps:")
        print("  1. Add people to people.csv")
        print("  2. Add missions: --add-mission")
        print("  3. Plan vacations: --plan-vacations --date=YYYY-MM-DD")
        print("  4. Assign people: --assign --date=YYYY-MM-DD")
    else:
        print("Use --help to see available commands.")


def ensure_campaign(data_dir: Path, name: str) -> Campaign:
    """Load or create campaign interactively."""
    campaign_path = data_dir / "campaign.csv"
    if campaign_path.exists():
        return load_campaign(campaign_path)

    print(f"Campaign data missing in {data_dir}. Let's create it.")
    while True:
        start_raw = input("Start date (YYYY-MM-DD): ").strip()
        end_raw = input("End date   (YYYY-MM-DD): ").strip()
        try:
            start_date = dt.date.fromisoformat(start_raw)
            end_date = dt.date.fromisoformat(end_raw)
        except ValueError:
            print("Invalid date format, please retry.")
            continue
        if end_date < start_date:
            print("End date must be on/after start date.")
            continue
        break

    estimates: Dict[str, int] = {}
    print("Enter on-duty estimates per role as role=count, comma-separated (e.g., soldier=20,commander=3).")
    estimates_raw = input("On-duty estimates: ").strip()
    if estimates_raw:
        for part in estimates_raw.split(","):
            if not part.strip():
                continue
            if "=" not in part:
                print(f"Skipping invalid entry: {part}")
                continue
            role, val = part.split("=", 1)
            try:
                estimates[role.strip()] = int(val.strip())
            except ValueError:
                print(f"Skipping invalid count for {role}: {val}")
    
    rest_cap = input("Rest cap hours (default 12): ").strip()
    rest_cap_hours = 12
    if rest_cap:
        try:
            rest_cap_hours = int(rest_cap)
        except ValueError:
            print("Invalid rest cap, using 12.")

    campaign = Campaign(
        name=name,
        start_date=start_date,
        end_date=end_date,
        on_duty_estimates=estimates,
        rest_cap_hours=rest_cap_hours,
    )
    save_campaign(campaign_path, campaign)
    print(f"Created campaign.csv in {data_dir}")
    return campaign


# ============================================================================
# Mission Commands
# ============================================================================

def add_mission_interactive(data_dir: Path) -> None:
    """Interactively add a mission to the campaign."""
    data_dir.mkdir(parents=True, exist_ok=True)
    missions_path = data_dir / "missions.csv"
    campaign_path = data_dir / "campaign.csv"
    
    if not campaign_path.exists():
        print("Campaign not found. Please create the campaign first.")
        return
    
    campaign = load_campaign(campaign_path)
    existing_missions = load_missions(missions_path)
    existing_ids = {m.mission_id for m in existing_missions}
    
    print("Adding a new mission to the campaign.")
    print()
    
    # Get mission ID
    while True:
        mission_id = input("Mission ID: ").strip()
        if not mission_id:
            print("Mission ID cannot be empty.")
            continue
        if mission_id in existing_ids:
            print(f"Mission ID '{mission_id}' already exists. Please choose a different ID.")
            continue
        break
    
    # Get mission name
    while True:
        name = input("Mission name: ").strip()
        if not name:
            print("Mission name cannot be empty.")
            continue
        break
    
    # Check if repeated mission
    while True:
        is_repeated_raw = input("Is this a repeated mission (runs every day)? (y/n): ").strip().lower()
        if is_repeated_raw in ("y", "yes"):
            is_repeated = True
            break
        elif is_repeated_raw in ("n", "no"):
            is_repeated = False
            break
        else:
            print("Please enter 'y' or 'n'.")
    
    # Get start time
    while True:
        start_time_raw = input("Start time (HH:MM, e.g., 07:00): ").strip()
        try:
            start_time = dt.datetime.strptime(start_time_raw, "%H:%M").time()
        except ValueError:
            print("Invalid time format. Please use HH:MM")
            continue
        break
    
    # Get duration
    while True:
        duration_raw = input("Duration (hours, e.g., 8 or 8.5): ").strip()
        try:
            duration_hours = float(duration_raw)
            if duration_hours <= 0:
                print("Duration must be positive.")
                continue
        except ValueError:
            print("Invalid duration. Please enter a number.")
            continue
        break
    
    # Get date if not repeated
    if not is_repeated:
        while True:
            date_raw = input(f"Date (YYYY-MM-DD, between {campaign.start_date} and {campaign.end_date}): ").strip()
            try:
                mission_date = dt.date.fromisoformat(date_raw)
                if mission_date < campaign.start_date or mission_date > campaign.end_date:
                    print(f"Date must be between {campaign.start_date} and {campaign.end_date}")
                    continue
            except ValueError:
                print("Invalid date format. Please use YYYY-MM-DD")
                continue
            break
    else:
        mission_date = None
    
    # Get roles required
    print("Enter roles required as role=count, comma-separated (e.g., commander=1,soldier=2).")
    roles_required: Dict[str, int] = {}
    while True:
        roles_raw = input("Roles required: ").strip()
        if not roles_raw:
            print("At least one role is required.")
            continue
        valid = True
        for part in roles_raw.split(","):
            if not part.strip():
                continue
            if "=" not in part:
                print(f"Invalid format: {part}. Use role=count")
                valid = False
                break
            role, val = part.split("=", 1)
            try:
                count = int(val.strip())
                if count <= 0:
                    print(f"Count must be positive for {role}")
                    valid = False
                    break
                roles_required[role.strip()] = count
            except ValueError:
                print(f"Invalid count for {role}: {val}")
                valid = False
                break
        if valid and roles_required:
            break
    
    # Create mission(s)
    new_missions: List[Mission] = []
    
    if is_repeated:
        current_date = campaign.start_date
        day_num = 1
        while current_date <= campaign.end_date:
            start_datetime = dt.datetime.combine(current_date, start_time)
            end_datetime = start_datetime + dt.timedelta(hours=duration_hours)
            
            daily_mission_id = f"{mission_id}_day{day_num}"
            daily_name = f"{name} - {current_date}"
            
            mission = Mission(
                mission_id=daily_mission_id,
                name=daily_name,
                start=start_datetime,
                end=end_datetime,
                roles_required=roles_required.copy(),
                status="planned",
            )
            new_missions.append(mission)
            current_date += dt.timedelta(days=1)
            day_num += 1
    else:
        start_datetime = dt.datetime.combine(mission_date, start_time)
        end_datetime = start_datetime + dt.timedelta(hours=duration_hours)
        
        mission = Mission(
            mission_id=mission_id,
            name=name,
            start=start_datetime,
            end=end_datetime,
            roles_required=roles_required,
            status="planned",
        )
        new_missions.append(mission)
    
    existing_missions.extend(new_missions)
    save_missions(missions_path, existing_missions)
    
    print()
    if is_repeated:
        print(f"Repeated mission '{name}' added successfully!")
        print(f"  Created {len(new_missions)} missions (one per day)")
    else:
        print(f"Mission '{name}' (ID: {mission_id}) added successfully!")
        print(f"  Date: {mission_date}")
    print(f"  Start time: {start_time.strftime('%H:%M')}")
    print(f"  Duration: {duration_hours} hours")
    print(f"  Roles required: {roles_required}")


def edit_mission_interactive(data_dir: Path, mission_id: str) -> None:
    """Edit a mission interactively."""
    missions_path = data_dir / "missions.csv"
    missions = load_missions(missions_path)
    
    mission = None
    for m in missions:
        if m.mission_id == mission_id:
            mission = m
            break
    
    if mission is None:
        print(f"Mission '{mission_id}' not found.")
        return
    
    if mission.status != "planned":
        print(f"Cannot edit mission with status '{mission.status}'. Only 'planned' missions can be edited.")
        return
    
    print(f"Editing mission: {mission.name}")
    print(f"  Current start: {mission.start}")
    print(f"  Current end: {mission.end}")
    print(f"  Current roles: {mission.roles_required}")
    print(f"  Current assignments: {mission.assignments}")
    print()
    print("Press Enter to keep current value, or enter new value.")
    
    # Name
    new_name = input(f"Name [{mission.name}]: ").strip()
    if new_name:
        mission.name = new_name
    
    # Start time
    new_start = input(f"Start datetime [{mission.start.isoformat()}]: ").strip()
    if new_start:
        try:
            mission.start = dt.datetime.fromisoformat(new_start)
        except ValueError:
            print("Invalid datetime, keeping current value.")
    
    # End time
    new_end = input(f"End datetime [{mission.end.isoformat()}]: ").strip()
    if new_end:
        try:
            mission.end = dt.datetime.fromisoformat(new_end)
        except ValueError:
            print("Invalid datetime, keeping current value.")
    
    # Status
    new_status = input(f"Status [{mission.status}] (planned/started/completed): ").strip()
    if new_status in ("planned", "started", "completed"):
        mission.status = new_status
    
    save_missions(missions_path, missions)
    print(f"Mission '{mission_id}' updated.")


def list_missions(data_dir: Path, filter_date: Optional[dt.date] = None) -> None:
    """List missions with optional date filter."""
    missions, _ = load_missions_with_templates(data_dir)
    people = load_people(data_dir / "people.csv")
    people_by_id = {p.person_id: p for p in people}
    
    if not missions:
        print("No missions found.")
        return
    
    if filter_date:
        missions = [m for m in missions if m.start.date() == filter_date]
    
    if not missions:
        print(f"No missions found for {filter_date}.")
        return
    
    missions.sort(key=lambda m: m.start)
    
    print(f"\nFound {len(missions)} mission(s):")
    print("-" * 100)
    
    for mission in missions:
        duration = mission.duration_hours()
        print(f"ID: {mission.mission_id}")
        print(f"  Name: {mission.name}")
        print(f"  Time: {mission.start.strftime('%Y-%m-%d %H:%M')} - {mission.end.strftime('%H:%M')} ({duration:.1f}h)")
        print(f"  Roles required: {mission.roles_required}")
        
        if mission.assignments:
            print("  Assignments:")
            for role, person_ids in mission.assignments.items():
                person_info = []
                for pid in person_ids:
                    p = people_by_id.get(pid)
                    if p:
                        person_info.append(f"{p.name} ({p.phone_number})")
                    else:
                        person_info.append(pid)
                print(f"    {role}: {', '.join(person_info)}")
        else:
            print("  Assignments: none")
        
        print(f"  Status: {mission.status}")
        print()


def generate_missions_cmd(data_dir: Path, start_date: Optional[dt.date] = None, end_date: Optional[dt.date] = None, clear: bool = False) -> None:
    """Generate mission instances from templates for a date range."""
    campaign = load_campaign(data_dir / "campaign.csv")
    templates = load_mission_templates(data_dir / "mission_meta.csv")
    missions_path = data_dir / "missions.csv"
    
    if not templates:
        print("No mission templates found. Create mission_meta.csv first.")
        return
    
    # Use campaign dates if not specified
    start = start_date or campaign.start_date
    end = end_date or campaign.end_date
    
    # Load existing missions or start fresh
    if clear:
        existing_missions = []
        print("Clearing existing missions...")
    else:
        existing_missions = load_missions(missions_path)
    
    existing_ids = {m.mission_id for m in existing_missions}
    new_missions: List[Mission] = []
    
    print(f"\nGenerating missions from {start} to {end}")
    print(f"Using {len(templates)} templates")
    print("-" * 60)
    
    # Generate missions for each day
    current_date = start
    day_num = 0
    while current_date <= end:
        day_num += 1
        
        for template in templates:
            # Generate instances
            for instance in range(1, template.instances + 1):
                # Create mission ID
                if template.instances > 1:
                    mission_id = f"{template.template_id}_{instance}_day{day_num}"
                    mission_name = f"{template.name} #{instance} - {current_date}"
                else:
                    mission_id = f"{template.template_id}_day{day_num}"
                    mission_name = f"{template.name} - {current_date}"
                
                # Skip if already exists
                if mission_id in existing_ids:
                    continue
                
                # Calculate start and end times
                start_datetime = dt.datetime.combine(current_date, template.start_time)
                end_datetime = start_datetime + dt.timedelta(hours=template.duration_hours)
                
                mission = Mission(
                    mission_id=mission_id,
                    name=mission_name,
                    start=start_datetime,
                    end=end_datetime,
                    roles_required=template.roles_required.copy(),
                    status="planned",
                    assignments={},
                    continuous=template.continuous,
                )
                new_missions.append(mission)
        
        current_date += dt.timedelta(days=1)
    
    # Combine and save
    all_missions = existing_missions + new_missions
    save_missions(missions_path, all_missions)
    
    print(f"Generated {len(new_missions)} new missions")
    print(f"Total missions: {len(all_missions)}")
    
    # Summary by template
    print("\nMissions per template:")
    for template in templates:
        count = sum(1 for m in new_missions if m.mission_id.startswith(template.template_id))
        print(f"  {template.name}: {count}")


def list_templates_cmd(data_dir: Path) -> None:
    """List mission templates."""
    templates = load_mission_templates(data_dir / "mission_meta.csv")
    
    if not templates:
        print("No mission templates found.")
        return
    
    print(f"\nMission Templates ({len(templates)}):")
    print("-" * 100)
    
    for t in templates:
        continuous_mark = " [CONTINUOUS]" if t.continuous else ""
        instances_mark = f" x{t.instances}" if t.instances > 1 else ""
        print(f"{t.template_id}: {t.name}")
        print(f"  Time: {t.start_time.strftime('%H:%M')} ({t.duration_hours}h){instances_mark}{continuous_mark}")
        print(f"  Roles: {t.roles_required}")
        if t.notes:
            print(f"  Notes: {t.notes}")
        print()


# ============================================================================
# Vacation Commands
# ============================================================================

def set_vacation_cmd(data_dir: Path, person_id: str, date: dt.date, days: int = 1, description: str = "") -> None:
    """Set vacation for a person."""
    people = load_people(data_dir / "people.csv")
    vacations_path = data_dir / "vacations.csv"
    vacations = load_vacations(vacations_path)
    
    # Find person
    person = get_person_by_id(people, person_id) or get_person_by_name(people, person_id)
    if person is None:
        print(f"Person '{person_id}' not found.")
        return
    
    # Add vacation for each day
    for i in range(days):
        vacation_date = date + dt.timedelta(days=i)
        vacations = add_vacation(vacations, person.person_id, vacation_date, description)
        print(f"  Added vacation: {person.name} on {vacation_date}")
    
    save_vacations(vacations_path, vacations)
    print(f"Vacation scheduled for {person.name}: {days} day(s) starting {date}")


def remove_vacation_cmd(data_dir: Path, person_id: str, date: dt.date) -> None:
    """Remove vacation for a person."""
    people = load_people(data_dir / "people.csv")
    vacations_path = data_dir / "vacations.csv"
    vacations = load_vacations(vacations_path)
    
    person = get_person_by_id(people, person_id) or get_person_by_name(people, person_id)
    if person is None:
        print(f"Person '{person_id}' not found.")
        return
    
    before_count = len(vacations)
    vacations = remove_vacation(vacations, person.person_id, date)
    
    if len(vacations) < before_count:
        save_vacations(vacations_path, vacations)
        print(f"Removed vacation for {person.name} on {date}")
    else:
        print(f"No vacation found for {person.name} on {date}")


def plan_vacations_cmd(data_dir: Path, target_date: dt.date, days: int = 1) -> None:
    """Suggest who can go on vacation."""
    campaign = load_campaign(data_dir / "campaign.csv")
    people = load_people(data_dir / "people.csv")
    vacations = load_vacations(data_dir / "vacations.csv")
    missions, _ = load_missions_with_templates(data_dir)
    
    suggestions = suggest_vacations(people, vacations, missions, campaign, target_date, days)
    
    print(f"\nVacation suggestions for {target_date} ({days} day(s)):")
    print("-" * 80)
    print(f"{'#':<3} {'Name':<20} {'Role':<15} {'Score':<10} {'Notes'}")
    print("-" * 80)
    
    for i, (person, score, reason) in enumerate(suggestions[:20], 1):
        status = "OK" if score < 100 else "BLOCKED" if score >= 500 else "WARN"
        print(f"{i:<3} {person.name:<20} {person.role:<15} {score:<10.0f} {status}: {reason}")
    
    print("-" * 80)
    print("Lower score = better candidate for vacation")
    print("BLOCKED = assigned to mission or would leave role understaffed")


# ============================================================================
# Preference Commands
# ============================================================================

def add_preference_interactive(data_dir: Path) -> None:
    """Add a preference interactively."""
    people = load_people(data_dir / "people.csv")
    preferences_path = data_dir / "preferences.csv"
    preferences = load_preferences(preferences_path)
    
    print("Add a preference")
    print("Types: rest_multiplier, pair_with, avoid_person, prefer_mission, avoid_mission,")
    print("       prefer_weekend, prefer_weekday, prefer_vacation_date, must_vacation_date")
    print()
    
    # Get person
    person_input = input("Person ID or name: ").strip()
    person = get_person_by_id(people, person_input) or get_person_by_name(people, person_input)
    if person is None:
        print(f"Person '{person_input}' not found.")
        return
    
    # Get type
    pref_type = input("Preference type: ").strip()
    valid_types = [
        "rest_multiplier", "pair_with", "avoid_person", "prefer_mission",
        "avoid_mission", "prefer_weekend", "prefer_weekday",
        "prefer_vacation_date", "must_vacation_date"
    ]
    if pref_type not in valid_types:
        print(f"Invalid type. Valid types: {', '.join(valid_types)}")
        return
    
    # Get target
    target = ""
    if pref_type in ("rest_multiplier", "pair_with", "avoid_person", "prefer_mission",
                     "avoid_mission", "prefer_vacation_date", "must_vacation_date"):
        target = input("Target value: ").strip()
    
    # Get priority
    priority = input("Priority (low/medium/high) [medium]: ").strip() or "medium"
    if priority not in ("low", "medium", "high"):
        priority = "medium"
    
    # Get expiration
    expires = None
    expires_raw = input("Expires date (YYYY-MM-DD) [never]: ").strip()
    if expires_raw:
        try:
            expires = dt.date.fromisoformat(expires_raw)
        except ValueError:
            print("Invalid date, setting no expiration.")
    
    pref = Preference(
        person_id=person.person_id,
        type=pref_type,
        target=target,
        priority=priority,
        expires=expires,
    )
    preferences = add_preference(preferences, pref)
    save_preferences(preferences_path, preferences)
    
    print(f"Added preference: {person.name} - {pref_type}={target} ({priority})")


# ============================================================================
# Assignment Commands
# ============================================================================

def _get_mission_base_name(mission_name: str) -> str:
    """Extract base name from mission name (e.g., 'hapak - 2026-02-19' -> 'hapak')."""
    # Remove date suffix if present
    if " - " in mission_name:
        parts = mission_name.rsplit(" - ", 1)
        # Check if the last part looks like a date
        try:
            dt.date.fromisoformat(parts[-1])
            return parts[0]
        except ValueError:
            pass
    return mission_name


def _find_previous_day_mission(missions: List[Mission], mission: Mission, prev_date: dt.date) -> Optional[Mission]:
    """Find yesterday's mission with the same base name."""
    base_name = _get_mission_base_name(mission.name)
    for m in missions:
        if m.start.date() == prev_date:
            if _get_mission_base_name(m.name) == base_name:
                # Also check similar time slot
                if m.start.time() == mission.start.time():
                    return m
    return None


def assign_cmd(data_dir: Path, target_date: dt.date, auto_accept: bool = False) -> None:
    """Assign people to missions for a date."""
    campaign = load_campaign(data_dir / "campaign.csv")
    people = load_people(data_dir / "people.csv")
    vacations = load_vacations(data_dir / "vacations.csv")
    preferences = load_preferences(data_dir / "preferences.csv")
    missions_path = data_dir / "missions.csv"
    missions, _ = load_missions_with_templates(data_dir)
    
    # Get missions for target date (support old status values: tentative, must)
    assignable_statuses = {"planned", "tentative", "must"}
    day_missions = [m for m in missions if m.start.date() == target_date and m.status in assignable_statuses]
    
    if not day_missions:
        print(f"No planned missions found for {target_date}")
        return
    
    # For continuous missions, carry forward yesterday's assignments
    prev_date = target_date - dt.timedelta(days=1)
    for mission in day_missions:
        if mission.continuous and not mission.assignments:
            prev_mission = _find_previous_day_mission(missions, mission, prev_date)
            if prev_mission and prev_mission.assignments:
                # Copy assignments, excluding people on vacation today
                for role, person_ids in prev_mission.assignments.items():
                    carried = []
                    for pid in person_ids:
                        if not is_on_vacation(vacations, pid, target_date):
                            carried.append(pid)
                            print(f"[Continuous] {mission.name}: Carrying forward {pid} as {role}")
                        else:
                            print(f"[Continuous] {mission.name}: {pid} is on vacation, not carrying forward")
                    if carried:
                        mission.assignments[role] = carried
    
    scheduler = Scheduler(people, vacations, preferences, campaign, missions)
    
    print(f"\nAssigning missions for {target_date}")
    print("=" * 80)
    
    changes_made = False
    
    for mission in sorted(day_missions, key=lambda m: m.start):
        unfilled = mission.unfilled_roles()
        if not unfilled:
            continue
        
        print(f"\n{mission.name} ({mission.start.strftime('%H:%M')} - {mission.end.strftime('%H:%M')})")
        print(f"  Current assignments: {mission.assignments or 'none'}")
        
        for role, needed in unfilled.items():
            for slot in range(needed):
                already_assigned = set(mission.all_assigned_people())
                candidates = scheduler.get_candidates(mission, role, already_assigned)
                
                if not candidates:
                    print(f"  [{role} #{slot+1}] No candidates available!")
                    continue
                
                print(f"\n  [{role} #{slot+1}] Top candidates:")
                for i, cand in enumerate(candidates[:5], 1):
                    vacation_marker = " (ON VACATION!)" if cand.vacation_penalty > 0 else ""
                    print(f"    {i}. {cand.person.name} ({cand.person.unit}) "
                          f"score={cand.total_score:.1f} {cand.score_breakdown()}{vacation_marker}")
                
                if auto_accept:
                    choice = 1
                    print(f"  Auto-accepting: {candidates[0].person.name}")
                else:
                    choice_raw = input(f"  Select (1-{min(5, len(candidates))}), or 's' to skip [1]: ").strip()
                    if choice_raw.lower() == 's':
                        print("  Skipped.")
                        continue
                    try:
                        choice = int(choice_raw) if choice_raw else 1
                        if choice < 1 or choice > len(candidates):
                            choice = 1
                    except ValueError:
                        choice = 1
                
                selected = candidates[choice - 1]
                scheduler.assign_to_mission(mission, role, selected.person.person_id)
                print(f"  Assigned: {selected.person.name}")
                changes_made = True
    
    if changes_made:
        save_missions(missions_path, missions)
        print(f"\nAssignments saved to {missions_path}")
    else:
        print("\nNo changes made.")


# ============================================================================
# View Commands
# ============================================================================

def view_date_cmd(data_dir: Path, target_date: dt.date) -> None:
    """View missions, assignments, and vacations for a date."""
    people = load_people(data_dir / "people.csv")
    missions, _ = load_missions_with_templates(data_dir)
    vacations = load_vacations(data_dir / "vacations.csv")
    
    people_by_id = {p.person_id: p for p in people}
    
    print(f"\n{'='*80}")
    print(f"  DATE: {target_date} ({target_date.strftime('%A')})")
    print(f"{'='*80}")
    
    # Missions
    day_missions = get_missions_for_date(missions, target_date)
    day_missions.sort(key=lambda m: m.start)
    
    print(f"\nMISSIONS ({len(day_missions)}):")
    print("-" * 80)
    
    if not day_missions:
        print("  No missions scheduled.")
    
    for mission in day_missions:
        print(f"\n  {mission.name}")
        print(f"  Time: {mission.start.strftime('%H:%M')} - {mission.end.strftime('%H:%M')} | Status: {mission.status}")
        print(f"  Required: {mission.roles_required}")
        
        if mission.assignments:
            print("  Assigned:")
            for role, person_ids in mission.assignments.items():
                person_info = []
                for pid in person_ids:
                    p = people_by_id.get(pid)
                    if p:
                        person_info.append(f"{p.name} ({p.phone_number})")
                    else:
                        person_info.append(pid)
                print(f"    {role}: {', '.join(person_info)}")
        else:
            print("  Assigned: (none)")
        
        unfilled = mission.unfilled_roles()
        if unfilled:
            print(f"  UNFILLED: {unfilled}")
    
    # Vacations
    day_vacations = get_vacations_for_date(vacations, target_date)
    
    print(f"\n\nVACATIONS ({len(day_vacations)}):")
    print("-" * 80)
    
    if not day_vacations:
        print("  No one on vacation.")
    else:
        for vacation in day_vacations:
            person = people_by_id.get(vacation.person_id)
            if person:
                info = f"{person.name} ({person.phone_number})"
                role = person.role
            else:
                info = vacation.person_id
                role = "?"
            desc = f" - {vacation.description}" if vacation.description else ""
            print(f"  {info} [{role}]{desc}")
    
    print()


# ============================================================================
# Report Commands
# ============================================================================

def report_date_cmd(data_dir: Path, target_date: dt.date, strict: bool = False) -> None:
    """
    Attendance report for a date.
    
    Non-strict: Person is on vacation if they slept at home (have vacation entry)
    Strict: Person is on vacation only if slept at home AND had no mission
    """
    people = load_people(data_dir / "people.csv")
    missions, _ = load_missions_with_templates(data_dir)
    vacations = load_vacations(data_dir / "vacations.csv")
    
    people_by_id = {p.person_id: p for p in people}
    
    # Get mission assignments for this date
    day_missions = get_missions_for_date(missions, target_date)
    assigned_people = set()
    for mission in day_missions:
        if mission.status in ("started", "completed"):  # Only count actual missions
            assigned_people.update(mission.all_assigned_people())
    
    on_site = []
    on_vacation = []
    
    for person in people:
        has_vacation = is_on_vacation(vacations, person.person_id, target_date)
        had_mission = person.person_id in assigned_people
        
        if strict:
            # Vacation only if slept home AND no mission
            is_vacation = has_vacation and not had_mission
        else:
            # Vacation if slept home (regardless of mission)
            is_vacation = has_vacation
        
        if is_vacation:
            on_vacation.append(person)
        else:
            on_site.append(person)
    
    mode = "strict" if strict else "standard"
    print(f"\nAttendance Report for {target_date} ({mode} mode)")
    print("=" * 60)
    
    print(f"\nON SITE ({len(on_site)}):")
    print("-" * 40)
    by_role: Dict[str, List[Person]] = {}
    for p in on_site:
        by_role.setdefault(p.role, []).append(p)
    for role, persons in sorted(by_role.items()):
        print(f"  {role}: {len(persons)}")
        for p in sorted(persons, key=lambda x: x.name):
            print(f"    - {p.name} ({p.unit})")
    
    print(f"\nON VACATION ({len(on_vacation)}):")
    print("-" * 40)
    for p in sorted(on_vacation, key=lambda x: x.name):
        print(f"  - {p.name} ({p.role}, {p.unit})")
    
    print()


def report_person_cmd(data_dir: Path, person_id: Optional[str] = None) -> None:
    """Report per-person statistics."""
    people = load_people(data_dir / "people.csv")
    missions, _ = load_missions_with_templates(data_dir)
    vacations = load_vacations(data_dir / "vacations.csv")
    
    # Filter to specific person if requested
    if person_id:
        person = get_person_by_id(people, person_id) or get_person_by_name(people, person_id)
        if person is None:
            print(f"Person '{person_id}' not found.")
            return
        people = [person]
    
    print("\nPerson Statistics")
    print("=" * 80)
    print(f"{'Name':<20} {'Role':<12} {'Unit':<10} {'Missions':<10} {'Hours':<10} {'Vacations'}")
    print("-" * 80)
    
    for person in sorted(people, key=lambda p: (p.role, p.name)):
        # Count completed missions
        mission_count = 0
        total_hours = 0.0
        for mission in missions:
            if mission.status in ("started", "completed"):
                if person.person_id in mission.all_assigned_people():
                    mission_count += 1
                    total_hours += mission.duration_hours()
        
        # Count vacation days
        vacation_count = sum(1 for v in vacations if v.person_id == person.person_id)
        
        print(f"{person.name:<20} {person.role:<12} {person.unit:<10} {mission_count:<10} {total_hours:<10.1f} {vacation_count}")
    
    print("-" * 80)


def vacation_summary_cmd(data_dir: Path) -> None:
    """Show daily vacation summary table with returning/leaving details."""
    from collections import defaultdict
    
    campaign = load_campaign(data_dir / "campaign.csv")
    people = load_people(data_dir / "people.csv")
    vacations = load_vacations(data_dir / "vacations.csv")
    
    # Filter to units 1-3 only
    people = [p for p in people if p.unit in ['1', '2', '3']]
    people_by_id = {p.person_id: p for p in people}
    valid_ids = set(people_by_id.keys())
    
    # Build vacation lookup by date
    vacation_dates: Dict[str, set] = defaultdict(set)
    for v in vacations:
        if v.person_id in valid_ids:
            vacation_dates[v.date.isoformat()].add(v.person_id)
    
    # Effective role mapping (medics = soldiers, cmd+off+samal = command)
    def get_effective_role(person: Person) -> str:
        if person.role in ['medic', 'soldier']:
            return 'soldier'
        elif person.role in ['commander', 'officer', 'samal']:
            return 'command'
        return person.role
    
    # Required on-site
    REQUIRED = {'soldier': 27, 'command': 7}
    
    # Generate all dates
    all_dates = []
    current = campaign.start_date
    while current <= campaign.end_date:
        all_dates.append(current.isoformat())
        current += dt.timedelta(days=1)
    
    # Helper to format people list
    def format_people(pids: set, limit: int = 3) -> str:
        if not pids:
            return "-"
        by_unit: Dict[str, List[str]] = defaultdict(list)
        for pid in pids:
            if pid in people_by_id:
                p = people_by_id[pid]
                by_unit[p.unit].append(p.name.split()[0])
        
        parts = []
        for unit in sorted(by_unit.keys()):
            names = by_unit[unit]
            if len(names) <= limit:
                parts.append(f"U{unit}:{','.join(names)}")
            else:
                parts.append(f"U{unit}:{len(names)} ppl")
        return ' '.join(parts)
    
    # Print header
    print("\n" + "=" * 140)
    print("DAILY VACATION SUMMARY")
    print("=" * 140)
    print(f"\n{'Date':<12} {'Day':<4} │{'Home':>5} {'Site':>5}│{'Sol':>4} {'Cmd':>4}│ {'Returning':<40} {'Leaving':<40}")
    print("-" * 140)
    
    prev_home: set = set()
    for date_str in all_dates:
        d = dt.date.fromisoformat(date_str)
        dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]
        
        home_today = vacation_dates.get(date_str, set())
        on_site = valid_ids - home_today
        
        # Count by effective role on site
        sol = sum(1 for pid in on_site if get_effective_role(people_by_id[pid]) == 'soldier')
        cmd = sum(1 for pid in on_site if get_effective_role(people_by_id[pid]) == 'command')
        
        # Returning (was home yesterday, on site today)
        returning = prev_home - home_today
        # Leaving (was on site yesterday, home today)
        leaving = home_today - prev_home
        
        ret_str = format_people(returning)
        lvg_str = format_people(leaving)
        
        # Constraint check
        sol_ok = "✓" if sol >= REQUIRED['soldier'] else f"!{sol}"
        cmd_ok = "✓" if cmd >= REQUIRED['command'] else f"!{cmd}"
        
        print(f"{date_str:<12} {dow:<4} │{len(home_today):>5} {len(on_site):>5}│{sol:>4} {cmd:>4}│ {ret_str:<40} {lvg_str:<40}")
        
        prev_home = home_today
    
    # Summary by effective role
    print("\n" + "=" * 140)
    print("VACATION DAYS BY ROLE")
    print("=" * 140)
    
    by_eff_role: Dict[str, List[tuple]] = defaultdict(list)
    for p in people:
        eff_role = get_effective_role(p)
        vac_count = sum(1 for v in vacations if v.person_id == p.person_id)
        by_eff_role[eff_role].append((p.name, vac_count))
    
    for role in ['soldier', 'command']:
        persons = by_eff_role.get(role, [])
        if persons:
            days = [d for _, d in persons]
            print(f"\n{role.upper()} ({len(persons)} people):")
            print(f"  Vacation days: min={min(days)}, max={max(days)}, avg={sum(days)/len(days):.1f}")
    
    # Constraint check
    violations = []
    for date_str in all_dates:
        home = vacation_dates.get(date_str, set())
        on_site = valid_ids - home
        sol = sum(1 for pid in on_site if get_effective_role(people_by_id[pid]) == 'soldier')
        cmd = sum(1 for pid in on_site if get_effective_role(people_by_id[pid]) == 'command')
        if sol < REQUIRED['soldier']:
            violations.append(f"{date_str}: {sol} soldiers")
        if cmd < REQUIRED['command']:
            violations.append(f"{date_str}: {cmd} command")
    
    if violations:
        print(f"\n⚠️ {len(violations)} constraint violations!")
        for v in violations[:5]:
            print(f"  {v}")
    else:
        print("\n✅ All days meet staffing requirements!")


# ============================================================================
# Main CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Campaign mission scheduling")
    
    # Campaign context
    parser.add_argument(
        "--name",
        required=True,
        help="Campaign name (folder under data-root)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parent / "data",
        help="Root directory containing campaign folders",
    )
    
    # Commands
    parser.add_argument("--add-mission", action="store_true", help="Add a new mission interactively")
    parser.add_argument("--edit-mission", metavar="ID", help="Edit a mission by ID")
    parser.add_argument("--get-missions", action="store_true", help="List missions")
    parser.add_argument("--get-templates", action="store_true", help="List mission templates")
    parser.add_argument("--generate-missions", action="store_true", help="Generate missions from templates")
    parser.add_argument("--clear", action="store_true", help="Clear existing missions when generating")
    
    parser.add_argument("--set-vacation", action="store_true", help="Set vacation for a person")
    parser.add_argument("--remove-vacation", action="store_true", help="Remove vacation for a person")
    parser.add_argument("--plan-vacations", action="store_true", help="Suggest vacation candidates")
    
    parser.add_argument("--add-preference", action="store_true", help="Add a preference interactively")
    
    parser.add_argument("--assign", action="store_true", help="Assign people to missions for a date")
    parser.add_argument("-Y", action="store_true", dest="auto_accept", help="Auto-accept assignment suggestions")
    
    parser.add_argument("--view", action="store_true", help="View missions and assignments for a date")
    
    parser.add_argument("--report", action="store_true", help="Attendance report for a date")
    parser.add_argument("--strict", action="store_true", help="Strict vacation counting (no mission = vacation)")
    
    parser.add_argument("--report-person", action="store_true", help="Per-person statistics")
    parser.add_argument("--vacation-summary", action="store_true", help="Daily vacation summary table")
    
    # Common arguments
    parser.add_argument("--date", type=dt.date.fromisoformat, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--start", type=dt.date.fromisoformat, help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end", type=dt.date.fromisoformat, help="End date for range (YYYY-MM-DD)")
    parser.add_argument("--person", help="Person ID or name")
    parser.add_argument("--days", type=int, default=1, help="Number of days (for vacation)")
    parser.add_argument("--desc", default="", help="Description (for vacation)")
    
    args = parser.parse_args()
    data_dir = args.data_root / args.name
    
    # Ensure campaign exists for most commands
    if not args.add_mission:
        data_dir.mkdir(parents=True, exist_ok=True)
    
    # Route to command
    if args.add_mission:
        add_mission_interactive(data_dir)
    
    elif args.edit_mission:
        edit_mission_interactive(data_dir, args.edit_mission)
    
    elif args.get_missions:
        list_missions(data_dir, filter_date=args.date)
    
    elif args.get_templates:
        list_templates_cmd(data_dir)
    
    elif args.generate_missions:
        generate_missions_cmd(data_dir, args.start, args.end, args.clear)
    
    elif args.set_vacation:
        if not args.person or not args.date:
            print("--set-vacation requires --person and --date")
            return
        set_vacation_cmd(data_dir, args.person, args.date, args.days, args.desc)
    
    elif args.remove_vacation:
        if not args.person or not args.date:
            print("--remove-vacation requires --person and --date")
            return
        remove_vacation_cmd(data_dir, args.person, args.date)
    
    elif args.plan_vacations:
        if not args.date:
            print("--plan-vacations requires --date")
            return
        plan_vacations_cmd(data_dir, args.date, args.days)
    
    elif args.add_preference:
        add_preference_interactive(data_dir)
    
    elif args.assign:
        if not args.date:
            print("--assign requires --date")
            return
        assign_cmd(data_dir, args.date, args.auto_accept)
    
    elif args.view:
        if not args.date:
            print("--view requires --date")
            return
        view_date_cmd(data_dir, args.date)
    
    elif args.report:
        if not args.date:
            print("--report requires --date")
            return
        report_date_cmd(data_dir, args.date, args.strict)
    
    elif args.report_person:
        report_person_cmd(data_dir, args.person)
    
    elif args.vacation_summary:
        vacation_summary_cmd(data_dir)
    
    else:
        # Default: initialize campaign (create missing files)
        init_campaign(data_dir, args.name)


if __name__ == "__main__":
    main()
