import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .domain import canonical_url, classify, fingerprint, ROLE, location_status, job_attributes,us_location_label
from .sources import ATS, AGGREGATORS


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY, provider TEXT NOT NULL, slug TEXT NOT NULL,
                    name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, discovered_from TEXT,
                    last_attempt TEXT, last_success TEXT, last_error TEXT, job_count INTEGER,
                    UNIQUE(provider,slug));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, canonical_url TEXT UNIQUE NOT NULL, apply_url TEXT NOT NULL,
                    title TEXT NOT NULL, company TEXT NOT NULL, location TEXT NOT NULL, country TEXT NOT NULL,
                    description TEXT NOT NULL, description_hash TEXT NOT NULL, posted_at TEXT,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, verified_at TEXT,
                    in_scope INTEGER NOT NULL, scope_reasons TEXT NOT NULL, min_years INTEGER,
                    location_status TEXT NOT NULL, sponsorship TEXT NOT NULL, evidence TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new', notes TEXT NOT NULL DEFAULT '',
                    availability TEXT NOT NULL DEFAULT 'unverified', ai_review TEXT, ai_hash TEXT);
                CREATE TABLE IF NOT EXISTS sightings (
                    source_id INTEGER NOT NULL REFERENCES sources(id), external_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id), last_seen TEXT NOT NULL,
                    misses INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source_id,external_id));
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    captured_at TEXT NOT NULL, description_hash TEXT NOT NULL, description TEXT NOT NULL,
                    evidence TEXT NOT NULL, UNIQUE(job_id,description_hash));
                CREATE TABLE IF NOT EXISTS unverified_checks (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    source_id INTEGER NOT NULL REFERENCES sources(id), misses INTEGER NOT NULL,
                    PRIMARY KEY(job_id,source_id));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    status TEXT NOT NULL, source_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
                    found_count INTEGER DEFAULT 0, new_count INTEGER DEFAULT 0, error TEXT);
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY, run_id TEXT REFERENCES runs(id), source_id INTEGER REFERENCES sources(id),
                    checked_at TEXT NOT NULL, status TEXT NOT NULL, job_count INTEGER, error TEXT);
                CREATE INDEX IF NOT EXISTS sighting_jobs ON sightings(job_id);
                CREATE INDEX IF NOT EXISTS job_feed ON jobs(in_scope,sponsorship,first_seen);
            ''')
            c.execute("INSERT OR IGNORE INTO meta VALUES('host_id',?)", ('urn:uuid:' + str(uuid.uuid4()),))
        self.normalize_urls()
        self.index_boards()
        with self.connect() as c:
            fields={r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
            for name,definition in [('role_family',"TEXT NOT NULL DEFAULT 'software'"),
                                    ('work_model',"TEXT NOT NULL DEFAULT 'unknown'"),
                                    ('early_career','INTEGER NOT NULL DEFAULT 0'),
                                    ('cohort_2027','INTEGER NOT NULL DEFAULT 0')]:
                if name not in fields:c.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
            c.execute('CREATE INDEX IF NOT EXISTS us_feed ON jobs(location_status,in_scope,status,first_seen)')

    def refresh_location_rules(self, start_date):
        """Reclassify stored locations before serving the updated feed; retain user history."""
        if self.get('us_location_rules_version')==1:return
        changed=0
        with self.connect() as c:
            rows=c.execute('SELECT id,title,location,country,location_status,in_scope,scope_reasons,work_model FROM jobs').fetchall()
            for row in rows:
                loc=location_status(row['location'],row['country'],row['title'])
                reasons=[r for r in json.loads(row['scope_reasons']) if r not in {
                    'Location is outside the US','US work location needs verification','US work location is unconfirmed'}]
                scope=row['in_scope']
                if loc!='us':
                    scope=0
                    reasons.append('Location is outside the US' if loc=='outside_us' else 'US work location is unconfirmed')
                elif row['location_status']!='us' and not scope:
                    description=c.execute('SELECT description FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]
                    result=classify(row['title'],description,row['location'],row['country'],start_date)
                    scope,reasons=result['in_scope'],result['scope_reasons']
                attrs=job_attributes(row['title'],row['location'],row['work_model'])
                c.execute('UPDATE jobs SET location_status=?,in_scope=?,scope_reasons=?,role_family=?,work_model=?,early_career=?,cohort_2027=? WHERE id=?',
                          (loc,scope,json.dumps(reasons),attrs['role_family'],attrs['work_model'],attrs['early_career'],attrs['cohort_2027'],row['id']))
                changed+=int(loc!=row['location_status'])
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('us_location_rules_version','1'))
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('us_location_migration',json.dumps({'at':now(),'reviewed':len(rows),'changed':changed})))

    def index_boards(self):
        from .sources import board_from_url
        with self.connect() as c:
            fields={r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
            if 'board_provider' not in fields:
                c.execute("ALTER TABLE jobs ADD COLUMN board_provider TEXT NOT NULL DEFAULT ''")
                c.execute("ALTER TABLE jobs ADD COLUMN board_slug TEXT NOT NULL DEFAULT ''")
                for row in c.execute('SELECT id,canonical_url FROM jobs').fetchall():
                    board=board_from_url(row['canonical_url']) or ('','')
                    c.execute('UPDATE jobs SET board_provider=?,board_slug=? WHERE id=?',(*board,row['id']))
            c.execute('CREATE INDEX IF NOT EXISTS unverified_boards ON jobs(board_provider,board_slug,verified_at)')

    def normalize_urls(self):
        """Upgrade older /application identities without losing status, notes, or sightings."""
        if self.get('url_normalization_version') == 2:
            return
        with self.connect() as c:
            rows=c.execute('SELECT * FROM jobs ORDER BY first_seen').fetchall()
            for row in rows:
                if not c.execute('SELECT 1 FROM jobs WHERE id=?',(row['id'],)).fetchone(): continue
                url=canonical_url(row['canonical_url'])
                keep=c.execute('SELECT * FROM jobs WHERE canonical_url=? AND id!=?',(url,row['id'])).fetchone()
                if keep:
                    if (row['verified_at'] or '')>(keep['verified_at'] or ''):
                        fields=['apply_url','title','company','location','country','description','description_hash','posted_at',
                                'verified_at','in_scope','scope_reasons','min_years','location_status','sponsorship','evidence','availability','ai_review','ai_hash']
                        c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',[row[k] for k in fields]+[keep['id']])
                    c.execute('UPDATE jobs SET first_seen=?,last_seen=? WHERE id=?',(min(row['first_seen'],keep['first_seen']),max(row['last_seen'],keep['last_seen']),keep['id']))
                    if keep['status']=='new' and row['status']!='new':
                        c.execute('UPDATE jobs SET status=? WHERE id=?',(row['status'],keep['id']))
                    if row['notes'] and row['notes']!=keep['notes']:
                        c.execute('UPDATE jobs SET notes=? WHERE id=?',('\n'.join(n for n in [keep['notes'],row['notes']] if n),keep['id']))
                    c.execute('UPDATE sightings SET job_id=? WHERE job_id=?',(keep['id'],row['id']))
                    c.execute('INSERT OR IGNORE INTO revisions(job_id,captured_at,description_hash,description,evidence) SELECT ?,captured_at,description_hash,description,evidence FROM revisions WHERE job_id=?',(keep['id'],row['id']))
                    c.execute('DELETE FROM revisions WHERE job_id=?',(row['id'],))
                    c.execute('DELETE FROM jobs WHERE id=?',(row['id'],))
                else:
                    c.execute('UPDATE jobs SET canonical_url=? WHERE id=?',(url,row['id']))
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('url_normalization_version','2'))

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, key, default=None):
        with self.connect() as c:
            r = c.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(r['value']) if r and key != 'host_id' else r['value'] if r else default

    def set(self, key, value):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, json.dumps(value)))

    def add_source(self, provider, slug, name, discovered_from=None):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO sources(provider,slug,name,discovered_from) VALUES(?,?,?,?)',
                      (provider, slug, name, discovered_from))
            return c.execute('SELECT id FROM sources WHERE provider=? AND slug=?', (provider, slug)).fetchone()[0]

    def add_sources(self, rows, discovered_from):
        """Atomic directory import; existing disabled boards stay disabled."""
        with self.connect() as c:
            for provider,slug,name in rows:
                c.execute('INSERT INTO sources(provider,slug,name,discovered_from) VALUES(?,?,?,?) '
                          'ON CONFLICT(provider,slug) DO UPDATE SET name=excluded.name '
                          'WHERE sources.name=sources.slug AND excluded.name!=excluded.slug',
                          (provider,slug,name,discovered_from))

    def directory_succeeded(self, source, count, run_id):
        ts=now()
        with self.connect() as c:
            c.execute('UPDATE sources SET last_attempt=?,last_success=?,last_error=NULL,job_count=? WHERE id=?',
                      (ts,ts,count,source['id']))
            c.execute('INSERT INTO checks(run_id,source_id,checked_at,status,job_count) VALUES(?,?,?,?,?)',
                      (run_id,source['id'],ts,'success',count))

    def sources(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM sources ORDER BY provider,name')]

    def source_summary(self):
        threshold=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()-36*3600,timezone.utc).isoformat()
        with self.connect() as c:
            row=c.execute("""SELECT count(*) total,
                coalesce(sum(enabled=1),0) enabled,
                coalesce(sum(enabled=1 AND last_success IS NOT NULL AND last_error IS NULL),0) healthy,
                coalesce(sum(enabled=1 AND last_error IS NOT NULL),0) failed,
                coalesce(sum(enabled=1 AND last_attempt IS NULL),0) pending,
                coalesce(sum(enabled=1 AND last_success>=? AND last_error IS NULL),0) recent
                FROM sources WHERE provider!='manual'""",(threshold,)).fetchone()
            platforms=[dict(r) for r in c.execute("SELECT provider,count(*) count FROM sources WHERE enabled=1 AND provider!='manual' GROUP BY provider")]
            return {**dict(row),'platforms':platforms}

    def source_page(self, search='', health='', offset=0, limit=100):
        clauses=["provider!='manual'"];args=[]
        if search:
            clauses.append("(name LIKE ? ESCAPE '\\' OR slug LIKE ? ESCAPE '\\' OR provider LIKE ? ESCAPE '\\')")
            term='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            args += [term]*3
        if health=='failed': clauses.append('enabled=1 AND last_error IS NOT NULL')
        elif health=='pending': clauses.append('enabled=1 AND last_attempt IS NULL')
        elif health=='enabled': clauses.append('enabled=1')
        where=' WHERE '+' AND '.join(clauses)
        with self.connect() as c:
            total=c.execute('SELECT count(*) FROM sources'+where,args).fetchone()[0]
            rows=c.execute('SELECT * FROM sources'+where+' ORDER BY provider,name,id LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        return {'sources':[dict(r) for r in rows],'total':total,'offset':offset}

    def ingest(self, source, jobs, run_id, start_date):
        """One atomic source snapshot; failed/partial collection never reaches this method."""
        ts, new_count = now(), 0
        authoritative = source['provider'] in ATS
        # Parse and classify before acquiring the SQLite write lock. Large boards must
        # not hold the database transaction while doing CPU-heavy description work.
        prepared=[]
        for job in jobs:
            # Large directories include every industry. Do not persist unrelated
            # job families unless already tracked; this is title scope, never CV matching.
            relevant=source['provider']=='manual' or bool(ROLE.search(job['title']))
            result=classify(job['title'],job.get('description','') if relevant and (authoritative or source['provider'] in AGGREGATORS) else '',
                            job.get('location',''),job.get('country',''),start_date)
            if not authoritative:
                # Provider descriptions can establish experience scope, but their
                # sponsorship claims still require the employer's own evidence.
                result['sponsorship'],result['evidence']='unknown',[]
            prepared.append((job,canonical_url(job['apply_url']),result,relevant))
        with self.connect() as c:
            c.execute('UPDATE sightings SET misses=misses+1 WHERE source_id=?', (source['id'],))
            for job,url,result,relevant in prepared:
                external_id = str(job['external_id'])
                existing = c.execute('SELECT * FROM jobs WHERE canonical_url=?',(url,)).fetchone()
                if not existing:
                    existing = c.execute('SELECT j.* FROM sightings s JOIN jobs j ON j.id=s.job_id '
                                         'WHERE s.source_id=? AND s.external_id=?',
                                         (source['id'],external_id)).fetchone()
                if not relevant and not existing:
                    continue
                job_id = existing['id'] if existing else str(uuid.uuid4())
                description = job.get('description', '')
                # A list-only sighting cannot overwrite an employer's full posting or visa evidence.
                if existing and not authoritative and (existing['verified_at'] or source['provider']=='github'):
                    c.execute('UPDATE jobs SET last_seen=? WHERE id=?', (ts, job_id))
                else:
                    values = dict(job_id=job_id, canonical_url=url, apply_url=job['apply_url'], title=job['title'],
                                  company=job['company'], location=job.get('location',''), country=job.get('country',''),
                                  description=description, description_hash=fingerprint(description), posted_at=job.get('posted_at'),
                                  first_seen=ts, last_seen=ts, verified_at=ts if authoritative else None,
                                  **result, availability='open' if authoritative else 'unverified')
                    values.update(job_attributes(job['title'],job.get('location',''),job.get('work_model','')))
                    from .sources import board_from_url
                    values['board_provider'],values['board_slug']=board_from_url(url) or ('','')
                    values['scope_reasons'] = json.dumps(result['scope_reasons'])
                    values['evidence'] = json.dumps(result['evidence'])
                    columns = [k for k in values if k != 'job_id']
                    if existing:
                        update = [k for k in columns if k not in ('first_seen', 'canonical_url')]
                        c.execute('UPDATE jobs SET '+','.join(k+'=?' for k in update)+' WHERE id=?',
                                  [values[k] for k in update]+[job_id])
                    else:
                        c.execute('INSERT INTO jobs(id,'+','.join(columns)+') VALUES('+','.join('?' for _ in range(len(columns)+1))+')',
                                  [job_id]+[values[k] for k in columns])
                        new_count += 1
                    c.execute('INSERT OR IGNORE INTO revisions(job_id,captured_at,description_hash,description,evidence) VALUES(?,?,?,?,?)',
                              (job_id,ts,values['description_hash'],description,values['evidence']))
                c.execute('INSERT INTO sightings VALUES(?,?,?,?,0) ON CONFLICT(source_id,external_id) DO UPDATE SET '
                          'job_id=excluded.job_id,last_seen=excluded.last_seen,misses=0', (source['id'],external_id,job_id,ts))
            if authoritative:
                # A live board can also disprove stale list links that were never on a prior ATS snapshot.
                from .sources import board_from_url
                unverified=c.execute("SELECT id,canonical_url FROM jobs WHERE verified_at IS NULL AND availability!='closed' AND board_provider=? AND board_slug=?",(source['provider'],source['slug'])).fetchall()
                for candidate in unverified:
                    if board_from_url(candidate['canonical_url'])==(source['provider'],source['slug']):
                        c.execute('INSERT INTO unverified_checks VALUES(?,?,1) ON CONFLICT(job_id,source_id) DO UPDATE SET misses=misses+1', (candidate['id'],source['id']))
                        misses=c.execute('SELECT misses FROM unverified_checks WHERE job_id=? AND source_id=?',(candidate['id'],source['id'])).fetchone()[0]
                        if misses>=2:
                            c.execute("UPDATE jobs SET availability='closed' WHERE id=?",(candidate['id'],))
                # Only trusted ATS sightings determine closed status; list removal alone proves nothing.
                c.execute('''UPDATE jobs SET availability='closed' WHERE id IN
                    (SELECT job_id FROM sightings WHERE source_id=? AND misses>=2)
                    AND NOT EXISTS(SELECT 1 FROM sightings s JOIN sources p ON p.id=s.source_id
                    WHERE s.job_id=jobs.id AND p.enabled=1 AND p.provider IN ('greenhouse','ashby','lever','recruitee') AND s.misses<2)''', (source['id'],))
            c.execute('UPDATE sources SET last_attempt=?,last_success=?,last_error=NULL,job_count=? WHERE id=?', (ts,ts,len(jobs),source['id']))
            c.execute('INSERT INTO checks(run_id,source_id,checked_at,status,job_count) VALUES(?,?,?,?,?)', (run_id,source['id'],ts,'success',len(jobs)))
        return new_count

    def source_failed(self, source_id, run_id, error):
        with self.connect() as c:
            c.execute('UPDATE sources SET last_attempt=?,last_error=? WHERE id=?', (now(),error,source_id))
            c.execute('INSERT INTO checks(run_id,source_id,checked_at,status,error) VALUES(?,?,?,?,?)', (run_id,source_id,now(),'failed',error))

    def jobs(self, view='feed', search='', status='', sponsorship='', limit=100, offset=0,
             role='',work_model='',found_days=0,experience='',graduate='',verified=False,sort='recommended',unapplied=False):
        clauses, args = [], []
        if view == 'feed':
            clauses += ["location_status='us'", "in_scope=1", "sponsorship!='restricted'", "availability!='closed'", "status!='dismissed'"]
        elif view=='saved':
            clauses += ["location_status='us'", "status='saved'"]
        elif view == 'excluded':
            clauses += ["(in_scope=0 OR sponsorship='restricted' OR location_status!='us')"]
        elif view == 'tracked':
            clauses += ["location_status='us'", "status IN ('applied','interview','offer','rejected')"]
        elif view == 'closed':
            clauses += ["availability='closed'"]
        if search:
            clauses += ["(title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')"]
            term = '%' + search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
            args += [term]*3
        if status:
            clauses += ['status=?']; args += [status]
        if sponsorship:
            if sponsorship == 'review':
                clauses += ["(sponsorship IN ('unknown','conflict') OR location_status='unknown')"]
            else:
                clauses += ['sponsorship=?']; args += [sponsorship]
        if role: clauses.append('role_family=?');args.append(role)
        if work_model: clauses.append('work_model=?');args.append(work_model)
        if found_days:
            clauses.append('julianday(first_seen)>=julianday(?)')
            args.append(datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()-found_days*86400,timezone.utc).isoformat())
        if experience=='unknown':clauses.append('min_years IS NULL')
        elif experience:clauses.append('min_years IS NOT NULL AND min_years<=?');args.append(int(experience))
        if graduate=='early':clauses.append('early_career=1')
        elif graduate=='2027':clauses.append('cohort_2027=1')
        if verified:clauses.append("verified_at IS NOT NULL AND julianday(verified_at)>=julianday('now','-36 hours')")
        if unapplied and view=='feed' and not status:clauses.append("status IN ('new','saved')")
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        order={'newest':'first_seen DESC,company,title,id','company':'company COLLATE NOCASE,title,id',
               'posted':"(julianday(posted_at) IS NULL),julianday(posted_at) DESC,first_seen DESC,id"}.get(sort,
               'early_career DESC,CASE WHEN min_years IS NOT NULL THEN 0 ELSE 1 END,first_seen DESC,company,title,id')
        with self.connect() as c:
            total = c.execute('SELECT COUNT(*) FROM jobs'+where,args).fetchone()[0]
            rows = c.execute('SELECT * FROM jobs'+where+' ORDER BY '+order+' LIMIT ? OFFSET ?', args+[limit,offset]).fetchall()
            output = []
            for r in rows:
                item = dict(r)
                item['us_location']=us_location_label(item['location'],item['country'],item['work_model']) if item['location_status']=='us' else item['location']
                for key in ('evidence','scope_reasons','ai_review'):
                    item[key] = json.loads(item[key]) if item[key] else None
                item['sources'] = [dict(s) for s in c.execute('SELECT p.name,p.provider,p.last_success,p.last_error,s.last_seen,s.misses FROM sightings s JOIN sources p ON p.id=s.source_id WHERE s.job_id=?', (item['id'],))]
                output.append(item)
            return {'jobs':output,'total':total}

    def runs(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM runs ORDER BY started_at DESC LIMIT 15')]
