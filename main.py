# 4chan (/b/) related image crawler

"""
This script allows you to supply either:
    1. An archived.moe URL to an individual post number, with which all linked (parents, replies)
       images will be downloaded.
    2. An archived.moe URL to an image hash, where each page will be crawled, and linked images
       downloaded. The crawler will also view each new image hash and repeat the process until no
       more images can be found.
        - The user will be prompted whenever a new image hash is found to ensure only related images
          are crawled.

Optionally, a path to an output directory can also be supplied, otherwise the current directory is used.
"""

import os
import re
import shutil
import sys
import pickle
from PIL import Image
import imagehash
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from math import ceil
from pathlib import Path
from time import sleep
import requests
from bs4 import BeautifulSoup
from collections import OrderedDict

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
        return sorted(_processed_posts)


class Archiver:
    @staticmethod
    def get_threads_from_hash(i_hash):
        """Gets all the threads from a given hash.

        :param i_hash:
        :return: list of thread#post_ids
        """
        print(f'INFO: Fetching threads with hash: {i_hash}')

        for attempt in range(6):
            try:
                if attempt > 4:
                    print(f'ERROR: Maximum attempts reached for hash {i_hash}')
                    return []

                _r = s.get('https://archived.moe/b/search/image/' + i_hash, headers=h, timeout=30)

                if _r.status_code != 200:
                    print(f'ERROR: Status code {_r.status_code} received for hash {i_hash}.')
                    sleep(15)
                    continue

                break

            except requests.exceptions.ReadTimeout:
                pass

        html = BeautifulSoup(_r.text, 'html.parser')

        try:
            # get result count to work out number of pages
            _ct = int(re.match('^[0-9]*', html.find('div', id='main').h3.small.contents[0])[0])
            _page_ct = ceil(_ct / 25)
        except AttributeError:
            # no results found my archived.moe search
            return []

        _thread_post_ids = set()

        with ThreadPoolExecutor(max_workers=3) as executor:
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

        return {i_hash: {i: None for i in _thread_post_ids}}

    @staticmethod
    def extract_threads(url):
        _thread_post_ids = None

        for attempt in range(6):
            if attempt > 4:
                print(f'ERROR: Maximum attempts reached for {url}')
                return []

            _r = s.get(url, headers=h, timeout=30)
            if _r.status_code != 200:
                print(f'ERROR: Status code {_r.status_code} received for {url}')
                sleep(15)
                continue

            html = BeautifulSoup(_r.text, 'html.parser')

            _t = html.body.find('div', id='main').find('aside', {'class': 'posts'}).findAll('article')
            _thread_post_ids = [''.join(t.header.find('div', {'class': 'post_data'})
                                        .find('a', {'data-function': 'highlight'})['href'].split('/')[-2:]) for t in _t]
            break

        return _thread_post_ids

    @staticmethod
    def get_thread_posts(url):
        for attempt in range(6):
            if attempt > 4:
                print(f'ERROR: Maximum attempts reached for {url}')
                return [], []

            _r = s.get(url, headers=h, timeout=30)

            if _r.status_code != 200:
                print(f'ERROR: Status code {_r.status_code} received for thread {url}.')
                sleep(15)
                continue

            break

        # extract posts
        _post_ids, _post_images = Archiver.extract_posts(_r.text)

        return _post_ids, _post_images

    @staticmethod
    def get_image(url, out_dir, img_name=None):
        if not img_name:
            img_name = url.split('/')[-1]

        Path(out_dir).mkdir(exist_ok=True, parents=True)

        for attempt in range(6):
            if attempt > 4:
                print(f'ERROR: Maximum attempts reached for image {url}')
                return url

            # wipe image if it already exists
            if Path(out_dir, img_name).exists():
                Path(out_dir, img_name).unlink()

            _r = s.get(url, headers=h, timeout=30)
            if _r.status_code != 200:
                print(f'ERROR: Status code {_r.status_code} received for image ({url}), retrying in 15s.')
                sleep(15)
                continue

            break

        with open(Path(out_dir, img_name), 'wb') as _i:
            _i.write(_r.content)

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
                post_image = [post_image_url, sanitize(post_image_hash)]
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
        op_image = [op_image_url, sanitize(op_image_hash)]
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
        print(f'INFO: Fetching posts for url: {url.replace("thebarchive.com", "archived.moe").replace("#", "/#")}')
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
                _l = _post_images[post_id]
                _l.append(post_id)
                url_hash_list.append(_l)

        if ret:
            if url_hash_list:
                return {url.replace('https://thebarchive.com/b/thread/', ''): url_hash_list}
            else:
                return {url.replace('https://thebarchive.com/b/thread/', ''): None}

        print(f'INFO: Downloading images to {self.output_dir}')

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(Archiver.get_image, image[0], self.output_dir) for image in url_hash_list]
            for future in as_completed(futures):
                # print(future.result())
                pass

    def crawl_hash(self, root_hash):
        checked_hashes = {root_hash}
        completed_threads = set()
        image_phashes = set()
        image_queue = dict()

        # fetch hash of root
        _r_threads = Archiver.get_threads_from_hash(root_hash)
        _r_post = self.crawl_thread('https://thebarchive.com/b/thread/' + list(_r_threads[root_hash].keys())[0], True)

        if _r_post:
            # find root image in thread
            for _pid in list(_r_post.values())[0]:
                if sanitize(_pid[1]) == sanitize(root_hash):
                    extension = '.' + _pid[0].split('.')[-1]
                    Archiver.get_image(_pid[0], self.output_dir, _pid[2] + extension)
                    if 'jpg' in extension or 'png' in extension:
                        image_phashes.add(get_image_hash(Path(self.output_dir, _pid[2] + extension)))
                    break

        else:
            print('ERROR: Root image hash could not be found.')

        # queue {
        #        hash# {
        #               thread# {
        #                        (image_url, image_hash)
        queue = {root_hash: {}}
        _temp_dir = '.' + os.urandom(6).hex()
        os.makedirs(Path(self.output_dir, _temp_dir), exist_ok=True)

        # restore progress
        if Path(self.output_dir, '.resume').exists():
            with open(Path(self.output_dir, '.resume'), 'rb') as _resume:
                _resume_data = pickle.load(_resume)
                checked_hashes = set(_resume_data[0])
                image_phashes = set(_resume_data[1])
                image_queue = dict(_resume_data[2])
                queue = dict(_resume_data[3])

        prev_queue_len = 0
        while prev_queue_len < len(queue):
            # set prev queue length to check for loop end
            prev_queue_len = len(queue)

            # perform thread discovery for new hashes
            with ThreadPoolExecutor(max_workers=3) as executor:
                # create pool of hashes, only selecting queue keys without values
                futures = []
                for _hash in queue.keys():
                    if not queue[_hash]:
                        futures.append(executor.submit(Archiver.get_threads_from_hash, _hash))

                for future in as_completed(futures):
                    if future.result():
                        # print(future.result())
                        # update queue key with thread ids
                        queue.update(future.result())

            # discover all hashes in threads
            crawled = set()
            futures = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                for _hash in queue.keys():
                    # skip hashes not archived by thebarchive / archivedmoe
                    if not queue[_hash]:
                        continue

                    for _thread in queue[_hash]:
                        if queue[_hash][_thread] or _thread in crawled:
                            # skip already processed threads
                            continue

                        crawled.add(_thread)
                        # build future for each thread of hash
                        futures.append(executor.submit(self.crawl_thread, f'https://thebarchive.com/b/thread/{_thread}', True))

                    # execute futures
                    for future in as_completed(futures):
                        if future.result() and future.result().values():
                            # update queue with found threads
                            queue[_hash].update(future.result())

                    # add found images to global queue
                    image_queue[_hash] = OrderedDict(sorted(queue[_hash].items(), key=lambda t: t[0]))

            # create futures for multithreading downloading of images
            futures = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                for _hash in image_queue.keys():
                    for _thread in image_queue[_hash]:
                        # catch threads without linked posts
                        if not image_queue[_hash][_thread]:
                            continue

                        for _image_tuple in image_queue[_hash][_thread]:
                            # skip if image already crawled
                            if _image_tuple[1] in checked_hashes:
                                continue

                            try:
                                extension = '.' + _image_tuple[0].split('.')[-1]
                                # skip if image file already exists
                                if Path(Path(self.output_dir, _temp_dir, _thread.split('#')[0]), _image_tuple[2] + extension).exists():
                                    continue

                            except PermissionError:
                                continue

                            executor.submit(Archiver.get_image, _image_tuple[0], Path(self.output_dir, _temp_dir, _thread.split('#')[0]), _image_tuple[2] + extension)

                # perform downloads
                print('INFO: Downloading images...')
                for future in as_completed(futures):
                    if future.result():
                        print(future.result())
                        continue
                        # do something on download fail?

            input('Press enter to begin hash verification.')
            print('You can either:\n\tSelect a provided option.\n\tDelete any undesired photos, choose [Y]es or [N]o for the current photo then select the [A]ll option.')

            # pick out hashes we actually want
            for _hash in image_queue:
                _skip_hash = False

                thread_queue = set(image_queue[_hash]) - completed_threads

                for _thread in thread_queue:
                    _all = False
                    _none = False
                    idx = 0

                    # skip threads without linked posts/images
                    if not image_queue[_hash][_thread]:
                        idx += 1
                        continue

                    # skip threads without image folder
                    if not Path(self.output_dir, _temp_dir, _thread.split('#')[0]).exists():
                        continue

                    print(f'Performing verification for thread https://thebarchive.com/b/thread/{_thread.replace("#", "/#")}')

                    while idx < len(image_queue[_hash][_thread]):
                        checked_hashes.add(image_queue[_hash][_thread][idx][1])

                        if _skip_hash:
                            break

                        # if image deleted we skip as the user doesnt want it
                        extension = '.' + image_queue[_hash][_thread][idx][0].split('.')[-1]
                        if not Path(self.output_dir, _temp_dir, _thread.split('#')[0], image_queue[_hash][_thread][idx][2] + extension).exists():
                            idx += 1
                            continue

                        # get image comparison hash for checking if it matches any existing image hash
                        image_phash = None
                        if 'jpg' in extension or 'png' in extension:
                            image_phash = get_image_hash(Path(self.output_dir, _temp_dir, _thread.split('#')[0], image_queue[_hash][_thread][idx][2] + extension))

                        if _all:
                            # skip adding to queue if image already present
                            if sanitize(image_queue[_hash][_thread][idx][1]) in queue.keys():
                                idx += 1
                                continue

                            queue[sanitize(image_queue[_hash][_thread][idx][1])] = None
                            if image_phash:
                                image_phashes.add(image_phash)
                            try:
                                shutil.move(Path(self.output_dir, _temp_dir, _thread.split('#')[0],
                                                 image_queue[_hash][_thread][idx][2] + extension),
                                            Path(self.output_dir, image_queue[_hash][_thread][idx][2] + extension))

                            except FileNotFoundError:
                                pass

                            idx += 1
                            continue

                        if _none or _skip_hash:
                            break

                        # compare against all hashes
                        if image_phash:
                            similarity = compare_image_against_hashlist(image_phash, image_phashes)
                            # print(f'INFO: Image similarity: {similarity}.')

                            if similarity < 5:
                                print('INFO: Image matches an already verified picture.')
                                image_phashes.add(image_phash)
                                if sanitize(image_queue[_hash][_thread][idx][1]) in queue.keys():
                                    idx += 1
                                    continue

                                queue[sanitize(image_queue[_hash][_thread][idx][1])] = None
                                try:
                                    shutil.move(Path(self.output_dir, _temp_dir, _thread.split('#')[0],
                                                     image_queue[_hash][_thread][idx][2] + extension),
                                                Path(self.output_dir, image_queue[_hash][_thread][idx][2] + extension))
                                except FileNotFoundError:
                                    pass

                                finally:
                                    idx += 1
                                    break

                        # get user to verify hash is wanted
                        # loop in case of invalid input
                        while True:
                            try:
                                os.startfile(Path(self.output_dir, _temp_dir, _thread.split('#')[0], image_queue[_hash][_thread][idx][2] + extension))

                            except FileNotFoundError:
                                idx += 1
                                break

                            except OSError:
                                sleep(1)
                                continue

                            _i = input(f'{idx}/{len(image_queue[_hash][_thread])} Crawl hash {sanitize(image_queue[_hash][_thread][idx][1])}? [Y]es | [N]o | [A]ll | N[o]ne | [B]ack | [S]kip Hash: ')
                            if _i.lower() == 'y':
                                if sanitize(image_queue[_hash][_thread][idx][1]) in queue.keys():
                                    idx += 1
                                    break
                                queue[sanitize(image_queue[_hash][_thread][idx][1])] = None
                                if image_phash:
                                    image_phashes.add(image_phash)
                                try:
                                    shutil.move(Path(self.output_dir, _temp_dir, _thread.split('#')[0], image_queue[_hash][_thread][idx][2] + extension), Path(self.output_dir, image_queue[_hash][_thread][idx][2] + extension))
                                except FileNotFoundError:
                                    pass
                                finally:
                                    idx += 1
                                    break

                            elif _i.lower() == 'n':
                                pass

                            elif _i.lower() == 'o':
                                _none = True

                            elif _i.lower() == 'a':
                                _all = True
                                if sanitize(image_queue[_hash][_thread][idx][1]) in queue.keys():
                                    idx += 1
                                    break
                                queue[sanitize(image_queue[_hash][_thread][idx][1])] = None
                                if image_phash:
                                    image_phashes.add(image_phash)
                                try:
                                    shutil.move(Path(self.output_dir, _temp_dir, _thread.split('#')[0], image_queue[_hash][_thread][idx][2] + extension), Path(self.output_dir, image_queue[_hash][_thread][idx][2] + extension))
                                except FileNotFoundError:
                                    pass

                            elif idx > 0 and _i.lower() == 'b':
                                idx -= 1
                                break

                            elif _i.lower() == 's':
                                _skip_hash = True
                                break

                            else:
                                continue

                            idx += 1
                            break

                    try:
                        shutil.rmtree(Path(self.output_dir, _temp_dir, _thread.split('#')[0]))
                    except FileNotFoundError:
                        pass

                    # save progress
                    with open(Path(self.output_dir, '.resume'), 'wb') as _resume:
                        pickle.dump([checked_hashes, image_phashes, image_queue, queue], _resume)

                    completed_threads.add(_thread)

            # wipe image queue before processing new hashes
            image_queue = dict()


def get_image_hash(image):
    try:
        _hash = imagehash.phash(Image.open(image))
    except FileNotFoundError:
        return
    return _hash


def compare_image_against_hashlist(image_hash, hash_list, cutoff=5):
    """Compares an image against a provided list of hashes.

    :param image_hash: image to compare
    :param hash_list: set of images to compare image_phash against
    :param cutoff: number of dissimilar bits
    :returns: True if any image in the given set has n < cutoff number of different bets
    """
    similarity = set()

    for _hash in hash_list:
        similarity.add(image_hash - _hash)

    if similarity:
        return min(similarity)

    return 99


if __name__ == '__main__':
    if not (1 < len(sys.argv) < 4):
        print('ERROR: Invalid number of arguments supplied.')
        sys.exit(1)

    c = Crawler(sys.argv)

    # if link is to a post number
    if c.mode == 'thread':
        c.crawl_thread(sys.argv[1])

    elif c.mode == 'hash':
        c.crawl_hash(sanitize(sys.argv[1].split("/")[-2].replace('==', '') + '=='))

    else:
        print('ERROR: Invalid url supplied.')
        sys.exit(1)
