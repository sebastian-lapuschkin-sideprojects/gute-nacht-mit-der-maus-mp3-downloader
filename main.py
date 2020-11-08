""" This script downloads the 'Gute Nacht Mit Der Maus' Website at https://www.wdrmaus.de/hoeren/gute_nacht_mit_der_maus.php5 and collets and downloads all publicly available, yet not already downloaded mp3 files """

import os
import sys
import time
import datetime
import click
from termcolor import cprint
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FFOptions
from selenium.webdriver.chrome.options import Options as COptions
from html.parser import HTMLParser
import requests

class Mp3DownloadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.mp3_links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and ('class', 'mp3dl') in attrs:
            self.mp3_links.extend([v for k,v in attrs if k == 'href'])

SITE_URLS = {'gutenacht':'https://www.wdrmaus.de/hoeren/gute_nacht_mit_der_maus.php5',
            'hoerspiel':'https://www.wdrmaus.de/hoeren/hoerspiel.php5'}

@click.command()
@click.option('--content', '-c', default='gutenacht'    , help="What is the target content to download? pick 'gutenacht' (default) for 'Gute Nacht mit der Maus' or 'hoerspiel' for 'Maus Hörspiel'.")
@click.option('--browser', '-b', default='chrome'       , help="Which browser to use for? Pick between 'firefox' and 'chrome'.")
@click.option('--waittime','-w', default=10             , help="Time to allow the browser to request resources and render.")
@click.option('--output',  '-o' , default='.'           , help="The output directory to create (if required) and write the discovered files into.")
def main(content, browser, waittime, output):

    cprint('Script called at {} : {}'.format(datetime.datetime.now(), ' '.join(sys.argv) ), 'green')

    # start with some basic data preprocessing and assertion
    browser = browser.lower()
    content = content.lower()

    assert browser in ['firefox', 'chrome'], 'Unsupported browser "{}"'.format(browser)
    assert content in SITE_URLS.keys(), 'Unsupported download target "{}"'.format(content)
    outdir = '{}/{}'.format(output, content)
    if not os.path.isdir(outdir): os.makedirs(outdir)


    # set up webdriver
    if browser == 'firefox':
        Options = FFOptions
        WebDriver = webdriver.Firefox
    elif browser == 'chrome':
        Options = COptions
        WebDriver = webdriver.Chrome
    else:
        exit()

    options = Options()
    options.headless = True
    driver = WebDriver(options=options)
    print('Headless browser ({}) instantiated.\nRequesting "{}" and waiting ({}s) for site to render...'.format(browser, SITE_URLS[content], waittime))

    # request and load resources
    driver.get(SITE_URLS[content])
    time.sleep(waittime)

    # after rendering the page in headless mode, get the html_source, and parse for mp3 download tags
    parser = Mp3DownloadParser()
    parser.feed(driver.page_source)
    driver.quit()

    # download mp3 files and save
    for i, link in enumerate(parser.mp3_links):
        filename = '{}/{}'.format(outdir, os.path.basename(link))
        if os.path.isfile(filename):
            cprint('({}) Skipping {} (file exists in {})'.format(i, link, outdir), attrs=['dark'])

        else:
            print('({}) Downloading {}...'.format(i, link))
            with open(filename, 'wb') as f:
                f.write(requests.get(link, allow_redirects=True).content)

    # clean up
    if os.path.isfile('geckodriver.log'): os.remove('geckodriver.log')
    print() # extra empty line for e.g. logs




if __name__ == '__main__':
    main()
