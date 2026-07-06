"""Repository discovery: scan a project tree into a ProjectProfile, then draft
a CastingPlan from it.

Modules:
  profile.py — the ProjectProfile type, sanitization boundary, and rendering.
  scanner.py — scan(root) -> ProjectProfile. Pure detection, no policy.
  advisor.py — propose_plan(...) -> CastingPlan. Pure policy, no I/O.
"""
