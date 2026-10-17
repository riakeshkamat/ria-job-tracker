"""Conservative, inspectable rules. No resume matching or inferred visa approval."""
import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.skipping=0

    def handle_starttag(self, tag, attrs):
        if tag in {'script','style'}: self.skipping+=1

    def handle_endtag(self, tag):
        if tag in {'script','style'}: self.skipping=max(0,self.skipping-1)

    def handle_data(self, data):
        if not self.skipping and data.strip(): self.parts.append(data.strip())


def plain(value):
    if not value or '<' not in value:
        return value or ''
    parser=_Text()
    parser.feed(value)
    return ' '.join(parser.parts)


def canonical_url(value):
    p = urlsplit(value.strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('An HTTP(S) application link is required')
    # Keep job identity parameters; remove advertising and referral parameters only.
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(('utm_',)) and k.lower() not in
             {'source', 'ref', 'referral', 'gh_src', 'lever-source', 'lever-origin', 'src', 'refid', 'trackingid'}]
    host = p.hostname.lower()
    if host in ('boards.greenhouse.io', 'job-boards.greenhouse.io'):
        host = 'job-boards.greenhouse.io'
    path = p.path.rstrip('/')
    if host in {'jobs.ashbyhq.com','jobs.lever.co'}:
        path = re.sub(r'/(?:apply|application)$','',path)
    if re.fullmatch(r'/o/[^/]+/c/new',path):
        path=path[:-6]
    return urlunsplit(('https' if p.scheme == 'https' else 'http', host, path, urlencode(sorted(query)), ''))


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


NEGATIVE = [
    r'\b(?:must|shall|need to)\s+(?:be\s+)?(?:a\s+)?(?:u\.?s\.?|united states)\s+citizen\b',
    r'\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required\b',
    r'\b(?:u\.?s\.?|united states)\s+citizens?\s+only\b',
    r'\b(?:only|exclusively)\s+(?:open|available)\s+to\s+(?:u\.?s\.?|united states)\s+citizens\b',
    r'\b(?:citizens|citizenship)\s+(?:or|and)\s+(?:permanent residents|permanent residency)\s+only\b',
    r'\b(?:must|need to)\s+be\s+(?:a\s+)?(?:u\.?s\.?\s+)?(?:citizen\s+or\s+)?(?:permanent resident|green card holder)\b',
    r'\b(?:cannot|can not|unable to|will not|do not|does not|not able to)\s+(?:provide\s+|offer\s+)?(?:visa\s+|immigration\s+)?sponsor(?:ship)?\b',
    r'\bno\s+(?:(?:visa|immigration|employment)\s+)?sponsorship\b',
    r'\bsponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided)|unavailable)\b',
    r'\bwithout\s+(?:the\s+)?(?:need\s+for\s+)?(?:employment\s+|visa\s+|immigration\s+)?sponsorship\b[^.!?]{0,80}\b(?:future|ever)\b',
    r'\b(?:not\s+(?:require|need)|never\s+(?:require|need))\b[^.!?]{0,80}\bsponsorship\b',
    r'\b(?:OPT|CPT|F-1)\s+(?:candidates?\s+)?(?:are\s+)?not\s+(?:accepted|eligible|supported)\b',
]
POSITIVE = [
    r'\b(?:visa|immigration)\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b',
    r'\b(?:we|company|employer)\s+(?:will|can|does)\s+(?:provide\s+|offer\s+)?(?:visa\s+|immigration\s+)?sponsor(?:ship)?\b',
    r'\b(?:offer|provide|offers|provides)\s+(?:visa|immigration)\s+sponsorship\b',
]
ROLE = re.compile(r'\b(software|developer|swe|sde|backend|back.end|frontend|front.end|full.?stack|devops|sre|site reliability|data engineer|machine learning|ml engineer|ai engineer|cloud engineer|platform engineer|infrastructure engineer|production engineer|release engineer|forward.deployed engineer|security engineer|test engineer|quality engineer|qa engineer|automation engineer|systems engineer|embedded|firmware|quantitative developer|research engineer|application engineer)\b', re.I)
EARLY = re.compile(r'\b(new[ -]?(?:college[ -]?)?grad(?:uate)?s?|entry[ -]?level|early[ -]?career|university grad|junior|associate|engineer\s*(?:i|1))\b', re.I)
SENIOR = re.compile(r'\b(senior|sr\.?|staff|principal|director|lead|manager|engineer\s*(?:iii|iv|[4-9]))\b', re.I)
US_STATES = {'alabama','alaska','arizona','arkansas','california','colorado','connecticut','delaware','florida','georgia','hawaii','idaho','illinois','indiana','iowa','kansas','kentucky','louisiana','maine','maryland','massachusetts','michigan','minnesota','mississippi','missouri','montana','nebraska','nevada','new hampshire','new jersey','new mexico','new york','north carolina','north dakota','ohio','oklahoma','oregon','pennsylvania','rhode island','south carolina','south dakota','tennessee','texas','utah','vermont','virginia','washington','west virginia','wisconsin','wyoming'}
US_CODES = 'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()
US_CITIES = {'san francisco','san jose','seattle','new york','boston','philadelphia','austin','chicago','palo alto','mountain view','sunnyvale','los angeles','san diego','santa clara','denver','atlanta','pittsburgh','washington dc','redmond','bellevue','menlo park','irvine'}


def location_status(location, country=''):
    if country.upper() in {'US', 'USA', 'UNITED STATES'}:
        return 'us'
    if country and country.upper() not in {'US', 'USA', 'UNITED STATES'}:
        return 'outside_us'
    text = location.lower()
    if re.search(r'\b(united states|usa|u\.s\.|remote.{0,8}us)\b', text):
        return 'us'
    if any(re.search(r'\b' + re.escape(s) + r'\b', text) for s in US_STATES | US_CITIES):
        return 'us'
    if re.search(r',\s*(?:' + '|'.join(US_CODES) + r')(?:\b|\s|$)', location):
        return 'us'
    if re.search(r'\b(canada|toronto|vancouver|london|united kingdom|india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|germany|berlin|munich|frankfurt|singapore|australia|sydney|melbourne|ireland|dublin|israel|tel aviv|poland|warsaw|france|paris|netherlands|amsterdam|mexico|switzerland|zurich|lausanne|japan|tokyo|korea|seoul|taiwan|taipei|china|beijing|shanghai|hong kong|spain|madrid|barcelona|portugal|lisbon|sweden|stockholm|finland|helsinki|denmark|copenhagen|norway|oslo|brazil|sao paulo)\b', text):
        return 'outside_us'
    return 'unknown'


def classify(title, description, location='', country='', start_date='2027-06-01'):
    text = plain(description)
    evidence = []
    for sentence in re.split(r'(?<=[!?;])\s+|\n+|(?<=[a-z0-9])\.\s+(?=[A-Z])', text):
        negative = any(re.search(p, sentence, re.I) for p in NEGATIVE)
        positive = not negative and any(re.search(p, sentence, re.I) for p in POSITIVE)
        if negative or positive:
            evidence.append({'kind': 'restriction' if negative else 'support', 'quote': sentence[:1200], 'origin': 'posting'})
    blocked = any(e['kind'] == 'restriction' for e in evidence)
    supports = any(e['kind'] == 'support' for e in evidence)
    sponsorship = 'conflict' if blocked and supports else 'restricted' if blocked else 'supported' if supports else 'unknown'
    reasons = []
    scope = True
    if not ROLE.search(title):
        scope = False
        reasons.append('Outside software and related engineering titles')
    if re.search(r'\b(land developer|property developer|mechanical|fluids|civil engineer|manufacturing.*quality|quality.*manufacturing)\b', title,re.I) and not re.search(r'software|firmware|embedded|automation',title,re.I):
        scope = False
        reasons.append('Explicit engineering specialty outside software-related roles')
    if SENIOR.search(title) and not EARLY.search(title):
        scope = False
        reasons.append('Explicit seniority outside entry level')
    if re.search(r'\b(interns?|internships?|co-op)\b', title, re.I):
        scope = False
        reasons.append('Internship, not a full-time graduate role')
    # Experience in the actual requirement, never unrelated numbers elsewhere in the posting.
    years = []
    for m in re.finditer(r'\b(\d{1,2})\s*(?:(?:[-–]|to)\s*\d{1,2}|\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:[^.;\n]{0,90}?\b)?(?:experience|building|developing|designing|shipping|working)\b', text, re.I):
        context = text[max(0, m.start()-70):m.end()+60]
        if not re.search(r'preferred|nice.to.have|bonus|desirable', context, re.I):
            years.append(int(m.group(1)))
    min_years = min(years) if years else None
    if min_years is not None and min_years > 3 and not EARLY.search(title):
        scope = False
        reasons.append(f'Requires at least {min_years} years of experience')
    if min_years is None and not EARLY.search(title):
        reasons.append('Experience requirement needs verification')
    loc = location_status(location, country)
    if loc == 'outside_us':
        scope = False
        reasons.append('Location is outside the US')
    elif loc == 'unknown':
        reasons.append('US work location needs verification')
    if re.search(r'\b202[0-6]\b', title) and not re.search(r'\b202[7-9]\b', title) and EARLY.search(title):
        scope = False
        reasons.append('Explicit graduate cohort predates 2027')
    # Do not invent a start date from a publication date or graduation-year guess.
    for m in re.finditer(r'\b(?:start date|starting|must start|start by)\s*:?\s*(20\d\d-\d\d-\d\d)', text, re.I):
        if m.group(1) < start_date:
            scope = False
            reasons.append('Explicit start date is before availability')
    return {'in_scope': int(scope), 'scope_reasons': reasons, 'min_years': min_years,
            'location_status': loc, 'sponsorship': sponsorship, 'evidence': evidence}
