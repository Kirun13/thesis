"""Download only the selected CSV from the dataset author's public Kaggle release."""
import hashlib
import json
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
REF = 'mohamedamineferrag/edgeiiotset-cyber-security-dataset-of-iot-iiot'
FILE = 'Edge-IIoTset dataset/Selected dataset for ML and DL/DNN-EdgeIIoT-dataset.csv'
TARGET = ROOT / 'data/raw/DNN-EdgeIIoT-dataset.csv'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    metadata = {}
    token = None
    for _ in range(10):
        response = requests.get(f'https://www.kaggle.com/api/v1/datasets/list/{REF}',
                                params={'pageToken': token} if token else {}, timeout=60)
        response.raise_for_status()
        listing = response.json()
        for item in listing.get('datasetFiles', []):
            if item['name'] == FILE:
                metadata = item
        token = listing.get('nextPageToken')
        if metadata or not token:
            break
    if not metadata:
        raise RuntimeError('Selected CSV not found in the author release; no substitute used.')
    print(f"Source file: {FILE}; uncompressed bytes: {metadata['totalBytes']}", flush=True)
    if not TARGET.exists():
        archive = TARGET.with_suffix('.download')
        url = f'https://www.kaggle.com/api/v1/datasets/download/{REF}/{quote(FILE, safe="")}'
        with requests.get(url, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', ''):
                raise RuntimeError('Kaggle returned an HTML page, not the public dataset.')
            downloaded, last = 0, time.monotonic()
            with archive.open('wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
                    downloaded += len(chunk)
                    if time.monotonic() - last > 10:
                        print(f'Downloaded {downloaded / 1e6:.1f} MB', flush=True)
                        last = time.monotonic()
        partial = TARGET.with_suffix('.partial')
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as source:
                matches = [name for name in source.namelist() if name.endswith('DNN-EdgeIIoT-dataset.csv')]
                if len(matches) != 1:
                    raise RuntimeError(f'Ambiguous archive: {source.namelist()}')
                with source.open(matches[0]) as input_file, partial.open('wb') as output:
                    while chunk := input_file.read(1024 * 1024):
                        output.write(chunk)
        else:
            archive.replace(partial)
        if partial.stat().st_size != metadata['totalBytes']:
            raise RuntimeError(f'File size mismatch: {partial.stat().st_size}')
        partial.replace(TARGET)
        if archive.exists():
            archive.unlink()
    if TARGET.stat().st_size != metadata['totalBytes']:
        raise RuntimeError('Existing file size does not match release metadata.')
    digest = hashlib.file_digest(TARGET.open('rb'), 'sha256').hexdigest()
    provenance = {'source': f'https://www.kaggle.com/datasets/{REF}', 'file': FILE,
                  'sha256': digest, 'bytes': TARGET.stat().st_size, 'release_file': metadata}
    TARGET.with_suffix('.source.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(json.dumps(provenance, indent=2), flush=True)


if __name__ == '__main__':
    main()
