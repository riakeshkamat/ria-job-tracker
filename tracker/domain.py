"""Conservative, inspectable rules. No resume matching or inferred visa approval."""
import hashlib
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .profile import PROFILE, ROLE_FAMILIES, TECHNICAL_ROLES

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
    r'\b(?:u\.?s\.?|united states)\s+person\s+(?:is\s+)?required\b',
    r'\bmust\s+be\s+(?:a\s+)?(?:u\.?s\.?|united states)\s+person\b(?![^.!?]{0,60}\b(?:or|export license)\b)',
    r'\b(?:must|shall|need to)\s+(?:be\s+)?(?:a\s+)?(?:u\.?s\.?|united states)\s+citizen\b',
    r'\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required\b',
    r'\b(?:u\.?s\.?|united states)\s+citizens?\s+only\b',
    r'\b(?:only|exclusively)\s+(?:open|available)\s+to\s+(?:u\.?s\.?|united states)\s+citizens\b',
    r'\b(?:citizens|citizenship)\s+(?:or|and)\s+(?:permanent residents|permanent residency)\s+only\b',
    r'\b(?:must|need to)\s+be\s+(?:a\s+)?(?:u\.?s\.?\s+)?(?:citizen\s+or\s+)?(?:permanent resident|green card holder)\b',
    r'\b(?:cannot|can not|unable to|will not|do not|does not|not able to)\s+(?:provide\s+|offer\s+)?(?:(?:visa|immigration|H[ -]?1B)\s+)?sponsor(?:ship)?\b',
    r'\bno\s+(?:(?:visa|immigration|employment|H[ -]?1B)\s+)?sponsorship\b',
    r'\bsponsorship\s+(?:is\s+)?(?:not\s+(?:available|offered|provided)|unavailable)\b',
    r'\bwithout\s+(?:the\s+)?(?:need\s+for\s+)?(?:employment\s+|visa\s+|immigration\s+)?sponsorship\b[^.!?]{0,80}\b(?:future|ever)\b',
    r'\b(?:not\s+(?:require|need)|never\s+(?:require|need))\b[^.!?]{0,80}\bsponsorship\b',
    r'\b(?:OPT|CPT|F-1)\s+(?:candidates?\s+)?(?:are\s+)?not\s+(?:accepted|eligible|supported)\b',
]
POSITIVE = [
    r'\b(?:visa|immigration)\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b',
    r'\b(?:we|company|employer)\s+(?:will|can|does)\s+(?:provide\s+|offer\s+)?(?:(?:visa|immigration|H[ -]?1B)\s+)?sponsor(?:ship)?\b',
    r'\b(?:offer|provide|offers|provides)\s+(?:visa|immigration)\s+sponsorship\b',
]
ROLE = re.compile('|'.join(ROLE_FAMILIES.values()), re.I)
EARLY = re.compile(r'\b(new[ -]?(?:college[ -]?)?grad(?:uate)?s?|entry[ -]?level|early[ -]?career|university grad(?:uate)?|graduate|junior|associate|trainee|rotational|analyst\s*(?:i|1))\b', re.I)
SENIOR = re.compile(r'\b(senior|sr\.?|staff|principal|director|lead|manager|architect|vice president|vp|head of|(?:analyst|consultant)\s*(?:iii|iv|[4-9]))\b', re.I)


def relevant_role(title):
    return bool(ROLE.search(title)) and not re.search(TECHNICAL_ROLES, title, re.I)
US_STATES = {'alabama','alaska','arizona','arkansas','california','colorado','connecticut','delaware','florida','georgia','hawaii','idaho','illinois','indiana','iowa','kansas','kentucky','louisiana','maine','maryland','massachusetts','michigan','minnesota','mississippi','missouri','montana','nebraska','nevada','new hampshire','new jersey','new mexico','new york','north carolina','north dakota','ohio','oklahoma','oregon','pennsylvania','rhode island','south carolina','south dakota','tennessee','texas','utah','vermont','virginia','washington','west virginia','wisconsin','wyoming'}
US_CODES = 'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()
US_CITIES = {'san francisco','san jose','seattle','new york','boston','philadelphia','austin','chicago','palo alto','mountain view','sunnyvale','los angeles','san diego','santa clara','denver','atlanta','pittsburgh','washington dc','redmond','bellevue','menlo park','irvine'}


US_TOKEN = re.compile(r'(?<!\w)(?:united states(?: of america)?|usa|u\.s\.?|us)(?!\w)',re.I)
US_PLACE = re.compile(r'\b(?:'+ '|'.join(re.escape(x) for x in sorted((US_STATES-{'georgia'})|US_CITIES, key=len, reverse=True))+r')\b',re.I)
US_STATE_CODE = re.compile(r',\s*(?:'+ '|'.join(US_CODES) +r')(?:\b|\s|$)')
FOREIGN = re.compile(r'\b(?:united arab emirates|uae|u\.a\.e\.?|dubai|abu dhabi|sharjah|qatar|doha|saudi arabia|riyadh|kuwait|bahrain|oman|muscat|egypt|cairo|south africa|nigeria|kenya|morocco|canada|toronto|vancouver|montreal|ottawa|united kingdom|uk|england|scotland|london|india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|delhi|germany|berlin|munich|frankfurt|singapore|australia|sydney|melbourne|ireland|dublin|israel|tel aviv|poland|warsaw|france|paris|netherlands|amsterdam|mexico|switzerland|zurich|lausanne|japan|tokyo|south korea|seoul|taiwan|taipei|china|beijing|shanghai|hong kong|spain|madrid|barcelona|portugal|lisbon|sweden|stockholm|finland|helsinki|denmark|copenhagen|norway|oslo|brazil|sao paulo|argentina|chile|colombia|peru|pakistan|bangladesh|vietnam|thailand|malaysia|indonesia|philippines|new zealand|armenia|serbia|kazakhstan|tbilisi|european union|europe|emea|apac|latam|czechia|czech republic|romania|bulgaria|hungary|ukraine|russia|belarus|turkey|turkiye|greece|italy|austria|belgium|luxembourg|estonia|latvia|lithuania|croatia|costa rica|panama|uruguay|ecuador|cambodia|laos|nepal|sri lanka|bangladesh|lebanon|jordan)\b',re.I)


def _location_signal(location, country=''):
    text=''.join(c for c in unicodedata.normalize('NFKD',location or '') if not unicodedata.combining(c))
    country=(country or '').strip().upper()
    if country and country not in {'US','USA','UNITED STATES','UNITED STATES OF AMERICA'}:
        return 'outside_us'
    if re.search(r'\b(?:non[ -]?(?:us|usa)|(?:excluding|except|outside(?:\s+of)?|not(?:\s+available|\s+eligible)?(?:\s+in|\s+to)?)\s+(?:the\s+)?(?:united states|usa|u\.s\.?|us))\b',text,re.I):
        return 'outside_us'
    if US_TOKEN.search(text): return 'us'
    if not country and re.search(r'\bOntario\s*,\s*CA\b',text,re.I):return 'unknown'
    # A real US state code disambiguates Paris, TX / Berlin, NJ. Canada/CA
    # and Georgia alone are ambiguous; foreign locations must not prove US eligibility.
    state_code=US_STATE_CODE.search(text)
    foreign=FOREIGN.search(text)
    if state_code and not (foreign and state_code.group().strip(' ,')=='CA'):
        return 'us'
    if foreign:
        alternatives=re.split(r'\s*[;·|/]\s*|\s+(?:or|and|&)\s+',text,flags=re.I)
        if len(alternatives)>1 and any(_location_signal(part)=='us' for part in alternatives):
            return 'us'
        return 'outside_us'
    if country or US_PLACE.search(text): return 'us'
    return 'unknown'


def location_status(location, country='', title=''):
    result=_location_signal(location,country)
    if result=='us' and title:
        # Some aggregate feeds mislabel a foreign vacancy as US. A location
        # suffix in the title can contradict that metadata; quarantine it.
        suffix=re.search(r'\b(?:remote|based in|located in)\s*[:\-]?\s*(.+)$',title,re.I)
        parenthetical=re.findall(r'\(([^)]+)\)',title)
        scopes=([suffix.group(1)] if suffix else [])+parenthetical
        if any(_location_signal(part)=='outside_us' and not US_TOKEN.search(part) for part in scopes):
            return 'unknown'
    return result


COUNTRY_ALIASES = {'US':'US','USA':'US','UNITED STATES':'US','UNITED STATES OF AMERICA':'US',
                   'CA':'CA','CAN':'CA','CANADA':'CA','GB':'GB','GBR':'GB','UK':'GB',
                   'UNITED KINGDOM':'GB','GREAT BRITAIN':'GB'}
CANADA = re.compile(r'\b(?:canada|toronto|vancouver|montreal|ottawa|calgary|edmonton|winnipeg|quebec|nova scotia|new brunswick|british columbia|saskatchewan|manitoba|newfoundland|prince edward island|alberta)\b|,\s*(?-i:ON|BC|QC|AB|MB|SK|NS|NB|NL|PE)(?:\b|$)', re.I)
UK = re.compile(r'\b(?:united kingdom|great britain|england|scotland|wales|northern ireland|UK|GB|GBR)\b', re.I)
TARGET_EXCLUSION = re.compile(r'(?:\b(?:excluding|except|outside(?: of)?|not(?: (?:available|eligible))?(?: (?:in|to))?)\s+(?:the\s+)?|\bnon[- ]?)(United States|USA|US|Canada|CA|United Kingdom|UK|GB)\b',re.I)


def _search_countries(location, country=''):
    text=''.join(c for c in unicodedata.normalize('NFKD',location or '') if not unicodedata.combining(c))
    canonical=COUNTRY_ALIASES.get((country or '').strip().upper())
    # A country field from a single-location employer is authoritative. Multi-
    # location adapters choose a supported country and preserve all location text.
    if country and not canonical:
        return []
    exclusions={COUNTRY_ALIASES[m.group(1).upper()] for m in TARGET_EXCLUSION.finditer(text)}
    text=TARGET_EXCLUSION.sub('',text)
    countries=set()
    parts=re.split(r'\s*[;·|/]\s*|\s+(?:or|and|&)\s+',text,flags=re.I)
    for part in parts:
        us=_location_signal(part)=='us'
        if us:countries.add('US')
        # Toronto, OH and Scotland, PA are US cities. Do not invent Canadian
        # or UK options from their names and accidentally bypass US restrictions.
        if us and US_STATE_CODE.search(part) and not re.search(r'\b(?:Canada|United Kingdom|UK|GB|Great Britain)\b',part,re.I):
            continue
        if CANADA.search(part):countries.add('CA')
        if UK.search(part):countries.add('GB')
    if canonical and countries and canonical not in countries:
        return []
    foreign=[m.group().lower() for m in FOREIGN.finditer(text)]
    if canonical and not countries and foreign:
        if canonical not in {'CA','GB'} or any(place!='london' for place in foreign):return []
    if canonical:countries.add(canonical)
    countries-=exclusions
    return [code for code in PROFILE.countries if code in countries]


def search_location(location, country='', title=''):
    countries=_search_countries(location,country)
    if countries and title:
        suffix=re.search(r'\b(?:remote|based in|located in)\s*[:\-]?\s*(.+)$',title,re.I)
        scopes=([suffix.group(1)] if suffix else [])+re.findall(r'\(([^)]+)\)',title)
        for scope in scopes:
            title_countries=_search_countries(scope)
            if title_countries and not set(title_countries)&set(countries):
                return 'unknown',[]
            if not title_countries and _location_signal(scope)=='outside_us':
                return 'unknown',[]
    if countries:return {'US':'us','CA':'ca','GB':'uk'}[countries[0]],countries
    if COUNTRY_ALIASES.get((country or '').upper()):return 'unknown',[]
    outside=bool(country) or _location_signal(location)=='outside_us'
    return ('outside_target' if outside else 'unknown'),[]


def sponsorship_blocks(location, country, title, sponsorship):
    """US restrictions filter US-only jobs. Canada/UK evidence remains visible."""
    _,countries=search_location(location,country,title)
    return countries==['US'] and sponsorship in {'restricted','conflict'}


def experience_requirements(description):
    """Mandatory minima, preserving alternative degree paths for human review."""
    text=plain(description)
    text=re.sub(r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten)\s*\((\d{1,2})\)',r'\1',text,flags=re.I)
    for number,word in enumerate(['zero','one','two','three','four','five','six','seven','eight','nine','ten']):
        text=re.sub(r'\b'+word+r'(?=\s+(?:to\s+\w+\s+)?(?:years?|yrs?)\b)',str(number),text,flags=re.I)
    requirements=[]
    for sentence in re.split(r'[;\n]|(?<=[.!?])\s+',text):
        pattern=r"\b(\d{1,2})\s*(?:(?:[-–]|to)\s*(\d{1,2})|\+|or more|or greater|plus)?\s*(?:years?|yrs?)[’']?\s+(?:of\s+)?(?:[^.;\n]{0,90}?\b)?(?:experience|building|developing|designing|shipping|working)\b"
        for match in re.finditer(pattern,sentence,re.I):
            context=sentence[max(0,match.start()-40):match.end()+35]
            preferred=re.search(r'preferred|nice.to.have|bonus|desirable|not required',context,re.I)
            required=re.search(r'\b(?:required|must|minimum|at least)\b',context.replace('not required',''),re.I)
            if preferred and not required:continue
            upper_bound=re.search(r'\b(?:up to|less than|at most|no more than|fewer than|maximum(?: of)?)\s*$',sentence[max(0,match.start()-25):match.start()],re.I)
            requirements.append((0 if upper_bound else int(match.group(1)),sentence.strip()))
        if not re.search(r'preferred|nice.to.have|bonus|desirable|not required',sentence,re.I):
            for match in re.finditer(r'\b(\d{1,2})\+?\s+years?\s+(?:with|and)\s+(?:a\s+)?(?:bachelor|master|ph\.?d|doctoral)',sentence,re.I):
                requirements.append((int(match.group(1)),sentence.strip()))
    return requirements


def job_attributes(title, location='', work_model=''):
    model=(work_model or '').lower().replace('-','').replace('_','').replace(' ','')
    if model not in {'remote','hybrid','onsite'}:
        match=re.search(r'\bhybrid\b',location or '',re.I) or re.search(r'\b(remote|on[ -]?site)\b',location or '',re.I)
        model=match.group(0).lower().replace('-','').replace(' ','') if match else 'unknown'
    return {'role_family':next((k for k,p in ROLE_FAMILIES.items() if re.search(p,title,re.I)), 'other'),
            'work_model':model,'early_career':int(bool(EARLY.search(title)) and not SENIOR.search(title)),
            'cohort_2027':int(bool(re.search(r'\b2027\b',title) and EARLY.search(title)) and not SENIOR.search(title))}


def us_location_label(location, country='', work_model='unknown'):
    """Keep the US options on the compact row; original locations stay in details."""
    parts=re.split(r'\s*[;·]\s*',location or '')
    us_parts=[p for p in parts if _location_signal(p)=='us' and not FOREIGN.search(p)]
    if not us_parts:
        if FOREIGN.search(location or ''):return 'US option listed'
        return location or ('US remote' if work_model=='remote' else 'United States')
    return ' · '.join(us_parts[:2])+(f' +{len(us_parts)-2} US locations' if len(us_parts)>2 else '')


def location_label(location, country='', work_model='unknown'):
    _,countries=search_location(location,country)
    parts=re.split(r'\s*[;·]\s*',location or '')
    supported=[part for part in parts if _search_countries(part)]
    if not supported:
        from .profile import COUNTRY_LABELS
        return ' / '.join(COUNTRY_LABELS[code] for code in countries) or location or 'Location unconfirmed'
    return ' · '.join(supported[:2])+(f' +{len(supported)-2} locations' if len(supported)>2 else '')


def classify(title, description, location='', country='', start_date=PROFILE.start_date):
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
    if not relevant_role(title):
        scope = False
        reasons.append('Outside business, finance, data analysis and strategy roles; software engineering excluded')
    if SENIOR.search(title):
        scope = False
        reasons.append('Explicit seniority outside entry level')
    if re.search(r'\b(interns?|internships?|co-op|industrial placement|year in industry|summer analyst|summer associate)\b', title, re.I):
        scope = False
        reasons.append('Internship, not a full-time graduate role')
    # Experience in the actual requirement, never unrelated numbers elsewhere in the posting.
    years = [years for years,_ in experience_requirements(text)]
    min_years = max(years) if years else None
    if min_years is not None and min_years > PROFILE.max_experience:
        scope = False
        reasons.append(f'Requires at least {min_years} years of experience')
    if min_years is None and not EARLY.search(title):
        reasons.append('Experience requirement needs verification')
    loc,countries = search_location(location, country, title)
    if not countries:
        scope = False
        reasons.append('Location is outside the US, Canada and UK' if loc=='outside_target' else 'US, Canada or UK work location is unconfirmed')
    if re.search(r'\b202[0-6]\b', title) and not re.search(r'\b202[7-9]\b', title) and EARLY.search(title):
        scope = False
        reasons.append('Explicit graduate cohort predates 2027')
    # Do not invent a start date from a publication date or graduation-year guess.
    for m in re.finditer(r'\b(?:start date|starting|must start|start by)\s*:?\s*(20\d\d-\d\d-\d\d)', text, re.I):
        if m.group(1) < start_date:
            scope = False
            reasons.append('Explicit start date is before availability')
    return {'in_scope': int(scope), 'scope_reasons': reasons, 'min_years': min_years,
            'location_status': loc, 'work_countries': countries, 'sponsorship': sponsorship, 'evidence': evidence}
