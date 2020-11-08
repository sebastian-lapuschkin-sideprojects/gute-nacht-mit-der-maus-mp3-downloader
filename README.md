# gute-nacht-mit-der-maus-mp3-downloader
Automation tool for downloading the daily "Gute Nacht mit der Maus" audio plays as mp3 file.

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
    -b, --browser TEXT      Which browser to use for? Pick between firefox and
                            chrome.
    -w, --waittime INTEGER  Time to allow the browser to request resources and
                            render.
    -o, --output TEXT       The output directory to create (if required) and
                            write the discovered files into.
    --help                  Show this message and exit.
  ```

Consider running this as a cron job.

