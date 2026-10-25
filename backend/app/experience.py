"""Customer-facing summaries and practice-event rules. No external delivery here."""
import hashlib
import json

LIMITATION = ("Experimental model, trained on two local storm periods. Independent tests show large errors. "
              "Risk bands are planning indicators, not validated outage probabilities.")
STAGES = ["pre_storm", "outage_confirmed", "estimate_updated", "restored"]
TITLES = ["Before the storm", "Outage begins", "Estimate reviewed", "Power restored"]


def checklist(tips, completed=()):
    tasks, seen = [], set()
    for group in ("your_needs", "now", "if_out"):
        for text in tips[group]:
            key = hashlib.sha256(text.encode()).hexdigest()[:24]
            if key not in seen:
                tasks.append(dict(key=key, text=text, group=group, done=key in completed))
                seen.add(key)
    return tasks


def snapshot(status):
    est = status["restoration"]
    return dict(band=status["risk"]["band"],
                range={k: est[k] for k in ("p10", "p50", "p90")} if est else None,
                timeline=status["event"]["timeline"],
                all_restored_hour=status["event"]["all_restored_hour"])


def changes(before, after, old_access, new_access):
    changed = before != after
    old_range, new_range = before["range"], after["range"]
    delta = round(new_range["p50"] - old_range["p50"], 1) if old_range and new_range else None
    reason = (f"Repair-access difficulty changed from {old_access:g}x to {new_access:g}x. "
              "The same storm and crew assumptions were recalculated; this is a what-if experiment.")
    if not changed:
        reason += " No change in the displayed results for this home."
    return dict(before=before, after=after, changed=changed, typical_hours_delta=delta, reason=reason,
                next_action="Review your preparation checklist and the updated outage-duration range.")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def range_text(value):
    return f"{value['p10']:g}-{value['p90']:g} hours" if value else "no outage-duration range available"


def practice_message(stage, status, change=None):
    """Every message is clearly a practice event, never a utility confirmation."""
    home = status["event"]["timeline"]
    duration = range_text(snapshot(status)["range"])
    if stage == 0:
        text = f"Planning indicator: {status['risk']['band']}. Review your three preparation priorities."
    elif not home and stage in (1, 3):
        text = "Your home keeps power in this map outcome. Other simulation runs may differ."
    elif stage == 1:
        text = f"Your home's modeled outage has begun. Outage-duration range across runs: {duration}."
    elif stage == 2:
        text = (f"Earlier: {range_text(change['before']['range'])}. Updated: {duration}. "
                f"{change['reason']}")
        before, after = change['before']['range'], change['after']['range']
        if before and after:
            text += f" Typical modeled duration: {before['p50']:g} hours before; {after['p50']:g} hours now."
    else:
        text = "Your home is restored in this simulated outcome. Other areas may still be without power."
    return "[Practice simulation] " + text


def stage_allowed(current, requested):
    return requested == current + 1
