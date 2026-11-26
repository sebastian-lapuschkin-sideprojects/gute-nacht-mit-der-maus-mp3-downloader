import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import maus


class TestTempo(unittest.TestCase):
    def test_fits(self):
        self.assertEqual(maus.factor(3606 + 1206, 2), 1.0)
        self.assertEqual(maus.factor(maus.TARGET - 2, 2), 1.0)

    def test_faster_stays_below_target(self):
        for seconds, count in [(5610, 3), (6248, 2), (7212, 2), (5399, 1)]:
            f = maus.factor(seconds, count)
            self.assertGreater(f, 1)
            self.assertLessEqual((seconds + count) / f, maus.TARGET)
            f = maus.factor(seconds, count, measured=True)
            self.assertLessEqual((seconds + 0.1 * count) / f, maus.TARGET)

    def test_verdict(self):
        self.assertEqual(maus.verdict(1.0)[0], 'fits')
        self.assertEqual(maus.verdict(1.0001)[0], 'unnoticed')
        self.assertIn('0,1 %', maus.verdict(1.0001)[1])
        self.assertEqual(maus.verdict(1.05)[0], 'unnoticed')
        self.assertEqual(maus.verdict(1.0501)[0], 'slight')
        self.assertEqual(maus.verdict(1.10)[0], 'slight')
        self.assertEqual(maus.verdict(1.2)[0], 'taste')
        self.assertEqual(maus.verdict(2.1)[0], 'too-much')
        self.assertIn('würde um 20,0 % schneller abgespielt werden', maus.verdict(1.2)[1])
        self.assertIn('wird um 20,0 % schneller abgespielt.', maus.verdict(1.2, final=True)[1])
        self.assertIn('Bitte wähle weniger', maus.verdict(2.1)[1])
        self.assertIn('wird um 110,0 % schneller', maus.verdict(2.1, final=True)[1])     # not advised, but done
        self.assertNotIn('Bitte wähle weniger', maus.verdict(2.1, final=True)[1])

    def test_tempo_filter(self):
        self.assertEqual(maus.tempo_filter(1.25), 'atempo=1.25')
        self.assertEqual(maus.tempo_filter(2.0), 'atempo=2.0')
        self.assertEqual(maus.tempo_filter(3.4), 'atempo=2.0,atempo=1.7')
        self.assertEqual(maus.tempo_filter(5.0), 'atempo=2.0,atempo=2.0,atempo=1.25')
        self.assertTrue(maus.verdict(1.2)[1].endswith('Das ist Geschmackssache.'))

    def test_total_text(self):
        self.assertEqual(maus.total_text(4812, 3),
                         'Die drei ausgewählten Folgen dauern zusammen 80:12. Auf den Tonie passen 89:59 Minuten.')
        self.assertIn('Die 13 ausgewählten Folgen', maus.total_text(9000, 13))
        self.assertEqual(maus.total_text(3006, 1), 'Die ausgewählte Folge dauert 50:06. Auf den Tonie passen 89:59 Minuten.')


class TestText(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(maus.clock(3606), '1:00:06')
        self.assertEqual(maus.clock(1793), '29:53')
        self.assertEqual(maus.clock(5398.6), '1:29:59')
        self.assertEqual(maus.minutes(4812.5), '80:12')
        self.assertEqual(maus.minutes(maus.TARGET), '89:59')
        self.assertEqual(maus.minutes(12160), '202:40')

    def test_dates(self):
        self.assertEqual(maus.german_date('2026-11-25'), 'Mi 25.11.2026')

    def test_file_names(self):
        episode = {'title': 'Oma verbuddeln (1/2) | Familiengeschichte ab 8 Jahren', 'series': 'lang', 'date': '2026-09-11'}
        self.assertEqual(maus.file_name(episode, 3), '03 Oma verbuddeln (1-2) (MausHörspiel lang, 2026-09-11).mp3')
        other = {'title': 'Wintertiere', 'series': 'zumhoeren', 'date': '2026-11-25'}
        self.assertEqual(maus.mix_name([other, episode]), 'Maus-Tonie 2026-11-25 Wintertiere und 1 weitere Folge.mp3')

    def test_ffmpeg_log(self):
        log = 'Input #0, mp3\n  Duration: 01:00:06.17, start: 0.023021, bitrate: 129 kb/s\n'
        self.assertAlmostEqual(maus.duration_from_log(log), 3606.17)
        self.assertAlmostEqual(maus.time_from_log('size=  1024KiB time=00:12:34.56 bitrate=128.0kbits/s'), 754.56)
        self.assertIsNone(maus.duration_from_log('nothing'))

    def test_formats(self):
        log128 = '  Stream #0:0: Audio: mp3 (mp3float), 48000 Hz, stereo, fltp, 128 kb/s, start 0.023021\n'
        log160 = '  Stream #0:0: Audio: mp3 (mp3float), 48000 Hz, stereo, fltp, 160 kb/s\n'
        log44 = '  Stream #0:0: Audio: mp3 (mp3float), 44100 Hz, stereo, fltp, 128 kb/s\n'
        self.assertEqual(maus.audio_format(log128), ('mp3', '48000', 'stereo'))
        self.assertTrue(maus.joinable([maus.audio_format(log128), maus.audio_format(log160)]))
        self.assertFalse(maus.joinable([maus.audio_format(log128), maus.audio_format(log44)]))
        self.assertFalse(maus.joinable([maus.audio_format(log128), None]))
        self.assertFalse(maus.joinable([]))
        self.assertEqual(maus.describe_formats([maus.audio_format(log128), maus.audio_format(log44), maus.audio_format(log160)]),
                         'MP3 48 kHz stereo / MP3 44,1 kHz stereo')


class TestEpisodes(unittest.TestCase):
    def test_parse(self):
        answer = {'data': {
            'zumhoeren': {'items': {'nodes': [
                {'id': 1, 'title': 'Wintertiere', 'publishDate': '2026-11-25T06:00:06+01:00', 'duration': 3606,
                 'summary': 'Die Maus zum Hören - Lach- und Sachgeschichten. Heute: mit Wintertieren',
                 'audios': [{'url': 'https://example.org/a.mp3', 'downloadUrl': None}]}]}},
            'gutenacht': {'items': {'nodes': [
                {'id': 2, 'title': 'Trailer - Die Maus am Morgen', 'publishDate': '2026-09-30T06:00:00+02:00', 'duration': 60,
                 'summary': '', 'audios': [{'url': 'https://example.org/t.mp3'}]},
                {'id': 3, 'title': 'Ein wichtiger Hinweis', 'publishDate': '2026-07-19T06:00:00+02:00', 'duration': 31,
                 'summary': '', 'audios': [{'url': 'https://example.org/h.mp3'}]}]}},
            'kurz': None}}
        found = maus.episodes(answer)
        self.assertEqual([e['id'] for e in found], ['1'])
        self.assertEqual(found[0]['summary'], 'mit Wintertieren')
        self.assertEqual(found[0]['date'], '2026-11-25')
        self.assertEqual(maus.default_selection(found), ['1'])

    def test_query_names_all_series(self):
        q = maus.query()
        for key, pid, *_ in maus.SERIES:
            self.assertIn('{}: programSet(id: {})'.format(key, pid), q)


class TestStories(unittest.TestCase):
    def episode(self, i, title, date='2026-10-22', series='kurz', summary=''):
        return {'id': str(i), 'title': title, 'date': date, 'series': series, 'duration': 500, 'summary': summary}

    def test_parts(self):
        self.assertEqual(maus.part('Luftpiraten (15): Alles wird gut'), 15)
        self.assertEqual(maus.part('Eine lange Reise (3/5) I Tierliches ab 6 Jahren'), 3)
        self.assertEqual(maus.part('Detektei Cleo Fischer - Brunzi Dummbatz (Teil 2)'), 2)
        self.assertEqual(maus.part('Der Umstandsheini 03 von 05: Sport'), 3)
        self.assertEqual(maus.part('Luftpiraten - Teil 3: Kaspar, der Luftikus'), 3)
        self.assertEqual(maus.part('Teilen'), 0)

    def test_story_names(self):
        self.assertEqual(maus.story_name('Luftpiraten (15): Alles wird gut'), 'Luftpiraten')
        self.assertEqual(maus.story_name('KunstKrimi - Der Silvesterraub (1/2)'), 'KunstKrimi')
        self.assertEqual(maus.story_name('Kurt, das Einhorn: Rosen'), 'Kurt, das Einhorn')
        self.assertEqual(maus.story_name('Florentine Blix. Geheimakte Flaschenpost (1/2) | Spürnasen-Krimi'), 'Florentine Blix')
        self.assertEqual(maus.story_name('Der Umstandsheini Teil 05 von 05: Ein ungebetener Gast'), 'Der Umstandsheini')
        self.assertIsNone(maus.story_name('Heute fängt die Zukunft an | Musikalisches Hörspiel ab 6 Jahren'))
        self.assertIsNone(maus.story_name('Dr. Brumm geht baden'))

    def test_groups(self):
        found = [self.episode(1, 'Luftpiraten (2): Ein blinder Passagier'), self.episode(2, 'Luftpiraten (1): Das Luftpaket'),
                 self.episode(3, 'Ein Alien in Wiebelmund: Schule', '2025-06-01'), self.episode(4, 'EIn Alien in Wiebelmund: Urlaub', '2025-06-02'),
                 self.episode(5, 'Der Umstandsheini: Winterhose', '2024-01-01'), self.episode(6, 'Der Umstandsheini im Garten - 1 von 5 - Fugen', '2026-04-10'),
                 self.episode(7, 'Einzelstück: nur einmal'), self.episode(8, 'MausNachrichten vom 1. Mai: x', series='nachrichten'),
                 self.episode(9, 'MausNachrichten vom 2. Mai: y', series='nachrichten')]
        groups = {g['name']: g['ids'] for g in maus.stories(found)}
        self.assertEqual(groups, {'Luftpiraten': ['2', '1'], 'Ein Alien in Wiebelmund': ['3', '4'], 'Der Umstandsheini': ['5', '6']})
        self.assertEqual([g['name'] for g in maus.stories(found)], ['Luftpiraten', 'Der Umstandsheini', 'Ein Alien in Wiebelmund'])

    def test_orders_and_search(self):
        found = [self.episode(1, 'Luftpiraten (2): Ein blinder Passagier'), self.episode(2, 'Luftpiraten (10): In den Händen'),
                 self.episode(3, 'Luftpiraten (1): Das Luftpaket'), self.episode(4, 'Mozart', '2026-11-20', summary='dicke Luft')]
        self.assertEqual([e['id'] for e in maus.newest_first(found)], ['4', '2', '1', '3'])
        self.assertEqual([e['id'] for e in maus.listening_order(found)], ['3', '1', '2', '4'])
        self.assertEqual([e['id'] for e in found if maus.matches(e, 'luft')], ['1', '2', '3'])
        self.assertEqual([e['id'] for e in found if maus.matches(e, 'luft', in_summary=True)], ['1', '2', '3', '4'])
        self.assertEqual([e['id'] for e in found if maus.matches(e, 'LUFTPIRATEN paket')], ['3'])


if __name__ == '__main__':
    unittest.main()
