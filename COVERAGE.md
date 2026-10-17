# Daily search coverage

Every scheduled run refreshes the directories and lists below, imports new employer identifiers, and checks all enabled employer feeds. The application reports enabled, never-attempted, recently successful (36 hours), and failed feeds separately. A directory count is not a count of reachable boards, unique employers, or suitable jobs.

## Employer discovery

- [Open ATS Feed](https://github.com/veresk06/open-ats-feed), `actor/data/companies.json`. The four supported platforms in the snapshot inspected October 17, 2026 contain 13,753 board identifiers. Other vendors in the directory are not imported. MIT; copyright 2026 open-ats-feed contributors. No source code or directory copy is redistributed with this app.
- [LastRound AI ATS directory](https://github.com/fyrosofttech/lastroundai-hiring-data/tree/main/ats-directory), `lastroundai-ats-company-directory-2026-08.csv`. 9,935 entries in the inspected snapshot, with substantial overlap. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: LastRound AI, [pay transparency study](https://lastroundai.com/), [DOI](https://doi.org/10.6084/m9.figshare.33154145). The app combines factual board identifiers and preserves manually disabled feeds. Directory timestamps describe upstream verification, not this app's live checks.

Directory updates are downloaded on each daily run; upstream publication cadence is outside this app's control. Failed, malformed, or suspiciously small directories leave the existing registry intact. Employer names may fall back to board slugs. An identifier can become obsolete, and different boards can belong to the same employer.

## Employer feeds

| Platform | Collection | Evidence / availability |
|---|---|---|
| Greenhouse | Full public board snapshot | Employer description and two-snapshot closure checks |
| Ashby | Listed public jobs | Employer description and two-snapshot closure checks |
| Lever | All public pages, up to 10,000 postings per board | Employer description and two-snapshot closure checks |
| Recruitee | Published offers, including requirements and multiple locations | Employer description and two-snapshot closure checks |

Public feed documentation: [Greenhouse](https://docs.greenhouse.io/job-board), [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api), [Lever](https://github.com/lever/postings-api), [Recruitee](https://docs.recruitee.com/reference/offers).

## New-grad lists

1. [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions), README.
2. [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027), README.
3. [SpeedyApply](https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/NEW_GRAD_USA.md), US new-graduate file; internship files are not imported.
4. [ApplyGuy](https://github.com/ApplyGuy/2027-New-Grad-Jobs), machine-readable new-grad feed. Uses the employer's `listingUrl`, not the one-click-application service.
5. [Ricsign](https://github.com/ricsign/Ricsign-New-Grads-Jobs-2027), machine-readable feed, active `new-grad-swe` track only.

These lists can surface employers using Workday, Microsoft Careers, Amazon Jobs, and other unsupported systems. Such records have application links but remain unverified by an employer feed. Community sponsorship annotations cannot establish eligibility or exclude jobs. Different lists overlap and may apply their own selection rules.

## Remote-job feeds

| Source | Scope | Limitations |
|---|---|---|
| [Remotive](https://github.com/remotive-com/remote-jobs-api) | Entire free public feed, software-related titles retained | Public listings are delayed 24 hours; links stay on Remotive for attribution/application access |
| [Jobicy](https://github.com/Jobicy/remote-jobs-api) | Entire public seven-day feed, all cursor pages, software-related titles retained | Feed expiry does not mean a job closed; links stay on Jobicy |
| [Himalayas](https://himalayas.app/api) | US search, Entry-level and Mid-level labels, all pages until empty | Results can shift during traversal and upstream seniority labels can be wrong; links stay on Himalayas |

The normal US, role, and experience rules apply. Worldwide jobs remain visible for location verification. Remote listings carry provider descriptions, are not employer-verified, and cannot overwrite authoritative employer evidence. No remote-feed disappearance is treated as a confirmed job closure. Source names and canonical provider links are preserved. This is a private personal tracker, not a public redistribution feed or signup collection service.

## Remaining gaps

- LinkedIn and Jobright are not automatically collected. Broad employer coverage does not imply complete coverage of either platform.
- No comprehensive direct crawling of Workday, iCIMS, Taleo, Workable, SmartRecruiters, company-specific sites, or every large employer. New-grad lists can expose individual links from these systems, but there is no full daily employer snapshot for them.
- No paid job/search/scraping API, proxy service, or OpenAI API-key billing fallback. Collection itself requires no AI call. The existing Plus review is advisory and capped separately.
- Listings can omit OPT acceptance, future sponsorship, start dates, or minimum experience. Unknown is kept separate from a verified match. The app cannot guarantee every suitable vacancy will be found.
