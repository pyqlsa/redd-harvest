import abc
import os
import shutil
import stat
from string import Template
import typing

import praw
import yaml

from redd_harvest.post import Post

# global config defaults
DEFAULT_REDD_HARVEST_APP = "redd-harvest"
DEFAULT_REDD_HARVEST_USERNAME = "unknown"
DEFAULT_POST_LIMIT = 5
DEFAULT_RATE_LIMIT_MAX_WAIT = 120
DEFAULT_BACKOFF_SLEEP = 0.1
DEFAULT_DOWNLOAD_FOLDER = os.sep.join(["~", ".redd-harvest", "data"])

FAVOR_REDDITOR = "redditor"
FAVOR_SUBREDDIT = "subreddit"
FAVOR_DISABLED = "disabled"
ALL_FAVOR_SETTINGS = [FAVOR_REDDITOR, FAVOR_SUBREDDIT, FAVOR_DISABLED]

# search sort enums
HOT = "hot"
NEW = "new"
TOP = "top"
CONTROVERSIAL = "controversial"
STREAM = "stream"
RANDOM = "random"  # single random submission
RANDOM_RISING = "random_rising"  # random rising submission(s?)
RISING = "rising"
# all submission sort types
ALL_SORT_TYPES = [HOT, NEW, TOP, CONTROVERSIAL, STREAM, RANDOM, RANDOM_RISING, RISING]
# applicable subset for redditors
REDDITOR_SORT_TYPES = [HOT, NEW, TOP, CONTROVERSIAL, STREAM]
HOUR = "hour"
DAY = "day"
WEEK = "week"
MONTH = "month"
YEAR = "year"
ALL = "all"
# only applies to 'TOP' and 'CONTROVERSIAL' sort_types
SORT_TOGGLES = [HOUR, DAY, WEEK, MONTH, YEAR, ALL]

# store media either nested (for subredddits: <subreddit>/<redditor>, for
# redditors: <redditor>/<subreddit>), or flat (for subreddits: <subreddit>,
# for redditors: <redditor>)
STORE_TYPE_NESTED = "nested"
STORE_TYPE_FLAT = "flat"
STORE_TYPE_REALLY_FLAT = "really-flat"
STORE_TYPES = [STORE_TYPE_NESTED, STORE_TYPE_FLAT, STORE_TYPE_REALLY_FLAT]

# template for redditor metadata
REDDITOR_PRINT_TEMPLATE = (
    "--------------------\n"
    "user: $name\n"
    "  id: $id\n"
    "  is_mod: $is_mod\n"
    "  is_gold: $is_gold\n"
    "  has_verified_email: $has_verified_email\n"
)

# template for redditor metadata
SUBREDDIT_PRINT_TEMPLATE = (
    "--------------------\n"
    "display_name: $display_name\n"
    "  id: $id\n"
    "  name: $name\n"
    "  over18: $over18\n"
    "  description: $description\n"
)


class Globals(yaml.YAMLObject):
    yaml_tag = "!global"

    def __init__(self, **conf):
        self.app: str = conf.get("app", DEFAULT_REDD_HARVEST_APP)
        self.username: str = conf.get("username", DEFAULT_REDD_HARVEST_USERNAME)
        self.password: str = conf.get("password", "")
        self.client_id: str = conf.get("client_id", "")
        self.client_secret: str = conf.get("client_secret", "")
        self.post_limit: int = conf.get("post_limit", DEFAULT_POST_LIMIT)
        self.rate_limit_max_wait: int = conf.get(
            "rate_limit_max_wait", DEFAULT_RATE_LIMIT_MAX_WAIT
        )
        self.backoff_sleep: float = conf.get("backoff_sleep", DEFAULT_BACKOFF_SLEEP)
        self.download_folder: str = os.path.abspath(
            os.path.expanduser(conf.get("download_folder", DEFAULT_DOWNLOAD_FOLDER))
        )
        self.separate_media: bool = conf.get("separate_media", True)
        self.bonk: bool = conf.get("bonk", False)
        if not isinstance(self.bonk, bool):
            self.bonk = False
        self.prune_ignorables: bool = conf.get("prune_ignorables", False)
        if not isinstance(self.prune_ignorables, bool):
            self.prune_ignorables = False
        self.favor_entity: str = conf.get("favor_entity", FAVOR_REDDITOR).lower()
        if self.favor_entity not in ALL_FAVOR_SETTINGS:
            self.favor_entity = FAVOR_REDDITOR  # default to redditor


class SubSearch(yaml.YAMLObject):
    yaml_tag = "!sub_search"

    def __init__(self, **conf):
        self.page_search_regex: str = conf.get("page_search_regex", None)
        self.extension: str = conf.get("extension", None)


class Link(yaml.YAMLObject):
    yaml_tag = "!link"

    def __init__(self, **conf):
        self.base_url: str = conf.get("base_url", None)
        self.direct_dl_url_extensions: typing.List[str] = conf.get(
            "direct_dl_url_extensions", []
        )
        searches: typing.List[typing.Dict[str, str]] = conf.get("sub_searches", [])
        # redundant since we've initialized this above?
        self.sub_searches: typing.List[SubSearch] = []
        for search in searches:
            s = SubSearch(**search)
            if s.page_search_regex is not None:
                self.sub_searches.append(s)  # only load qualifying sub_searches


class SearchCriteria(yaml.YAMLObject):
    yaml_tag = "!search_criteria"

    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.post_limit: int = conf.get("post_limit", default_post_limit)
        self.sort_type: str = conf.get("sort_type", NEW).lower()
        if self.sort_type not in ALL_SORT_TYPES:
            self.sort_type = NEW  # default to new if unsupported
        if self.sort_type in [TOP, CONTROVERSIAL]:
            self.sort_toggle: str = conf.get("sort_toggle", WEEK).lower()
            if self.sort_toggle not in SORT_TOGGLES:
                self.sort_toggle = WEEK  # default to week if unsupported
        else:
            self.sort_toggle = conf.get("sort_toggle", None)


class EntityInterface(metaclass=abc.ABCMeta):
    """Interface for interacting with redditors and subreddits"""

    @classmethod
    def __subclasshook__(cls, subclass):
        return (
            hasattr(subclass, "is_redditor")
            and callable(subclass.is_redditor)
            and hasattr(subclass, "is_subreddit")
            and callable(subclass.is_subreddit)
            or hasattr(subclass, "get_name")
            and callable(subclass.get_name)
            or hasattr(subclass, "get_alias")
            and callable(subclass.get_alias)
            or hasattr(subclass, "get_store_type")
            and callable(subclass.get_store_type)
            or hasattr(subclass, "get_search_criteria")
            and callable(subclass.get_search_criteria)
            or hasattr(subclass, "validate")
            and callable(subclass.validate)
            or hasattr(subclass, "is_valid")
            and callable(subclass.is_valid)
            or hasattr(subclass, "get_submissions")
            and callable(subclass.get_submissions)
            or hasattr(subclass, "get_download_folder")
            and callable(subclass.get_download_folder)
            or NotImplemented
        )

    @abc.abstractmethod
    def is_redditor(self) -> bool:
        """Is this entity a redditor"""
        raise NotImplementedError

    @abc.abstractmethod
    def is_subreddit(self) -> bool:
        """Is this entity a subreddit"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_name(self) -> str:
        """Name of the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_alias(self) -> str:
        """Alias of the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_store_type(self) -> str:
        """Storage type for the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_search_criteria(self) -> SearchCriteria:
        """Search criteria for the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def validate(self, reddit: praw.Reddit):
        """Validate against Reddit"""
        raise NotImplementedError

    @abc.abstractmethod
    def is_valid(self) -> bool:
        """Whether or not the entity has been successfully validate against Reddit"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_submissions(
        self, reddit: praw.Reddit
    ) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions (posts) from the entity from Reddit"""
        raise NotImplementedError

    def get_download_folder(self, post_author: str, post_subreddit_name: str) -> str:
        """Determine the intended download folder based on the provided post
        author and name of the subreddit where it was posted.
        """
        if self.get_store_type() == STORE_TYPE_FLAT:
            return self.get_alias()
        elif self.is_redditor() and self.get_store_type() == STORE_TYPE_FLAT:
            return os.sep.join([self.get_alias(), post_subreddit_name])
        elif self.is_subreddit() and self.get_store_type() == STORE_TYPE_FLAT:
            return os.sep.join([self.get_alias(), post_author])
        # STORE_TYPE_REALLY_FLAT
        return "."


class EntityMeta(type(yaml.YAMLObject), type(EntityInterface)):
    pass


class Redditor(yaml.YAMLObject, EntityInterface, metaclass=EntityMeta):
    yaml_tag = "!redditor"

    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.name: str = conf.get("name", None)
        self.alias: str = conf.get("alias", self.name)
        # redditors default to flat when not specified
        self.store_type: str = conf.get("store_type", STORE_TYPE_FLAT)
        if self.store_type not in STORE_TYPES:
            # default to flat if unsupported
            self.store_type = STORE_TYPE_FLAT
        sc = conf.get("search_criteria", {})
        self.search_criteria: SearchCriteria = SearchCriteria(default_post_limit, **sc)
        if self.search_criteria.sort_type not in REDDITOR_SORT_TYPES:
            # not all sort types supported for redditors; default to new if
            # unsupported
            self.search_criteria.sort_type = NEW
        self.valid: bool = False

    def is_redditor(self) -> bool:
        return True

    def is_subreddit(self) -> bool:
        return False

    def get_name(self) -> str:
        return self.name

    def get_alias(self) -> str:
        return self.alias

    def get_store_type(self) -> str:
        return self.store_type

    def get_search_criteria(self) -> SearchCriteria:
        return self.search_criteria

    def validate(self, reddit: praw.Reddit):
        """Validate the configured Redditor via a query to reddit."""
        print(f"attempting to get user {self.get_name()}")
        r = reddit.redditor(self.get_name())
        rdtr_data = Template(REDDITOR_PRINT_TEMPLATE).substitute(
            name=r.name.strip(),
            id=r.id.strip(),
            is_mod=r.is_mod,
            is_gold=r.is_gold,
            has_verified_email=r.has_verified_email,
        )
        print(rdtr_data)
        self.valid = True

    def is_valid(self) -> bool:
        """Is this redditor valid?"""
        return self.valid

    def get_submissions(
        self, reddit: praw.Reddit
    ) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions for the Redditor based on it's configuration."""
        print(
            f"searching submissions from '{self.get_name().strip()}' by {self.search_criteria.sort_type}/{self.search_criteria.sort_toggle}"
        )
        if self.search_criteria.sort_type == NEW:
            return reddit.redditor(self.get_name()).submissions.new(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == HOT:
            return reddit.redditor(self.get_name()).submissions.hot(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == TOP:
            return reddit.redditor(self.get_name()).submissions.top(
                self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == CONTROVERSIAL:
            return reddit.redditor(self.get_name()).submissions.controversial(
                self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == STREAM:
            return reddit.redditor(self.get_name()).stream.submissions()
        else:  # default to new
            return reddit.redditor(self.get_name()).submissions.new(
                limit=self.search_criteria.post_limit
            )


class Subreddit(yaml.YAMLObject, EntityInterface, metaclass=EntityMeta):
    yaml_tag = "!subreddit"

    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.name: str = conf.get("name", None)
        self.alias: str = conf.get("alias", self.name)
        # subreddits default to nested when not specified
        self.store_type: str = conf.get("store_type", STORE_TYPE_NESTED)
        if self.store_type not in STORE_TYPES:
            # default to nested if unsupported
            self.store_type = STORE_TYPE_NESTED
        sc = conf.get("search_criteria", {})
        self.search_criteria: SearchCriteria = SearchCriteria(default_post_limit, **sc)
        self.valid: bool = False

    def is_redditor(self) -> bool:
        return False

    def is_subreddit(self) -> bool:
        return True

    def get_name(self) -> str:
        return self.name

    def get_alias(self) -> str:
        return self.alias

    def get_store_type(self) -> str:
        return self.store_type

    def get_search_criteria(self) -> SearchCriteria:
        return self.search_criteria

    def validate(self, reddit: praw.Reddit):
        """Validate the configured Subreddit via a query to reddit."""
        print(f"attempting to get subreddit {self.get_name()}")
        s = reddit.subreddit(self.get_name())
        subr_data = Template(SUBREDDIT_PRINT_TEMPLATE).substitute(
            display_name=s.display_name.strip(),
            id=s.id.strip(),
            name=s.name.strip(),
            over18=s.over18,
            description=(s.description[:300] + "...")
            if len(s.description) > 300
            else s.description,
        )
        print(subr_data)
        self.valid = True

    def is_valid(self) -> bool:
        """Is this subreddit valid?"""
        return self.valid

    def get_submissions(
        self, reddit: praw.Reddit
    ) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions for the Subreddit based on it's configuration."""
        print(
            f"searching submissions from '{reddit.subreddit(self.get_name()).display_name.strip()}' by {self.search_criteria.sort_type}/{self.search_criteria.sort_toggle}"
        )
        if self.search_criteria.sort_type == NEW:
            return reddit.subreddit(self.get_name()).new(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == HOT:
            return reddit.subreddit(self.get_name()).hot(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == TOP:
            return reddit.subreddit(self.get_name()).top(
                self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == CONTROVERSIAL:
            return reddit.subreddit(self.get_name()).controversial(
                self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == STREAM:
            return reddit.subreddit(self.get_name()).stream.submissions()
        elif self.search_criteria.sort_type == RISING:
            return reddit.subreddit(self.get_name()).rising(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == RANDOM_RISING:
            return reddit.subreddit(self.get_name()).random_rising(
                limit=self.search_criteria.post_limit
            )
        elif self.search_criteria.sort_type == RANDOM:
            return reddit.subreddit(self.get_name()).random()
        else:  # default to new
            return reddit.subreddit(self.get_name()).new(
                limit=self.search_criteria.post_limit
            )
        # TODO: possibly handle 'front'?


class IgnoredUser(yaml.YAMLObject):
    yaml_tag = "!ignored_redditor"

    def __init__(self, **conf):
        self.name: str = conf.get("name", None)


class IgnoredSubreddit(yaml.YAMLObject):
    yaml_tag = "!ignored_subreddit"

    def __init__(self, **conf):
        self.name: str = conf.get("name", None)


class ReddHarvestConfig:
    def __init__(
        self,
        globals,
        redditors,
        subreddits,
        ignored_redditors,
        ignored_subreddits,
        links,
    ):
        self.globals: Globals = globals
        self.redditors: typing.List[Redditor] = redditors
        self.subreddits: typing.List[Subreddit] = subreddits
        self.ignored_redditors: typing.List[IgnoredUser] = ignored_redditors
        self.ignored_subreddits: typing.List[IgnoredSubreddit] = ignored_subreddits
        self.links: typing.List[Link] = links

    def get_entities(self) -> typing.List[EntityInterface]:
        """Get entities to retrieve posts from based on the configuration;
        only entities that are not defined as ignored are returned.
        """
        entity_list: typing.List[EntityInterface] = []

        # print("---")
        # print("determining ignorable entities")
        # print("---")
        for user in self.redditors:
            # print(f"- parsing redditor '{user.name}'")
            ignore = False
            for igr in self.ignored_redditors:
                if igr.name.strip() == user.name.strip():
                    ignore = True
                    break
            if ignore:
                # print("-- ignoring...")
                continue
            entity_list.append(user)

        for sub in self.subreddits:
            # print(f"- parsing subreddit '{sub.name}'")
            ignore = False
            for igs in self.ignored_subreddits:
                if igs.name.strip() == sub.name.strip():
                    ignore = True
                    break
            if ignore:
                # print("-- ignoring...")
                continue
            entity_list.append(sub)
        # print("---")
        # print()

        return entity_list

    def prune_ignorables(self):
        """If we can determine that an ignored redditor posted in a subreddit
        that is being followed, attempt to remove just that redditor's posts
        from where nested posts would be saved. If we can determine that a
        redditor that is being followed has posted in an ignored subreddit,
        attempt to remove just posts from that subreddit from where nested
        posts would be saved.
        """
        prune = []
        for igr in self.ignored_redditors:
            prune.append(os.sep.join([self.globals.download_folder, igr.name.strip()]))
            prune.append(
                os.sep.join([self.globals.download_folder, "images", igr.name.strip()])
            )
            prune.append(
                os.sep.join([self.globals.download_folder, "videos", igr.name.strip()])
            )
            prune.append(
                os.sep.join([self.globals.download_folder, "unknown", igr.name.strip()])
            )
            for sub in self.subreddits:
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            sub.name,
                            igr.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "images",
                            sub.name,
                            igr.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "videos",
                            sub.name,
                            igr.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "unknown",
                            sub.name,
                            igr.name.strip(),
                        ]
                    )
                )
        for igs in self.ignored_subreddits:
            prune.append(
                os.sep.join(
                    [
                        self.globals.download_folder,
                        igs.name.strip(),
                    ]
                )
            )
            prune.append(
                os.sep.join(
                    [
                        self.globals.download_folder,
                        "images",
                        igs.name.strip(),
                    ]
                )
            )
            prune.append(
                os.sep.join(
                    [
                        self.globals.download_folder,
                        "videos",
                        igs.name.strip(),
                    ]
                )
            )
            prune.append(
                os.sep.join(
                    [
                        self.globals.download_folder,
                        "unknown",
                        igs.name.strip(),
                    ]
                )
            )
            for user in self.redditors:
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            user.name,
                            igs.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "images",
                            user.name,
                            igs.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "videos",
                            user.name,
                            igs.name.strip(),
                        ]
                    )
                )
                prune.append(
                    os.sep.join(
                        [
                            self.globals.download_folder,
                            "unknown",
                            user.name,
                            igs.name.strip(),
                        ]
                    )
                )
        must_delete = []
        for p in prune:
            if os.path.exists(p):
                must_delete.append(p)
        if len(must_delete) > 0:
            print("---")
            print("pruning detectable content for ignored entities")
            print("---")
            for p in must_delete:
                print(f"--- removing folder: {p}")
                shutil.rmtree(p)
            print("---")
            print()

    def should_ignore_post(self, post: Post) -> bool:
        for igr in self.ignored_redditors:
            if igr.name == post.author:
                return True
        for igs in self.ignored_subreddits:
            if igs.name == post.subreddit_name:
                return True
        return False

    def separate_media(self) -> bool:
        return self.globals.separate_media

    def get_download_root(self) -> str:
        """Get the root download folder."""
        return self.globals.download_folder

    def get_download_sub_folder(self, entity: EntityInterface, post: Post) -> str:
        """For a given entity and post, return the folder that should be used
        to save content from the post.
        """
        dl_sub_folder = entity.get_download_folder(post.author, post.subreddit_name)
        # handle specials case favoring if enabled and entity type is opposite
        # of what should be favored
        if self.globals.favor_entity == FAVOR_REDDITOR and entity.is_subreddit():
            for rdtr in self.redditors:
                if post.author == rdtr.name:
                    dl_sub_folder = rdtr.get_download_folder(
                        post.author, post.subreddit_name
                    )
                    break
        elif self.globals.favor_entity == FAVOR_SUBREDDIT and entity.is_redditor():
            for sub in self.subreddits:
                if post.subreddit_name == sub.name:
                    dl_sub_folder = sub.get_download_folder(
                        post.author, post.subreddit_name
                    )
                    break
        else:  # else disabled or we can just use as-is
            pass
        return os.path.normpath(dl_sub_folder)


def _make_file_private(file: str):
    st = os.stat(file)
    if bool(
        st.st_mode
        & sum(
            [
                stat.S_IRGRP,
                stat.S_IWGRP,
                stat.S_IXGRP,
                stat.S_IROTH,
                stat.S_IWOTH,
                stat.S_IXOTH,
            ]
        )
    ):
        print(f"making config file {file} private as it contains sensitive information")
        os.chmod(file, 0o600)


def gather_config(config_file: str) -> ReddHarvestConfig:
    """Gather configuration from the specified file."""
    config_data = {}
    file = os.path.abspath(os.path.expanduser(config_file))
    _make_file_private(file)
    with open(file, "r") as c:
        yaml.add_path_resolver("!global", ["globals"], dict)
        yaml.add_path_resolver("!redditor", ["redditors"], list)
        yaml.add_path_resolver("!subreddit", ["subreddits"], list)
        yaml.add_path_resolver("!ignored_redditor", ["ignored_redditors"], list)
        yaml.add_path_resolver("!ignored_subreddit", ["ignored_subreddits"], list)
        yaml.add_path_resolver("!link", ["links"], list)
        config_data = yaml.safe_load(c)

    # print("---")
    # print("resolved configuration")
    # print("---")
    global_config = Globals(**config_data["globals"])
    # print(yaml.dump(global_config))
    redditors: typing.List[Redditor] = []
    for r in config_data.get("redditors", []):
        redditor = Redditor(global_config.post_limit, **r)
        redditors.append(redditor)
    # print(yaml.dump(redditors))
    subreddits: typing.List[Subreddit] = []
    for s in config_data.get("subreddits", []):
        subreddit = Subreddit(global_config.post_limit, **s)
        subreddits.append(subreddit)
    # print(yaml.dump(subreddits))
    ignored_redditors: typing.List[IgnoredUser] = []
    if config_data["ignored_redditors"] is not None:
        for igr in config_data.get("ignored_redditors", []):
            ignored_redditor = IgnoredUser(**igr)
            ignored_redditors.append(ignored_redditor)
    # print(yaml.dump(ignored_redditors))
    ignored_subreddits: typing.List[IgnoredSubreddit] = []
    if config_data["ignored_subreddits"] is not None:
        for igs in config_data.get("ignored_subreddits", []):
            ignored_subreddit = IgnoredSubreddit(**igs)
            ignored_subreddits.append(ignored_subreddit)
    # print(yaml.dump(ignored_subreddits))
    links: typing.List[Link] = []
    for ln in config_data["links"]:
        link = Link(**ln)
        links.append(link)
    # print(yaml.dump(links))
    # print("---")
    # print()

    return ReddHarvestConfig(
        global_config,
        redditors,
        subreddits,
        ignored_redditors,
        ignored_subreddits,
        links,
    )
