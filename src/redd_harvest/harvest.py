from datetime import datetime
from importlib.resources import files as pkg_files

# from importlib_resources import files # would need to install this for python < 3.10
import os
import signal
from string import Template
import sys
from threading import Event
import traceback

import click
import praw

from redd_harvest import fetch
from redd_harvest.config import ReddHarvestConfig, gather_config
from redd_harvest.post import Post
from redd_harvest.version import __version__

DEFAULT_CONFIG_FILE = os.sep.join(["~", ".config", "redd-harvest", "config.yml"])
REDD_HARVEST_USER_AGENT_TEMPLATE = "python:$app:$ver (by /u/$username)"


def build_praw_client(redd_config: ReddHarvestConfig) -> praw.Reddit:
    """Build a praw reddit client based on available credentials and
    configuration.
    """
    cid = redd_config.globals.client_id
    cs = redd_config.globals.client_secret
    assert (
        cid is not None and len(cid) > 0 and cs is not None and len(cs) > 0
    ), "client_id and client_secret are required configurations; aborting..."

    u = redd_config.globals.username
    p = redd_config.globals.password
    ua = Template(REDD_HARVEST_USER_AGENT_TEMPLATE).substitute(
        app=redd_config.globals.app,
        ver=__version__,
        username=u,
    )
    print(f"constructed user-agent: '{ua}'")
    if p is None or len(p) < 1:
        print("password not defined, continuing with unauthenticated client...")
        return praw.Reddit(
            client_id=cid,
            client_secret=cs,
            user_agent=ua,
            ratelimit_seconds=redd_config.globals.rate_limit_max_wait,
        )

    print("continuing with fully authenticated client...")
    return praw.Reddit(
        client_id=cid,
        client_secret=cs,
        username=u,
        password=p,
        user_agent=ua,
        ratelimit_seconds=redd_config.globals.rate_limit_max_wait,
    )


class Harvester:
    def __init__(self, interactive: bool = False):
        self.interrupt_flag: bool = False
        self.interactive: bool = interactive
        self.orig_sigint = signal.getsignal(signal.SIGINT)
        self.sleepy: Event = Event()
        signal.signal(signal.SIGINT, self.interrupt)

    def interrupt(self, signum, frame):
        """A SIGINT handler."""
        # Restore original signal handler in case bad things happen when CTRL+C
        # is pressed again, and our signal handler is not re-entrant.
        signal.signal(signal.SIGINT, self.orig_sigint)
        try:
            if not self.interactive:
                self.interrupt_flag = True
                self.sleepy.set()
            else:
                res = input("do you really want to exit? (y/n): ")
                if res.lower().startswith("y"):
                    self.interrupt_flag = True
                    self.sleepy.set()
        except KeyboardInterrupt:
            print("ok ok, quitting, sheesh...")
            sys.exit(1)
        # Restore our own handler.
        signal.signal(signal.SIGINT, self.interrupt)

    def is_interrupted(self) -> bool:
        """Sets an internal flag for cleanly terminating."""
        return self.interrupt_flag

    def sleep(self, timeout: float = 1) -> bool:
        """Wrapper for the per-instance threading.Event()."""
        return self.sleepy.wait(timeout=timeout)

    def harvest(
        self,
        reddit: praw.Reddit,
        redd_config: ReddHarvestConfig,
        subreddits_only: bool = False,
        redditors_only: bool = False,
        only_name: str = "",
    ) -> int:
        """Harvest posts from reddit with the given client and config."""
        # before doing anything, prune ignorable entities if configured to do so
        if redd_config.globals.prune_ignorables:
            if not self.interactive:
                redd_config.prune_ignorables()
            else:
                print("---")
                res = input(
                    "configured to prune content from ignorable entities, do you wish to continue? (y/n): "
                )
                if res.lower().startswith("y"):
                    redd_config.prune_ignorables()
                else:
                    print("not an affirmative response, pruning will be skipped...")

        post_stats = []
        entity_count = 0
        for entity in redd_config.get_entities():
            if self.is_interrupted():
                print("- interrupted, quitting early...")
                break
            if entity.is_redditor() and subreddits_only:
                print(
                    f"- configured to skip redditors; skipping '{entity.get_name()}'..."
                )
                continue
            if entity.is_subreddit() and redditors_only:
                print(
                    f"- configured to skip subreddits; skipping '{entity.get_name()}'..."
                )
                continue
            if (
                only_name is not None
                and len(only_name) > 0
                and entity.get_name() != only_name
            ):
                print(
                    f"- configured to only retrieve from '{only_name}'; skipping '{entity.get_name()}'..."
                )
                continue

            # skip backoff sleep if retrieval hasn't been attempted yet
            if entity_count > 0:
                remaining = reddit.auth.limits.get("remaining", 0)
                used = reddit.auth.limits.get("used", 0)
                ts = reddit.auth.limits.get("reset_timestamp", 0)
                tsf = 0.0
                if ts is not None:
                    try:
                        tsf = float(ts)
                    except Exception as _:
                        tsf = 0.0
                reset_timestamp = datetime.fromtimestamp(tsf)
                print(
                    f"--- current rate limits: remaining - {remaining}, used - {used}, reset_timestamp = '{reset_timestamp}'"
                )
                print(
                    f"--- sleeping for {redd_config.globals.backoff_sleep}s before next batch"
                )
                self.sleep(timeout=redd_config.globals.backoff_sleep)
            print()
            entity_count += 1
            if self.is_interrupted():
                print("- interrupted, quitting early...")
                break
            try:
                entity.validate(reddit)
                if not entity.is_valid():
                    print(
                        f"- trouble fetching submissions from '{entity.get_name()}'; continuing..."
                    )
                    continue
            except BaseException as err:
                print(
                    f"- exception occured while fetching submissions from '{entity.get_name()}': {err}\n"
                )
                continue

            count = 0
            for submission in entity.get_submissions(reddit):
                if self.is_interrupted():
                    print("- interrupted, quitting early...")
                    break
                post = Post(submission)
                print(
                    f"- processing post {count} w/ id '{post.id}' from {post.author} in {post.subreddit_name} w/ url {post.url}"
                )
                retrieval_status = [
                    fetch.RetrievalStatus(fetch.IGNORED, post.url, "", "")
                ]
                if not redd_config.should_ignore_post(post):
                    if post.over_18 and not redd_config.globals.bonk:
                        retrieval_status = [
                            fetch.RetrievalStatus(fetch.BONK, post.url, "", "")
                        ]
                    else:
                        root_folder = redd_config.get_download_root()
                        sub_folder = redd_config.get_download_sub_folder(entity, post)
                        retrieval_status = fetch.retrieve_content(
                            redd_config.separate_media(),
                            f"{root_folder}",
                            f"{sub_folder}",
                            post,
                            redd_config.links,
                        )
                for dl_status in retrieval_status:
                    print(
                        f"-- status: {dl_status.status}; source_url: {dl_status.source_url}"
                    )
                    # not sure tracking post stats is interesting anymore
                    post_stats.append(
                        [
                            post.title,
                            post.author,
                            post.subreddit_name,
                            post.url,
                            post.selftext,
                            post.created,
                            dl_status.status,
                            dl_status.source_url,
                            dl_status.local_file,
                            dl_status.digest,
                        ]
                    )
                count += 1
                # manually check to handle searches that do not accept limits (i.e. stream)
                if count >= entity.get_search_criteria().post_limit:
                    break
            print(f"--- processed {count} posts from '{entity.get_name()}'")

        return 0


@click.command(name="setup")
def bootstrap_config() -> int:
    """Bootstrap an example config in the default location."""
    config_file = os.path.expanduser(DEFAULT_CONFIG_FILE)
    if os.path.exists(config_file):
        print(f"config '{config_file}' already exists, no action taken...")
        return 1
    os.makedirs(os.path.dirname(config_file), 0o700, True)
    data = pkg_files("redd_harvest.data").joinpath("example.yml").read_bytes()
    descriptor = os.open(
        path=config_file, flags=(os.O_WRONLY | os.O_CREAT | os.O_TRUNC), mode=0o600
    )
    with open(descriptor, "wb") as out:
        out.write(data)
    print(f"wrote example configuration to '{config_file}', check it out!")
    return 0


@click.command(name="run")
@click.option(
    "-c",
    "--config",
    default=os.path.expanduser(DEFAULT_CONFIG_FILE),
    help=f"Path to config file (default: {DEFAULT_CONFIG_FILE}).",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True, readable=True),
)
@click.option(
    "-s",
    "--subreddits-only",
    is_flag=True,
    help="Only download from configured subreddits (useful in testing).",
)
@click.option(
    "-r",
    "--redditors-only",
    is_flag=True,
    help="Only download from configured redditors (useful in testing).",
)
@click.option(
    "-o",
    "--only-name",
    default="",
    help="Only download from a configured entity with the given name (useful in testing).",
    type=str,
)
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    help="Elevates a few interactive prompts when certain events occur.",
)
def run(
    config: str,
    subreddits_only: bool,
    redditors_only: bool,
    only_name: str,
    interactive: bool,
) -> int:
    """Run the harvester."""
    # TODO: accept --debug flag for debug logging; better logging in general

    print(f"using config file: {config}")
    redd_config = gather_config(config)
    rc = 0
    try:
        reddit = build_praw_client(redd_config)
        harvester = Harvester(interactive)
        rc = harvester.harvest(
            reddit, redd_config, subreddits_only, redditors_only, only_name
        )
    except Exception as _:
        traceback.print_exc()
        rc = 1
    return rc


@click.group(name="redd-harvest")
@click.version_option(version=__version__)
@click.help_option()
def main():
    """Download media from Reddit posts. Why? Why not."""
    pass


main.add_command(run)
main.add_command(bootstrap_config)
