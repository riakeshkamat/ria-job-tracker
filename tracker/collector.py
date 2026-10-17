import asyncio
import json
import logging
import uuid
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

import httpx

from .db import now
from .sources import Fetcher, board_from_url, ATS, AGGREGATORS

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
            headers={'User-Agent':'OpenJobTracker/1.1 (public job board reader; personal use)'},limits=httpx.Limits(max_connections=12)))

    def recover(self):
        with self.db.connect() as c:
            c.execute("UPDATE runs SET status='interrupted',finished_at=?,error='Service restarted during collection; existing jobs preserved' WHERE status='running'", (now(),))
        latest=self.db.runs()
        if latest and latest[0]['status']=='interrupted':
            self.db.set('last_schedule_attempt',None)

    async def run(self):
        if self.lock.locked():
            return None
        async with self.lock:
            run_id, started = str(uuid.uuid4()), now()
            with self.db.connect() as c:
                c.execute('INSERT INTO runs(id,started_at,status) VALUES(?,?,?)', (run_id,started,'running'))
            self.db.set('last_schedule_attempt',started)
            counts = {'sources':0,'success':0,'found':0,'new':0}
            writer = asyncio.Lock()
            try:
                async with self.client_factory() as client:
                    fetcher = Fetcher(client)

                    async def collect(source):
                        # Fixed worker pools bound memory; network pacing is per host.
                        counts['sources'] += 1
                        try:
                            jobs, boards = await fetcher.collect(source)
                            if source['provider'] == 'directory':
                                async with writer:
                                    await asyncio.to_thread(self.db.add_sources,boards,source['slug'])
                                    await asyncio.to_thread(self.db.directory_succeeded,source,len(boards),run_id)
                                counts['success'] += 1
                                return
                            if not jobs and source.get('job_count',0):
                                raise ValueError('Unexpected empty board; previous records preserved. Confirm employer board identifier.')
                            # Discover real ATS boards from application links, not guessed slugs.
                            if source['provider'] in {'github'} | AGGREGATORS:
                                discovered = [(board[0],board[1],job['company']) for job in jobs
                                              if (board := board_from_url(job['apply_url']))]
                                async with writer:
                                    await asyncio.to_thread(self.db.add_sources,discovered,source['slug'])
                            async with writer:
                                new = await asyncio.to_thread(self.db.ingest,source,jobs,run_id,self.config.start_date)
                            counts['success'] += 1
                            counts['found'] += len(jobs)
                            counts['new'] += new
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            # No response bodies or credentials in the audit log.
                            error = f'HTTP {exc.response.status_code}' if isinstance(exc,httpx.HTTPStatusError) else str(exc)[:250] if isinstance(exc,ValueError) else type(exc).__name__
                            await asyncio.to_thread(self.db.source_failed,source['id'],run_id,error)
                        finally:
                            def persist_progress():
                                with self.db.connect() as c:
                                    c.execute('UPDATE runs SET source_count=?,success_count=?,found_count=?,new_count=? WHERE id=?',
                                              (counts['sources'],counts['success'],counts['found'],counts['new'],run_id))
                            await asyncio.to_thread(persist_progress)
                    async def pool(sources, size):
                        queue = asyncio.Queue()
                        for source in sources: queue.put_nowait(source)
                        async def worker():
                            while not queue.empty():
                                await collect(queue.get_nowait())
                        await asyncio.gather(*(worker() for _ in range(size)))

                    # Discovery runs before collection. Different platform pools keep
                    # slow or rate-limited platforms from blocking every other feed.
                    sources = [s for s in self.db.sources() if s['enabled']]
                    await pool([s for s in sources if s['provider']=='directory'],2)
                    await pool([s for s in sources if s['provider']=='github'],3)
                    sources = [s for s in self.db.sources() if s['enabled']]
                    await asyncio.gather(
                        *(pool([s for s in sources if s['provider']==provider],1 if provider=='lever' else 3)
                          for provider in sorted(ATS)),
                        pool([s for s in sources if s['provider'] in AGGREGATORS],3))
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
                last=self.db.get('last_schedule_attempt')
                interval_due=not last or datetime.now(timezone.utc)-datetime.fromisoformat(last)>=timedelta(hours=self.config.collection_interval)
                if interval_due or schedule_due(last,datetime.now(timezone.utc),self.config.hour,self.config.timezone):
                    result = await self.run()
                    if result and enrich:
                        await enrich()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Scheduled collection did not complete')
            await asyncio.sleep(60)
