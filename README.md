# Audio Play Download Automation of daily "Sendung mit der Maus" content
My son loves the Sendung mit der Maus, and so do I (since my early childhood, in fact).
The [Sendung mit der Maus](https://www.wdrmaus.de/) is an excellent series of educational and creative media published by the [Westdeutsche Rundfink Köln (WDR)](https://www.wdr.de).
The format appears weekly on Television since 1971 and for Streaming.
Since the COVID-19 pandemic of 2020, there is also a daily series of freely streamable and as mp3 file downloadable daily audio plays.

For some weird reason however, in germany publicly funded and freely available media gets depublished after one week of online availability. In the past, I have tried to keep track of the newly published episodes, but some slipped between my fingers. I therefore set out to create this small automation tool (which can be run as a cron job, for example) to automatically collect and download any newly appearing mp3 audio files.

This tool is built with python and uses selenium to request the full html source code of the php pages in order to extract and then download newly published mp3 files for safekeeping. Only the mp3 files not already present in the output directory will be downloaded. Existing files will be skipped.

## Installation on Debian-based systems
For use with Firefox:
  ```
  sudo apt install -y firefox firefox-geckodriver
  ```

For use with Chrome/Chromium:
  ```
  sudo apt install -y chromium-browser chromium-chromedriver
  ```

Installing the required python packages
  ```
  pip install -r requirements.txt
  ```

## How to use
Everything is pretty straight forward:
  ```
  $python main.py --help

  Usage: main.py [OPTIONS]

  Options:
    -c, --content TEXT      What is the target content to download? pick
                          'gutenacht' (default) for 'Gute Nacht mit der Maus'
                          or 'hoerspiel' for 'Maus Hörspiel'.
    -b, --browser TEXT      Which browser to use for? Pick between 'firefox' and
                          'chrome'.
    -w, --waittime INTEGER  Time to allow the browser to request resources and
                          render.
    -o, --output TEXT       The output directory to create (if required) and
                          write the discovered files into.
    --help                  Show this message and exit.
  ```

Consider running this as a cron job.

