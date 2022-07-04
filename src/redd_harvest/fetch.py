import hashlib
import os
import pprint
import re
import typing

import urllib3
from urllib.parse import urlparse

from redd_harvest.config import Link, SubSearch
from redd_harvest.post import Post

NEW_SAVED = 'NEW_SAVED'
ALREADY_SAVED = 'ALREADY_SAVED'
SEEN_NOT_SAVED = 'SEEN_NOT_SAVED'
NEW_NOT_SAVED = 'NEW_NOT_SAVED'
IGNORED ='IGNORED'
BONK = 'BONK'

class RetrievalStatus():
    def __init__(self, status, source_url, local_file, digest):
        self.status:str = status
        self.source_url:str = source_url
        self.local_file:str = local_file
        self.digest:str = digest

#def wget_file(url: str, outfile: str) -> bool:
#    http = urllib3.PoolManager()
#    rsp = http.request('GET', url, preload_content=False)
#    with open(outfile, 'wb') as out:
#        while True:
#            data = rsp.read(64)
#            if not data:
#                break
#            out.write(data)
#    rsp.release_conn()
#    return True

def wget_data(url: str):
    """Get raw data from the specified url."""
    # TODO: refactor to use requests instead of urlllib3?
    http = urllib3.PoolManager()
    rsp = http.request('GET', url, preload_content=False) # TODO: handle redirects
    data = rsp.read()
    rsp.release_conn()
    return data

def wget_page(url: str) -> str:
    """Get the page from the given url; if it can't be decoded as a utf-8
    string, this will fail and simply return an empty string.
    """
    # TODO: refactor to use requests instead of urlllib3?
    # for debug... print(f'fetching page at {url}')
    http = urllib3.PoolManager()
    rsp = http.request('GET', url, preload_content=False)
    try:
        data = rsp.read().decode('utf-8')
    except UnicodeDecodeError as e:
        print(f'- page fetch status code: {rsp.status}')
        print(f'- error decoding page at {url}: {e.reason}')
        data = ''
    rsp.release_conn()
    return data

def uri_validator(x: str) -> bool:
    """Is it a valid URI?"""
    try:
        result = urlparse(x)
        return all([result.scheme, result.netloc, result.path])
    except:
        return False

def get_url_from_page(page: str, subsearch: SubSearch) -> str:
    """Extract a url from from the given page with criteria specified in the
    given SubSearch.
    """
    regex_str = rf'{subsearch.page_search_regex}'
    if not is_valid_regex(regex_str, False):
        print(f'- failed searching page contents: invalid regex: {regex_str}')
        return None
    matches = re.findall(regex_str, page)
    if matches is not None and len(matches) > 0:
        # for debug... print(f'matched page contents: {pprint.pformat(matches)}')
        for match in matches:
            print(f'- validating matched page contents: {pprint.pformat(match)}')
            if uri_validator(match): # make sure the match is a valid url
                # return earliest match (some webpages will have duplicate matches)
                return match
            else: print(f'- not a valid url: {match}')
    else: # consider leaving this for debug-only
        print(f'- no matches w/ regex: \'{regex_str}\'')
        # for debug... print(page)
    return None

def is_valid_regex(regex_from_user: str, escape: bool) -> bool:
    """Is it a valid regex? Can choose whether or not to escape."""
    try:
        if escape: re.compile(re.escape(regex_from_user))
        else: re.compile(regex_from_user)
        is_valid = True
    except re.error:
        is_valid = False
    return is_valid

def safe_matches_regex(regex_str: str, url: str) -> bool:
    """Returns whether or not the given url matches the given regex string.  If
    the regex string fails to compile, returns False.  If the given url cast to
    lowercase matches the regex string, returns True, otherwise returns False.
    """
    lower_url = url.lower()
    if not is_valid_regex(regex_str, False):
        print(f'- failed checking \'{url}\' invalid regex: {regex_str}')
        return False
    elif re.search(regex_str, lower_url):
        return True
    return False

def get_direct_download_url(url: str, link: Link) -> typing.List[str]:
    """If the given url matched the direct download criteria in the given link,
    a massaged url is returned.  Returns as a list just for consistency with
    similar functions.
    """
    dl_urls:typing.List[str] = []
    for ext in link.direct_dl_url_extensions:
        if safe_matches_regex(f'^.+\.{ext.lower()}$', url):
            dl_urls.append(url) # easy match!
            continue
        # try to handle imgur-like _d thumbnail url w/ extra properties
        if safe_matches_regex(f'^.+_d\.{ext.lower()}\?.*$', url):
            d_index = url.index('_d')
            new_url = f'{url[:d_index]}.{ext.lower()}'
            dl_urls.append(new_url)
            continue
        # try to handle imgur-like url w/ just extra properties
        if safe_matches_regex(f'^.+\.{ext.lower()}\?.*$', url):
            prop_index = url.index('?')
            new_url = url[:prop_index]
            dl_urls.append(new_url)
            continue
        # for debug... else: print(f'couldn\'t match {url} and extension {ext}')
    return dl_urls

def get_urls_from_media_metadata(post_raw: typing.Dict[str, typing.Any]) -> typing.List[str]:
    """Extract urls from gallery item media metadata for highest available
    quality media.
    """
    # debug... print(pprint.pformat(post_raw))
    dl_urls:typing.List[str] = []
    for gallery_item in post_raw['media_metadata'].keys():
        gallery_item_url = post_raw['media_metadata'][gallery_item]['s']['u']
        dl_urls.append(gallery_item_url.strip())
    return dl_urls

def get_urls_from_gallery(post: Post) -> typing.List[str]:
    """Get direct download urls from a post when it's a gallery."""
    url = post.url
    post_raw = post.post_raw
    dl_urls:typing.List[str] = []
    # extract links from raw post json (if gallery or crosspost of gallery)
    if post_raw.get('is_gallery', False):
        try:
            dl_urls.extend(get_urls_from_media_metadata(post_raw))
        except (KeyError, AttributeError) as e:
            print(f'- error getting gallery items from post at {url}: {e}')
    elif post_raw.get('crosspost_parent', False):
        print(f"- found a crosspost of \'{post_raw.get('crosspost_parent')}\''")
        try:
            for cross in post_raw.get('crosspost_parent_list', []):
                if cross.get('is_gallery', False):
                    dl_urls.extend(get_urls_from_media_metadata(cross))
        except (KeyError, AttributeError) as e:
            print(f'- error getting gallery items from (cross)post at {url}: {e}')
    return dl_urls

def get_matching_urls_from_page(url: str, link: Link) -> typing.List[str]:
    """Extract urls from the page the given url points to that match the
    criteria specified in the given link.
    """
    lower_url = url.lower()
    dl_urls:typing.List[str] = []
    page = wget_page(url)
    for ss in link.sub_searches:
        dl_url:str = ""
        if ss.extension is not None: # match extension if provided
            if re.search(f'^.*\.{ss.extension.lower()}$', lower_url):
                dl_url = get_url_from_page(page, ss)
        else:
            dl_url = get_url_from_page(page, ss)
        if dl_url is not None and dl_url != "" and dl_url not in dl_urls: # append unique
            dl_urls.append(dl_url)
    # for debug... else: print(f'\'{lower_url}\' didn\'t match \'{link.base_url.lower()}\'')
    return dl_urls

def get_all_matching_urls(post: Post, links: typing.List[Link]) -> typing.List[str]:
    """Get urls that point to desired content based on the the given Post and
    the list of Links that define desired matches.
    """
    dl_urls:typing.List[str] = []
    for link in links:
        # a single url should only match one from link list, so return on first
        # match should be safe;
        if post.url.lower().find(link.base_url.lower()) == 0:
            dl_urls.extend(get_direct_download_url(post.url, link))
            if len(dl_urls) > 0: # early return for direct download urls if matched
                return dl_urls
            dl_urls.extend(get_urls_from_gallery(post))
            if len(dl_urls) > 0: # early return for gallery urls if matched
                return dl_urls
            dl_urls.extend(get_matching_urls_from_page(post.url, link))
    return dl_urls

def retrieve_content(dl_folder: str, post: Post, links: typing.List[Link]) -> typing.List[RetrievalStatus]:
    """Attempt to retrieve content from the given post, based on the provided
    list of Links to define desired content, and save matches in the given 
    download folder. Returns a status.
    """
    result:typing.List[RetrievalStatus] = []
    os.makedirs(dl_folder, 0o755, True)

    dl_urls = get_all_matching_urls(post, links)
    if dl_urls is not None and len(dl_urls) > 0:
        for dl_url in dl_urls:
            filename = os.path.basename(dl_url)
            if '?' in filename:
                prop_index = filename.index('?')
                if prop_index > 0:
                    filename = filename[:prop_index]
            _, file_ext = os.path.splitext(filename)
            tmp_data = wget_data(dl_url)
            tmp_digest = hashlib.sha1(tmp_data).hexdigest()
            finalfile = os.sep.join([dl_folder, f'{tmp_digest}{file_ext}'])
            if os.path.exists(finalfile):
                result.append(RetrievalStatus(ALREADY_SAVED, dl_url, finalfile, tmp_digest))
            else:
                with open(finalfile, 'wb') as out:
                    out.write(tmp_data)
                result.append(RetrievalStatus(NEW_SAVED, dl_url, finalfile, tmp_digest))
    else:
        result.append(RetrievalStatus(NEW_NOT_SAVED, post.url, '', ''))
    
    return result