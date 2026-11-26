"""
The core, shared by the web page (web.py, in the browser) and the command line (cli.py).

Episodes come from the ARD Audiothek (the WDR podcasts of "Die Maus" are published there with
the same mp3 files as on wdrmaus.de). A selection of episodes is brought to at most 89:59 so
that it fits on a Creative-Tonie (90 minutes): if it is longer, ffmpeg's atempo filter plays it
faster without changing the pitch.

Plain Python, no packages: Pyodide runs it as it is. Texts for the page come in German ('de')
and English ('en'); German is the default.
"""

import math
import re
import json
from datetime import datetime
from urllib.parse import quote

API = 'https://api.ardaudiothek.de/graphql?query='
TARGET = 89 * 60 + 59      # seconds: just under the 90 minutes of a Creative-Tonie
ADVISED_MAX = 2.0          # faster than this is not recommended (the page says so, but does not stop anyone)
BITRATE = '128k'           # of the converted files (the WDR files have 128k, long Hörspiele 160k)
LANGS = ('de', 'en')       # the languages of the page

# The series of "Die Maus" in the ARD Audiothek: key, Audiothek id, title (a name, the same in both
# languages), what it is, how many of the newest episodes to list (the news are worth listing for a
# few weeks only).
SERIES = [
    ('zumhoeren', 69106028, 'Die Maus zum Hören',
     {'de': 'Jeden Tag gibt es eine Stunde Lach- und Sachgeschichten mit Musik.',
      'en': 'Every day there is an hour of stories to laugh at and to learn from, with music.'}, 100),
    ('kurz', 81889970, 'MausHörspiel kurz',
     {'de': 'Hier gibt es kurze Hörspiele, die höchstens etwa 10 Minuten dauern.',
      'en': 'Here you find short audio plays that last about ten minutes at most.'}, 300),
    ('lang', 36244846, 'MausHörspiel lang',
     {'de': 'Hier gibt es lange Hörspiele, die meist 40 bis 55 Minuten dauern.',
      'en': 'Here you find long audio plays, most of which last 40 to 55 minutes.'}, 200),
    ('gutenacht', 81471712, 'Gute Nacht mit der Maus',
     {'de': 'Jede Folge dauert etwa 20 Minuten und ist zum Einschlafen gedacht. Die Reihe wurde im Juli 2026 eingestellt.',
      'en': 'Each episode lasts about 20 minutes and is meant for falling asleep. The series ended in July 2026.'}, 200),
    ('nachrichten', 10378841, 'MausNachrichten',
     {'de': 'Jeden Werktag gibt es Nachrichten für Kinder.',
      'en': 'Every weekday there is news for children.'}, 30),
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


VERDICTS = {
    'de': {'fits': 'Diese Zusammenstellung passt ohne Änderung auf den Tonie.',
           'would': 'Diese Zusammenstellung würde um {} schneller abgespielt werden.',
           'will': 'Diese Zusammenstellung wird um {} schneller abgespielt.',
           'too-much': 'Eine mehr als doppelt so schnelle Wiedergabe ist nicht empfohlen.',
           'fewer': 'Bitte wähle weniger oder andere Folgen aus.',
           'unnoticed': 'Das hört man nicht.',
           'slight': 'Das fällt kaum auf.',
           'taste': 'Das ist Geschmackssache.'},
    'en': {'fits': 'This selection fits on the Tonie as it is.',
           'would': 'This selection would be played {} faster.',
           'will': 'This selection will be played {} faster.',
           'too-much': 'Playback at more than twice the speed is not recommended.',
           'fewer': 'Please choose fewer or other episodes.',
           'unnoticed': 'You will not hear the difference.',
           'slight': 'It is hardly noticeable.',
           'taste': 'That is a matter of taste.'},
}


def verdict(f, final=False, lang='de'):
    # (level, text) about a speed-up factor, for the page. final: the factor is measured, the
    # files get converted now ("wird ... abgespielt" instead of "würde ... abgespielt werden").
    say = VERDICTS[lang]
    percent = math.ceil(round((f - 1) * 1000, 6)) / 10     # rounded up to a tenth: never "0,0 %"
    if f <= 1:
        return 'fits', say['fits']
    faster = say['will' if final else 'would'].format(percent_text(percent, lang))
    if f > ADVISED_MAX:
        return 'too-much', faster + ' ' + say['too-much'] + ('' if final else ' ' + say['fewer'])
    if percent <= 10:                   # subjective, from listening: up to 10 % nobody notices,
        return 'unnoticed', faster + ' ' + say['unnoticed']
    if percent <= 20:                   # up to 20 % hardly anyone
        return 'slight', faster + ' ' + say['slight']
    return 'taste', faster + ' ' + say['taste']


def total_text(seconds, count, lang='de'):
    # the sum under the selection, in minutes like the Tonie's 89:59
    if lang == 'en':
        if count == 1:
            return 'The selected episode lasts {}. The Tonie holds {} minutes.'.format(minutes(seconds), minutes(TARGET))
        return 'The {} selected episodes last {} together. The Tonie holds {} minutes.'.format(
            number_word(count, lang), minutes(seconds), minutes(TARGET))
    if count == 1:
        return 'Die ausgewählte Folge dauert {}. Auf den Tonie passen {} Minuten.'.format(minutes(seconds), minutes(TARGET))
    return 'Die {} ausgewählten Folgen dauern zusammen {}. Auf den Tonie passen {} Minuten.'.format(
        number_word(count), minutes(seconds), minutes(TARGET))


NUMBER_WORDS = {
    'de': ['null', 'eine', 'zwei', 'drei', 'vier', 'fünf', 'sechs', 'sieben', 'acht', 'neun', 'zehn', 'elf', 'zwölf'],
    'en': ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'],
}


def number_word(n, lang='de'):
    # numbers up to twelve are written as words in texts: 3 -> 'drei' (or 'three'), 16 -> '16'
    words = NUMBER_WORDS[lang]
    return words[n] if 0 <= n < len(words) else str(n)


def decimal(x, digits, lang='de'):
    # 44.1 -> '44,1' in German, '44.1' in English
    text = '{:.{}f}'.format(x, digits)
    return text.replace('.', ',') if lang == 'de' else text


def percent_text(percent, lang='de'):
    # '5,6 %' in German (with a space), '5.6%' in English
    return decimal(percent, 1, lang) + (' %' if lang == 'de' else '%')


def clock(seconds):
    # 3606 -> '1:00:06', 1793 -> '29:53'
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return '{}:{:02d}:{:02d}'.format(h, m, s) if h else '{}:{:02d}'.format(m, s)


def minutes(seconds):
    # 4812 -> '80:12': lengths compared with the Tonie's 89:59 are given in minutes, like the Tonie
    seconds = int(round(seconds))
    return '{}:{:02d}'.format(seconds // 60, seconds % 60)


def date_text(iso, lang='de'):
    # '2026-11-25' -> 'Mi 25.11.2026' (German) or 'Wed 25 Nov 2026' (English)
    try:
        day = datetime.strptime(iso, '%Y-%m-%d')
    except ValueError:
        return iso
    if lang == 'en':
        month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][day.month - 1]
        return '{} {} {} {}'.format(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][day.weekday()], day.day, month, day.year)
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


def mix_name(selected, lang='de'):
    # one file for the whole selection: 'Maus-Tonie 2026-11-25 Wintertiere und 3 weitere.mp3'
    # (in English '... Wintertiere and 3 more.mp3')
    newest = max(e['date'] for e in selected)
    rest = len(selected) - 1
    name = 'Maus-Tonie {} {}'.format(newest, short_title(selected[0]))
    if rest and lang == 'en':
        name += ' and {} {}'.format(rest, 'more' if rest > 1 else 'more episode')
    elif rest:
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


def describe_formats(formats, lang='de'):
    # 'MP3 48 kHz stereo / MP3 44,1 kHz stereo': the different formats among the files
    names = []
    for f in formats:
        if f:
            rate = re.sub(r'[.,]0$', '', decimal(int(f[1]) / 1000, 1, lang))
            name = '{} {} kHz {}'.format(f[0].upper(), rate, f[2])
        else:
            name = 'unknown' if lang == 'en' else 'unbekannt'
        if name not in names:
            names.append(name)
    return ' / '.join(names)


def time_from_log(line):
    # ffmpeg's progress lines contain 'time=00:12:34.56'
    match = re.search(r'time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)', line)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def tempo_filter(f):
    # 'atempo=1.3'; above 2 a chain such as 'atempo=2.0,atempo=1.7': a single atempo takes up to 100,
    # but above 2 it skips samples instead of blending them (ffmpeg's documentation suggests the chain)
    steps = []
    while f > 2:
        steps.append(2.0)
        f /= 2
    return ','.join('atempo={}'.format(step) for step in steps + [f])


def convert_args(source, target, f, episode):
    # ffmpeg arguments: audio only (the files carry a cover picture), faster by f, mp3 again,
    # with the episode's title in the tags
    args = ['-hide_banner', '-nostdin', '-y', '-i', source, '-map', '0:a', '-map_metadata', '-1']
    if f != 1:
        args += ['-af', tempo_filter(f)]
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
