# Ria's deployment

This is a separate personal deployment on Sauransh's Railway subscription.

- Project: `ria-job-tracker` (`c0cafce0-28c2-443b-8925-a8e979884bfb`)
- Service: `web` (`f07052a9-9149-45a4-b247-8758d019364f`)
- Environment: `production`
- Site: https://ria-job-tracker.up.railway.app
- New volume: `web-volume` (`baa99180-6dac-4f57-9560-b03c4fd7fcfd`), mounted at `/data`

The volume starts empty. No application history, database, tracker password,
encryption secret or ChatGPT connection was copied from the original tracker.
Restarting or deploying never resets the database. Use volume backups and the
in-app JSON export to preserve Ria's application history.

## Credentials

The owner-only local file `data/ria/deployment.env` contains the generated tracker
password and encryption secret. This file is ignored by Git and Docker and must
never be committed. Keep `APP_SECRET` stable across deployments.

In Ria's tracker, open Settings and follow the connection instructions while
signed in to **Ria's own ChatGPT account/workspace**. Use the host ID shown by
this deployment, not the local preview or original tracker. The local helper
writes `data/ria/chatgpt.credentials.json`; import it over HTTPS and delete the
transfer file. Verify a completed review before relying on AI advice. The
account must be eligible for ChatGPT plan usage. Collection works while AI is
disconnected, unavailable or capped.

## Deploy updates

This service is deployed from the local checkout using Railway CLI. A GitHub
push alone does not deploy it until a GitHub source and deployment branch are
explicitly connected in Railway.

```sh
railway up \
  --project c0cafce0-28c2-443b-8925-a8e979884bfb \
  --service f07052a9-9149-45a4-b247-8758d019364f \
  --environment production \
  --detach
```

Use one replica and one worker. The Dockerfile starts collection every two hours
with no overlapping runs. Daily publication is independent at **6:30 PM Eastern**,
with a **100-job total cap** across all three countries. AI reviews have a separate
30-attempt daily cap. The first edition waits until the next cutoff. Discoveries
are available as soon as sources produce records; older or unverifiable posting
dates never pad the daily edition.

Workday and employer-specific career sites remain coverage gaps. See
[COVERAGE.md](COVERAGE.md) for source and timestamp limitations.
