import hashlib
import io
import os
import pprint
import re
import typing

import filetype
import requests
from tqdm import tqdm
from urllib.parse import urlparse

from redd_harvest.config import Link, SubSearch
from redd_harvest.post import Post

NEW_SAVED = "NEW_SAVED"
ALREADY_SAVED = "ALREADY_SAVED"
SEEN_NOT_SAVED = "SEEN_NOT_SAVED"
NOT_SAVED = "NOT_SAVED"
IGNORED = "IGNORED"
BONK = "BONK"


class RetrievalStatus:
    def __init__(self, status, source_url, local_file, digest):
        self.status: str = status
        self.source_url: str = source_url
        self.local_file: str = local_file
        self.digest: str = digest


def _uri_validator(x: str) -> bool:
    """Is it a valid URI?"""
    try:
        result = urlparse(x)
        return all([result.scheme, result.netloc, result.path])
    except Exception as _:
        return False


def _wget_data(url: str, progress_bar: tqdm) -> bytes:
    """Get raw data from the specified url."""
    data = bytes()
    with requests.get(url, stream=True, timeout=(5, 8)) as r:
        r.raise_for_status()
        total_size_bytes = int(r.headers.get("content-length", 0))
        block_size = 16384  # 16 kibibytes
        progress_bar.total = total_size_bytes
        progress_bar.refresh()
        # figure out better way of handling for extremely large file case
        with io.BytesIO() as buf:
            for chunk in r.iter_content(chunk_size=block_size):
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                # if chunk:
                progress_bar.update(len(chunk))
                buf.write(chunk)
            data = buf.getvalue()
    return data


def _wget_page(url: str) -> str:
    """Get the page from the given url; if an exception occurs, this will fail
    and simply return an empty string.
    """
    data = ""
    rsp = requests.get(url, timeout=(5, 8))
    rsp.raise_for_status()
    data = rsp.text
    return data


def get_url_from_page(page: str, subsearch: SubSearch) -> str:
    """Extract a url from from the given page with criteria specified in the
    given SubSearch.
    """
    regex_str = rf"{subsearch.page_search_regex}"
    if not is_valid_regex(regex_str, False):
        print(f"- failed searching page contents: invalid regex: {regex_str}")
        return ""
    matches = re.findall(regex_str, page)
    if matches is not None and len(matches) > 0:
        # for debug... print(f'matched page contents: {pprint.pformat(matches)}')
        for match in matches:
            print(f"- validating matched page contents: {pprint.pformat(match)}")
            if _uri_validator(match):  # make sure the match is a valid url
                # return earliest match (some webpages will have duplicate matches)
                return match.replace("&amp;", "&")
            else:
                print(f"- not a valid url: {match}")
    else:  # consider leaving this for debug-only
        print(f"- no matches w/ regex: '{regex_str}'")
        # for debug... print(page)
    return ""


def is_valid_regex(regex_from_user: str, escape: bool) -> bool:
    """Is it a valid regex? Can choose whether or not to escape."""
    try:
        if escape:
            re.compile(re.escape(regex_from_user))
        else:
            re.compile(regex_from_user)
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
        print(f"- failed checking '{url}' invalid regex: {regex_str}")
        return False
    elif re.search(regex_str, lower_url):
        return True
    return False


def get_direct_download_url(url: str, link: Link) -> typing.List[str]:
    """If the given url matched the direct download criteria in the given link,
    a massaged url is returned.  Returns as a list just for consistency with
    similar functions.
    """
    dl_urls: typing.List[str] = []
    for ext in link.direct_dl_url_extensions:
        if safe_matches_regex(f"^.+\\.{ext.lower()}$", url):
            dl_urls.append(url)  # easy match!
            continue
        # try to handle imgur-like _d thumbnail url w/ extra properties
        if safe_matches_regex(f"^.+_d\\.{ext.lower()}\\?.*$", url):
            d_index = url.index("_d")
            new_url = f"{url[:d_index]}.{ext.lower()}"
            dl_urls.append(new_url)
            continue
        # try to handle imgur-like url w/ just extra properties
        if safe_matches_regex(f"^.+\\.{ext.lower()}\\?.*$", url):
            prop_index = url.index("?")
            new_url = url[:prop_index]
            dl_urls.append(new_url)
            continue
        # for debug... else: print(f'couldn\'t match {url} and extension {ext}')
    return dl_urls


def get_urls_from_media_metadata(
    post_raw: typing.Dict[str, typing.Any],
) -> typing.List[str]:
    """Extract urls from gallery item media metadata for highest available
    quality media.
    """
    # debug... print(pprint.pformat(post_raw))
    dl_urls: typing.List[str] = []
    for gallery_item in post_raw["media_metadata"].keys():
        gallery_item_url = post_raw["media_metadata"][gallery_item]["s"]["u"]
        dl_urls.append(gallery_item_url.strip())
    return dl_urls


def get_urls_from_gallery(post: Post) -> typing.List[str]:
    """Get direct download urls from a post when it's a gallery."""
    url = post.url
    post_raw = post.post_raw
    dl_urls: typing.List[str] = []
    # extract links from raw post json (if gallery or crosspost of gallery)
    if post_raw.get("is_gallery", False):
        try:
            dl_urls.extend(get_urls_from_media_metadata(post_raw))
        except (KeyError, AttributeError) as e:
            print(f"- error getting gallery items from post at {url}: {e}")
    elif post_raw.get("crosspost_parent", False):
        print(f"- found a crosspost of '{post_raw.get('crosspost_parent')}''")
        try:
            for cross in post_raw.get("crosspost_parent_list", []):
                if cross.get("is_gallery", False):
                    dl_urls.extend(get_urls_from_media_metadata(cross))
        except (KeyError, AttributeError) as e:
            print(f"- error getting gallery items from (cross)post at {url}: {e}")
    return dl_urls


def get_matching_urls_from_page(url: str, link: Link) -> typing.List[str]:
    """Extract urls from the page the given url points to that match the
    criteria specified in the given link.
    """
    lower_url = url.lower()
    dl_urls: typing.List[str] = []
    try:
        page = _wget_page(url)
        for ss in link.sub_searches:
            dl_url: str = ""
            if ss.extension is not None:  # match extension if provided
                if re.search(f"^.*\\.{ss.extension.lower()}$", lower_url):
                    dl_url = get_url_from_page(page, ss)
            else:
                dl_url = get_url_from_page(page, ss)
            if dl_url != "" and dl_url not in dl_urls:  # append unique
                dl_urls.append(dl_url)
        # for debug... else: print(f'\'{lower_url}\' didn\'t match \'{link.base_url.lower()}\'')
    except Exception as e:
        print(f"- error extracting urls from page at '{url}': {e}")
    return dl_urls


def get_urls_from_media_reddit_video(
    post_raw: typing.Dict[str, typing.Any],
) -> typing.List[str]:
    """Extract urls from media.reddit_video for original media."""
    # debug... print(pprint.pformat(post_raw))
    dl_urls: typing.List[str] = []
    video_url = post_raw["media"]["reddit_video"]["fallback_url"]
    dl_urls.append(video_url.strip())
    return dl_urls


def get_urls_from_reddit_video(post: Post) -> typing.List[str]:
    """Get direct download urls from a post when it's a reddit video."""
    url = post.url
    post_raw = post.post_raw
    dl_urls: typing.List[str] = []
    # extract links from raw post json (if reddit video or crosspost of reddit_video)
    if post_raw.get("is_video", False):
        try:
            dl_urls.extend(get_urls_from_media_reddit_video(post_raw))
        except (KeyError, AttributeError) as e:
            print(f"- error getting video from post at {url}: {e}")
    elif post_raw.get("crosspost_parent", False):
        print(f"- found a crosspost of '{post_raw.get('crosspost_parent')}''")
        try:
            for cross in post_raw.get("crosspost_parent_list", []):
                if post_raw.get("is_video", False):
                    dl_urls.extend(get_urls_from_media_reddit_video(cross))
        except (KeyError, AttributeError) as e:
            print(f"- error getting video from (cross)post at {url}: {e}")
    return dl_urls


def get_all_matching_urls(post: Post, links: typing.List[Link]) -> typing.List[str]:
    """Get urls that point to desired content based on the the given Post and
    the list of Links that define desired matches.
    """
    dl_urls: typing.List[str] = []
    # debug... print(pprint.pformat(post.post_raw))
    for link in links:
        # a single url should only match one from link list, so return on first
        # match should be safe;
        if post.url.lower().find(link.base_url.lower()) == 0:
            dl_urls.extend(get_direct_download_url(post.url, link))
            if len(dl_urls) > 0:  # early return for direct download urls if matched
                return dl_urls
            dl_urls.extend(get_urls_from_gallery(post))
            if len(dl_urls) > 0:  # early return for gallery urls if matched
                return dl_urls
            dl_urls.extend(get_urls_from_reddit_video(post))
            if len(dl_urls) > 0:  # early return for hosted reddit video if matched
                return dl_urls
            dl_urls.extend(get_matching_urls_from_page(post.url, link))
    return dl_urls


def _filename_from_url(dl_url: str) -> str:
    """Returns name of the file from the given url and removes properties,
    if they exist in the url."""
    filename = os.path.basename(dl_url)
    if "?" in filename:
        prop_index = filename.index("?")
        if prop_index > 0:
            filename = filename[:prop_index]
    return filename


def _dir_and_ext_by_type(
    tmp_data: bytes, filename: str, sep_by_media: bool
) -> typing.Tuple[str, str]:
    """Given the file bytes and filename, determines a folder to sort media
    into and determines an appropriate file extension."""
    _, file_ext = os.path.splitext(filename)
    file_ext = file_ext.lower()
    if file_ext == ".jpeg":
        file_ext = ".jpg"
    media_dir = "."
    if sep_by_media:
        try:
            data_kind = filetype.guess(tmp_data)
            if filetype.is_image(tmp_data):
                media_dir = "images"
                if data_kind is not None:
                    file_ext = f".{data_kind.extension}"
            elif filetype.is_video(tmp_data):
                media_dir = "videos"
                if data_kind is not None:
                    file_ext = f".{data_kind.extension}"
            else:
                media_dir = "unknown"
        except Exception as e:
            print(f"ERROR: exception raised while parsing filetype: {e}")
            media_dir = "unknown"
    return media_dir, file_ext


def retrieve_content(
    sep_by_media: bool,
    dl_root: str,
    dl_subdir: str,
    post: Post,
    links: typing.List[Link],
) -> typing.List[RetrievalStatus]:
    """Attempt to retrieve content from the given post, based on the provided
    list of Links to define desired content, and save matches in the given
    download folder. Returns a status.
    """
    result: typing.List[RetrievalStatus] = []
    os.makedirs(dl_root, 0o755, True)

    dl_urls = get_all_matching_urls(post, links)
    if dl_urls is not None and len(dl_urls) > 0:
        for dl_url in dl_urls:
            filename = _filename_from_url(dl_url)
            progress_bar = tqdm(unit="iB", unit_scale=True, colour="#546975")
            try:
                tmp_data = _wget_data(dl_url, progress_bar)
                tmp_digest = hashlib.sha256(tmp_data).hexdigest()
                media_dir, file_ext = _dir_and_ext_by_type(
                    tmp_data, filename, sep_by_media
                )
                dl_folder = os.path.normpath(
                    os.sep.join([dl_root, media_dir, dl_subdir])
                )
                os.makedirs(dl_folder, 0o755, True)
                finalfile = os.sep.join([dl_folder, f"{tmp_digest}{file_ext}"])
                # if we already have at least one file with matching digest
                if len(
                    [
                        file
                        for file in os.listdir(dl_folder)
                        if re.search(rf"{tmp_digest}", file)
                    ]
                ):
                    result.append(
                        RetrievalStatus(ALREADY_SAVED, dl_url, finalfile, tmp_digest)
                    )
                else:
                    with open(finalfile, "wb") as out:
                        out.write(tmp_data)
                    result.append(
                        RetrievalStatus(NEW_SAVED, dl_url, finalfile, tmp_digest)
                    )
                    progress_bar.colour = "#196593"
                    progress_bar.refresh()
                progress_bar.close()
            except Exception as e:
                print(f"- error fetching content from {post.url}: {e}")
                result.append(RetrievalStatus(NOT_SAVED, post.url, "", ""))
                progress_bar.colour = "#9042f5"
                progress_bar.refresh()
                progress_bar.close()
    else:
        result.append(RetrievalStatus(NOT_SAVED, post.url, "", ""))

    return result
