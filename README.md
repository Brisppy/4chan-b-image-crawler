
# 4chan /b/ related image crawler

```
A Python3 script for downloading linked images based on replies, parents from a single thread, or
downloading a given image hash, and any connected images based on linked images (replies, parents).

- archived.moe and thebarchive.com are used for downloading and crawling.


This script allows you to supply either:
    1. An archived.moe URL to an individual post number, with which all linked (parents, replies)
       images will be downloaded.
    2. An archived.moe URL to an image hash, where each page will be crawled, and linked images
       downloaded. The crawler will also view each new image hash and repeat the process until no
       more images can be found.
        - The user will be prompted whenever a new image hash is found to ensure only related images
          are crawled.

Optionally, a path to an output directory can also be supplied, otherwise the current directory is used.

Requirements:
    bs4
    requests
    ImageHash
    opencv-python

# python3 -m pip install bs4 requests ImageHash opencv-python

Changelog:
(29-09-22)
- Rewrote hash crawler
- Added option to go back while verifying hashes
- Added option to skip the current hash
- Sorted posts by id when verifying
- Added automatic image comparison, similar images will automatically be grabbed
- Increased save interval
- Added option to manually delete images from the temp folders which aren't wanted, this can then
  be combined with the [A]ll option to quickly grab only relevant images from a thread / hash
- Images are only downloaded once and moved if approved by user
- Multithreaded everything
- Bugfixes and other smaller improvements
```