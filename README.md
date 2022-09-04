
# 4chan-b-image-crawler

```
A Python3 script for downloading linked images based on replies, parents from a single thread, or
downloading a given image hash, and any connected images based on linked images (replies, parents).

- archived.moe and thebarchive.com are used for downloading and crawling.


This script allows you to supply either:
    1. An archived.moe URL to an individual post number, with which all linked (parents, replies)
       images will be downloaded.
    2. A archived.moe URL to an image hash, where each page will be crawled, and linked images
       downloaded. The crawler will also view each new image hash and repeat the process until no
       more images can be found.
        - The user will be prompted whenever a new image hash is found to ensure only related images
          are crawled.

Optionally, a path to an output directory can also be supplied, otherwise the current directory is used.


Requirements:
    bs4         (python3 -m pip install bs4)
    requests    (python3 -m pip install requests)
```