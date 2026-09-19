"""Prepare timed scenes and speech chunks from versioned, sanitized source assets."""
import array
import json
import math
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path('/home/user/academy-phase1')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True)


def prepare():
    videos = json.loads((ROOT / 'manifest.json').read_text())
    narration = json.loads((ROOT / 'narration.json').read_text())
    alignment = json.loads((ROOT / 'alignment.json').read_text())
    (ROOT / 'audio').mkdir(exist_ok=True)
    for v, n, a in zip(videos, narration, alignment):
        path = ROOT / 'audio' / f'{v["id"]}.wav'
        if not path.exists():
            urllib.request.urlretrieve(n['url'], path)
        log = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path), '-af',
                              'silencedetect=noise=-38dB:d=0.06', '-f', 'null', '-'],
                             capture_output=True, text=True, check=True).stderr
        silences = []
        start = None
        for line in log.splitlines():
            match = re.search(r'silence_start: ([0-9.]+)', line)
            if match:
                start = float(match.group(1))
            match = re.search(r'silence_end: ([0-9.]+)', line)
            if match and start is not None:
                silences.append((start, float(match.group(1))))
                start = None
        samples = array.array('f', run('ffmpeg', '-v', 'error', '-i', str(path),
                                       '-ac', '1', '-ar', '16000', '-f', 'f32le', '-').stdout)
        boundaries = [0.0]
        boundary_checks = []
        for left, right in zip(a['spans'], a['spans'][1:]):
            target = (left['end'] + right['start']) / 2
            candidates = [(lo, hi) for lo, hi in silences
                          if hi > left['end'] - .08 and lo < right['start'] + .9
                          and (lo + hi) / 2 > boundaries[-1] + .4]
            if candidates:
                lo, hi = min(candidates, key=lambda pair: abs(sum(pair) / 2 - target))
                split = (lo + hi) / 2
                boundary_checks.append({'split': split, 'silence': [lo, hi]})
            else:
                # Quietest 24ms window near the word-alignment boundary. This
                # fallback is reported for explicit review; it is never hidden.
                options = []
                for ms in range(round((target - .10) * 1000), round((target + .40) * 1000), 5):
                    ix = max(0, ms * 16)
                    window = samples[ix:ix + 384]
                    if window:
                        options.append((sum(x*x for x in window) / len(window), ms / 1000 + .012))
                power, split = min(options)
                boundary_checks.append({'split': split, 'quiet_window_rms_db': 10 * math.log10(max(power, 1e-12))})
            boundaries.append(split)
        boundaries.append(a['duration'])
        at = 0
        for i, s in enumerate(v['shots']):
            begin, end = boundaries[i:i+2]
            for lo, hi in silences:
                if lo <= begin <= hi:
                    begin = max(begin, hi - .10)
                if lo <= end <= hi:
                    end = min(end, lo + .13)
            s.update(audio_from=round(begin, 6), audio_to=round(end, 6),
                     narration=n['lines'][i], audio_lead=.18)
            minimum = max(end-begin+.55, 2+.3*len(s['caption'].split()))
            s['dur'] = max(s['dur'], math.ceil(minimum*24)/24)
            s['at'] = at
            at += s['dur']
        total = max(v['duration'], math.ceil(at))
        v['shots'][-1]['dur'] += total-at
        v.update(duration=total, transcript=' '.join(n['lines']),
                 audio='Arthur narration', boundary_checks=boundary_checks)
        assert total <= 75, (v['id'], total)
        assert 3 <= v['shots'][0]['dur'] <= 5, (v['id'], 'intro too long')
        assert len(n['lines']) == len(v['shots'])
        print('TIMING', v['id'], total, 'seconds', flush=True)
    (ROOT/'timed-manifest.json').write_text(json.dumps(videos, indent=2))
    return videos


if __name__ == '__main__':
    prepare()
