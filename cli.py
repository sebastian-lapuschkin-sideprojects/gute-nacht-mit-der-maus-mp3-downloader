"""
The web page's job on the command line (needs ffmpeg installed). Examples:

    python cli.py list                       (all episodes that can be downloaded now)
    python cli.py list kurz gutenacht        (only these series: zumhoeren kurz lang gutenacht nachrichten)
    python cli.py convert                    (the newest "Die Maus zum Hören", as on the page)
    python cli.py convert 11615465 11603321 --single -o toniefied
"""

import os
import sys
import json
import argparse
import subprocess
import urllib.request

import maus

USER_AGENT = 'gute-nacht-mit-der-maus (https://github.com/sebastian-lapuschkin-sideprojects/gute-nacht-mit-der-maus-mp3-downloader)'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def all_episodes():
    return maus.episodes(json.loads(fetch(maus.query_url())))


def ffmpeg(args):
    result = subprocess.run(['ffmpeg'] + args, capture_output=True, text=True)
    return result.stderr


def show(args):
    found = [e for e in all_episodes() if not args.series or e['series'] in args.series]
    for e in found:
        print('{:>9}  {:<12} {}  {:>7}  {}'.format(e['id'], e['series'], e['date'], maus.clock(e['duration']), e['title']))


def convert(args):
    found = {e['id']: e for e in all_episodes()}
    ids = args.ids or maus.default_selection(list(found.values()))
    missing = [i for i in ids if i not in found]
    if missing:
        sys.exit('not available (any more): ' + ' '.join(missing))
    selected = [found[i] for i in ids]
    os.makedirs(args.output, exist_ok=True)

    sources, seconds, formats = [], 0, []
    for e in selected:
        source = os.path.join(args.output, '.source-{}.mp3'.format(e['id']))
        print('downloading', e['title'], '...')
        with open(source, 'wb') as f:
            f.write(fetch(e['url']))
        sources.append(source)
        log = ffmpeg(['-hide_banner', '-i', source])
        seconds += maus.duration_from_log(log)
        formats.append(maus.audio_format(log))

    f = maus.factor(seconds, len(selected), measured=True)
    print('together {}: {}'.format(maus.clock(seconds), maus.verdict(f)[1]))
    if f > maus.MAX_FACTOR:
        sys.exit(1)

    parts = []
    for number, (e, source) in enumerate(zip(selected, sources), 1):
        part = os.path.join(args.output, maus.file_name(e, number))
        if f == 1 and (not args.single or maus.joinable(formats)):
            os.replace(source, part)      # fits as it is: nothing to convert, only renamed (and joined below)
        else:
            print('converting', os.path.basename(part), '...')
            ffmpeg(maus.convert_args(source, part, f, e))
            os.remove(source)
        parts.append(part)

    if args.single:
        mix = os.path.join(args.output, maus.mix_name(selected))
        listing = os.path.join(args.output, '.parts.txt')
        with open(listing, 'w', encoding='utf-8') as out:
            out.write(maus.concat_list([os.path.abspath(p) for p in parts]))
        ffmpeg(maus.concat_args(listing, mix, os.path.basename(mix)[:-4]))
        for p in parts + [listing]:
            os.remove(p)
        parts = [mix]

    for p in parts:
        print('written: {} ({})'.format(p, maus.clock(maus.duration_from_log(ffmpeg(['-hide_banner', '-i', p])))))


def main():
    parser = argparse.ArgumentParser(description='Maus episodes for the Creative-Tonie (at most 89:59).')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('list', help='list the episodes that can be downloaded now')
    p.add_argument('series', nargs='*', help='only these series: ' + ' '.join(key for key, *_ in maus.SERIES))
    p.set_defaults(run=show)
    p = commands.add_parser('convert', help='download episodes and bring them to at most 89:59')
    p.add_argument('ids', nargs='*', help='episode ids (see list); default: the newest "Die Maus zum Hören"')
    p.add_argument('--single', action='store_true', help='one file instead of one file per episode')
    p.add_argument('-o', '--output', default='toniefied', help='output directory (default: toniefied)')
    p.set_defaults(run=convert)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
