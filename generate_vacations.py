import csv
import json
import random
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Any, Union
from dataclasses import dataclass, field
import sys
import os
import concurrent.futures

# --- Data Structures ---

@dataclass
class ShiftRequirement:
    role: str
    count: Union[int, List[int]]

@dataclass
class Person:
    id: str
    name: str
    roles: List[str]
    unit: Optional[str] = None
    unavailable_dates: List[str] = field(default_factory=list)
    preferences: List[Dict[str, str]] = field(default_factory=list)

@dataclass
class CampaignConfig:
    name: str
    start_date: datetime
    end_date: datetime
    requirements: List[ShiftRequirement]
    alat_end_date: Optional[datetime]
    retries: int
    boost: int = 0
    boost_dates: List[str] = field(default_factory=list)

@dataclass
class Shift:
    id: str
    date: str
    role: str
    person_id: str

# --- CSV Parsing & Data Loading ---

def parse_csv(file_path: str) -> List[Dict[str, str]]:
    with open(file_path, 'r', encoding='utf-8') as f:
        # Filter out comments
        lines = [line for line in f if not line.strip().startswith('#')]
        reader = csv.DictReader(lines)
        return list(reader)

def load_people(file_path: str) -> List[Person]:
    raw_rows = parse_csv(file_path)
    people = []

    for i, row in enumerate(raw_rows):
        # ID and Name
        pid = row.get('id') or f"person-{datetime.now().timestamp()}-{i}"
        name = row.get('name') or row.get('Name') or 'Unknown'
        
        # Parse Roles
        roles = []
        primary = row.get('role') or row.get('Role')
        if primary:
            roles.append(primary.strip())
            
        secondary_str = row.get('secondary_roles') or row.get('SecondaryRoles') or row.get('secondary roles')
        if secondary_str:
            for r in secondary_str.split(','):
                r = r.strip()
                if r and r not in roles:
                    roles.append(r)

        # Unit Parsing
        unit = row.get('unit') or row.get('Unit') or None
        if unit:
            unit = str(unit).strip()
        
        is_unit_123 = unit in ['1', '2', '3']

        # Logic Ported from csvParser.ts: csvToPeople
        
        # 1. Expand Samal
        if any(r.lower() == 'samal' for r in roles):
            if not any(r.lower() == 'officer' for r in roles): roles.append('officer')
            if not any(r.lower() == 'commander' for r in roles): roles.append('commander')
        
        # 2. Identify Types
        is_staff_role = any(r.lower() in ['commander', 'officer', 'samal'] for r in roles)
        
        # soldier_extra criteria: (soldier/medic/driver) AND !Staff AND Unit 1/2/3
        is_soldier_type = (
            any(r.lower() in ['soldier', 'medic', 'driver'] for r in roles)
            and not is_staff_role
            and is_unit_123
        )

        # 3. Add Extra Roles
        if is_staff_role:
            if 'staff_extra' not in roles: roles.append('staff_extra')
            if 'total_command' not in roles: roles.append('total_command')
            # ONLY primary commanders in field units can also do soldier duties
            is_primary_commander = any(r.lower() == 'commander' for r in roles)
            if is_primary_commander and is_unit_123:
                if 'soldier' not in roles: roles.append('soldier')
                if 'total_soldiers' not in roles: roles.append('total_soldiers')
                if 'soldier_extra' not in roles: roles.append('soldier_extra')
            
        if is_soldier_type:
            if 'soldier_extra' not in roles: roles.append('soldier_extra')
            if 'total_soldiers' not in roles: roles.append('total_soldiers')
            # Implicit soldier role for medic/drivers in field units
            if not any(r.lower() == 'soldier' for r in roles):
                roles.append('soldier')

        # 4. Final Cleanup: Remove fighter roles from non-field units
        final_roles = roles
        if not is_unit_123:
            final_roles = [r for r in roles if r.lower() not in ['soldier', 'medic', 'driver']]

        people.append(Person(
            id=pid,
            name=name,
            roles=final_roles,
            unit=unit
        ))
    
    return people

def load_preferences(file_path: str, people: List[Person]):
    if not os.path.exists(file_path):
        return
    
    raw_rows = parse_csv(file_path)
    people_map = {p.id: p for p in people}
    
    for row in raw_rows:
        pid = row.get('person_id') or row.get('personId')
        p_type = row.get('type')
        target = row.get('target')
        
        if pid and pid in people_map:
            if p_type == 'must_vacation_date' and target:
                if target not in people_map[pid].unavailable_dates:
                    people_map[pid].unavailable_dates.append(target)
            elif p_type in ['prefer_weekend', 'prefer_weekday']:
                people_map[pid].preferences.append({
                    'type': p_type,
                    'target': target
                })

def load_campaigns(file_path: str) -> List[CampaignConfig]:
    rows = parse_csv(file_path)
    if not rows:
        raise ValueError("Campaign CSV is empty")
    
    campaigns = []
    
    for row in rows:
        name = row.get('name') or 'unknown'
        start_str = row.get('start_date') or row.get('startDate')
        end_str = row.get('end_date') or row.get('endDate')
        alat_end_str = row.get('alat_end') or row.get('alatEnd')
        retries_str = row.get('retries') or '100'
        
        if not start_str or not end_str:
            print(f"Skipping campaign {name}: Missing dates")
            continue
            
        start_date = datetime.strptime(start_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_str, "%Y-%m-%d")
        
        alat_end_date = None
        if alat_end_str:
            alat_end_date = datetime.strptime(alat_end_str, "%Y-%m-%d")
        
        requirements = []
        
        # JSON Parsing for on_duty_estimates
        estimates_str = row.get('on_duty_estimates') or row.get('onDutyEstimates')
        if estimates_str:
            try:
                if estimates_str.startswith('"') and estimates_str.endswith('"'):
                    estimates_str = estimates_str[1:-1].replace('""', '"')
                
                estimates = json.loads(estimates_str)
                for role, count in estimates.items():
                    requirements.append(ShiftRequirement(role=role.strip(), count=count))
            except Exception as e:
                print(f"Error parsing JSON estimates for {name}: {e}")
                continue

        boost_str = row.get('boost') or '0'
        try:
            boost = int(boost_str)
        except ValueError:
            boost = 0

        boost_dates_str = row.get('boost_dates') or ''
        boost_dates = [d.strip() for d in boost_dates_str.split(',') if d.strip()]
                
        try:
            retries = int(retries_str)
        except ValueError:
            retries = 100
            
        campaigns.append(CampaignConfig(
            name=name,
            start_date=start_date,
            end_date=end_date,
            requirements=requirements,
            alat_end_date=alat_end_date,
            retries=retries,
            boost=boost,
            boost_dates=boost_dates
        ))

    return campaigns

# --- Scheduler Algorithm ---

def generate_schedule(
    people: List[Person],
    requirements: List[ShiftRequirement],
    start_date: datetime,
    end_date: datetime,
    alat_end_date: Optional[datetime],
    boost: int = 0,
    boost_dates: List[str] = [],
    max_tries: int = 100
) -> List[Shift]:
    
    # print(f"Simulating {max_tries} randomized schedules...")
    
    successful_attempts = []
    
    days_list = []
    curr = start_date
    while curr <= end_date:
        days_list.append(curr)
        curr += timedelta(days=1)

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = [
            executor.submit(attempt_generate, people, requirements, days_list, alat_end_date, boost, boost_dates) 
            for _ in range(max_tries)
        ]
        
        for future in concurrent.futures.as_completed(futures):
            try:
                shifts, success = future.result()
                if success:
                    field_people = [p for p in people if p.unit in ['1', '2', '3']]
                    if field_people:
                        counts = []
                        for p in field_people:
                            c = len([s for s in shifts if s.person_id == p.id])
                            counts.append(c)
                        spread = max(counts) - min(counts)
                        successful_attempts.append({'shifts': shifts, 'spread': spread})
                    else:
                        successful_attempts.append({'shifts': shifts, 'spread': 0})
            except Exception as e:
                # print(f"Simulation failed with error: {e}")
                pass
    
    if successful_attempts:
        successful_attempts.sort(key=lambda x: x['spread'])
        best = successful_attempts[0]
        # print(f"Found {len(successful_attempts)} valid schedules. Picking best (Spread: {best['spread']})")
        return best['shifts']
    
    # print("Critical: No valid schedule found.")
    return []

def attempt_generate(
    people: List[Person],
    requirements: List[ShiftRequirement],
    days: List[datetime],
    alat_end_date: Optional[datetime],
    boost: int = 0,
    boost_dates: List[str] = [],
    debug: bool = False
) -> tuple[List[Shift], bool]:
    
    shifts = []
    
    shift_counts = {p.id: 0 for p in people}
    last_shift_date = {p.id: None for p in people} 
    work_streaks = {p.id: 0 for p in people}
    role_counts = {p.id: {} for p in people}

    for day in days:
        day_str = day.strftime("%Y-%m-%d")
        yesterday = day - timedelta(days=1)
        tomorrow = day + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        is_saturday = (day.weekday() == 5)
        
        available = [p for p in people if day_str not in p.unavailable_dates]
        
        # Check ALAT Period (or last 2 days)
        is_alat = False
        if alat_end_date and day <= alat_end_date:
            is_alat = True
            
        assigned_today = set()
        assigned_units_today = set()

        # If ALAT: Everyone available works
        if is_alat:
            for person in available:
                # Assign to their specific primary role or default
                # We need a role name for the shift. 
                # Let's derive it from their roles. 
                # Preference: Commander/Officer > Specialist > Soldier > Extra
                
                r_name = 'on_duty'
                # Simple heuristic for role name in Alat
                for r in person.roles:
                    if r.lower() in ['commander', 'officer', 'medic', 'driver', 'mp', 'rsp']:
                        r_name = r
                        break
                if r_name == 'on_duty' and 'soldier' in person.roles:
                    r_name = 'soldier'
                elif r_name == 'on_duty' and person.roles:
                     r_name = person.roles[0]

                # Create shift directly, skipping scoring
                s = Shift(
                    id=f"{day_str}-{r_name}-alat-{person.id}",
                    date=day_str,
                    role=r_name,
                    person_id=person.id
                )
                shifts.append(s)
                
                shift_counts[person.id] += 1
                last_shift_date[person.id] = day
                work_streaks[person.id] += 1
                if r_name not in role_counts[person.id]:
                    role_counts[person.id][r_name] = 0
                role_counts[person.id][r_name] += 1
            
            # Continue to next day (skip normal generation)
            continue

        # Post-Alat Rotation logic: Track who has been home
        is_post_alat_week = False
        if alat_end_date and (alat_end_date < day <= alat_end_date + timedelta(days=7)):
            is_post_alat_week = True
        
        # Check last day of campaign: Copy shifts from yesterday
        # This creates a 2-day block (yesterday + today matched)
        if day == days[-1]:
            yesterday_shifts = [s for s in shifts if s.date == yesterday.strftime("%Y-%m-%d")]
            for prev_s in yesterday_shifts:
                s = Shift(
                    id=f"{day_str}-{prev_s.role}-copy-{prev_s.person_id}",
                    date=day_str,
                    role=prev_s.role,
                    person_id=prev_s.person_id
                )
                shifts.append(s)
                
                # Update state
                shift_counts[prev_s.person_id] += 1
                last_shift_date[prev_s.person_id] = day
                work_streaks[prev_s.person_id] += 1
                if prev_s.role not in role_counts[prev_s.person_id]:
                    role_counts[prev_s.person_id][prev_s.role] = 0
                role_counts[prev_s.person_id][prev_s.role] += 1
            continue
        
        # --- Normal Generation Logic ---
        
        daily_reqs = []
        for req in requirements:
            qualified_count = len([p for p in people if req.role in p.roles])
            
            # Determine count for this specific day
            needed = 0
            if isinstance(req.count, int):
                needed = req.count
            elif isinstance(req.count, list):
                # day.weekday(): Mon=0, Sun=6
                idx = day.weekday()
                if 0 <= idx < len(req.count):
                    needed = req.count[idx]
                else:
                    needed = req.count[0] # Fallback
            
            if req.role == 'total_soldiers' and boost > 0 and day_str in boost_dates:
                needed += boost

            daily_reqs.append({
                'role': req.role,
                'total': needed,
                'remaining': needed,
                'rarity': qualified_count
            })
        
        daily_reqs.sort(key=lambda x: x['rarity'])
        
        total_needed = sum(r['remaining'] for r in daily_reqs)
        
        for p in people:
            last = last_shift_date[p.id]
            if not last or (last.date() if isinstance(last, datetime) else last) != yesterday.date():
                work_streaks[p.id] = 0

        while total_needed > 0:
            best_choice = None 
            
            for req in daily_reqs:
                if req['remaining'] <= 0:
                    continue
                
                for person in available:
                    if person.id in assigned_today:
                        continue
                    
                    if req['role'] not in person.roles:
                        continue
                    
                    current_total = shift_counts[person.id]
                    streak = work_streaks[person.id]
                    last_date = last_shift_date[person.id]
                    worked_yesterday = False
                    days_since = 999
                    
                    if last_date:
                        diff = day - last_date
                        days_since = diff.days
                        if days_since == 1:
                            worked_yesterday = True
                    
                    # Sandwich Constraint: Don't schedule for 1 day if they were just on vacation and have vacation tomorrow
                    if not worked_yesterday and tomorrow_str in person.unavailable_dates:
                        continue
                    
                    # 1. High-order workload penalty (Minimize differences)
                    # Using an 8th power penalty still forces balance, but allows preferences to compete.
                    projected_total = current_total
                    if len(days) >= 2 and day == days[-2]:
                         projected_total += 1
                    score = (projected_total ** 8) * 1000000
                    
                    # 2. Unavailability Bonus (Prioritize people who have fewer available days)
                    # This helps people with many requests reach the same total shift count as others.
                    score -= len(person.unavailable_dates) * 5000000
                    
                    # 2. Minimal Jitter
                    score += random.random() * 1000

                    # 3. Preferences (prefer_weekend, prefer_weekday)
                    for pref in person.preferences:
                        if pref['type'] == 'prefer_weekend':
                            # If they prefer weekends (Fri-Sat) for vacation, they should NOT work on Saturday
                            if is_saturday:
                                score += 5000000  # Penalty for working
                            else:
                                score -= 100000   # Slight bonus for weekdays
                        elif pref['type'] == 'prefer_weekday':
                            # If they prefer weekdays for vacation, they SHOULD work on Saturday
                            if is_saturday:
                                score -= 5000000  # Bonus for working
                            else:
                                score += 100000   # Slight penalty for weekdays
                    
                    if is_saturday:
                        if worked_yesterday:
                            score -= 10000000 
                        else:
                            score += 10000000 
                    
                    if not worked_yesterday:
                        if days_since < 3: score += 500000  # Softened rest penalty
                        if days_since == 2: score += 2000000 # Penalize single day vacation
                        if days_since < 2: score += 1000000
                    
                    if not is_saturday and streak > 0 and streak < 3:
                        score -= 150000

                    # 4. Post-ALAT Rotation Penalty
                    # Ensure everyone goes home at least once in the week following ALAT.
                    # We penalize picking someone who hasn't had a day off yet in this week.
                    if is_post_alat_week:
                        # Count days off since alat_end_date
                        days_since_alat = (day - alat_end_date).days # 1 to 7
                        # Check how many shifts in this period 
                        period_shifts = [s for s in shifts if s.person_id == person.id and alat_end_date < datetime.strptime(s.date, "%Y-%m-%d") < day]
                        if len(period_shifts) == days_since_alat - 1 and days_since_alat > 1:
                            # They have worked every day so far! Give penalty.
                            # Increasing penalty as we get closer to day 7.
                            score += days_since_alat * 3000000
                    
                    p_role_count = role_counts[person.id].get(req['role'], 0)
                    score += p_role_count * 100
                    
                    is_specialist = req['role'].lower() in ['medic', 'driver']
                    is_staff_unit = (person.unit or '').lower() == 'staff'
                    
                    if not is_specialist and not is_staff_unit and person.unit and person.unit in assigned_units_today:
                        score -= 500000
                    
                    if best_choice is None or score < best_choice['score']:
                        best_choice = {
                            'person': person,
                            'role': req['role'],
                            'score': score,
                            'req_obj': req
                        }
            
            if not best_choice:
                if debug:
                    print(f"  [Fail] Could not find candidate for any role on {day_str}. Remaining needs: {[(r['role'], r['remaining']) for r in daily_reqs if r['remaining'] > 0]}")
                break
                
            p = best_choice['person']
            r_name = best_choice['role']
            req_obj = best_choice['req_obj']
            
            s = Shift(
                id=f"{day_str}-{r_name}-{req_obj['total'] - req_obj['remaining']}-{p.id}",
                date=day_str,
                role=r_name,
                person_id=p.id
            )
            shifts.append(s)
            
            shift_counts[p.id] += 1
            last_shift_date[p.id] = day
            assigned_today.add(p.id)
            if p.unit:
                assigned_units_today.add(p.unit)
            work_streaks[p.id] += 1
            
            if r_name not in role_counts[p.id]:
                role_counts[p.id][r_name] = 0
            role_counts[p.id][r_name] += 1
            
            req_obj['remaining'] -= 1
            total_needed -= 1
            
    dates_in_period = [d.strftime("%Y-%m-%d") for d in days]
    last_two_days = [d.strftime("%Y-%m-%d") for d in days[-2:]]
    
    for d_str in dates_in_period:
        if d_str in last_two_days:
            continue
            
        d_obj = datetime.strptime(d_str, "%Y-%m-%d")
        if alat_end_date and d_obj <= alat_end_date:
            continue
            

        day_shifts = [s for s in shifts if s.date == d_str]
        for req in requirements:
            target_count = req.count
            if req.role == 'total_soldiers' and boost > 0 and d_str in boost_dates:
                target_count += boost
                
            count = len([s for s in day_shifts if s.role == req.role])
            if count < target_count:
                if debug:
                    print(f"  [Fail] {d_str}: {req.role} {count}/{target_count}")
                return shifts, False 
                
    return shifts, True

def fill_extra_shifts(
    initial_shifts: List[Shift], 
    people: List[Person], 
    days_list: List[datetime], 
    alat_end_date: Optional[datetime],
    target_min_vacation: int = 15,
    max_boost_param: int = 0
) -> List[Shift]:
    
    if max_boost_param <= 0:
        return initial_shifts

    print(f"\n--- Post-Processing: Filling Extra Shifts (Max Boost: {max_boost_param}) ---")
    
    # helper
    def get_assignment_map(current_shifts):
        m = {d.strftime("%Y-%m-%d"): set() for d in days_list}
        for s in current_shifts:
            if s.date in m:
                m[s.date].add(s.person_id)
        return m

    # Calculate current vacation days
    total_days = len(days_list)
    people_vacation = {}
    for p in people:
        worked = len([s for s in initial_shifts if s.person_id == p.id])
        people_vacation[p.id] = total_days - worked

    # Identify people with "slack" (vacation > target)
    slack_people = [p for p in people if people_vacation[p.id] > target_min_vacation]
    # Filter only relevant unit soldiers
    slack_people = [p for p in slack_people if 'total_soldiers' in p.roles]
    
    # Sort by who has the MOST vacation (least work)
    slack_people.sort(key=lambda p: people_vacation[p.id], reverse=True)
    
    print(f"Found {len(slack_people)} soldiers with > {target_min_vacation} vacation days to utilize.")
    
    current_shifts = list(initial_shifts)
    assignment_map = get_assignment_map(current_shifts)
    
    # Last shift date cache for validity checks
    last_shift_date = {p.id: None for p in people}
    # Pre-populate last dates from initial schedule (must scan chronologically)
    sorted_shifts = sorted(initial_shifts, key=lambda s: s.date)
    for s in sorted_shifts:
        d = datetime.strptime(s.date, "%Y-%m-%d")
        # simplistic: just overwrite, we only need to know "most recent" relative to where we insert
        # Actually, for insertion logic we need to be careful. 
        # Let's just do checks dynamically per day.
        pass

    # Better approach: Iterate days, try to fit slack people
    dates_str = [d.strftime("%Y-%m-%d") for d in days_list]
    last_two = dates_str[-2:]
    
    boosted_days = {}

    # Better approach: Iterate days, try to fit slack people
    dates_str = [d.strftime("%Y-%m-%d") for d in days_list]
    last_two = dates_str[-2:]
    
    boosted_days = {}

    # NEW LOGIC: Any 2 days per week, target +4
    
    # helper to check ability to add
    def can_add(p, d_str, d_obj, current_map):
        if d_str in p.unavailable_dates: return False
        if d_str in current_map and p.id in current_map[d_str]: return False
        
        yesterday_str = (d_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow_str = (d_obj + timedelta(days=1)).strftime("%Y-%m-%d")
        if yesterday_str in current_map and p.id in current_map[yesterday_str]: return False
        if tomorrow_str in current_map and p.id in current_map[tomorrow_str]: return False
        return True

    # Group days by week (Sunday to Saturday)
    weeks = {}
    for d_obj in days_list:
        d_str = d_obj.strftime("%Y-%m-%d")
        if alat_end_date and d_obj <= alat_end_date: continue
        if d_str in last_two: continue
        
        # ISO week starts Monday, let's use standard ISO week number
        wk = d_obj.isocalendar()[1]
        if wk not in weeks: weeks[wk] = []
        weeks[wk].append(d_obj)
        
    # Process each week
    for wk, week_days in weeks.items():
        # Find best 2 days in this week to boost
        day_potentials = []
        
        for d_obj in week_days:
            d_str = d_obj.strftime("%Y-%m-%d")
            potential = 0
            for p in slack_people:
                if people_vacation[p.id] <= target_min_vacation: continue
                if can_add(p, d_str, d_obj, assignment_map):
                    potential += 1
            day_potentials.append({'date': d_obj, 'potential': potential})
            
        # Sort by potential descending
        day_potentials.sort(key=lambda x: x['potential'], reverse=True)
        
        # Pick top 2
        target_days = [x['date'] for x in day_potentials[:2]]
        
        # Apply Boost to target days
        for d_obj in target_days:
            d_str = d_obj.strftime("%Y-%m-%d")
            added_count = 0
            # Target slightly less than max in burst to allow topping up? 
            # Or target max directly. Let's target max directly.
            target_boost = max_boost_param
            
            potential_shifts = []
            potential_people = []

            for p in slack_people:
                if added_count >= target_boost: break
                if people_vacation[p.id] <= target_min_vacation: continue
                
                if can_add(p, d_str, d_obj, assignment_map):
                    # Assign
                    new_shift = Shift(
                        id=f"{d_str}-soldier_extra_fill_burst-{p.id}",
                        date=d_str,
                        role='soldier_extra',
                        person_id=p.id
                    )
                    potential_shifts.append(new_shift)
                    potential_people.append(p)
                    added_count += 1
            
            # Commit only if >= 3
            if added_count >= 3:
                 current_shifts.extend(potential_shifts)
                 for p in potential_people:
                     assignment_map[d_str].add(p.id)
                     people_vacation[p.id] -= 1
                 boosted_days[d_str] = added_count

    # 2. General Pass (Remaining Slack)
    for d_obj in days_list:
        d_str = d_obj.strftime("%Y-%m-%d")
        
        # Skip ALAT & Last 2
        if alat_end_date and d_obj <= alat_end_date: continue
        if d_str in last_two: continue
        
        
        current_added = boosted_days.get(d_str, 0)
        max_boost = max_boost_param
        if current_added >= max_boost:
            continue
            
        added_count = 0
        potential_shifts = []
        potential_people = []
        
        for p in slack_people:
            if added_count >= (max_boost - current_added): break
            if people_vacation[p.id] <= target_min_vacation: continue
            
            if can_add(p, d_str, d_obj, assignment_map):
                new_shift = Shift(
                    id=f"{d_str}-soldier_extra_fill-{p.id}",
                    date=d_str,
                    role='soldier_extra',
                    person_id=p.id
                )
                potential_shifts.append(new_shift)
                potential_people.append(p)
                added_count += 1
            
        # Commit only if total boost (existing + new) is >= 3
        # If we already have a boost (from burst pass), we might be adding just +1 to reach max 5, that is fine.
        # But if the day has 0 boost so far, we must add at least 3.
        
        total_boost = current_added + added_count
        if total_boost >= 3 and added_count > 0:
             current_shifts.extend(potential_shifts)
             for i, p in enumerate(potential_people):
                 assignment_map[d_str].add(p.id)
                 people_vacation[p.id] -= 1
             boosted_days[d_str] = total_boost
            


    print(f"Boosted {len(boosted_days)} days with extra soldiers.")
    for d, count in boosted_days.items():
        print(f"  {d}: +{count} soldiers")
        
    return current_shifts

# --- Main Execution ---

def main():
    # Use the current directory as the base since the script is in the app root
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, 'data', 'test')
    
    people_path = os.path.join(data_dir, 'people.csv')
    prefs_path = os.path.join(data_dir, 'preferences.csv')
    campaign_path = os.path.join(data_dir, 'planning_campaign.csv')
    
    # We'll save the output in data/test as well, to keep it consistent
    output_dir = data_dir
    
    print(f"Reading files from {data_dir}...")
    if not os.path.exists(people_path):
        print(f"Error: Could not find {people_path}")
        return
    
    people = load_people(people_path)
    load_preferences(prefs_path, people)
    campaigns = load_campaigns(campaign_path)
    
    print(f"Loaded {len(people)} people.")
    print(f"Found {len(campaigns)} campaigns to process.")
    
    campaign_summaries = []

    for campaign in campaigns:
        print(f"\n==========================================")
        print(f"Running Campaign: {campaign.name}")
        print(f"Dates: {campaign.start_date.date()} to {campaign.end_date.date()}")
        print(f"Retries: {campaign.retries}")
        print(f"==========================================")

        # Generate days list
        d_list = []
        curr = campaign.start_date
        while curr <= campaign.end_date:
            d_list.append(curr)
            curr += timedelta(days=1)

        # Filter out external roles (filled by external personnel)
        internal_requirements = [req for req in campaign.requirements if not req.role.startswith('external_')]

        schedule = generate_schedule(people, internal_requirements, campaign.start_date, campaign.end_date, campaign.alat_end_date, campaign.boost, campaign.boost_dates, campaign.retries)
        
        if not schedule:
            print(f"!!! Failed to generate schedule for {campaign.name} !!!")
            # Run one attempt with debug info
            print("Running a debug attempt...")
            attempt_generate(people, internal_requirements, d_list, campaign.alat_end_date, campaign.boost, campaign.boost_dates, debug=True)
            continue
            
            
        # Optional: we can still run fill_extra_shifts if we want to add even more people where possible
        # but the core boost is now handled in generate_schedule.
        # Let's keep it but maybe set boost to 0 here if it's already handled, 
        # OR allow it to add even more. The user said "force it", so it's already forced.
        # Let's disable the extra fill to avoid over-working if boost is high.
        # schedule = fill_extra_shifts(schedule, people, d_list, campaign.alat_end_date, target_min_vacation=15, max_boost_param=campaign.boost)
        
        # --- Stats Calculation ---
        total_campaign_days = (campaign.end_date - campaign.start_date).days + 1
        soldier_data = [] # List of (name, vac_days)
        commander_data = []

        for p in people:
            shifts_worked = len([s for s in schedule if s.person_id == p.id])
            vacation_days = total_campaign_days - shifts_worked
            
            if p.unit in ['1', '2', '3']:
                role = p.roles[0].lower() if p.roles else ''
                if 'commander' in role or 'officer' in role or 'samal' in role:
                    commander_data.append((p.name, vacation_days))
                else:
                    soldier_data.append((p.name, vacation_days))
        
        def get_avg(data):
            if not data: return 0
            return sum(d[1] for d in data) / len(data)

        def get_min_max_people(data):
            if not data: return 0, 0, [], []
            min_v = min(d[1] for d in data)
            max_v = max(d[1] for d in data)
            least_v_people = [d[0] for d in data if d[1] == min_v]
            most_v_people = [d[0] for d in data if d[1] == max_v]
            return min_v, max_v, least_v_people, most_v_people

        s_min, s_max, s_least_names, s_most_names = get_min_max_people(soldier_data)
        c_min, c_max, c_least_names, c_most_names = get_min_max_people(commander_data)

        summary = {
            'name': campaign.name,
            'total_days': total_campaign_days,
            'soldier_avg_vac': get_avg(soldier_data),
            'soldier_min_vac': s_min,
            'soldier_max_vac': s_max,
            'soldier_least_names': s_least_names,
            'soldier_most_names': s_most_names,
            'soldier_count': len(soldier_data),
            'commander_avg_vac': get_avg(commander_data),
            'commander_min_vac': c_min,
            'commander_max_vac': c_max,
            'commander_least_names': c_least_names,
            'commander_most_names': c_most_names,
            'commander_count': len(commander_data),
        }
        campaign_summaries.append(summary)

        # Output CSV for this campaign
        if campaign.name == 'test':
            output_filename = "vacations.csv"
        else:
            output_filename = f"vacations_{campaign.name}.csv"
        output_path = os.path.join(output_dir, output_filename)
        
        dates_full = []
        c = campaign.start_date
        while c <= campaign.end_date:
            dates_full.append(c.strftime("%Y-%m-%d"))
            c += timedelta(days=1)

        csv_lines = ['person_id,date,description']
        for d_str in dates_full:
            workers_today = {s.person_id for s in schedule if s.date == d_str}
            for p in people:
                if p.id not in workers_today:
                    desc = 'vacation'
                    if p.unit:
                        desc = f"unit_{p.unit}_rotation"
                    csv_lines.append(f"{p.id},{d_str},{desc}")
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            f.write('\n'.join(csv_lines))
        
        print(f"Created {output_filename}")


    # --- Final Summary Report ---
    print("\n\n######################################################")
    print(f"{'Campaign Name':<15} | {'Soldier (Vac/Work) Avg':<25} | {'Min/Max Vac (People)':<40}")
    print("-" * 85)
    
    for s in campaign_summaries:
        s_vac_work = f"{s['soldier_avg_vac']:.1f}d / {s['total_days'] - s['soldier_avg_vac']:.1f}d"
        s_min_str = f"{s['soldier_min_vac']}d ({', '.join(s['soldier_least_names'][:2])}{'...' if len(s['soldier_least_names']) > 2 else ''})"
        s_max_str = f"{s['soldier_max_vac']}d ({', '.join(s['soldier_most_names'][:2])}{'...' if len(s['soldier_most_names']) > 2 else ''})"
        
        print(f"{s['name'] + ' (Soldier)':<15} | {s_vac_work:<25} | Min: {s_min_str}")
        print(f"{'':<15} | {'':<25} | Max: {s_max_str}")
        
        c_vac_work = f"{s['commander_avg_vac']:.1f}d / {s['total_days'] - s['commander_avg_vac']:.1f}d"
        c_min_str = f"{s['commander_min_vac']}d ({', '.join(s['commander_least_names'][:2])}{'...' if len(s['commander_least_names']) > 2 else ''})"
        c_max_str = f"{s['commander_max_vac']}d ({', '.join(s['commander_most_names'][:2])}{'...' if len(s['commander_most_names']) > 2 else ''})"
        
        print(f"{s['name'] + ' (Command)':<15} | {c_vac_work:<25} | Min: {c_min_str}")
        print(f"{'':<15} | {'':<25} | Max: {c_max_str}")
        print("-" * 85)
        
    print("######################################################\n")

if __name__ == "__main__":
    main()

