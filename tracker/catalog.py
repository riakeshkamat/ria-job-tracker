"""Public employer-directory readers. Directories discover boards, never verify jobs."""
import csv
import io
import json


DIRECTORIES = {
    'open-ats': 'https://raw.githubusercontent.com/veresk06/open-ats-feed/main/actor/data/companies.json',
    'lastround': 'https://raw.githubusercontent.com/fyrosofttech/lastroundai-hiring-data/main/ats-directory/lastroundai-ats-company-directory-2026-08.csv',
}


def parse_directory(text, slug):
    from .sources import ATS, validate_source
    rows = []
    if slug == 'open-ats':
        data = json.loads(text)
        if not isinstance(data.get('providers'), dict):
            raise ValueError('Employer directory schema changed')
        for provider in sorted(ATS):
            entry = data['providers'].get(provider)
            if not isinstance(entry, dict) or not isinstance(entry.get('live'), list):
                raise ValueError('Employer directory is missing a supported platform')
            for row in entry['live']:
                if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str):
                    raise ValueError('Invalid employer directory entry')
                rows.append((provider, row[0], row[0]))
    elif slug == 'lastround':
        reader = csv.DictReader(io.StringIO(text))
        if not {'ats_vendor', 'company_name', 'board_slug', 'last_crawled'} <= set(reader.fieldnames or []):
            raise ValueError('Employer directory CSV schema changed')
        for row in reader:
            if row['ats_vendor'] in ATS:
                rows.append((row['ats_vendor'], row['board_slug'], row['company_name'] or row['board_slug']))
    else:
        raise ValueError('Unknown employer directory')
    if len(rows) < 1000 or len(rows) > 50000:
        raise ValueError('Unexpected employer directory size; prior registry preserved')
    for provider, token, name in rows:
        validate_source(provider, token)
        if not isinstance(name, str) or len(name) > 500:
            raise ValueError('Invalid employer name')
    return rows
