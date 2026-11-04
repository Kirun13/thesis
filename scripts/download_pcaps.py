"""Fetch small author-release capture/CSV pairs, with exact provenance."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
REF = 'mohamedamineferrag/edgeiiotset-cyber-security-dataset-of-iot-iiot'


def main():
    target = ROOT / 'data/pcap-audit'
    target.mkdir(parents=True, exist_ok=True)
    listing, token = [], None
    for _ in range(20):
        response = requests.get(f'https://www.kaggle.com/api/v1/datasets/list/{REF}',
                                params={'pageToken': token} if token else {}, timeout=60)
        response.raise_for_status()
        page = response.json()
        listing.extend(page.get('datasetFiles', []))
        token = page.get('nextPageToken')
        if not token:
            break
    (target / 'release-files.json').write_text(json.dumps(listing, indent=2), encoding='utf-8')
    chosen = [item for item in listing if any(word in item['name'].lower() for word in ['backdoor', 'port_scanning', 'port scanning', 'normal traffic'])
              and item['name'].lower().endswith(('.csv', '.pcap')) and item['totalBytes'] < 350_000_000]
    print('Selected files:', [(item['name'], item['totalBytes']) for item in chosen], flush=True)
    for item in chosen:
        path = target / Path(item['name']).name
        if not path.exists():
            url = f'https://www.kaggle.com/api/v1/datasets/download/{REF}/{quote(item["name"], safe="")}'
            archive = path.with_suffix('.download')
            with requests.get(url, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                with archive.open('wb') as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
            if zipfile.is_zipfile(archive):
                with zipfile.ZipFile(archive) as z:
                    names = [n for n in z.namelist() if n.endswith(path.name)]
                    assert len(names) == 1
                    with z.open(names[0]) as source, path.open('wb') as output:
                        shutil.copyfileobj(source, output)
                archive.unlink()
            else:
                archive.replace(path)
        assert path.stat().st_size == item['totalBytes']
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        path.with_suffix(path.suffix + '.source.json').write_text(json.dumps({'source_ref': REF, 'release_file': item,
                  'sha256': digest, 'bytes': path.stat().st_size}, indent=2), encoding='utf-8')
        print(f'Verified {path.name}: {path.stat().st_size:,} bytes', flush=True)


if __name__ == '__main__':
    main()
