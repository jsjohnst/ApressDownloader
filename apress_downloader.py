#!/usr/bin/env python
""" Downloads products from Apress """
import requests
import signal
import sys
import os
import re
import argparse
import getpass
import pprint
import bs4
import HTMLParser
import logging
import colorlog

VERSION = 1.0

class ApressDownloader(object):
    """ Handles downloading products you own from Apress.com """

    def __init__(self, overwrite=False, parser='html.parser'):
        self.request = requests.Session()
        self.unescape = HTMLParser.HTMLParser().unescape
        self.logger = logging.getLogger('ApressDownloader')
        self.overwrite = overwrite
        self.soup_parser = parser

    def stream_file(self, url, filename):
        """ Streams a file from a URL to disk """
        self.logger.debug("Downloading '%s' to '%s'", url, filename)
        response = self.request.get(url, stream=True)

        with open(filename, 'wb') as fileh:
            writes = [fileh.write(chunk) for chunk in response.iter_content(chunk_size=1024) if chunk]

        return writes

    def download_product(self, product, path="ebooks"):
        """ Downloads the given product """
        name = re.sub(r'[^-a-zA-Z0-9_+()\[\]]+', '_',
                      product.get('title').encode('ascii', 'ignore').strip())

        try:
            os.mkdir(path + '/' + name)
        except OSError:
            pass

        filename = "%s/%s/%s." % (path, name, name)

        self.logger.info("Downloading: %s as %s.{%s}",
                         product.get('title'), name, "|".join(product.get('links').keys()))

        for extension, url in product.get('links').iteritems():
            local_file = filename + extension

            if not os.path.isfile(local_file) or self.overwrite:
                self.stream_file(url, local_file)
            else:
                self.logger.info("   Not re-downloading: %s", local_file)

    def login(self, username, password):
        """ Logs into Apress.com website """
        self.logger.info("Authenticating with Username: %s and Password: %s",
                         username, "*" * len(password))
        auth = {'login[username]': username, 'login[password]': password, 'send': ''}
        self.request.get("https://www.apress.com/customer/account/login/")
        response = self.request.post("https://www.apress.com/customer/account/loginPost/",
                                     data=auth)

        if response.url == 'https://www.apress.com/customer/account/login/':
            self.logger.error("Failed to authenticate with Apress.com")
            return False
        elif response.url == 'https://www.apress.com/customer/account/':
            return True
        else:
            self.logger.error("Failed to authenticate with Apress.com, redirected to: %s", response.url)
            return True


    def fetch_products(self, limit=50):
        """ Fetches a list of products which you own """
        products = []
        has_more = True
        page = 1
        url = "https://www.apress.com/customer/account/index/?limit=%d&p=%d"

        while has_more:
            self.logger.info("Fetching products page %d...", page)
            soup = bs4.BeautifulSoup(self.request.get(url % (limit, page), allow_redirects=False).text,
                                     self.soup_parser)

            rows = soup.select('table#my-downloadable-products-table tbody tr')

            if not rows:
                self.logger.warn("Didn't find any products on page %d!", page)
                return products

            for row in rows:
                product = {}
                product['links'] = {}

                title = row.select_one('td:nth-of-type(3)')

                if not title:
                    self.logger.warn("Couldn't find title in product table row!")
                    continue

                #sadly, Apress sometimes double encodes :(
                product['title'] = self.unescape(title.text)

                opts = row.select('td:nth-of-type(4) option')

                if not opts:
                    self.logger.warn("Couldn't find list of downloads for '%s'", title.text)

                for opt in opts:
                    extension = opt.text.lower()
                    product['links'][extension] = opt['value']

                products.append(product)

            pager = soup.find('div', class_='pager').find('div', class_='pages')
            if pager and pager.find('li', class_='next'):
                page += 1
            else:
                has_more = False

        return products

    def start(self, path):
        """ Starts the download process """
        try:
            if not os.path.isdir(path):
                os.makedirs(path)
        except OSError:
            self.logger.error("Could not create / use path: %s", path)
            return False

        products = self.fetch_products()

        self.logger.info("Found %d products in your Apress account...", len(products))

        for product in products:
            self.download_product(product, path=path)

        return True

def setup_logging(loglevel):
    """ Sets up the console logging """
    formatter = colorlog.ColoredFormatter(
        "%(message_log_color)s%(message)s",
        secondary_log_colors={
            'message': {
                'DEBUG':    'cyan',
                'INFO':     'green',
                'WARNING':  'yellow',
                'ERROR':    'red',
                'CRITICAL': 'red'
            }
        }
    )

    logger = logging.getLogger('ApressDownloader')
    logger.setLevel(loglevel)

    console_logger = logging.StreamHandler()
    console_logger.setFormatter(formatter)
    logger.addHandler(console_logger)

    return logger


def main():
    """ CLI mode handler """
    parser = argparse.ArgumentParser(description='Downloads your purchased eBooks from Apress.com')
    parser.add_argument('username', help='Email address for your account')

    parser.add_argument('-o', '--overwrite', action='store_true', help='Overwrite any existing files')
    parser.add_argument('-q', '--quiet', action='store_true', help='Don\'t output any progress info')
    parser.add_argument('-d', '--debug', action='store_true', help='Lists out your owned products and quits')

    parser.add_argument('--path', default='./ebooks', help='Where to download too (Default: ./ebooks)')

    parser.add_argument('--loglevel', default='info', choices=['error', 'warn', 'info', 'debug'],
                        help='What level of logging to output (Default: info)')

    parser.add_argument('--parser', default='html.parser', choices=['html.parser', 'lxml', 'html5lib'],
                        help='Override the HTML parser used by BeautifulSoup (Default: html.parser)')

    parser.add_argument('--password', help='Password for your account (will prompt if not provided)')

    parser.add_argument('--version', action='version', version='%(prog)s ' + str(VERSION))

    args = parser.parse_args()

    if not args.password:
        password = getpass.getpass("Password for %s: " % args.username)
    else:
        password = args.password

    if args.quiet:
        loglevel = 100
    else:
        loglevel = getattr(logging, args.loglevel.upper())

    logger = setup_logging(loglevel)
    logger.critical(" ") # puts separation between password prompt / command prompt and output

    def sig_handler(signum, frame):
        """ handles signals """
        logger.error("download aborted!")
        sys.exit(1)
        _ = (signum, frame) # PEP8 FTW?

    signal.signal(signal.SIGINT, sig_handler)

    downloader = ApressDownloader(overwrite=args.overwrite, parser=args.parser)

    if downloader.login(args.username, password):
        if args.debug:
            products = downloader.fetch_products()
            logger.info("Found %d products!", len(products))

            logger.info("Products:")
            pprint.pprint(products)
        else:
            if not downloader.start(args.path):
                sys.exit(2)
    else:
        logger.error("download aborted!")
        sys.exit(3)


if __name__ == '__main__':
    main()
