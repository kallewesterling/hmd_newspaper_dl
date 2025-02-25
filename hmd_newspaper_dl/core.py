# AUTOGENERATED! DO NOT EDIT! File to edit: 00_core.ipynb (unless otherwise specified).

__all__ = ['get_newspaper_links', 'get_download_urls', 'create_session', 'download_from_urls', 'cli']

# Cell
import concurrent
import itertools
import json
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import random
import sys
import time
from collections import namedtuple
from functools import lru_cache
from operator import itemgetter

# from os import umask
import os
from pathlib import Path
from typing import List, Optional, Union

import requests
from bs4 import BeautifulSoup
from fastcore.script import *
from fastcore.test import *
from fastcore.net import urlvalid
from loguru import logger
from nbdev.showdoc import *
from tqdm import tqdm

# Cell
def _get_link(x: str):
    end = x.split("/")[-1]
    return "https://bl.iro.bl.uk/concern/datasets/" + end

# Cell
@lru_cache(256)
def get_newspaper_links():
    """Returns titles from the Newspaper Collection"""
    urls = [
        f"https://bl.iro.bl.uk/collections/9a6a4cdd-2bfe-47bb-8c14-c0a5d100501f?locale=en&page={page}"
        for page in range(1, 3)
    ]
    link_tuples = []
    for url in urls:
        r = requests.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        links = soup.find_all(
            "p",
            class_="media-heading",
        )
        for link in links:
            link = link.find("a")
            url = link["href"]
            if url:
                t = (link.text, _get_link(url))
                link_tuples.append(t)
        return link_tuples

# Cell
@lru_cache(256)
def get_download_urls(url: str) -> list:
    """Given a dataset page on the IRO repo return all download links for that page"""
    data, urls = None, None
    try:
        r = requests.get(url, timeout=30)
    except requests.exceptions.MissingSchema as E:
        print(E)

    soup = BeautifulSoup(r.text, "lxml")
    link_ends = soup.find_all("a", id="file_download")
    urls = ["https://bl.iro.bl.uk" + link["href"] for link in link_ends]
    # data = json.loads(soup.find("script", type="application/ld+json").string)
    # except AttributeError as E:
    #     print(E)
    # if data:
    #     #data = data["distribution"]
    #     #urls = [item["contentUrl"] for item in data]
    return list(set(urls))

# Cell
def create_session() -> requests.sessions.Session:
    """returns a requests session"""
    retry_strategy = Retry(total=60)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# Cell
def _download(url: str, dir: Union[str, Path]):
    time.sleep(10)
    fname = None
    s = create_session()
    try:
        r = s.get(url, stream=True, timeout=(30))
        r.raise_for_status()
        # fname = r.headers["Content-Disposition"].split('_')[1]
        fname = "_".join(r.headers["Content-Disposition"].split('"')[1].split("_")[0:5])
        if fname:
            with open(f"{dir}/{fname}", "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    except KeyError:
        pass
    except requests.exceptions.RequestException as request_exception:
        logger.error(request_exception)
    return fname

# Cell
def download_from_urls(urls: List[str], save_dir: Union[str, Path], n_threads: int = 4):
    """Downloads from an input lists of `urls` and saves to `save_dir`, option to set `n_threads` default = 8"""
    download_count = 0
    tic = time.perf_counter()
    Path(save_dir).mkdir(exist_ok=True)
    logger.remove()
    logger.add(lambda msg: tqdm.write(msg, end=""))
    with tqdm(total=len(urls)) as progress:
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
            future_to_url = {
                executor.submit(_download, url, save_dir): url for url in urls
            }
            for future in future_to_url:
                future.add_done_callback(lambda p: progress.update(1))
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    data = future.result()
                except Exception as e:
                    logger.error("%r generated an exception: %s" % (url, e))
                else:
                    if data:
                        logger.info(f"{url} downloaded to {data}")
                        download_count += 1
        toc = time.perf_counter()
    logger.remove()
    logger.info(f"Downloads completed in {toc - tic:0.4f} seconds")
    return download_count

# Cell
@call_parse
def cli(
    save_dir: Param("Output Directory", str),
    n_threads: Param("Number threads to use") = 8,
    subset: Param("Download subset of HMD", int, opt=True) = None,
    url: Param("Download from a specific URL", str, opt=True) = None,
):
    "Download HMD newspaper from iro to `save_dir` using `n_threads`"
    if url is not None:
        logger.info(f"Getting zip download file urls for {url}")
        try:
            zip_urls = get_download_urls(url)
            print(zip_urls)
        except Exception as e:
            logger.error(e)
        download_count = download_from_urls(zip_urls, save_dir, n_threads=n_threads)
    else:
        logger.info("Getting title urls")
        title_urls = get_newspaper_links()
        logger.info(f"Found {len(title_urls)} title urls")
        all_urls = []
        print(title_urls)
        for url in title_urls:
            logger.info(f"Getting zip download file urls for {url}")
            try:
                zip_urls = get_download_urls(url[1])
                all_urls.append(zip_urls)
            except Exception as e:
                logger.error(e)
        all_urls = list(itertools.chain(*all_urls))
        if subset:
            if len(all_urls) < subset:
                raise ValueError(
                    f"Size of requested sample {subset} is larger than total number of urls:{all_urls}"
                )
            all_urls = random.sample(all_urls, subset)
        print(all_urls)
        download_count = download_from_urls(all_urls, save_dir, n_threads=n_threads)
        request_url_count = len(all_urls)
        if request_url_count == download_count:
            logger.info(
                f"\U0001F600 Requested count of urls: {request_url_count} matches number downloaded: {download_count}"
            )
        if request_url_count > download_count:
            logger.warning(
                f"\U0001F622 Requested count of urls: {request_url_count} higher than number downloaded: {download_count}"
            )
        if request_url_count < download_count:
            logger.warning(
                f"\U0001F937 Requested count of urls: {request_url_count} lower than number downloaded: {download_count}"
            )