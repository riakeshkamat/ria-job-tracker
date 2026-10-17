import asyncio
import json
import logging
import uuid
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

import httpx

from .db import now
from .sources import Fetcher, board_from_url

log = logging.getLogger(__name__)


def schedule_due(last_attempt, current, hour=8, timezone_name='America/New_York'):
    local = current.astimezone(ZoneInfo(timezone_name))
    due = local.replace(hour=hour,minute=0,second=0,microsecond=0)
    if local < due:
        due -= timedelta(days=1)
    return not last_attempt or datetime.fromisoformat(last_attempt) < due.astimezone(timezone.utc)


class Collector:
    def __init__(self, db, config, client_factory=None):
        self.db, self.config = db,config
        self.lock = asyncio.Lock()
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(30,connect=10),
            headers={'User-Agent':'OpenJobTracker/1.0 (public job board reader; personal use)'},limits=httpx.Limits(max_connections=6)))

    def recover(self):
        with self.db.connect() as c:
            c.execute("UPDATE runs SET status='interrupted',finished_at=?,error='Service restarted during collection; existing jobs preserved' WHERE status='running'", (now(),))

    async def run(self):
        if self.lock.locked():
            return None
        async with self.lock:
            run_id, started = str(uuid.uuid4()), now()
            with self.db.connect() as c:
                c.execute('INSERT INTO runs(id,started_at,status) VALUES(?,?,?)', (run_id,started,'running'))
            self.db.set('last_schedule_attempt',started)
            counts = {'sources':0,'success':0,'found':0,'new':0}
            semaphore = asyncio.Semaphore(4)
            try:
                async with self.client_factory() as client:
                    fetcher = Fetcher(client)

                    async def collect(source):
                        async with semaphore:
                            counts['sources'] += 1
                            try:
                                jobs, _ = await fetcher.collect(source)
                                if not jobs and source.get('job_count',0):
                                    raise ValueError('Unexpected empty board; previous records preserved. Confirm employer board identifier.')
                                # Discover real ATS boards from application links, not guessed slugs.
                                if source['provider'] == 'github':
                                    for job in jobs:
                                        board = board_from_url(job['apply_url'])
                                        if board:
                                            self.db.add_source(*board,job['company'],source['slug'])
                                new = await asyncio.to_thread(self.db.ingest,source,jobs,run_id,self.config.start_date)
                                counts['success'] += 1
                                counts['found'] += len(jobs)
                                counts['new'] += new
                            except asyncio.CancelledError:
                                raise
                            except Exception as exc:
                                # No response bodies or credentials in the audit log.
                                error = f'HTTP {exc.response.status_code}' if isinstance(exc,httpx.HTTPStatusError) else str(exc)[:250] if isinstance(exc,ValueError) else type(exc).__name__
                                self.db.source_failed(source['id'],run_id,error)
                            finally:
                                with self.db.connect() as c:
                                    c.execute('UPDATE runs SET source_count=?,success_count=?,found_count=?,new_count=? WHERE id=?',
                                              (counts['sources'],counts['success'],counts['found'],counts['new'],run_id))

                    # Lists first, so their newly discovered employer boards join this same run.
                    sources = [s for s in self.db.sources() if s['enabled'] and s['provider']!='manual']
                    await asyncio.gather(*(collect(s) for s in sources if s['provider']=='github'))
                    await asyncio.gather(*(collect(s) for s in self.db.sources() if s['enabled'] and s['provider'] not in {'github','manual'}))
                status = 'success' if counts['success']==counts['sources'] else 'partial' if counts['success'] else 'failed'
                with self.db.connect() as c:
                    c.execute('UPDATE runs SET finished_at=?,status=?,source_count=?,success_count=?,found_count=?,new_count=? WHERE id=?',
                        (now(),status,counts['sources'],counts['success'],counts['found'],counts['new'],run_id))
                if status=='success':
                    self.db.set('last_complete_refresh',now())
                return run_id
            except BaseException:
                with self.db.connect() as c:
                    c.execute("UPDATE runs SET finished_at=?,status='interrupted',error='Collection interrupted; existing records preserved' WHERE id=?",(now(),run_id))
                raise

    async def loop(self, enrich=None):
        while True:
            try:
                if schedule_due(self.db.get('last_schedule_attempt'),datetime.now(timezone.utc),self.config.hour,self.config.timezone):
                    result = await self.run()
                    if result and enrich:
                        await enrich()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Scheduled collection did not complete')
            await asyncio.sleep(60)
