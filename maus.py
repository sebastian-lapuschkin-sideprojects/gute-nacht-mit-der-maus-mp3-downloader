"""
The core, shared by the web page (web.py, in the browser) and the command line (cli.py).

Episodes come from the ARD Audiothek (the WDR podcasts of "Die Maus" are published there with
the same mp3 files as on wdrmaus.de). A selection of episodes is brought to at most 89:59 so
that it fits on a Creative-Tonie (90 minutes): if it is longer, ffmpeg's atempo filter plays it
faster without changing the pitch.

Plain Python, no packages: Pyodide runs it as it is.
"""

import math
import re
import json
from datetime import datetime
from urllib.parse import quote

API = 'https://api.ardaudiothek.de/graphql?query='
TARGET = 89 * 60 + 59      # seconds: just under the 90 minutes of a Creative-Tonie
MAX_FACTOR = 2.0           # faster than this is no fun any more
BITRATE = '128k'           # of the converted files (the WDR files have 128k, long Hörspiele 160k)

# The series of "Die Maus" in the ARD Audiothek: key, Audiothek id, title, what it is, how many
# of the newest episodes to list (the news are worth listing for a few weeks only).
SERIES = [
    ('zumhoeren', 69106028, 'Die Maus zum Hören', 'jeden Tag eine Stunde Lach- und Sachgeschichten mit Musik', 100),
    ('kurz', 81889970, 'MausHörspiel kurz', 'Hörspiele bis etwa 10 Minuten', 300),
    ('lang', 36244846, 'MausHörspiel lang', 'lange Hörspiele, meist 40 bis 55 Minuten', 200),
    ('gutenacht', 81471712, 'Gute Nacht mit der Maus', 'etwa 20 Minuten zum Einschlafen (eingestellt im Juli 2026)', 200),
    ('nachrichten', 10378841, 'MausNachrichten', 'Nachrichten für Kinder, jeden Werktag', 30),
]
TITLES = {key: title for key, _, title, _, _ in SERIES}


def query():
    # one GraphQL query for all series: only published episodes (the Audiothek also knows
    # depublished ones and ones scheduled for the coming days), newest first
    parts = []
    for key, pid, _, _, limit in SERIES:
        parts.append('%s: programSet(id: %d) { items(first: %d, orderBy: PUBLISH_DATE_DESC, '
                     'filter: {isPublished: {equalTo: true}}) { nodes { id title publishDate duration '
                     'summary audios { url downloadUrl } } } }' % (key, pid, limit))
    return '{ ' + ' '.join(parts) + ' }'


def query_url():
    return API + quote(query())


def episodes(answer):
    # the API's answer (parsed json) -> list of episodes, per series newest first (parts of a story
    # published on the same day: the last part first). Trailers and notes of a few seconds are left out.
    found = []
    data = answer.get('data') or {}
    for key, _, _, _, _ in SERIES:
        nodes = (((data.get(key) or {}).get('items') or {}).get('nodes')) or []
        series = []
        for node in nodes:
            audios = node.get('audios') or []
            url = next((a.get('downloadUrl') or a.get('url') for a in audios if a.get('downloadUrl') or a.get('url')), None)
            title = (node.get('title') or '').strip()
            duration = node.get('duration') or 0
            if not url or duration < 60 or title.lower().startswith('trailer'):
                continue
            series.append({
                'id': str(node['id']), 'series': key, 'title': title, 'date': (node.get('publishDate') or '')[:10],
                'duration': duration, 'summary': clean_summary(node.get('summary') or ''), 'url': url,
            })
        found += newest_first(series)
    return found


# how parts of a story are numbered: 'Luftpiraten (15): ...', 'Eine lange Reise (3/5)', '... (Teil 2)',
# 'Luftpiraten - Teil 3: ...', 'Der Umstandsheini 03 von 05: ...', '... - 5 von 5 - ...'
PART = r'\((?:Teil\s*)?(\d+)(?:/\d+)?\)|\bTeil\s*(\d+)|\b(\d+)\s+von\s+\d+'


def part(title):
    # the number of a part of a story; 0 if none
    match = re.search(PART, title)
    return int(next(g for g in match.groups() if g)) if match else 0


def newest_first(found):
    return sorted(found, key=lambda e: (e['date'], part(e['title'])), reverse=True)


def listening_order(found):
    # oldest first, parts of a story in their order: the order to put them on the Tonie
    return sorted(found, key=lambda e: (e['date'], part(e['title'])))


def story_name(title):
    # The name of the story or series an episode belongs to, from how the Hörspiele are named:
    #   'Luftpiraten (15): Alles wird gut', 'Eine lange Reise (3/5) I Tierliches ab 6 Jahren',
    #   'KunstKrimi - Der Silvesterraub (1/2)', 'Kurt, das Einhorn: Rosen', 'Florentine Blix. Geheimakte Flaschenpost (1/2)'
    # -> the part before the part number or the first ' - ', ': ' or '. '. None if there is no such part.
    title = re.split(r' [|I] ', title)[0]
    match = re.search(r'\s*\((?:Teil\s*)?\d+(?:/\d+)?\)|\s+[-–]?\s*\bTeil\s*\d+|\s+\d+\s+von\s+\d+|\s+[-–]\s+|:\s|\.\s', title)
    if not match:
        return None
    name = re.sub(r'\s+', ' ', title[:match.start()]).strip()
    return name if len(re.sub(r'\W', '', name)) >= 4 else None    # not 'Dr' from 'Dr. ...'


STORY_SERIES = ('kurz', 'lang')     # the series that have stories in several episodes


def stories(found):
    # The stories and series of Hörspiele with at least two episodes, newest first:
    # [{'key', 'name', 'ids'}]. Names are compared ignoring case ('EIn Alien in Wiebelmund'), and a
    # name that starts with another one belongs to it ('Der Umstandsheini im Garten' -> 'Der Umstandsheini').
    named = {}
    for e in found:
        name = story_name(e['title']) if e['series'] in STORY_SERIES else None
        if name:
            named.setdefault(name.casefold(), []).append((name, e))
    keys = sorted(named, key=len)
    for i, short in enumerate(keys):
        for long in keys[i + 1:]:
            if long in named and short in named and long.startswith(short + ' '):
                named[short] += named.pop(long)
    groups = []
    for key, members in named.items():
        if len(members) < 2:
            continue
        spellings = [name for name, _ in members]
        # the most frequent spelling; on a tie the one with fewer capitals ('Ein', not 'EIn'), then the shorter one
        name = max(set(spellings), key=lambda s: (spellings.count(s), -sum(c.isupper() for c in s), -len(s), s))
        episodes_ = listening_order([e for _, e in members])
        groups.append({'key': key, 'name': name, 'ids': [e['id'] for e in episodes_],
                       'newest': max(e['date'] for e in episodes_), 'seconds': sum(e['duration'] for e in episodes_)})
    return sorted(groups, key=lambda g: (g['newest'], g['name']), reverse=True)


def matches(episode, text, in_summary=False):
    # all words of the search text appear in the title (or also in the description), whatever the case
    words = text.casefold().split()
    haystack = (episode['title'] + (' ' + episode['summary'] if in_summary else '')).casefold()
    return all(word in haystack for word in words)


def clean_summary(text):
    text = re.sub(r'\s+', ' ', text).strip()
    # 'Die Maus zum Hören - Lach- und Sachgeschichten. Heute: mit ...' (also ': Heute mit ...') -> 'mit ...'
    return re.sub(r'^Die Maus zum Hören - Lach- und Sachgeschichten[.:]?\s*(Heute:?\s*)?', '', text)


def default_selection(found):
    # the newest "Die Maus zum Hören"; everything else is up to the user
    for episode in found:
        if episode['series'] == 'zumhoeren':
            return [episode['id']]
    return []


def total(durations):
    return sum(durations)


def factor(seconds, count=1, measured=False):
    # How much faster the selection has to be played to fit into TARGET seconds. 1.0 if it fits.
    # The API's durations are rounded down to whole seconds (one second per file covers that);
    # measured durations are exact, and every converted file only gains a few milliseconds of
    # encoder padding (a tenth of a second per file). Rounded up to 4 digits.
    needed = (seconds + count * (0.1 if measured else 1)) / TARGET
    if needed <= 1:
        return 1.0
    return math.ceil(needed * 10000) / 10000


def verdict(f):
    # (level, text) about a speed-up factor, for the page
    percent = math.ceil(round((f - 1) * 1000, 6)) / 10     # rounded up to a tenth: never "0,0 %"
    if f <= 1:
        return 'fits', 'Passt ohne Änderung auf den Tonie.'
    amount = german_number(percent, 1) + ' %'
    if f > MAX_FACTOR:
        return 'too-much', 'Das wären {} schneller. Mehr als doppelt so schnell geht nicht, bitte weniger auswählen.'.format(amount)
    if percent <= 5:
        return 'unnoticed', 'Wird um {} schneller abgespielt. Das hört man nicht.'.format(amount)
    if percent <= 10:
        return 'slight', 'Wird um {} schneller abgespielt. Das fällt kaum auf.'.format(amount)
    return 'taste', 'Wird um {} schneller abgespielt. Ab hier ist es Geschmackssache.'.format(amount)


def german_number(x, digits):
    return '{:.{}f}'.format(x, digits).replace('.', ',')


def clock(seconds):
    # 3606 -> '1:00:06', 1793 -> '29:53'
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return '{}:{:02d}:{:02d}'.format(h, m, s) if h else '{}:{:02d}'.format(m, s)


def german_date(iso):
    # '2026-11-25' -> 'Mi 25.11.2026'
    try:
        day = datetime.strptime(iso, '%Y-%m-%d')
    except ValueError:
        return iso
    return '{} {:%d.%m.%Y}'.format(['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][day.weekday()], day)


def safe(text):
    # file names that work everywhere (also on the Tonie website): no slashes, colons, quotes ...
    text = re.sub(r'[\\/]', '-', text)
    text = re.sub(r'[:*?"<>|]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip(' .')


def short_title(episode):
    # long Hörspiele are called 'Oma verbuddeln (1/2) | Familiengeschichte ab 8 Jahren': the part before '|'
    return episode['title'].split(' | ')[0].strip()


def file_name(episode, number=None):
    # '01 Wintertiere (Die Maus zum Hören, 2026-11-25).mp3'
    name = '{} ({}, {})'.format(short_title(episode), TITLES[episode['series']], episode['date'])
    if number is not None:
        name = '{:02d} {}'.format(number, name)
    return safe(name) + '.mp3'


def mix_name(selected):
    # one file for the whole selection: 'Maus-Tonie 2026-11-25 Wintertiere und 3 weitere.mp3'
    newest = max(e['date'] for e in selected)
    rest = len(selected) - 1
    name = 'Maus-Tonie {} {}'.format(newest, short_title(selected[0]))
    if rest:
        name += ' und {} {}'.format(rest, 'weitere' if rest > 1 else 'weitere Folge')
    return safe(name) + '.mp3'


def duration_from_log(text):
    # ffmpeg prints 'Duration: 01:00:06.17, start: ...' for every input; the last one counts
    found = re.findall(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not found:
        return None
    h, m, s = found[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def audio_format(text):
    # ('mp3', '48000', 'stereo') from ffmpeg's 'Stream #0:0: Audio: mp3 (mp3float), 48000 Hz, stereo, fltp, 128 kb/s'
    match = re.search(r'Audio: (\w+)[^,]*, (\d+) Hz, ([\w.()]+)', text)
    return match.groups() if match else None


def joinable(formats):
    # mp3 files with the same sample rate and channels can be joined as they are, without converting
    # (different bitrates are fine: every mp3 frame says its own)
    return bool(formats) and all(f is not None and f[0] == 'mp3' and f == formats[0] for f in formats)


def time_from_log(line):
    # ffmpeg's progress lines contain 'time=00:12:34.56'
    match = re.search(r'time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)', line)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def convert_args(source, target, f, episode):
    # ffmpeg arguments: audio only (the files carry a cover picture), faster by f, mp3 again,
    # with the episode's title in the tags
    args = ['-hide_banner', '-nostdin', '-y', '-i', source, '-map', '0:a', '-map_metadata', '-1']
    if f != 1:
        args += ['-af', 'atempo={}'.format(f)]
    args += ['-c:a', 'libmp3lame', '-b:a', BITRATE,
             '-metadata', 'title=' + episode['title'],
             '-metadata', 'artist=' + TITLES[episode['series']],
             '-metadata', 'album=Die Maus auf dem Tonie',
             '-metadata', 'date=' + episode['date'][:4], target]
    return args


def concat_list(names):
    # the list file of ffmpeg's concat demuxer
    return ''.join("file '{}'\n".format(name.replace("'", "'\\''")) for name in names)


def concat_args(list_file, target, title):
    # join mp3 files without converting them (audio only: the WDR files also carry a cover picture)
    return ['-hide_banner', '-nostdin', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
            '-map', '0:a', '-map_metadata', '-1', '-c', 'copy',
            '-metadata', 'title=' + title, '-metadata', 'album=Die Maus auf dem Tonie', target]


if __name__ == '__main__':
    print(json.dumps(query(), ensure_ascii=False))
