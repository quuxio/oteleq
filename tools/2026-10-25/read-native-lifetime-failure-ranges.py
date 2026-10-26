"""Read selected failure members while the complete original ZIP is downloading."""

from collections import OrderedDict
import hashlib
import io
import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request, urlopen
import zipfile

OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-lifetime-build/hosted-3d64a4d-terminal-01')
API = 'https://api.github.com'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Ranges(io.RawIOBase):
    """A bounded seekable reader; signed URLs and credentials never enter records."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.position = url, size, 0
        self.cache, self.receipts, self.etag = OrderedDict(), [], None

    def seek(self, offset: int, whence: int = 0) -> int:
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        assert 0 <= self.position <= self.size
        return self.position

    def tell(self) -> int:
        return self.position

    def read(self, size: int = -1) -> bytes:
        length = self.size - self.position if size < 0 else min(size, self.size - self.position)
        assert 0 <= length <= 64 * 1024**2
        if not length:
            return b''
        begin, end = self.position, self.position + length
        for (left, right), data in self.cache.items():
            if left <= begin and end <= right:
                self.position = end
                return data[begin - left:end - left]
        block = 256 * 1024
        left, right = begin // block * block, min(self.size, (end + block - 1) // block * block)
        request = Request(self.url, headers={'Range': f'bytes={left}-{right - 1}'})
        try:
            with urlopen(request, timeout=60) as response:
                assert response.status == 206
                assert response.headers['Content-Range'] == f'bytes {left}-{right - 1}/{self.size}'
                etag = response.headers['ETag']
                assert self.etag is None or etag == self.etag
                self.etag = etag
                data = response.read(right - left + 1)
        except (HTTPError, URLError):
            raise RuntimeError('Artifact range request failed; signed URL withheld') from None
        assert len(data) == right - left
        self.receipts.append({'first_byte': left, 'last_byte': right - 1,
                              'sha256': hashlib.sha256(data).hexdigest()})
        self.cache[(left, right)] = data
        while sum(len(value) for value in self.cache.values()) > 64 * 1024**2:
            self.cache.popitem(last=False)
        self.position = end
        return data[begin - left:end - left]


def main() -> None:
    result = subprocess.run(['/opt/homebrew/bin/gh', 'auth', 'token', '--hostname', 'github.com', '--user', 'quuxio'],
                            capture_output=True, text=True, check=True)
    headers = {'Authorization': 'Bearer ' + result.stdout.strip(), 'Accept': 'application/vnd.github+json'}
    with urlopen(Request(API + '/user', headers=headers), timeout=30) as response:
        assert json.load(response)['login'] == 'quuxio'
    location = None
    try:
        build_opener(NoRedirect).open(Request(API + '/repos/quuxio/oteleq/actions/artifacts/12618095579/zip', headers=headers), timeout=30)
    except HTTPError as error:
        assert error.code == 302
        location = error.headers['Location']
    assert location and urlsplit(location).scheme == 'https'
    host = urlsplit(location).hostname
    assert host.endswith('.blob.core.windows.net') or host.endswith('.githubusercontent.com')
    artifact, = json.loads((OUTPUT / 'artifacts.json').read_text())['artifacts']
    source = Ranges(location, artifact['size_in_bytes'])
    output = OUTPUT / 'target-error-range-diagnosis-01'
    output.mkdir(mode=0o700)
    selected = {}
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        wanted = [name for name in names if name.startswith('native-lifetime-evidence/cpp-target-error/')
                  and name.endswith(('/run.stdout', '/run.stderr', '/run.exit', '/report.json'))]
        assert wanted
        for name in wanted:
            path = Path(name)
            assert not path.is_absolute() and '..' not in path.parts
            data = archive.read(name)
            target = output / path
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o600)
            selected[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            print(name, data.decode()[-12000:], flush=True)
    record = {'status': 'provisional failure diagnosis from authenticated artifact byte ranges',
        'artifact_id': artifact['id'], 'expected_full_archive_digest': artifact['digest'],
        'members': selected, 'ranges': source.receipts, 'etag': source.etag,
        'scope': 'ZIP member CRCs checked; full original archive SHA256 validation remains pending. No signed URL or account credential retained; no application executed.'}
    (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
