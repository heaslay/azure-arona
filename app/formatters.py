import re

_B_TAG_RE = re.compile(r"<b:([^>]+)>")
_C_TAG_RE = re.compile(r"<c:([^>]+)>")
_D_TAG_RE = re.compile(r"<d:([^>]+)>")
_PARAM_RE = re.compile(r"<\?(\d+)>")

def _strip_schale_markup(s: str) -> str:
    if not s:
        return ""
    s = _B_TAG_RE.sub(r"\1", s)                         # <b:ATK> -> ATK
    s = _C_TAG_RE.sub(r"\1", s)                         # <c:Fear> -> Fear
    s = _D_TAG_RE.sub(r"\1", s)                         # <d:Poison> -> Poison
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<b>\s*([^<]*?)\s*</b>", r"\1", s)      # <b>200</b> -> 200
    s = re.sub(r"</b>", "", s)                           # stray </b>
    s = re.sub(r"<b class='[^']*'>", "", s)              # <b class='ba-col-*'> -> strip
    s = re.sub(r"<kb:[^>]+>", "", s)                     # <kb:1> -> strip
    s = re.sub(r"<s:[^>]+>", "", s)                      # <s:...> -> strip
    s = re.sub(r"</?[^>]+>", "", s)                      # anything remaining
    return s

def _range_text(values: list[str]) -> str:
    """Convert a list like ['190%','219%','...','248%'] -> '(190% - 248%)'."""
    if not values:
        return ""
    if len(values) == 1:
        return f"({values[0]})"
    return f"({values[0]} - {values[-1]})"

def render_skill_line(student_name: str, skill_label: str, skill: dict) -> str:
    return f"{student_name}'s {skill_label} Skill: {render_skill_body(skill)}"


def render_skill_with_upgrade(
    student_name: str,
    base_label: str,
    base_skill: dict,
    upgrade_skill: dict | None = None,
    upgrade_prefix: str | None = None,   # NEW
) -> str:
    base = f"{student_name}'s {base_label} Skill: {render_skill_body(base_skill)}"

    if not upgrade_skill:
        return base

    upgrade_name = upgrade_skill.get("Name", "Upgrade")
    upgrade_desc = render_skill_desc_only(upgrade_skill)

    prefix = f" ({upgrade_prefix})" if upgrade_prefix else ""

    return (
        f"{base}\n\n"
        f"Upgrade{prefix}: {upgrade_name}\n"
        f"{upgrade_desc}"
    )

def render_skill_body(skill: dict, include_cost: bool = True) -> str:
    """Returns 'SkillName (Cost: X)\\nDescription' with params substituted and markup stripped."""
    skill_name = skill.get("Name", "Unknown Skill")
    desc = skill.get("Desc", "") or ""
    params = skill.get("Parameters", []) or []

    param_ranges = []
    for p in params:
        param_ranges.append(_range_text(p) if isinstance(p, list) else "")

    def repl(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(param_ranges) and param_ranges[idx]:
            return param_ranges[idx]
        return m.group(0)

    desc = _PARAM_RE.sub(repl, desc)
    desc = _strip_schale_markup(desc).strip()

    cost_txt = ""
    if include_cost:
        cost = skill.get("Cost")
        if isinstance(cost, list) and cost:
            cost_txt = f" (Cost: {cost[0]})"

    return f"{skill_name}{cost_txt}\n{desc}"

def render_skill_desc_only(skill: dict) -> str:
    """Description only (params substituted, markup stripped)."""
    desc = skill.get("Desc", "") or ""
    params = skill.get("Parameters", []) or []

    param_ranges = []
    for p in params:
        param_ranges.append(_range_text(p) if isinstance(p, list) else "")

    def repl(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(param_ranges) and param_ranges[idx]:
            return param_ranges[idx]
        return m.group(0)

    desc = _PARAM_RE.sub(repl, desc)
    return _strip_schale_markup(desc).strip()

def render_skill_header(skill_label: str, skill: dict) -> str:
    """e.g. 'EX - Q.E.D. (Cost: 3)'"""
    name = skill.get("Name", "Unknown")
    cost_txt = ""
    cost = skill.get("Cost")
    if isinstance(cost, list) and cost:
        cost_txt = f" (Cost: {cost[0]})"
    return f"{skill_label} - {name}{cost_txt}"

def _fmt_skill_table(skill: dict, ranks: int) -> str:
    params = skill.get("Parameters") or []
    desc = skill.get("Desc", "") or ""

    param_ranges = []
    for p in params:
        param_ranges.append(p if isinstance(p, list) else [p] * ranks)

    def repl(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(param_ranges):
            values = param_ranges[idx][:ranks]
            return f"({'/'.join(str(v) for v in values)})"
        return m.group(0)

    desc_out = _PARAM_RE.sub(repl, desc)
    desc_out = _strip_schale_markup(desc_out).strip()
    return desc_out

def _fmt_cost(skill: dict, ranks: int) -> str:
    cost = skill.get("Cost")
    if not isinstance(cost, list) or not cost:
        return ""
    cost_slice = cost[:ranks]
    if len(set(cost_slice)) == 1:
        return f" (Cost: {cost_slice[0]})"
    return f" (Cost: {'/'.join(str(c) for c in cost_slice)})"