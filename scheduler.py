from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .data_models import Campaign, Mission, Person, Preference, Vacation


# Very high penalty for assigning someone on scheduled vacation
VACATION_PENALTY = 10000.0


@dataclass
class PersonState:
    """Tracks a person's state during scheduling."""
    person: Person
    missions_assigned: List[Mission] = field(default_factory=list)
    
    def total_hours(self) -> float:
        """Total hours assigned to missions."""
        return sum(m.duration_hours() for m in self.missions_assigned)
    
    def mission_count(self) -> int:
        """Number of missions assigned."""
        return len(self.missions_assigned)
    
    def last_mission_end(self) -> Optional[dt.datetime]:
        """End time of most recent mission."""
        if not self.missions_assigned:
            return None
        return max(m.end for m in self.missions_assigned)
    
    def is_assigned_to(self, mission: Mission) -> bool:
        """Check if person is assigned to a specific mission."""
        return any(m.mission_id == mission.mission_id for m in self.missions_assigned)


@dataclass
class CandidateScore:
    """Score breakdown for a candidate."""
    person: Person
    total_score: float
    vacation_penalty: float = 0.0
    fairness_score: float = 0.0
    preference_score: float = 0.0
    unit_cohesion: float = 0.0
    role_match: float = 0.0
    
    def score_breakdown(self) -> str:
        """Return human-readable score breakdown."""
        parts = []
        if self.vacation_penalty > 0:
            parts.append(f"vacation:{self.vacation_penalty:.0f}")
        parts.append(f"fairness:{self.fairness_score:.1f}")
        if self.preference_score != 0:
            parts.append(f"pref:{self.preference_score:.1f}")
        if self.unit_cohesion != 0:
            parts.append(f"unit:{self.unit_cohesion:.1f}")
        if self.role_match != 0:
            parts.append(f"role:{self.role_match:.1f}")
        return f"[{', '.join(parts)}]"


class Scheduler:
    """
    Scheduler for assigning people to missions.
    
    Uses a filter/score approach:
    1. Filter out people who cannot be assigned (hard constraints)
    2. Score remaining candidates (soft constraints)
    3. Return ranked candidates for interactive selection
    """
    
    def __init__(
        self,
        people: Sequence[Person],
        vacations: Sequence[Vacation],
        preferences: Sequence[Preference],
        campaign: Campaign,
        missions: Sequence[Mission],
    ):
        self.people = {p.person_id: p for p in people}
        self.campaign = campaign
        self.rest_cap_hours = campaign.rest_cap_hours
        
        # Index vacations by (person_id, date)
        self.vacations: Dict[Tuple[str, dt.date], Vacation] = {}
        for v in vacations:
            self.vacations[(v.person_id, v.date)] = v
        
        # Index preferences by person_id
        self.preferences: Dict[str, List[Preference]] = defaultdict(list)
        for p in preferences:
            self.preferences[p.person_id].append(p)
        
        # Build person state from existing assignments
        self.states: Dict[str, PersonState] = {}
        for person in people:
            self.states[person.person_id] = PersonState(person=person)
        
        # Load existing assignments from missions
        for mission in missions:
            for person_id in mission.all_assigned_people():
                if person_id in self.states:
                    self.states[person_id].missions_assigned.append(mission)
        
        # Count vacations per person (for fairness calculation)
        self.vacation_counts: Dict[str, int] = defaultdict(int)
        for v in vacations:
            self.vacation_counts[v.person_id] += 1
    
    def is_on_vacation(self, person_id: str, date: dt.date) -> bool:
        """Check if person has scheduled vacation on date."""
        return (person_id, date) in self.vacations
    
    def get_rest_multiplier(self, person_id: str, date: dt.date) -> float:
        """Get rest multiplier from preferences."""
        for pref in self.preferences.get(person_id, []):
            if pref.type == "rest_multiplier" and pref.is_active(date):
                try:
                    return float(pref.target)
                except ValueError:
                    pass
        return 1.0
    
    def has_must_vacation(self, person_id: str, date: dt.date) -> bool:
        """Check if person has must_vacation_date preference for date."""
        for pref in self.preferences.get(person_id, []):
            if pref.type == "must_vacation_date" and pref.is_active(date):
                try:
                    pref_date = dt.date.fromisoformat(pref.target)
                    if pref_date == date:
                        return True
                except ValueError:
                    pass
        return False
    
    def get_candidates(
        self,
        mission: Mission,
        role: str,
        already_assigned: Set[str],
    ) -> List[CandidateScore]:
        """
        Get ranked candidates for a role in a mission.
        
        Args:
            mission: The mission to assign
            role: The role to fill
            already_assigned: Person IDs already assigned to this mission
        
        Returns:
            List of CandidateScore, sorted by total_score (lower is better)
        """
        candidates: List[CandidateScore] = []
        mission_date = mission.start.date()
        
        for person_id, state in self.states.items():
            person = state.person
            
            # === HARD CONSTRAINTS (filter out) ===
            
            # Must be able to fill the role
            if not person.can_fill_role(role):
                continue
            
            # Cannot be already assigned to this mission
            if person_id in already_assigned:
                continue
            
            # Cannot have must_vacation_date preference for this date
            if self.has_must_vacation(person_id, mission_date):
                continue
            
            # Cannot have overlapping mission
            if self._has_overlap(state, mission):
                continue
            
            # Must have enough rest from previous mission
            if not self._has_enough_rest(state, mission):
                continue
            
            # === SOFT CONSTRAINTS (scoring) ===
            score = self._calculate_score(state, mission, role, already_assigned)
            candidates.append(score)
        
        # Sort by total score (lower is better)
        candidates.sort(key=lambda c: (c.total_score, c.person.person_id))
        return candidates
    
    def _has_overlap(self, state: PersonState, mission: Mission) -> bool:
        """Check if person has an overlapping mission."""
        for assigned in state.missions_assigned:
            # Overlap if not (one ends before other starts)
            if not (mission.end <= assigned.start or mission.start >= assigned.end):
                return True
        return False
    
    def _has_enough_rest(self, state: PersonState, mission: Mission) -> bool:
        """Check if person has enough rest since last mission."""
        last_end = state.last_mission_end()
        if last_end is None:
            return True
        
        # Find the mission that just ended
        last_mission = None
        for m in state.missions_assigned:
            if m.end == last_end:
                last_mission = m
                break
        
        if last_mission is None:
            return True
        
        # Calculate required rest
        rest_multiplier = self.get_rest_multiplier(state.person.person_id, mission.start.date())
        mission_duration = last_mission.duration_hours()
        rest_needed = min(mission_duration, self.rest_cap_hours) * rest_multiplier
        
        # Check if enough time has passed
        rest_end = last_end + dt.timedelta(hours=rest_needed)
        return mission.start >= rest_end
    
    def _calculate_score(
        self,
        state: PersonState,
        mission: Mission,
        role: str,
        already_assigned: Set[str],
    ) -> CandidateScore:
        """Calculate score for a candidate. Lower is better."""
        person = state.person
        mission_date = mission.start.date()
        
        # Vacation penalty (very high if on scheduled vacation)
        vacation_penalty = 0.0
        if self.is_on_vacation(person.person_id, mission_date):
            vacation_penalty = VACATION_PENALTY
        
        # Fairness score: balance hours worked / vacation days within role group
        fairness_score = self._calculate_fairness(state, person.role)
        
        # Preference score
        preference_score = self._calculate_preference_score(
            state, mission, already_assigned
        )
        
        # Unit cohesion: small bonus if same unit as already-assigned people
        unit_cohesion = 0.0
        if already_assigned:
            same_unit = sum(
                1 for pid in already_assigned
                if pid in self.people and self.people[pid].unit == person.unit
            )
            if same_unit == 0:
                unit_cohesion = 5.0  # Small penalty for mixing units
        
        # Role match: prefer primary role over secondary
        role_match = 0.0
        if person.role != role:
            role_match = 10.0  # Penalty for using secondary role
        
        total_score = vacation_penalty + fairness_score + preference_score + unit_cohesion + role_match
        
        return CandidateScore(
            person=person,
            total_score=total_score,
            vacation_penalty=vacation_penalty,
            fairness_score=fairness_score,
            preference_score=preference_score,
            unit_cohesion=unit_cohesion,
            role_match=role_match,
        )
    
    def _calculate_fairness(self, state: PersonState, role: str) -> float:
        """
        Calculate fairness score based on work/vacation ratio.
        
        Goal: Everyone in same role should have similar (hours worked / vacation days) ratio.
        Penalty if this person is below average (they can work more).
        """
        # Get all people with same primary role
        role_states = [s for s in self.states.values() if s.person.role == role]
        
        if len(role_states) <= 1:
            return 0.0
        
        # Calculate ratio for each person
        def get_ratio(s: PersonState) -> float:
            hours = s.total_hours()
            vacations = self.vacation_counts.get(s.person.person_id, 0)
            # Add 1 to avoid division by zero, and to make ratio meaningful
            return hours / (vacations + 1)
        
        ratios = [get_ratio(s) for s in role_states]
        avg_ratio = sum(ratios) / len(ratios)
        person_ratio = get_ratio(state)
        
        # Penalty if below average (they've had more rest, can work more)
        # Score is how far below average they are (negative = below average)
        return max(0, avg_ratio - person_ratio) * 10
    
    def _calculate_preference_score(
        self,
        state: PersonState,
        mission: Mission,
        already_assigned: Set[str],
    ) -> float:
        """Calculate preference-based score adjustments."""
        score = 0.0
        person_id = state.person.person_id
        mission_date = mission.start.date()
        
        for pref in self.preferences.get(person_id, []):
            if not pref.is_active(mission_date):
                continue
            
            weight = pref.priority_weight()
            
            if pref.type == "pair_with":
                # Bonus if partner is already assigned to same mission
                if pref.target in already_assigned:
                    score -= 20 * weight  # Negative = bonus
            
            elif pref.type == "avoid_person":
                # Penalty if person to avoid is assigned
                if pref.target in already_assigned:
                    score += 50 * weight
            
            elif pref.type == "prefer_mission":
                # Bonus if mission name matches
                if pref.target.lower() in mission.name.lower():
                    score -= 15 * weight
            
            elif pref.type == "avoid_mission":
                # Penalty if mission name matches
                if pref.target.lower() in mission.name.lower():
                    score += 30 * weight
            
            elif pref.type == "prefer_weekend":
                # Bonus if mission is on weekend
                if mission_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    score -= 10 * weight
            
            elif pref.type == "prefer_weekday":
                # Bonus if mission is on weekday
                if mission_date.weekday() < 5:
                    score -= 10 * weight
        
        return score
    
    def assign_to_mission(self, mission: Mission, role: str, person_id: str) -> None:
        """
        Assign a person to a mission role.
        Updates both the mission and internal state.
        """
        mission.assign_person(role, person_id)
        if person_id in self.states:
            state = self.states[person_id]
            if not state.is_assigned_to(mission):
                state.missions_assigned.append(mission)
    
    def get_unfilled_slots(self, missions: Sequence[Mission]) -> List[Tuple[Mission, str, int]]:
        """
        Get all unfilled slots across missions.
        
        Returns:
            List of (mission, role, remaining_count) tuples
        """
        slots = []
        for mission in missions:
            for role, remaining in mission.unfilled_roles().items():
                slots.append((mission, role, remaining))
        return slots


def suggest_vacations(
    people: Sequence[Person],
    vacations: Sequence[Vacation],
    missions: Sequence[Mission],
    campaign: Campaign,
    target_date: dt.date,
    days: int = 1,
) -> List[Tuple[Person, float, str]]:
    """
    Suggest people who can go on vacation.
    
    Args:
        people: All people
        vacations: Existing vacations
        missions: All missions
        campaign: Campaign metadata
        target_date: Start date for vacation
        days: Number of vacation days
    
    Returns:
        List of (person, score, reason) tuples, sorted by score (lower = better candidate)
    """
    suggestions: List[Tuple[Person, float, str]] = []
    
    # Count current on-site staff per role for the target dates
    vacation_dates = [target_date + dt.timedelta(days=i) for i in range(days)]
    vacation_set = {(v.person_id, v.date) for v in vacations}
    
    # Get mission assignments for target dates
    missions_in_range = [
        m for m in missions
        if any(m.start.date() == d for d in vacation_dates)
    ]
    
    for person in people:
        reasons = []
        score = 0.0
        
        # Check capacity: would sending this person home violate on_duty_estimates?
        role = person.role
        min_required = campaign.on_duty_estimates.get(role, 0)
        
        # Count others with same role who are NOT on vacation for these dates
        on_site_count = 0
        for p in people:
            if p.role == role and p.person_id != person.person_id:
                on_vacation_any_day = any(
                    (p.person_id, d) in vacation_set for d in vacation_dates
                )
                if not on_vacation_any_day:
                    on_site_count += 1
        
        if on_site_count < min_required:
            score += 1000  # Cannot send home - would be understaffed
            reasons.append(f"would leave only {on_site_count}/{min_required} {role}s")
        
        # Check if assigned to missions on these dates
        for mission in missions_in_range:
            if person.person_id in mission.all_assigned_people():
                score += 500
                reasons.append(f"assigned to {mission.name}")
        
        # Check if already on vacation
        already_on_vacation = any(
            (person.person_id, d) in vacation_set for d in vacation_dates
        )
        if already_on_vacation:
            score += 2000
            reasons.append("already on vacation")
        
        # Fairness: prefer those who have worked more / had fewer vacations
        person_vacation_count = sum(
            1 for v in vacations if v.person_id == person.person_id
        )
        # Lower vacation count = should go on vacation = lower score
        score += person_vacation_count * 5
        
        # TODO: Add preference scoring for prefer_vacation_date, prefer_weekend, etc.
        
        reason = "; ".join(reasons) if reasons else "available"
        suggestions.append((person, score, reason))
    
    # Sort by score (lower is better)
    suggestions.sort(key=lambda x: (x[1], x[0].person_id))
    return suggestions
