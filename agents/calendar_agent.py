from datetime import date, timedelta
from typing import List, Dict
import uuid as uuid_lib

from icalendar import Calendar, Event


PRIORITY_LABELS = {"High": "🔴 HIGH", "Medium": "🟡 MEDIUM", "Low": "🟢 LOW"}


def generate_ics(dept_name: str, tasks: List[Dict]) -> bytes:
    """
    Convert a list of tasks (with YYYY-MM-DD deadlines) into an iCal file.
    The returned bytes can be sent directly as a .ics download.
    """
    cal = Calendar()
    cal.add("prodid", f"-//Doc Intelligence//{dept_name}//EN")
    cal.add("version", "2.0")
    cal.add("calname", f"{dept_name} — Document Action Items")
    cal.add("color", "red")

    for task in tasks:
        deadline_str = (task.get("deadline") or "")[:10]  # take YYYY-MM-DD part
        try:
            deadline_date = date.fromisoformat(deadline_str)
        except ValueError:
            continue  # skip tasks with non-parseable deadlines

        event = Event()
        priority_label = PRIORITY_LABELS.get(task.get("priority", "Medium"), "")
        event.add("summary", f"{priority_label} {task['task']}")
        event.add("dtstart", deadline_date)
        event.add("dtend", deadline_date + timedelta(days=1))

        description_parts = [
            f"Priority: {task.get('priority', 'Medium')}",
            f"Responsible: {task.get('responsible') or 'Not specified'}",
            f"Source: {task.get('filename', '')}",
            f"Status: {task.get('status', 'pending')}",
        ]
        if task.get("notes"):
            description_parts.append(f"Notes: {task['notes']}")
        event.add("description", "\n".join(description_parts))

        # VALARM — reminder 3 days before deadline
        from icalendar import Alarm
        from datetime import timedelta as td
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Due in 3 days: {task['task']}")
        alarm.add("trigger", td(days=-3))
        event.add_component(alarm)

        event.add("uid", str(uuid_lib.uuid4()))
        cal.add_component(event)

    return cal.to_ical()
