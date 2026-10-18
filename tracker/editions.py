"""Fixed daily editions. Missing evidence never becomes a fresh, eligible opening."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .domain import classify, EARLY, SENIOR, fingerprint, plain, experience_requirements, sponsorship_blocks
from .profile import PROFILE

POLICY_VERSION = 2
CAP = PROFILE.daily_cap


def timestamp(value):
    """Require an actual instant; a calendar date or naive time cannot prove 24h."""
    if not isinstance(value, str) or 'T' not in value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError,OverflowError):
        return None


def cutoff_for(current, hour, timezone_name, minute=0):
    local = current.astimezone(ZoneInfo(timezone_name))
    cutoff = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < cutoff:
        cutoff -= timedelta(days=1)
    return cutoff.astimezone(timezone.utc)


def next_cutoff(current, hour, timezone_name, minute=0):
    local = current.astimezone(ZoneInfo(timezone_name))
    cutoff = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local >= cutoff:
        cutoff += timedelta(days=1)
    return cutoff.astimezone(timezone.utc)


def identity(job):
    # The same role/location on two boards, or a changed URL, must not make a new edition.
    normalize = lambda x: re.sub(r'[^a-z0-9]', '', (x or '').lower())
    return fingerprint('|'.join(normalize(job.get(k)) for k in ('company', 'title', 'location')))


def eligibility(job, start_date='2027-06-01', strict_cohort=True):
    title, description = job['title'], plain(job.get('description', ''))
    result = classify(title, description, job.get('location', ''), job.get('country', ''), start_date)
    reasons = list(result['scope_reasons']) if not result['in_scope'] else []
    evidence = []
    if not job.get('verified_at') or not description.strip():
        reasons.append('Full employer posting has not been verified')
    if any(sponsorship_blocks(job.get('location',''),job.get('country',''),title,value) for value in (result['sponsorship'],job.get('sponsorship'))):
        reasons.append('Work authorization or future sponsorship is restricted or conflicting')
    if SENIOR.search(title):
        reasons.append('Senior title cannot qualify through an Analyst I or Associate suffix')
    if re.search(r'\b(?:grad\w*|entry[ -]level|early[ -]career)\b[^\n]{0,80}\b202[89]\b|\b202[89]\b[^\n]{0,80}\bgrad\w*\b', title, re.I) and not re.search(r'\b2027\b', title):
        reasons.append('Explicit graduate cohort is later than 2027')
    if re.search(r'\b(?:internship|intern|co-op|part[ -]?time|contractor|contract|temporary)\b', title, re.I) or re.sub('[^a-z]','',job.get('employment_type', '').lower()) in {'intern', 'internship', 'parttime', 'contract', 'contractor', 'temporary','fixedterm'}:
        reasons.append('Not a permanent full-time entry-level opening')
    if re.search(r'\b(?:contract|temporary|part[ -]?time)\s+(?:role|position|opening|opportunity)\b',description,re.I):
        reasons.append('Posting describes a contract, temporary or part-time position')
    if re.search(r'\b(?:senior|mid[ -]?(?:level|senior)|intermediate|experienced|expert|executive|manager)\b',job.get('employer_level',''),re.I):
        reasons.append('Employer labels this above entry level')
    if re.search(r'\b(?:ph\.?d\.?|doctoral|postdoc|masters?[- ]only)\b', title, re.I):
        reasons.append('Role targets an advanced degree rather than a bachelor graduate')
    for sentence in re.split(r'[;\n]|(?<=[.!?])\s+', description):
        if (re.search(r"(?:\b(?:require[sd]?|must (?:have|hold|possess))\b[^.;]{0,60}\b(?:master'?s?|ph\.?d\.?|doctoral)|\b(?:master'?s?|ph\.?d\.?|doctoral)\b[^.;]{0,50}\b(?:required|only)\b)",sentence,re.I)
            and not re.search(r"\b(?:bachelor'?s?|undergraduate|B\.?S\.?)\b",sentence,re.I)):
            reasons.append('Required advanced degree has no stated bachelor-degree path')

    requirements = experience_requirements(description)
    if any(years > PROFILE.max_experience for years, _ in requirements):
        reasons.append(f'Posting requires more than {PROFILE.max_experience} years of experience')
    evidence.extend(sentence for years,sentence in requirements if years <= PROFILE.max_experience)
    explicit = bool(EARLY.search(title))
    if explicit:
        evidence.append(title)
    # Unknown experience remains discoverable, with uncertainty exposed. Never
    # turn an absence of requirements into a claim of zero-experience eligibility.
    warnings=[]
    if not requirements and not explicit:
        warnings.append('Experience requirement is not stated; verify entry-level suitability')
    if any(years > 0 for years,_ in requirements):
        warnings.append('Prior experience is requested; assess transferable experience before applying')
    if result['sponsorship']=='unknown':
        warnings.append('Sponsorship and local work authorization are unconfirmed')
    if result['location_status'] in {'ca','uk'}:
        warnings.append('Canada/UK authorization restrictions are informational; personal eligibility is unverified')

    # A year elsewhere in boilerplate is not a graduation requirement.
    cohort = bool(re.search(r'\b2027\b', title) and re.search(r'\b(?:grad(?:uate|uation|uates)?|entry[ -]level|early[ -]career|start|university|campus)\b', title, re.I))
    for sentence in re.split(r'[;\n]|(?<=[.!?])\s+', description):
        if re.search(r'\b2027\b', sentence) and re.search(r'\b(?:graduat(?:e|es|ing|ion)|degree.*complet|start(?:ing| date)?|join(?:ing)? date)\b', sentence, re.I):
            cohort = True
            evidence.append(sentence.strip()[:600])
        if re.search(r'\b(?:graduat(?:e|es|ing|ion)|degree.*complet)\b',sentence,re.I):
            years=re.findall(r'\b202[0-9]\b',sentence)
            if years and '2027' not in years:
                reasons.append('Explicit graduation-year requirement does not include 2027')
    availability = datetime.fromisoformat(start_date).date()
    if availability > datetime.now(timezone.utc).date() and re.search(r'\b(?:immediate start|start immediately|start as soon as possible|must be available immediately)\b', description, re.I):
        reasons.append('Posting requires an immediate start before availability')
    months = {name[:3].lower(): i for i, name in enumerate(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'], 1)}
    month_pattern=r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    for match in re.finditer(r'\b(?:start(?:ing| date| by)?|commenc(?:e|ing)|join(?:ing)? date)\s*(?:is |: |in |on |by )*('+month_pattern+r')\s+(?:(\d{1,2}),?\s+)?(20\d\d)', description, re.I):
        try:date = datetime(int(match.group(3)), months[match.group(1)[:3].lower()], int(match.group(2) or 1)).date()
        except ValueError:
            reasons.append('Stated start date is invalid and needs review');continue
        if date < availability:
            reasons.append('Stated start date is before June 2027 availability')
        else:
            cohort = True
            evidence.append(match.group(0))
    if re.search(r'\b(?:graduat\w*|degree[^.]{0,35})[^.]{0,50}\b(?:by|before|no later than)\s+(?:January|February|March|April|May)\s+(?:\d{1,2},?\s+)?2027\b', description, re.I):
        reasons.append('Graduation deadline precedes June 2027')
    if strict_cohort and not cohort:
        reasons.append('June 2027 cohort or compatible start date is unconfirmed')
    if not cohort:warnings.append('June 2027 or later start date is unconfirmed')
    return {'eligible': not reasons, 'reasons': list(dict.fromkeys(reasons)), 'evidence': list(dict.fromkeys(evidence)), 'warnings':warnings, 'cohort_confirmed': cohort}
