# redd-harvest
Download media from Reddit posts.  Why? Why not.

# Install
This can be installed using pip:
```bash
python3 -m pip install --upgrade redd-harvest
```

## Setup from source
A `Makefile` is available that should make it easy (for most UNIX users) to get this project set up.  The only requirements are `python3`, `venv`, and `setuptools`.

```bash
# Set up a virtual environment and install the project's dependencies:
make
# Activate the virtual environment to interact with a live editable version:
. ./activate
# ...and it should be available to run:
redd-harvest --help
```

# Options
```
Global Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  run    Run the harvester.
  setup  Bootstrap an example config in the default location.

Options for 'run':
  -c, --config FILE      Path to config file (default: ~/.config/redd-
                         harvest/config.yml).
  -s, --subreddits-only  Only download from configured subreddits (useful in
                         testing).
  -r, --redditors-only   Only download from configured redditors (useful in
                         testing).
  -o, --only-name TEXT   Only download from a configured entity with the given
                         name (useful in testing).
  -i, --interactive      Elevates a few interactive prompts when certain
                         events occur.
  --help                 Show this message and exit.

Options for 'setup':
  --help  Show this message and exit.
```

# Configuration
This is where a majority of the tuneables live.  A default configuration is not initially provided upon installation, but if you want to use the below example as a starting point, just run `redd-harvest setup`.

## Before getting started
Before jumping in and running this, since this interacts with the Reddit API, you need a Reddit account.  Create one at [reddit.com](https://www.reddit.com/).

Next, at a minimum, you need a Client ID & Client Secret to access Reddit's API as a *script* application (that's what this is!).  If you don't already have those, follow Reddit's [First Steps Guide](https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example#first-steps) to create them.

Once you have a Client ID & Client Secret, these must be provided to `redd-harvest` via its configuration file.  This is enough to get you a read-only client to start running.

If an authorized client is desired, you'll also need to provide your username and password via the the configuration file, as well.  Currently, `redd-harvest` doesn't benefit much from being fully authenticated/authorized, except for seeing an increased upper bound for Reddit's API rate limit.

## Config File Structure
```yaml
---
globals:
  # Used in the construction of the user-agent; this should coincide with the
  # name of the associated app created in your reddit account.
  app: redd-harvest
  # Used in user-agent and reddit client construction (both username and
  # password are required to build a fully authenticated reddit client).
  username: <put-your-username-here>
  # Used to build a fully authenticated reddit client.
  password: <put-your-password-here>
  # Obtained from Reddit after setting up your script application.
  client_id: <put-your-client-id-here>
  # Obtained from Reddit after setting up your script application.
  client_secret: <put-your-client-secret-here>
  # Default post limit; can be overwritten here, or individually at each
  # redditor/subreddit entry.
  post_limit: 5
  # Direct pass-through to praw rate limit max wait setting.
  rate_limit_max_wait: 300
  # Seconds to sleep between fetching submisisons from each configured entity
  # (a redditor or subreddit). This can be used as a 'protective' measure to
  # reduce the likelihood of running up against the reddit api rate limits,
  # even though rate limits should be cleanly handled.
  backoff_sleep: 0.1
  # Folder to use for saving content retrieved from submissions.
  download_folder: ~/.redd-harvest/data
  # Within the download folder, store files by media type (image/video).
  separate_media: true
  # By default pruning is disabled; if set to true, pruning of saved media is
  # executed before retrieving new posts. Pruning: if we can determine that an
  # ignored redditor posted in a subreddit that is being followed, attempt to
  # remove just that redditor's posts from where nested posts would be saved.
  # If we can determine that a redditor that is being followed has posted in an
  # ignored subreddit, attempt to remove just posts from that subreddit from
  # where nested posts would be saved. 'nested' described in more detail below.
  prune_ignorables: false
  # When a post is retrieved for an entity (subreddit/redditor), and the post
  # overlaps with a configured entity of the opposite type, choose which entity
  # to favor when determining where to store the content from the post. For
  # example, if user ABC is a redditor we follow, and they also posted content
  # to a subreddit we're following, it can be chosen whether to favor the
  # download folder for user ABC or the specific subreddit. Accepted values are
  # 'redditor', 'subreddit', or 'disabled'. Default is 'redditor'.
  favor_entity: redditor
# Individual redditors can be followed the same as subreddits, but none are
# specified in this example.
redditors: []
# Specify subreddits to follow (case matters for the value of 'name').
subreddits:
  - name: EarthPorn
    # Within the specified download folder, choose how to store files; 'nested'
    # means <subreddit>/<redditor> for subreddits, and <redditor>/<subreddit>
    # for redditors. 'nested' is the default store_type for subreddits.
    store_type: nested
    # When creating a folder for the downloaded files, use this as the folder
    # name rather than the name of the subreddit/redditor; this is ignored when
    # using store_type 'really flat' (see below).
    alias: earthpapes
    search_criteria:
      # Post limit specified at the level of each entity takes precedence over
      # a globally defined post limit.
      post_limit: 10
      # Specify how to sort posts when retrieving from the entity, the same as
      # how you would when browsing reddit.  A special 'stream' option is also
      # supported which behaves like 'new', but live streams posts as they are
      # submitted (which has the side effect of ignoring pinned submissions).
      sort_type: hot
  - name: wallpaper
    # Within the specified download folder, you can also choose to store files
    # in a 'flat' structure; 'flat' means <subreddit> for subreddits, and
    # <redditor> for redditors. 'flat' is the default store_type for redditors.
    store_type: flat
    search_criteria:
      post_limit: 15
      sort_type: top
      # Some sort types ('top'/'controversial') support toggling a time
      # boundary; supported values are they same as when normally browsing
      # reddit ('hour', 'day', 'week', 'month', 'year', 'all').
      sort_toggle: month
  - name: wallpapers
    # Within the specified download folder, you can also choose to store files
    # in a 'really-flat' structure; 'really-flat' means files will be stored in
    # the root of the download folder.
    store_type: really-flat
    search_criteria:
      post_limit: 10
      sort_type: top
      sort_toggle: year
# Individual redditors can be ignored the same as subreddits, but none are
# specified in this example. Example situation: I want to follow a specific
# subreddit, but I don't care for seeing posts from X redditor. Just specify
# the name of the redditor (case matters). If a redditor is specified both here
# and in the redditors section, the redditor will be ignored.
ignored_redditors: []
# Example situation: I want to follow a specific redditor, but I don't care for
# seeing their posts in X subreddit. Just specify the name of the subreddit
# (case matters). If a subreddit is specified both here, and in the subreddits
# section, the subreddit will be ignored.
ignored_subreddits:
  - name: drawing
  - name: birding
  - name: wildlifephotography
# We need to whitelist the urls, file extensions, etc. that we trust and care
# about saving; it's important that we trust these domains / base urls since
# we will automatically be downloading content from them.
links:
  # If a given post links to a url with this base, ...
  - base_url: https://i.redd.it
    # ...then we'll try to directly download it if the url matches the listed
    # extensions.
    direct_dl_url_extensions: [ jpg, jpeg, png ]
  # Galleries are uniquely handled; all gallery items from a given post will be
  # downloaded (at the highest available quality).
  - base_url: https://www.reddit.com/gallery
  # Reddit-hosted videos are also uniquely handled; just specifying the
  # base_url is sufficient.
  - base_url: https://v.redd.it
  # Posts linking to a url with this base will also be entertained...
  - base_url: https://i.imgur.com
    # ...and we'll try to directly download content if the url matches the
    # listed extensions.
    direct_dl_url_extensions: [ jpg, jpeg, png ]
    sub_searches:
      # ...but if the url has this extension, we might be able to find the link
      # to the original content in the page...
      - extension: gifv
        # ...so let's use this regex to try to find the url we really want
        # within the page. Regexes are treated as raw strings, so no
        # language-specific care in escaping needs to be taken; if it works on
        # an online regex tester, there's a good chance it will work here; note
        # that this application doesn't support capture groups; if groups are
        # desired to be used, you must use non-capturing groups, like:
        # `(?:some|thing)`.
        page_search_regex: https://i\.imgur\.com/[0-9a-zA-Z]+\.mp4
  # Sometimes a site will host content from different domains/subdomains, so
  # we'll also trust imgur content from this base url...
  - base_url: https://imgur.com
    #...and we'll want to directly download the content if it matches these
    # extensions...
    direct_dl_url_extensions: [ jpg, jpeg, png ]
    # ...but if the content doesn't match the direct download extension, we can
    # use the list of regexes to search the page for the real content
    # (sub_search extentsions are optional).
    sub_searches:
      # let's look for video files...
      - page_search_regex: https://i\.imgur\.com/[0-9a-zA-Z]+\.mp4
      # ...as well as images.
      - page_search_regex: https://i\.imgur\.com/[0-9a-zA-Z]+\.jpg

```

# Behavior
## Saving content
When media files are saved, they are named by their SHA256 hash.

Instead of maintaining a separate database to track what content have already been encountered, this was chosen as a lazy means of deduplicating content.  Deduplication of files only occurs within a single given folder (i.e. deduplication does not occur across folders once a final download location is chosen based on the configuration).

Media file hashes are calculated before they are written to disk, so this also has a positive side effect of reducing writes to your filesystem.  Even though they're not written to disk, the media needs to be downloaded in order to calculate the hash, so this will still tax the network.

Another side effect of this scheme is that if you've downloaded some content that you're not interested in keeping, you can prevent `redd-harvest` from continuing to attempt to save the content by truncating the file in place.  If the content is ever encountered again, `redd-harvest` will think it already has a copy because a file name with the SHA256 already exists in the folder.  It's basically a lazy strategy for being able to ignore specific files.

## How is it intended to run?
This is designed as a one-shot tool that retrieves content from Reddit, serially.
