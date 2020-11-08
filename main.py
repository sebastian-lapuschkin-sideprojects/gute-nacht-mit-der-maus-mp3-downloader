""" This script downloads the 'Gute Nacht Mit Der Maus' Website at https://www.wdrmaus.de/hoeren/gute_nacht_mit_der_maus.php5 and collets and downloads all publicly available, yet not already downloaded mp3 files """

import os
import time
import click
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

# modules: selenium, click
# for fun maybe termcolor, tqdm and tctim for fun?

SITE_URL = 'https://www.wdrmaus.de/hoeren/gute_nacht_mit_der_maus.php5'

@click.command()
@click.option('--browser', '-b', default='chrome'  , help="Which browser to use for? Pick between firefox and chrome.")
@click.option('--waittime','-w', default=10        , help="Time to allow the browser to request resources and render.")
@click.option('--output',  '-o' , default='.'       , help="The output directory to create (if required) and write the discovered files into.")
def main(browser, waittime, output):

    browser = browser.lower()

    assert browser in ['firefox', 'chrome'], 'Unsupported browser "{}"'.format(browser)
    if not os.path.isdir(output): os.makedirs(output)

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
    print('Headless browser ({}) instantiated. Requesting "{}" and waiting...'.format(browser, SITE_URL))

    driver.get(SITE_URL)
    time.sleep(waittime)

    # after rendering the page in headless mode, get the html_source, and parse for mp3 download tags
    parser = Mp3DownloadParser()
    parser.feed(driver.page_source)
    driver.quit()

    # download files and save
    for link in parser.mp3_links:
        filename = '{}/{}'.format(output, os.path.basename(link))
        if os.path.isfile(filename):
            print('Skipping {} (file exists in {})'.format(link, output))

        else:
            print('Downloading {}...'.format(link))
            with open(filename, 'wb') as f:
                f.write(requests.get(link, allow_redirects=True).content)

    # clean up
    if os.path.isfile('geckodriver.log'): os.remove('geckodriver.log')




if __name__ == '__main__':
    main()
