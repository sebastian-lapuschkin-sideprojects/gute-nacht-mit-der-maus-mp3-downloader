"""
The web page. Runs inside the browser (Pyodide); index.html loads it and calls start().

Left: the episodes of all series, as the ARD Audiothek lists them right now. Right: the selection,
its length, and how much faster it has to be played to fit into 89:59. The button downloads the
mp3 files from the WDR, converts them with ffmpeg.wasm (in the browser) and offers the results.

The page speaks German or English (the button at the top, see index.html). The texts written here
come from TEXT below, in the language the page has right now; when it changes, the page is drawn again.
"""

import asyncio
from html import escape

import js
from pyodide.ffi import create_proxy, to_js
from pyodide.http import pyfetch

import maus

CORE = 'https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/umd/'   # ffmpeg itself (32 MB, cached by the browser)
PAGE = 25          # episodes shown at first, and added by "mehr anzeigen" ("show more")
WORKERS = 3        # ffmpeg instances at most; each runs in its own thread and converts one file at a time
DOWNLOADS = 3      # files downloaded at the same time
CACHE_LIMIT = 1.5e9 # bytes of downloaded and converted files kept for later runs (see "files kept between runs")

# the tabs: one per series, and all of them together
TABS = [(key, title, about) for key, _, title, about, _ in maus.SERIES] + [
    ('alle', {'de': 'Alle Reihen', 'en': 'All series'},
     {'de': 'Hier stehen die Folgen aller Reihen zusammen, die neuesten zuerst.',
      'en': 'Here you find the episodes of all series together, the newest first.'})]

STORIES = 12       # story buttons shown before "weitere"

state = {'episodes': [], 'by_id': {}, 'selected': [], 'series': 'zumhoeren', 'shown': {}, 'query': '', 'in_summary': False,
         'stories': [], 'story': None, 'all_stories': False, 'busy': False, 'urls': [],
         'cache': {}, 'measured': {}, 'used': set()}


# ---------------------------------------------------------------------------- the texts

TEXT = {
    # the list of episodes
    'story count': ('{} Folgen, zusammen {}', '{} episodes, {} in total'),
    'fewer': ('weniger', 'fewer'),
    'more stories': ('{} weitere', '{} more'),
    'story series': ('Hörspiel-Reihen', 'Audio play series'),
    'picked': ('ausgewählt', 'selected'),
    'story about': ('Zu „{}“ gibt es hier {} Folgen, die zusammen {} dauern. Sie stehen in der Reihenfolge zum Hören.',
                    'There are {1} episodes of “{0}” here, which last {2} together. They are listed in the order to listen to them.'),
    'choose': ('{} auswählen', 'select {}'),
    'no match': ('Für „{}“ gibt es keine Treffer.', 'There are no results for “{}”.'),
    'none here': ('Gerade gibt es hier keine Folgen.', 'There are no episodes here right now.'),
    'choose shown': ('alle {} angezeigten auswählen', 'select all {} shown'),
    'choose one shown': ('die angezeigte Folge auswählen', 'select the episode shown'),
    'loading list': ('Die Folgenliste wird geladen ...', 'Loading the episode list ...'),
    'no answer': ('Die ARD Audiothek antwortet gerade nicht. Bitte versuche es später noch einmal.',
                  'The ARD Audiothek is not responding right now. Please try again later.'),
    'no episodes': ('Keine Folgen', 'No episodes'),
    # the selection
    'forward': ('nach vorne', 'move up'),
    'back': ('nach hinten', 'move down'),
    'remove': ('entfernen', 'remove'),
    'nothing chosen': ('Es ist noch nichts ausgewählt. Klicke in der Liste auf Folgen, um sie hinzuzufügen.',
                       'Nothing is selected yet. Click on episodes in the list to add them.'),
    'to bottom': ('nach unten zum Speichern', 'down to the download'),
    'to bottom picked': ('nach unten zum Speichern ({} ausgewählt)', 'down to the download ({} selected)'),
    'download': ('Herunterladen', 'Download'),
    'convert': ('Umrechnen und herunterladen', 'Convert and download'),
    'one moment': ('Einen Moment bitte ...', 'One moment, please ...'),
    'measured': ('Genau gemessen dauern die Folgen zusammen {}.', 'Measured exactly, the episodes last {} together.'),
    # the progress list
    'load ffmpeg': ('ffmpeg laden', 'load ffmpeg'),
    'join row': ('zu einer Datei zusammenfügen', 'join into one file'),
    'waiting': ('wartet', 'waiting'),
    'kept source': ('schon geladen ({})', 'already loaded ({})'),
    'retry': ('neuer Versuch ...', 'trying again ...'),
    'loading': ('lädt ...', 'loading ...'),
    'loading percent': ('lädt {} %', 'loading {}%'),
    'loaded': ('geladen ({})', 'loaded ({})'),
    'loading ffmpeg': ('lädt (beim ersten Mal 32 MB) ...', 'loading (32 MB the first time) ...'),
    'ready': ('bereit', 'ready'),
    'converting': ('wird umgerechnet {} %', 'converting {}%'),
    'done': ('fertig ({})', 'done ({})'),
    'kept done': ('schon fertig ({})', 'already done ({})'),
    'joining': ('fügt zusammen ...', 'joining ...'),
    'not needed': ('nicht nötig', 'not needed'),
    'formats differ': ('Die Folgen haben unterschiedliche Audioformate ({}). Sie werden deshalb einmal umgerechnet. '
                       'Das dauert etwas länger als das reine Zusammenfügen.',
                       'The episodes have different audio formats ({}). They are therefore converted once, '
                       'which takes a little longer than just joining them.'),
    'upload': ('Lade die Dateien dann wie gewohnt über die Tonie-App oder my.tonies.com auf deinen Kreativ-Tonie.',
               'Then upload the files to your Creative-Tonie as usual, with the Tonies app or on my.tonies.com.'),
    # what can go wrong
    'download failed': ('„{}“ ließ sich nicht vom WDR-Server laden. Bitte versuche es später noch einmal.',
                        '“{}” could not be loaded from the WDR server. Please try again later.'),
    'convert failed': ('ffmpeg konnte „{}“ nicht umrechnen.', 'ffmpeg could not convert “{}”.'),
    'join failed': ('ffmpeg konnte die Teile nicht zusammenfügen.', 'ffmpeg could not join the parts.'),
    'failed': ('Da ist etwas schiefgegangen: {}', 'Something went wrong: {}'),
}


def lang():
    # the language of the page right now (index.html sets it, and the button at the top changes it)
    chosen = js.document.documentElement.lang
    return chosen if chosen in maus.LANGS else 'de'


def t(key, *args):
    # a text in the page's language
    return TEXT[key][maus.LANGS.index(lang())].format(*args)


def both(key, *args):
    # a text in both languages, as HTML: the page shows the one that is chosen (style.css). For what
    # is written once and not drawn again, such as the progress list.
    return ''.join('<span lang="{}">{}</span>'.format(code, escape(text.format(*args)))
                   for code, text in zip(maus.LANGS, TEXT[key]))


def pick(value):
    # a name that is the same in both languages, or {'de': ..., 'en': ...}
    return value[lang()] if isinstance(value, dict) else value


class Problem(Exception):
    # something that went wrong, said in both languages
    def __init__(self, key, *args):
        super().__init__(TEXT[key][0].format(*args))
        self.html = both(key, *args)


def el(name):
    return js.document.getElementById(name)


def js_object(d):
    return to_js(d, dict_converter=js.Object.fromEntries)


def output_mode():
    return js.document.querySelector('input[name="output"]:checked').value     # 'parts' or 'single'


def selection():
    return [state['by_id'][i] for i in state['selected']]


def megabytes(n):
    return '{:.0f} MB'.format(n / 1e6)


# ---------------------------------------------------------------------------------- the page

def render():
    render_tabs()
    render_stories()
    render_episodes()
    render_selection()


def searching():
    return bool(state['query'].strip())


def story():
    return next((g for g in state['stories'] if g['key'] == state['story']), None)


def in_tab(e, tab):
    return tab == 'alle' or e['series'] == tab


def listed(tab):
    # the episodes of a tab that match the search (and belong to the chosen story, in listening order)
    found = [e for e in state['episodes'] if in_tab(e, tab) and maus.matches(e, state['query'], state['in_summary'])]
    if story():
        ids = set(story()['ids'])
        return maus.listening_order([e for e in found if e['id'] in ids])
    return maus.newest_first(found) if tab == 'alle' else found


def visible():
    # what the list shows: while searching (or showing a story) all matches, otherwise the newest
    # ones ("show more" adds more)
    found = listed(state['series'])
    return found if searching() or story() else found[:state['shown'].get(state['series'], PAGE)]


def render_stories():
    # buttons for the stories and series of Hörspiele in this tab, newest first
    groups = [g for g in state['stories'] if any(in_tab(state['by_id'][i], state['series']) for i in g['ids'])]
    box = el('stories')
    box.hidden = not groups
    if not groups:
        return
    shown = groups if state['all_stories'] else groups[:STORIES]
    if story() and story() not in shown:
        shown = shown + [story()]
    buttons = ['<button data-action="story" data-key="{}" class="{}" title="{}">{} <span class="count">{}</span></button>'.format(
        escape(g['key']), 'on' if g['key'] == state['story'] else '', t('story count', len(g['ids']), maus.clock(g['seconds'])),
        escape(g['name']), len(g['ids'])) for g in shown]
    if len(groups) > STORIES:
        buttons.append('<button class="more" data-action="stories">{}</button>'.format(
            t('fewer') if state['all_stories'] else t('more stories', len(groups) - STORIES)))
    box.innerHTML = '<span class="cap">{}</span>'.format(t('story series')) + ''.join(buttons)


def render_tabs():
    buttons = []
    for key, title, _ in TABS:
        picked = sum(1 for e in selection() if key == 'alle' or e['series'] == key)
        buttons.append('<button data-action="series" data-key="{}" class="{}">{} <span class="count">{}</span>{}</button>'.format(
            key, 'on' if key == state['series'] else '', escape(pick(title)), len(listed(key)),
            '<span class="picked" title="{}">{}</span>'.format(t('picked'), picked) if picked else ''))
    el('series').innerHTML = ''.join(buttons)
    if story():
        el('about').textContent = t('story about', story()['name'], maus.number_word(len(story()['ids']), lang()),
                                    maus.clock(story()['seconds']))
    else:
        el('about').textContent = pick(next(about for key, _, about in TABS if key == state['series']))


def render_episodes():
    shown = visible()
    every = state['series'] == 'alle'
    rows = []
    for e in shown:
        on = e['id'] in state['selected']
        rows.append(
            '<li class="episode{}" data-action="toggle" data-id="{}">'
            '<input type="checkbox"{} aria-label="{}">'
            '<div><div class="title">{}</div><div class="meta">{}{}</div></div>'
            '<span class="dur">{}</span><p class="summary">{}</p></li>'.format(
                ' on' if on else '', e['id'], ' checked' if on else '', escape(t('choose', e['title'])), escape(e['title']),
                escape(maus.TITLES[e['series']]) + ' · ' if every else '', maus.date_text(e['date'], lang()),
                maus.minutes(e['duration']), escape(e['summary'])))
    empty = escape(t('no match', state['query'].strip()) if searching() else t('none here'))
    el('episodes').innerHTML = ''.join(rows) or '<li class="note">{}</li>'.format(empty)
    el('more').hidden = searching() or len(shown) >= len(listed(state['series']))

    # "alle angezeigten auswählen" ("select all shown"): checked if all of them are selected, half if some are
    picked = sum(1 for e in shown if e['id'] in state['selected'])
    box = el('all')
    box.disabled = not shown
    box.checked = bool(shown) and picked == len(shown)
    box.indeterminate = 0 < picked < len(shown)
    el('all-label').textContent = t('choose shown', len(shown)) if len(shown) != 1 else t('choose one shown')
    on_scroll()         # the page may have become shorter or longer


def render_selection():
    chosen = selection()
    rows = []
    for n, e in enumerate(chosen):
        rows.append(
            '<li><div><div class="title">{}</div><div class="meta">{} · {} · {}</div></div><span class="moves">'
            '<button data-action="up" data-id="{id}" title="{up}" aria-label="{up}"{}>↑</button>'
            '<button data-action="down" data-id="{id}" title="{down}" aria-label="{down}"{}>↓</button>'
            '<button data-action="toggle" data-id="{id}" title="{remove}" aria-label="{remove}">✕</button>'
            '</span></li>'.format(
                escape(e['title']), escape(maus.TITLES[e['series']]), maus.date_text(e['date'], lang()), maus.minutes(e['duration']),
                ' disabled' if n == 0 else '', ' disabled' if n == len(chosen) - 1 else '', id=e['id'],
                up=t('forward'), down=t('back'), remove=t('remove')))
    el('selected').innerHTML = ''.join(rows) or '<li class="empty">{}</li>'.format(t('nothing chosen'))
    count = el('jump-count')       # the number of selected episodes, also on the floating "down" button
    count.textContent = str(len(chosen))
    count.hidden = not chosen
    el('to-bottom').title = t('to bottom picked', len(chosen)) if chosen else t('to bottom')

    seconds = sum(e['duration'] for e in chosen)
    f = maus.factor(seconds, len(chosen))
    scale = max(seconds, maus.TARGET)
    el('fill').style.width = '{}%'.format(100 * min(seconds, maus.TARGET) / scale)
    el('over').style.left = '{}%'.format(100 * maus.TARGET / scale)
    el('over').style.width = '{}%'.format(100 * max(0, seconds - maus.TARGET) / scale)
    el('mark').style.left = 'calc({}% - 1px)'.format(100 * maus.TARGET / scale)
    el('sum').textContent = maus.total_text(seconds, len(chosen), lang()) if chosen else ''
    level, text = maus.verdict(f, lang=lang())
    el('verdict').className = 'verdict ' + level
    el('verdict').textContent = text if chosen else ''

    button = el('convert')
    if not state['busy']:
        button.disabled = not chosen
        button.textContent = t('download') if f == 1 else t('convert')     # (f == 1: only joined, if at all)
    on_scroll()


def on_click(event):
    target = event.target.closest('[data-action]')
    if not target:
        return
    action, key = target.getAttribute('data-action'), target.getAttribute('data-id')   # (dataset.id raises if missing)
    if action in ('top', 'bottom'):
        top = 0 if action == 'top' else js.document.documentElement.scrollHeight
        js.window.scrollTo(js_object({'top': top, 'behavior': 'smooth'}))
        return
    if action == 'convert':
        asyncio.ensure_future(convert())
        return
    if state['busy']:
        return          # the selection stays as it is while it is being converted
    if action == 'series':
        state['series'] = target.getAttribute('data-key')
        if story() and not any(in_tab(state['by_id'][i], state['series']) for i in story()['ids']):
            state['story'] = None
    elif action == 'story':
        # show one story (a second click shows everything again); the search starts afresh
        chosen = target.getAttribute('data-key')
        state['story'] = None if chosen == state['story'] else chosen
        state['query'] = el('search').value = ''
    elif action == 'stories':
        state['all_stories'] = not state['all_stories']
    elif action == 'more':
        state['shown'][state['series']] = state['shown'].get(state['series'], PAGE) + PAGE
    elif action == 'toggle':
        if key in state['selected']:
            state['selected'].remove(key)
        else:
            state['selected'].append(key)
    elif action == 'selectall':
        # all shown ones selected: unselect them; otherwise add the missing ones in listening order
        shown = visible()
        if all(e['id'] in state['selected'] for e in shown):
            state['selected'] = [i for i in state['selected'] if i not in {e['id'] for e in shown}]
        else:
            state['selected'] += [e['id'] for e in maus.listening_order(shown) if e['id'] not in state['selected']]
    elif action in ('up', 'down'):
        i = state['selected'].index(key)
        j = i - 1 if action == 'up' else i + 1
        if 0 <= j < len(state['selected']):
            state['selected'][i], state['selected'][j] = state['selected'][j], state['selected'][i]
    render()


def on_change(event):
    if event.target.name == 'output':
        render_selection()
    elif event.target.id == 'in-summary':
        state['in_summary'] = bool(event.target.checked)
        render_tabs()
        render_episodes()


def on_scroll(event=None):
    # the floating buttons: "up" once the page is scrolled a bit, "down" until its end is reached
    y, seen, height = js.window.scrollY, js.window.innerHeight, js.document.documentElement.scrollHeight
    el('to-top').classList.toggle('hide', y < 300)
    el('to-bottom').classList.toggle('hide', y + seen > height - 120)


def on_lang(event):
    # the language has changed: everything drawn by render() is drawn again in the new one
    # (the progress list and the downloads have both languages already)
    if state['episodes']:
        render()


def on_input(event):
    if event.target.id == 'search':
        state['query'] = event.target.value
        render_tabs()
        render_episodes()


async def start():
    js.document.addEventListener('click', create_proxy(on_click))
    js.document.addEventListener('change', create_proxy(on_change))
    js.document.addEventListener('input', create_proxy(on_input))
    js.document.addEventListener('maus-lang', create_proxy(on_lang))
    for name in ('scroll', 'resize'):
        js.window.addEventListener(name, create_proxy(on_scroll), js_object({'passive': True}))
    el('episodes').innerHTML = '<li class="note">{}</li>'.format(both('loading list'))
    try:
        response = await pyfetch(maus.query_url())
        state['episodes'] = maus.episodes(await response.json())
    except Exception as error:
        js.console.error(str(error))
    if not state['episodes']:
        el('episodes').innerHTML = '<li class="note">{}</li>'.format(both('no answer'))
        el('convert').innerHTML = both('no episodes')
        return
    state['by_id'] = {e['id']: e for e in state['episodes']}
    state['stories'] = maus.stories(state['episodes'])
    state['selected'] = maus.default_selection(state['episodes'])
    render()


# ------------------------------------------------------------------------------- the progress list

def show_progress(rows):
    # rows: what each line is about, as HTML
    el('progress').innerHTML = ''.join(
        '<li id="p{}"><div class="what"><span>{}</span><span class="state">{}</span></div>'
        '<div class="bar"><div></div></div></li>'.format(n, html, both('waiting')) for n, html in enumerate(rows))


def progress(row, fraction, key, *args, done=False):
    # how far a line is, and what it says (TEXT[key], in both languages)
    item = el('p{}'.format(row))
    if item is None:
        return
    item.querySelector('.state').innerHTML = both(key, *args)
    item.querySelector('.bar div').style.width = '{:.1f}%'.format(100 * max(0, min(1, fraction)))
    if done:
        item.classList.add('done')


# -------------------------------------------------------------------- files kept between runs
# Downloads, converted episodes and joined files stay in the page (as Blobs) for later runs, so that
# switching between one file per episode and one single file, reordering, or removing and adding
# episodes only downloads and converts what is new. The keys say what a file is made of:
#   'src:<id>'                the episode's mp3 file from the WDR
#   'out:<id>@<factor>'       that file, played <factor> times as fast (the result depends on nothing else)
#   'mix:<part>|<part>|...'   these parts (src: or out: keys), joined in this order
# The exact lengths and audio formats measured by ffmpeg are kept per episode in state['measured'].
# When the files together grow beyond CACHE_LIMIT, the ones used longest ago go, but never those of
# the last run.

def cached(key):
    blob = state['cache'].pop(key, None)
    if blob is not None:
        state['cache'][key] = blob          # the most recently used ones last
        state['used'].add(key)
    return blob


def keep(key, blob):
    state['cache'].pop(key, None)
    state['cache'][key] = blob
    state['used'].add(key)
    return blob


def trim_cache():
    total = sum(blob.size for blob in state['cache'].values())
    for key in list(state['cache']):
        if total <= CACHE_LIMIT:
            break
        if key not in state['used']:
            total -= state['cache'].pop(key).size


def to_blob(data):
    return js.Blob.new(to_js([data]), js_object({'type': 'audio/mpeg'}))


async def file_data(blob):
    # a fresh copy for ffmpeg: writeFile hands the buffer over to the worker, the Blob stays as it is
    return js.Uint8Array.new(await blob.arrayBuffer())


def plan_for(chosen, single):
    # What the result is made of, once the exact lengths of all episodes are known (else None):
    # the factor, the measured length, the key of every part and, for one single file, of the mix.
    if any(e['id'] not in state['measured'] for e in chosen):
        return None
    seconds = sum(state['measured'][e['id']][0] for e in chosen)
    formats = [state['measured'][e['id']][1] for e in chosen]
    f = maus.factor(seconds, len(chosen), measured=True)
    as_they_are = f == 1 and (not single or maus.joinable(formats))      # the WDR files themselves
    parts = ['src:{}'.format(e['id']) if as_they_are else 'out:{}@{}'.format(e['id'], f) for e in chosen]
    return {'f': f, 'seconds': seconds, 'formats': formats, 'parts': parts,
            'mix': 'mix:' + '|'.join(parts) if single else None}


def length(episode, plan):
    # the episode's length in the result
    return state['measured'][episode['id']][0] / plan['f']


# ------------------------------------------------------------------------- download and convert

async def source(episode, row, limit):
    # the episode's mp3 file from the WDR as a Blob: kept from an earlier run, or downloaded now
    key = 'src:{}'.format(episode['id'])
    blob = cached(key)
    if blob is not None:
        progress(row, 1, 'kept source', megabytes(blob.size))
        return blob
    return keep(key, await download(episode, row, limit))


async def download(episode, row, limit):
    # the mp3 file as a Blob; two more tries if the connection breaks off
    async with limit:
        for attempt in range(3):
            try:
                return await download_once(episode, row)
            except Exception as error:
                js.console.warn('download {}: {}'.format(episode['url'], error))
                if attempt == 2:
                    raise Problem('download failed', episode['title'])
                progress(row, 0, 'retry')
                await asyncio.sleep(2)


async def download_once(episode, row):
    progress(row, 0, 'loading')
    response = await js.fetch(episode['url'])      # no extra headers: the WDR server allows plain GETs only
    if not response.ok:
        raise RuntimeError('error {}'.format(response.status))
    size = int(response.headers.get('content-length') or 0)
    reader = response.body.getReader()
    chunks, got = js.Array.new(), 0
    while True:
        part = await reader.read()
        if part.done:
            break
        chunks.push(part.value)
        got += part.value.length
        if size:
            progress(row, got / size, 'loading percent', int(100 * got / size))
    blob = js.Blob.new(chunks, js_object({'type': 'audio/mpeg'}))
    progress(row, 1, 'loaded', megabytes(blob.size))
    return blob


async def new_ffmpeg():
    ff = js.FFmpegWASM.FFmpeg.new()
    worker = {'ff': ff, 'log': [], 'on_time': None}

    def on_log(event):
        worker['log'].append(event.message)
        if worker['on_time']:
            t = maus.time_from_log(event.message)
            if t is not None:
                worker['on_time'](t)

    worker['proxy'] = create_proxy(on_log)
    ff.on('log', worker['proxy'])
    await ff.load(js_object({'coreURL': CORE + 'ffmpeg-core.js', 'wasmURL': CORE + 'ffmpeg-core.wasm'}))
    return worker


async def load(count, workers, row):
    progress(row, 0, 'loading ffmpeg')
    workers.extend(await asyncio.gather(*[new_ffmpeg() for _ in range(count)]))
    progress(row, 1, 'ready', done=True)


async def run(worker, args):
    worker['log'] = []
    code = await worker['ff'].exec(to_js(args))
    return code, '\n'.join(worker['log'])


async def measure(worker, episode, blob, row):
    # the exact length and audio format of an episode's file, measured once by ffmpeg
    name = 'm{}.mp3'.format(row)
    await worker['ff'].writeFile(name, await file_data(blob))
    log = (await run(worker, ['-hide_banner', '-i', name]))[1]
    await worker['ff'].deleteFile(name)
    state['measured'][episode['id']] = (maus.duration_from_log(log) or episode['duration'], maus.audio_format(log))


async def convert_on(worker, jobs, plan):
    # one worker converts its share of the files, one after the other, and keeps the results
    for job in jobs:
        e, row, seconds = job['episode'], job['row'], length(job['episode'], plan)
        await worker['ff'].writeFile('in.mp3', await file_data(job['source']))
        worker['on_time'] = lambda t, row=row, seconds=seconds: progress(
            row, t / seconds, 'converting', min(99, int(100 * t / seconds)))
        code, log = await run(worker, maus.convert_args('in.mp3', 'out.mp3', plan['f'], e))
        worker['on_time'] = None
        await worker['ff'].deleteFile('in.mp3')
        if code != 0:
            js.console.error(log)
            raise Problem('convert failed', e['title'])
        keep(job['key'], to_blob(await worker['ff'].readFile('out.mp3')))
        await worker['ff'].deleteFile('out.mp3')
        progress(row, 1, 'done', maus.minutes(seconds), done=True)


async def join(worker, chosen, plan, row):
    # one single file: the parts one after the other, without converting them again
    progress(row, 0, 'joining')
    names = []
    for n, key in enumerate(plan['parts']):
        names.append('part{}.mp3'.format(n))
        await worker['ff'].writeFile(names[-1], await file_data(cached(key)))
    await worker['ff'].writeFile('parts.txt', maus.concat_list(names))
    name = maus.mix_name(chosen, lang())
    code, log = await run(worker, maus.concat_args('parts.txt', 'mix.mp3', name[:-4]))
    for part in names:
        await worker['ff'].deleteFile(part)
    if code != 0:
        js.console.error(log)
        raise Problem('join failed')
    blob = keep(plan['mix'], to_blob(await worker['ff'].readFile('mix.mp3')))
    await worker['ff'].deleteFile('mix.mp3')
    seconds = plan['seconds'] / plan['f']
    progress(row, 1, 'done', maus.minutes(seconds), done=True)
    offer(name, blob, maus.minutes(seconds))


def offer(name, blob, note):
    url = js.URL.createObjectURL(blob)
    state['urls'].append(url)
    link = js.document.createElement('a')
    link.href, link.download = url, name
    link.innerHTML = '⤓ {}<small>{}, {}</small>'.format(escape(name), note, megabytes(blob.size))
    el('downloads').appendChild(link)


def show_measured(plan):
    el('verdict').textContent = t('measured', maus.minutes(plan['seconds'])) + ' ' + maus.verdict(plan['f'], final=True, lang=lang())[1]


def offer_kept_mix(chosen, plan, ffmpeg_row, join_row):
    # one single file made earlier from the same parts in the same order: offered right away
    blob = cached(plan['mix']) if plan['mix'] else None
    if blob is None:
        return False
    seconds = plan['seconds'] / plan['f']
    for row, e in enumerate(chosen):
        progress(row, 1, 'kept done', maus.minutes(length(e, plan)), done=True)
    progress(ffmpeg_row, 1, 'not needed', done=True)
    progress(join_row, 1, 'kept done', maus.minutes(seconds), done=True)
    offer(maus.mix_name(chosen, lang()), blob, maus.minutes(seconds))
    return True


async def convert():
    chosen = selection()
    single = output_mode() == 'single'
    if state['busy'] or not chosen:
        return
    state['busy'] = True
    state['used'] = set()
    button = el('convert')
    button.disabled = True
    button.classList.add('busy')
    button.textContent = t('one moment')
    for url in state['urls']:
        js.URL.revokeObjectURL(url)
    state['urls'] = []
    el('downloads').innerHTML = ''
    workers = []
    try:
        await make(chosen, single, workers)
        done = js.document.createElement('p')
        done.className = 'hint'
        done.innerHTML = both('upload')
        el('downloads').appendChild(done)
    except Exception as error:
        js.console.error(str(error))
        failed = js.document.createElement('li')
        failed.className = 'error'
        failed.innerHTML = error.html if isinstance(error, Problem) else both('failed', str(error))
        el('progress').appendChild(failed)
    finally:
        for worker in workers:
            worker['ff'].terminate()
            worker['proxy'].destroy()
        trim_cache()
        state['busy'] = False
        button.classList.remove('busy')
        render_selection()


async def make(chosen, single, workers):
    n = len(chosen)
    limit = asyncio.Semaphore(DOWNLOADS)
    estimate = maus.factor(sum(e['duration'] for e in chosen), n)
    if estimate == 1 and not single:
        # fits as it is: the WDR files themselves, only renamed and numbered
        show_progress([escape(e['title']) for e in chosen])
        blobs = await asyncio.gather(*[source(e, row, limit) for row, e in enumerate(chosen)])
        for row, (e, blob) in enumerate(zip(chosen, blobs)):
            progress(row, 1, 'done', maus.minutes(e['duration']), done=True)
            offer(maus.file_name(e, row + 1), blob, maus.minutes(e['duration']))
        return

    show_progress([escape(e['title']) for e in chosen] + [both('load ffmpeg')] + ([both('join row')] if single else []))
    ffmpeg_row, join_row = n, n + 1
    plan = plan_for(chosen, single)       # known if all episodes were measured in earlier runs
    if plan:
        show_measured(plan)
        if offer_kept_mix(chosen, plan, ffmpeg_row, join_row):
            return

    # what is missing: everything while some lengths are unknown, else the parts not kept from earlier runs
    need = list(range(n)) if plan is None else [row for row in range(n) if cached(plan['parts'][row]) is None]
    for row in range(n):
        if row not in need:
            progress(row, 1, 'kept done', maus.minutes(length(chosen[row], plan)), done=True)
    if plan is None:
        count = 1 if estimate == 1 else min(WORKERS, n)       # a selection that fits probably only needs joining
    else:
        count = min(WORKERS, sum(1 for row in need if plan['parts'][row].startswith('out:'))) or (1 if single else 0)
    loading = asyncio.ensure_future(load(count, workers, ffmpeg_row)) if count else None    # ffmpeg loads while the files download
    if not count:
        progress(ffmpeg_row, 1, 'not needed', done=True)
    try:
        sources = dict(zip(need, await asyncio.gather(*[source(chosen[row], row, limit) for row in need])))
    finally:
        if loading:
            await loading

    if plan is None:
        # every file not measured yet goes to one worker, which measures its exact length and format
        unmeasured = [row for row in range(n) if chosen[row]['id'] not in state['measured']]

        async def measure_share(worker, rows):
            for row in rows:
                await measure(worker, chosen[row], sources[row], row)

        await asyncio.gather(*[measure_share(worker, unmeasured[i::len(workers)]) for i, worker in enumerate(workers)])
        plan = plan_for(chosen, single)
        show_measured(plan)
        if offer_kept_mix(chosen, plan, ffmpeg_row, join_row):
            return

    # the parts still missing are converted ones (the WDR files themselves are kept by now)
    todo = [row for row in range(n) if cached(plan['parts'][row]) is None]
    for row in need:
        if row not in todo:
            progress(row, 1, 'done', maus.minutes(length(chosen[row], plan)), done=True)
    if todo and plan['f'] == 1 and single:
        # different sample rates or channels: mp3 files like that cannot simply be put one after the other
        info = js.document.createElement('li')
        info.className = 'info'
        info.innerHTML = ''.join('<span lang="{}">{}</span>'.format(code, escape(TEXT['formats differ'][i].format(
            maus.describe_formats(plan['formats'], code)))) for i, code in enumerate(maus.LANGS))
        el('progress').prepend(info)
    jobs = [[] for _ in workers]
    for i, row in enumerate(todo):
        jobs[i % len(workers)].append({'row': row, 'episode': chosen[row], 'source': sources[row], 'key': plan['parts'][row]})
    await asyncio.gather(*[convert_on(worker, share, plan) for worker, share in zip(workers, jobs) if share])

    if not single:
        for row, e in enumerate(chosen):
            offer(maus.file_name(e, row + 1), cached(plan['parts'][row]), maus.minutes(length(e, plan)))
        return
    await join(workers[0], chosen, plan, join_row)
