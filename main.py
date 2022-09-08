# archived moe crawler

"""
A script for downloading linked images (replies, parents) from a single thread, or downloading a given image hash,
and any connected images based on linked images (replies, parents).


This script allows you to supply either:
    1. A post number, with which all linked (replied, replies) images will be downloaded.
    2. A URL to an image hash, where each page will be crawled, and linked images downloaded. The crawler will also
       view each new image hash and repeat the process.

Optionally, a path to an output directory can also be supplied, otherwise the current directory is used.
"""

import os
import re
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from math import ceil
from pathlib import Path
import requests
from bs4 import BeautifulSoup

h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36'}

s = requests.Session()


def sanitize(_hash):
    """Sanitize a given hash.

    :param _hash: hash
    :return: sanitize hash
    """
    if '/' in _hash:
        _hash = _hash.replace('/', '_')
    if '+' in _hash:
        _hash = _hash.replace('+', '-')
    return _hash


class Thread:
    def __init__(self, posts):
        self._posts = posts

    def build_thread(self, post_id):
        _processed_posts = set()

        def builder(pid):
            if pid not in _processed_posts and pid in self._posts.keys():
                _processed_posts.add(pid)
                [builder(i) for i in self._posts[pid] if i in self._posts.keys()]

        builder(post_id)
        return _processed_posts


class Archiver:
    @staticmethod
    def get_threads_from_hash(i_hash):
        """Gets all the threads from a given hash.

        :param i_hash:
        :return: list of thread#post_ids
        """
        _r = s.get('https://archived.moe/b/search/image/' + i_hash, headers=h)
        if _r.status_code != 200:
            return []

        html = BeautifulSoup(_r.text, 'html.parser')

        try:
            # get result count to work out number of pages
            _ct = int(re.match('^[0-9]*', html.find('div', id='main').h3.small.contents[0])[0])
            _page_ct = ceil(_ct / 25)
        except AttributeError:
            # no results found my archived.moe search
            return []

        _thread_post_ids = set()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for _p in range(_page_ct):
                if _p == 0:
                    futures.append(executor.submit(
                        Archiver.extract_threads, 'https://archived.moe/b/search/image/' + i_hash))

                else:
                    futures.append(executor.submit(
                        Archiver.extract_threads, f'https://archived.moe/b/search/image/{i_hash}==/page/{_p + 1}'))

            for future in as_completed(futures):
                _thread_post_ids.update(set(future.result()))

        return _thread_post_ids

    @staticmethod
    def extract_threads(url):
        _r = s.get(url, headers=h)
        if _r.status_code != 200:
            return 0

        html = BeautifulSoup(_r.text, 'html.parser')

        _t = html.body.find('div', id='main').find('aside', {'class': 'posts'}).findAll('article')
        _thread_post_ids = [''.join(t.header.find('div', {'class': 'post_data'})
                                    .find('a', {'data-function': 'highlight'})['href'].split('/')[-2:]) for t in _t]

        return _thread_post_ids

    @staticmethod
    def get_thread_posts(url):
        _r = s.get(url, headers=h)
        if _r.status_code != 200:
            print(f'ERROR: Status code {_r.status_code} received for thread.')
            return [], []

        # extract posts
        _post_ids, _post_images = Archiver.extract_posts(_r.text)

        return _post_ids, _post_images

    @staticmethod
    def get_image(url, out_dir):
        _r = s.get(url, headers=h, stream=True)
        if _r.status_code != 200:
            return 'ERROR: Image failed to download:', url

        with open(Path(out_dir, url.split('/')[-1]), 'wb') as _i:
            for chunk in _r:
                _i.write(chunk)

        return

    @staticmethod
    def extract_posts(html):
        """Extracts all the user posts for a given thread.

        :param html: raw thread html
        :return: dict of posts containing (post_id: {connected_posts})
        :return: dict of posts containing (post_id: {image_url, image_hash})
        """
        html = BeautifulSoup(html, 'html.parser')

        # create raw html list of all posts in thread
        html_posts = html.body.find('div', id='main').find('aside', {'class': 'posts'}).findAll('article')

        # parse posts to create post dict
        _post_ids = {}
        _post_images = {}
        for post in html_posts:
            post_id = post['id']
            try:
                post_image_url = post.find('a', {'class': 'thread_image_link'})['href']
                post_image_hash = post.find('a', {'class': 'thread_image_link'}).img['data-md5']
                post_image = [post_image_url, post_image_hash]
            except TypeError:
                post_image = None
            linked_posts = [i['data-post'] for i in post.findAll('a', {'class': 'backlink'})]
            _post_ids.update({post_id: linked_posts})
            _post_images.update({post_id: post_image})

        # extract op from main body
        op_id = html.body.find('div', id='main').article['id']
        op_image_url = html.body.find('div', id='main').find('article', {'class': 'post_is_op'}) \
            .find('a', {'class': 'thread_image_link'})['href']
        op_image_hash = html.body.find('div', id='main').find('article', {'class': 'post_is_op'}) \
            .find('a', {'class': 'thread_image_link'}).img['data-md5']
        op_image = [op_image_url, op_image_hash]
        op_linked_posts = \
            [i['data-post'] for i in html.body.find('div', id='main').find('article', {'class': 'post_is_op'})
                .find('div', {'class': 'backlink_list'}).findAll('a', {'class': 'backlink'})]
        _post_ids.update({op_id: op_linked_posts})
        _post_images.update({op_id: op_image})

        return _post_ids, _post_images


class Crawler:
    def __init__(self, args):
        if len(args) == 3:
            self.output_dir = Path(args[2])

        elif len(args) == 2:
            self.output_dir = Path(os.getcwd())

        os.makedirs(self.output_dir, exist_ok=True)

        self.crawled_threads = set()
        self.crawled_hashes = set()
        self.hash_queue = set()

        if '/thread/' in args[1]:
            self.mode = 'thread'

        elif '/search/image/' in args[1]:
            self.mode = 'hash'

        else:
            self.mode = None

    def crawl_thread(self, url, ret=False):
        print(f'INFO: Fetching posts for url: {url}')
        _posts_ids, _post_images = Archiver.get_thread_posts(url)

        if not _posts_ids or not _post_images:
            return []

        # generate thread using parents and replies of given post
        root_post_id = url.split('#')[-1]

        t = Thread(_posts_ids)
        thread = t.build_thread(root_post_id)

        # grab all images
        url_hash_list = []
        for post_id in thread:
            if _post_images[post_id]:
                url_hash_list.append(_post_images[post_id])

        if ret:
            return url_hash_list

        print(f'INFO: Downloading images to {self.output_dir}')

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(Archiver.get_image, image[0], self.output_dir) for image in url_hash_list]
            for future in as_completed(futures):
                print(future.result())

    def crawl_hash(self, root_hash):
        thread_queue = set()
        crawled_threads = set()
        hash_queue = {sanitize(root_hash)}
        crawled_hashes = set()
        unwanted_hashes = set()
        image_queue = set()
        _temp_dir = '.' + os.urandom(6).hex()
        os.makedirs(Path(self.output_dir, _temp_dir), exist_ok=True)

        # import saved vars if they exist
        if Path(self.output_dir, '.resume').exists():
            with open(Path(self.output_dir, '.resume'), 'r') as _resume:
                _vars = json.loads(_resume.read())
                hash_queue = set(_vars[0])
                crawled_threads = set(_vars[1])
                unwanted_hashes = set(_vars[2])
                image_queue = set(_vars[3])

        while True:
            for _hash in hash_queue:
                print(f'INFO: Fetching threads with hash: {_hash}')
                new_threads = Archiver.get_threads_from_hash(_hash)
                # append thread if id not in crawled threads
                [thread_queue.add(_t) for _t in new_threads if _t.split('#')[0] not in crawled_threads]

                crawled_hashes.add(_hash)

            # wipe hash queue
            hash_queue = set()
            for _thread in thread_queue:
                print(f'INFO: Crawling thread with id: {_thread}')
                new_hashes = self.crawl_thread(f'https://thebarchive.com/b/thread/{_thread}', True)

                # download images of new hashes temporarily for user checking
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(Archiver.get_image, _hash[0], Path(self.output_dir, _temp_dir))
                               for _hash in new_hashes if sanitize(_hash[1]) not in crawled_hashes
                               and sanitize(_hash[1]) not in hash_queue and sanitize(_hash[1]) not in unwanted_hashes]
                    for future in as_completed(futures):
                        if _f := future.result():
                            # remove hash if image dl failed
                            new_hashes.remove(new_hashes[[i[0] for i in new_hashes].index(_f[1])])

                # pick out hashes we actually want
                _all = _none = False
                for _hash in new_hashes:
                    if sanitize(_hash[1]) not in crawled_hashes and sanitize(_hash[1]) not in hash_queue \
                            and sanitize(_hash[1]) not in unwanted_hashes:

                        if _none:
                            unwanted_hashes.add(sanitize(_hash[1]))
                            Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                            continue

                        if _all:
                            hash_queue.add(sanitize(_hash[1]))
                            Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                            continue

                        # get user to verify hash is wanted
                        while True:
                            try:
                                os.startfile(Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])))
                            except FileNotFoundError:
                                unwanted_hashes.add(sanitize(_hash[1]))
                                break
                            _i = input(f'Crawl hash {sanitize(_hash[1])}? [Y]es | [N]o | [A]ll | N[o]ne : ')
                            if _i == 'Y' or _i == 'y':
                                hash_queue.add(sanitize(_hash[1]))
                                Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                            elif _i == 'N' or _i == 'n':
                                unwanted_hashes.add(sanitize(_hash[1]))
                                Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                            elif _i == 'O' or _i == 'o':
                                unwanted_hashes.add(sanitize(_hash[1]))
                                Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                                _none = True
                                break
                            elif _i == 'A' or _i == 'a':
                                _all = True
                                hash_queue.add(sanitize(_hash[1]))
                                Path(self.output_dir, _temp_dir, sanitize(_hash[0].split('/')[-1])).unlink()
                                break
                            else:
                                continue

                            break

                [image_queue.add(_i[0]) for _i in new_hashes if sanitize(_i[1]) not in crawled_threads
                 and sanitize(_i[1]) not in unwanted_hashes]

                crawled_threads.add(_thread.split('#')[0])

            # wipe thread queue
            thread_queue = set()

            # output vars
            with open(Path(self.output_dir, '.resume'), 'w') as _resume:
                _resume.write(json.dumps([list(hash_queue), list(crawled_threads), list(unwanted_hashes), list(image_queue)]))

            if not hash_queue and not thread_queue:
                shutil.rmtree(Path(self.output_dir, _temp_dir))
                break

        # download images
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(Archiver.get_image, image, self.output_dir) for image in image_queue]
            for future in as_completed(futures):
                print(future.result())


if __name__ == '__main__':
    if not (1 < len(sys.argv) < 4):
        print('ERROR: Invalid number of arguments supplied.')
        sys.exit(1)

    c = Crawler(sys.argv)

    # if link is to a post number
    if c.mode == 'thread':
        c.crawl_thread(sys.argv[1])

    elif c.mode == 'hash':
        c.crawl_hash(sys.argv[1].split("/")[-2].replace('==', '') + '==')

    else:
        print('ERROR: Invalid url supplied.')
        sys.exit(1)
