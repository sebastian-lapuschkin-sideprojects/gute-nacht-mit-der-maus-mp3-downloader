"""
(1) Takes the podcast and music mp3 files corresponding to a given date string (which usually are topically aligned),
(2) measures their length in time (slightly over 90 minutes in length when added up)
(3) and then uses ffmpeg to change playback speed to get just under 90 minutes of play time.
(4) the end result can then be uploaded conveniently to a "Creative-Tonie" (with 90min capacity) for Toniebox-playback. see https://tonies.com/en-gb/creative-tonies/
"""

import os
import glob
import math
import click
import shutil
import subprocess


def get_playback_duration(filename):
    process  = subprocess.Popen(['ffprobe', '-i', '{}'.format(filename)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    duration = [line.strip().split('Duration:')[1].split(',')[0].split(':') for line in process.stdout if 'Duration:' in line][0]
    return duration

def format_duration(duration):
    # convert over-seconds and minutes to minutes and hours
    for position in [2,1]: # 2 = seconds, 1 = minutes position
        if duration[position] > 60:
            o = duration[position] % 60
            duration[position-1] += (duration[position] - o)//60
            duration[position] = o
    return duration

def add_durations(duration_a, duration_b):
    duration = [math.ceil(float(duration_a[i]) + float(duration_b[i])) for i in range(len(duration_a))]
    return format_duration(duration)

def duration_to_minutes(duration):
    return duration[0]*60 + duration[1] + duration[2]/60

def ensure_directory(dirname):
    if not os.path.isdir(dirname):
        print('Creating output directory "{}"'.format(dirname))
        os.makedirs(dirname)

def ffmpeg_apply_atempo(input_filename, output_filename, atempo):
    #TODO convert to function to batch-process multiple input/output pairs?
    cmd = ['ffmpeg', '-y', '-i', input_filename, '-af', 'atempo={}'.format(atempo), output_filename]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    [line for line in process.stdout] # this is needed here to wait for process to exhaust its output pipe and (properly) finish the conversion process.


@click.command(help='(1) Takes the podcast and music mp3 files corresponding to a given date string (which usually are topically aligned),\n\
                     (2) measures their length in time (slightly over 90 minutes in length when added up)\n\
                     (3) and then uses ffmpeg to change playback speed to get just under 90 minutes of play time.\n\
                     (4) the end result can then be uploaded conveniently to a "Creative-Tonie" (with 90min capacity) for Toniebox-playback. see https://tonies.com/en-gb/creative-tonies/')
@click.argument('year',  nargs=1) # help="the year of the datestring part for identifying the podcast and music mp3 files of choice. depending on the regularity and intensity of your data crawling, values between 2020 and [the current year] might make sense.")
@click.argument('month', nargs=1) # help="the month part. values within [1,12] make sense.")
@click.argument('day',   nargs=1) # help="the day of choice. depending on the month, values within [1,31] make sense.")
@click.option('--output',  '-o' , default='./toniefied'           , help="The output location of choice.")
def main(year, month, day, output):

    assert len(year) == 4, 'Four digit year string expected, but got "{}"'.format(year)
    assert int(year) > 0 , 'Year value should be a positive integer, but got "{}"'.format(year)

    assert 0 < len(month) <= 2,  'One or two digit month string expected, but got "{}"'.format(month)
    assert 1 <= int(month) <= 12, 'Month value should be positive integer within range [1,12], but got "{}"'.format(month)

    assert 0 < len(day) <= 2,   'One or two digit day string expected, but got "{}"'.format(day)
    assert 1 <= int(month) <= 31, 'Day value should be positive integer within range [1,31] (depending on month), but got "{}"'.format(day)
    
    # year is required to be four-digit. keep as is
    # ensure leading zeroes for month and day
    datestring = '{year}-{month:02d}-{day:02d}'.format(year=year, month=int(month), day=int(day))
    print('Looking for podcast and music mp3 files with datestring "{}"'.format(datestring))

    # look for matching files
    podcast  = glob.glob('./podcast/{}*'.format(datestring))
    music    = glob.glob('./musik/{}*'.format(datestring))

    n_pod = len(podcast)
    n_mus = len(music)
    print('Found {} podcasts and {} music files with given datestring'.format(n_pod, n_mus))

    if n_pod >= 1 and n_mus >= 1: # all good.
        #select files
        print('Found one (or more) podcasts and music file with given date string. Picking (first) match per category.')
        podcast = podcast[0]
        music   = music[0]
        print('    podcast file:', podcast)
        print('    music file:  ', music)
    
    elif 0 in [n_pod, n_mus]:
        print('Could not satisfy search query for datestring "{}". At least one category did not find a match:'.format(datestring))
        print('    returned podcast files:', podcast)
        print('    returned music files:', music)
        print('Aborting.')
        exit()

    # matching files found with success, paths stored in "music" and "podcast"
    # now use ffmpeg and ffprobe to read file information and process file
    # get duratin as a list if [hours, minutes, seconds]
    p_duration = get_playback_duration(podcast)
    m_duration = get_playback_duration(music)
    print('Podcast duration: {}h {}m {}s'.format(*p_duration))
    print('Music duration: {}h {}m {}s'.format(*m_duration))

    # get combined duration
    c_duration = add_durations(p_duration, m_duration)
    print('Combined duration: ~ {}h {}m {}s'.format(*c_duration))

    # internally, now convert all to minutes in order to infer the playback speed scaling factor

    minutes_total = duration_to_minutes(c_duration)
    atempo = math.ceil(minutes_total/90 * 1000)/1000 # ceil to second decimal digit of playback speed percentage percentage 

    print('Total time in minutes: {:.2f}m'.format(minutes_total), '-> atempo for ffmpeg:', atempo)
    
    ensure_directory(output)
    if atempo <= 1:
        print('    that means playback speed would be REDUCED by {:.2f}%.'.format((1-atempo)*100))
        print('    I will just copy the discovered files to the output directory "{}".'.format(output))
        shutil.copy(podcast, output)
        shutil.copy(music, output)
    else:
        print('    that means playback speed will be INCREASED by {:.2f}%.'.format((atempo-1)*100))
        
        print('    using ffmpeg to process {} ... (this may take a while)'.format(os.path.basename(podcast)))
        p_out = '{}/{}'.format(output, os.path.basename(podcast.replace('.mp3', '_tonified.mp3')))
        ffmpeg_apply_atempo(podcast, p_out, atempo)
        p_out_duration = get_playback_duration(p_out)
        print('        output file written to {}'.format(p_out))
        print('        playback duration:{}h {}m {}s'.format(*p_out_duration))

        print('    using ffmpeg to process {} ... (this may take a while)'.format(os.path.basename(music)))
        m_out = '{}/{}'.format(output, os.path.basename(music.replace('.mp3', '_tonified.mp3')))
        ffmpeg_apply_atempo(music, m_out, atempo)
        m_out_duration = get_playback_duration(m_out)
        print('        output file written to {}'.format(m_out))
        print('        playback duration:{}h {}m {}s'.format(*m_out_duration))

        print('Combined playback duration of generated outputs: {}h {}m {}s'.format(*add_durations(p_out_duration, m_out_duration)))


    # TODO NEXT: 
    # parallelize ffmpeg_apply_atempo : ffmpeg runs single-threadedly




if __name__ == '__main__':
    main()
