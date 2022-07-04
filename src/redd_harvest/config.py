import abc
import os
import shutil
from string import Template
import typing

import praw
import yaml

from redd_harvest.post import Post

# global config defaults
DEFAULT_REDD_HARVEST_APP = 'redd-harvest'
DEFAULT_REDD_HARVEST_USERNAME = 'unknown'
DEFAULT_POST_LIMIT = 5
DEFAULT_RATE_LIMIT_MAX_WAIT = 120
DEFAULT_BACKOFF_SLEEP = 0.1
DEFAULT_DOWNLOAD_FOLDER = os.sep.join(['~','.redd-harvest','data'])

FAVOR_REDDITOR = "redditor"
FAVOR_SUBREDDIT = "subreddit"
FAVOR_DISABLED = "disabled"
ALL_FAVOR_SETTINGS = [FAVOR_REDDITOR, FAVOR_SUBREDDIT, FAVOR_DISABLED]

# search sort enums
HOT = 'hot'
NEW = 'new'
TOP = 'top'
CONTROVERSIAL = 'controversial'
STREAM = 'stream'
RANDOM = 'random' # single random submission
RANDOM_RISING = 'random_rising' # random rising submission(s?)
RISING = 'rising'
# all submission sort types
ALL_SORT_TYPES = [HOT, NEW, TOP, CONTROVERSIAL, STREAM, RANDOM, RANDOM_RISING, RISING]
# applicable subset for redditors
REDDITOR_SORT_TYPES = [HOT, NEW, TOP, CONTROVERSIAL, STREAM]
HOUR = 'hour'
DAY = 'day'
WEEK = 'week'
MONTH = 'month'
YEAR = 'year'
ALL = 'all'
# only applies to 'TOP' and 'CONTROVERSIAL' sort_types
SORT_TOGGLES = [HOUR, DAY, WEEK, MONTH, YEAR, ALL]

# store media either nested (for subredddits: <subreddit>/<redditor>, for
# redditors: <redditor>/<subreddit>), or flat (for subreddits: <subreddit>,
# for redditors: <redditor>)
STORE_TYPE_NESTED = 'nested'
STORE_TYPE_FLAT = 'flat'
STORE_TYPE_REALLY_FLAT = 'really-flat'
STORE_TYPES = [STORE_TYPE_NESTED, STORE_TYPE_FLAT, STORE_TYPE_REALLY_FLAT]

# template for redditor metadata
REDDITOR_PRINT_TEMPLATE = (
    '--------------------\n'
    'user: $name\n'
    '  id: $id\n'
    '  is_mod: $is_mod\n'
    '  is_gold: $is_gold\n'
    '  has_verified_email: $has_verified_email\n'
)

# template for redditor metadata
SUBREDDIT_PRINT_TEMPLATE = (
    '--------------------\n'
    'display_name: $display_name\n'
    '  id: $id\n'
    '  name: $name\n'
    '  over18: $over18\n'
    '  description: $description\n'
)

class Globals(yaml.YAMLObject):
    yaml_tag = u'!global'
    def __init__(self, **conf):
        self.app:str = conf.get('app', DEFAULT_REDD_HARVEST_APP)
        self.username:str = conf.get('username', DEFAULT_REDD_HARVEST_USERNAME)
        self.post_limit:int = conf.get('post_limit', DEFAULT_POST_LIMIT)
        self.rate_limit_max_wait:int = conf.get('rate_limit_max_wait', DEFAULT_RATE_LIMIT_MAX_WAIT)
        self.backoff_sleep:float = conf.get('backoff_sleep', DEFAULT_BACKOFF_SLEEP)
        self.download_folder:str = os.path.abspath(os.path.expanduser(conf.get('download_folder', DEFAULT_DOWNLOAD_FOLDER)))
        self.bonk:bool = conf.get('bonk', False)
        if not isinstance(self.bonk, bool):
            self.bonk = False
        self.prune_ignorables:bool = conf.get('prune_ignorables', False)
        if not isinstance(self.prune_ignorables, bool):
            self.prune_ignorables = False
        self.favor_entity:str = conf.get('favor_entity', FAVOR_REDDITOR).lower()
        if self.favor_entity not in ALL_FAVOR_SETTINGS:
            self.favor_entity = FAVOR_REDDITOR # default to redditor

class SubSearch(yaml.YAMLObject):
    yaml_tag = u'!sub_search'
    def __init__(self, **conf):
        self.page_search_regex:str = conf.get('page_search_regex', None)
        self.extension:str = conf.get('extension', None)

class Link(yaml.YAMLObject):
    yaml_tag = u'!link'
    def __init__(self, **conf):
        self.base_url:str = conf.get('base_url', None)
        self.direct_dl_url_extensions:typing.List[str] = conf.get('direct_dl_url_extensions', [])
        searches:typing.List[SubSearch] = conf.get('sub_searches', [])
        self.sub_searches:typing.List[SubSearch] = [] # redundant since we've initialized this above?
        for search in searches:
            s = SubSearch(**search)
            if s.page_search_regex is not None:
                self.sub_searches.append(s) # only load qualifying sub_searches
            
class SearchCriteria(yaml.YAMLObject):
    yaml_tag = u'!search_criteria'
    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.post_limit:int = conf.get('post_limit', default_post_limit)
        self.sort_type:str = conf.get('sort_type', NEW).lower()
        if self.sort_type not in ALL_SORT_TYPES:
            self.sort_type = NEW # default to new if unsupported
        if self.sort_type in [TOP, CONTROVERSIAL]:
            self.sort_toggle:str = conf.get('sort_toggle', WEEK).lower()
            if self.sort_toggle not in SORT_TOGGLES:
                self.sort_toggle = WEEK # default to week if unsupported
        else:
            self.sort_toggle = conf.get('sort_toggle', None)

class EntityInterface(metaclass=abc.ABCMeta):
    """Interface for interacting with redditors and subreddits"""
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'is_redditor') and 
                callable(subclass.is_redditor) and 
                hasattr(subclass, 'is_subreddit') and 
                callable(subclass.is_subreddit) or 
                hasattr(subclass, 'get_name') and 
                callable(subclass.get_name) or 
                hasattr(subclass, 'get_store_type') and 
                callable(subclass.get_store_type) or 
                hasattr(subclass, 'get_search_criteria') and 
                callable(subclass.get_search_criteria) or 
                hasattr(subclass, 'enrich') and 
                callable(subclass.enrich) or 
                hasattr(subclass, 'is_enriched') and 
                callable(subclass.is_enriched) or 
                hasattr(subclass, 'get_submissions') and 
                callable(subclass.get_submissions) or 
                hasattr(subclass, 'get_download_folder') and 
                callable(subclass.get_download_folder) or 
                NotImplemented)

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
    def get_store_type(self) -> str:
        """Storage type for the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_search_criteria(self) -> SearchCriteria:
        """Search criteria for the entity"""
        raise NotImplementedError

    @abc.abstractmethod
    def enrich(self, reddit: praw.Reddit):
        """Enrich with real data from Reddit"""
        raise NotImplementedError

    @abc.abstractmethod
    def is_enriched(self) -> bool:
        """Whether or not the entity has been successfully enriched with real data from Reddit"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_submissions(self) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions (posts) from the entity from Reddit"""
        raise NotImplementedError

    def get_download_folder(self, post_author: str, post_subreddit_name: str) -> str:
        """Determine the intended download folder based on the provided post
        author and name of the subreddit where it was posted.
        """
        dl_folder = post_author

        if self.get_store_type() == STORE_TYPE_REALLY_FLAT:
            dl_folder = '.'
        elif self.is_redditor():
            dl_folder = os.sep.join([post_author, post_subreddit_name])
            if self.get_store_type() == STORE_TYPE_FLAT:
                dl_folder = post_author
        elif self.is_subreddit():
            dl_folder = os.sep.join([post_subreddit_name, post_author])
            if self.get_store_type() == STORE_TYPE_FLAT:
                dl_folder = post_subreddit_name
        
        return f'{dl_folder}'

class EntityMeta(type(yaml.YAMLObject), type(EntityInterface)):
    pass

class Redditor(yaml.YAMLObject, EntityInterface, metaclass=EntityMeta):
    yaml_tag = u'!redditor'
    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.name:str = conf.get('name', None)
        # redditors default to flat when not specified
        self.store_type:str = conf.get('store_type', STORE_TYPE_FLAT)
        if self.store_type not in STORE_TYPES:
            # default to flat if unsupported
            self.store_type = STORE_TYPE_FLAT
        sc = conf.get('search_criteria', {})
        self.search_criteria:SearchCriteria = SearchCriteria(default_post_limit, **sc)
        if self.search_criteria.sort_type not in REDDITOR_SORT_TYPES:
            # not all sort types supported for redditors; default to new if
            # unsupported
            self.search_criteria.sort_type = NEW
        self.internal_redditor:praw.reddit.Redditor = None

    def is_redditor(self) -> bool:
        return True

    def is_subreddit(self) -> bool:
        return False

    def get_name(self) -> str:
        return self.name

    def get_store_type(self) -> str:
        return self.store_type

    def get_search_criteria(self) -> SearchCriteria:
        return self.search_criteria

    def enrich(self, reddit: praw.Reddit):
        """Enrich the configured Redditor via a query to reddit."""
        print(f'attempting to get user {self.get_name()}')
        self.internal_redditor = reddit.redditor(self.get_name())
        rdtr_data = Template(REDDITOR_PRINT_TEMPLATE).substitute(
            name = self.internal_redditor.name.strip(),
            id = self.internal_redditor.id.strip(),
            is_mod = self.internal_redditor.is_mod,
            is_gold = self.internal_redditor.is_gold,
            has_verified_email = self.internal_redditor.has_verified_email,
        )
        print(rdtr_data)

    def is_enriched(self) -> bool:
        """Was this successfully enriched."""
        return False if self.internal_redditor is None else True

    def get_submissions(self) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions for the Redditor based on it's configuration."""
        print(f'searching submissions from \'{self.get_name().strip()}\' by {self.search_criteria.sort_type}/{self.search_criteria.sort_toggle}')
        if self.search_criteria.sort_type == NEW:
            return self.internal_redditor.submissions.new(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == HOT:
            return self.internal_redditor.submissions.hot(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == TOP:
            return self.internal_redditor.submissions.top(self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == CONTROVERSIAL:
            return self.internal_redditor.submissions.controversial(self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == STREAM:
            return self.internal_redditor.stream.submissions()
        else: # default to new
            return self.internal_redditor.submissions.new(limit=self.search_criteria.post_limit)


class Subreddit(yaml.YAMLObject, EntityInterface, metaclass=EntityMeta):
    yaml_tag = u'!subreddit'
    def __init__(self, default_post_limit=DEFAULT_POST_LIMIT, **conf):
        self.name:str = conf.get('name', None)
        # subreddits default to nested when not specified
        self.store_type:str = conf.get('store_type', STORE_TYPE_NESTED)
        if self.store_type not in STORE_TYPES:
            # default to nested if unsupported
            self.store_type = STORE_TYPE_NESTED
        sc = conf.get('search_criteria', {})
        self.search_criteria:SearchCriteria = SearchCriteria(default_post_limit, **sc)
        self.internal_subreddit:praw.reddit.Subreddit = None

    def is_redditor(self) -> bool:
        return False

    def is_subreddit(self) -> bool:
        return True

    def get_name(self) -> str:
        return self.name

    def get_store_type(self) -> str:
        return self.store_type

    def get_search_criteria(self) -> SearchCriteria:
        return self.search_criteria

    def enrich(self, reddit: praw.Reddit):
        """Enrich the configured Subreddit via a query to reddit."""
        print(f'attempting to get subreddit {self.get_name()}')
        self.internal_subreddit = reddit.subreddit(self.get_name())
        subr_data = Template(SUBREDDIT_PRINT_TEMPLATE).substitute(
            display_name = self.internal_subreddit.display_name.strip(),
            id = self.internal_subreddit.id.strip(),
            name = self.internal_subreddit.name.strip(),
            over18 = self.internal_subreddit.over18,
            description = (self.internal_subreddit.description[:300] + '...') if len(self.internal_subreddit.description) > 300 else self.internal_subreddit.description,
        )
        print(subr_data)

    def is_enriched(self) -> bool:
        """Was this successfully enriched."""
        return False if self.internal_subreddit is None else True

    def get_submissions(self) -> typing.List[praw.reddit.models.Submission]:
        """Get submissions for the Subreddit based on it's configuration."""
        print(f'searching submissions from \'{self.internal_subreddit.display_name.strip()}\' by {self.search_criteria.sort_type}/{self.search_criteria.sort_toggle}')
        if self.search_criteria.sort_type == NEW:
            return self.internal_subreddit.new(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == HOT:
            return self.internal_subreddit.hot(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == TOP:
            return self.internal_subreddit.top(self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == CONTROVERSIAL:
            return self.internal_subreddit.controversial(self.search_criteria.sort_toggle, limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == STREAM:
            return self.internal_subreddit.stream.submissions()
        elif self.search_criteria.sort_type == RISING:
            return self.internal_subreddit.rising(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == RANDOM_RISING:
            return self.internal_subreddit.random_rising(limit=self.search_criteria.post_limit)
        elif self.search_criteria.sort_type == RANDOM:
            return self.internal_subreddit.random()
        else: # default to new
            return self.internal_subreddit.new(limit=self.search_criteria.post_limit)
        # TODO: possibly handle 'front'?

class IgnoredUser(yaml.YAMLObject):
    yaml_tag = u'!ignored_redditor'
    def __init__(self, **conf):
        self.name:str = conf.get('name', None)

class IgnoredSubreddit(yaml.YAMLObject):
    yaml_tag = u'!ignored_subreddit'
    def __init__(self, **conf):
        self.name:str = conf.get('name', None)

class ReddHarvestConfig():
    def __init__(self, globals, redditors, subreddits, ignored_redditors, ignored_subreddits, links):
        self.globals:Globals = globals
        self.redditors:typing.List[Redditor] = redditors
        self.subreddits:typing.List[Subreddit] = subreddits
        self.ignored_redditors:typing.List[IgnoredUser] = ignored_redditors
        self.ignored_subreddits:typing.List[IgnoredSubreddit] = ignored_subreddits
        self.links:typing.List[Link] = links

    def get_entities(self) -> typing.List[EntityInterface]:
        """Get entities to retrieve posts from based on the configuration;
        only entities that are not defined as ignored are returned.
        """
        entity_list: typing.List[EntityInterface] = []

        print("---")
        print("determining ignorable entities")
        print("---")
        for user in self.redditors:
            print(f'- parsing redditor \'{user.name}\'')
            ignore = False
            for igr in self.ignored_redditors:
                if igr.name.strip() == user.name.strip():
                    ignore = True
                    break
            if ignore:
                print('-- ignoring...')
                continue
            entity_list.append(user)

        for sub in self.subreddits:
            print(f'- parsing subreddit \'{sub.name}\'')
            ignore = False
            for igs in self.ignored_subreddits:
                if igs.name.strip() == sub.name.strip():
                    ignore = True
                    break
            if ignore:
                print('-- ignoring...')
                continue
            entity_list.append(sub)
        print("---")
        print()

        return entity_list

    def prune_ignorables(self):
        """If we can determine that an ignored redditor posted in a subreddit
        that is being followed, attempt to remove just that redditor's posts
        from where nested posts would be saved. If we can determine that a
        redditor that is being followed has posted in an ignored subreddit,
        attempt to remove just posts from that subreddit from where nested
        posts would be saved.
        """
        print("---")
        print("pruning detectable content for ignored entities")
        print("---")
        for sub in self.subreddits:
            for igr in self.ignored_redditors:
                ignore_folder = f'{self.globals.download_folder}/{sub.name}/{igr.name.strip()}'
                print(f'- checking for folder: {ignore_folder}')
                if os.path.exists(ignore_folder):
                    print(f'--- removing folder: {ignore_folder}')
                    shutil.rmtree(ignore_folder)
        for user in self.redditors:
            for igs in self.ignored_subreddits:
                ignore_folder = f'{self.globals.download_folder}/{user.name}/{igs.name.strip()}'
                print(f'- checking for folder: {ignore_folder}')
                if os.path.exists(ignore_folder):
                    print(f'--- removing folder: {ignore_folder}')
                    shutil.rmtree(ignore_folder)
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

    def get_download_folder(self, entity:EntityInterface, post: Post) -> str:
        """For a given entity and post, return the folder that should be used
        to save content from the post.
        """
        dl_sub_folder = entity.get_download_folder(post.author, post.subreddit_name)
        # handle specials case favoring if enabled and entity type is opposite
        # of what should be favored
        if self.globals.favor_entity == FAVOR_REDDITOR and entity.is_subreddit():
            for rdtr in self.redditors:
                if post.author == rdtr.name:
                    dl_sub_folder = rdtr.get_download_folder(post.author, post.subreddit_name)
                    break
        elif self.globals.favor_entity == FAVOR_SUBREDDIT and entity.is_redditor():
            for sub in self.subreddits:
                if post.subreddit_name == sub.name:
                    dl_sub_folder = sub.get_download_folder(post.author, post.subreddit_name)
                    break
        else: # else disabled or we can just use as-is
            pass
        return os.path.normpath(os.sep.join([self.globals.download_folder, dl_sub_folder]))


def gather_config(config_file: str) -> ReddHarvestConfig:
    """Gather configuration from the specified file."""
    config_data = {}
    file = os.path.abspath(os.path.expanduser(config_file))
    with open(file, 'r') as c:
        yaml.add_path_resolver('!global', ['globals'], dict)
        yaml.add_path_resolver('!redditor', ['redditors'], list)
        yaml.add_path_resolver('!subreddit', ['subreddits'], list)
        yaml.add_path_resolver('!ignored_redditor', ['ignored_redditors'], list)
        yaml.add_path_resolver('!ignored_subreddit', ['ignored_subreddits'], list)
        yaml.add_path_resolver('!link', ['links'], list)
        config_data = yaml.safe_load(c)

    print("---")
    print("resolved configuration")
    print("---")
    global_config = Globals(**config_data['globals'])
    print(yaml.dump(global_config))
    redditors:typing.List[Redditor] = []
    for r in config_data['redditors']:
        redditor = Redditor(global_config.post_limit, **r)
        redditors.append(redditor)
    print(yaml.dump(redditors))
    subreddits:typing.List[Subreddit] = []
    for s in config_data['subreddits']:
        subreddit = Subreddit(global_config.post_limit, **s)
        subreddits.append(subreddit)
    print(yaml.dump(subreddits))
    ignored_redditors:typing.List[IgnoredUser] = []
    if config_data['ignored_redditors'] is not None:
        for igr in config_data['ignored_redditors']:
            ignored_redditor = IgnoredUser(**igr)
            ignored_redditors.append(ignored_redditor)
    print(yaml.dump(ignored_redditors))
    ignored_subreddits:typing.List[IgnoredSubreddit] = []
    if config_data['ignored_subreddits'] is not None:
        for igs in config_data['ignored_subreddits']:
            ignored_subreddit = IgnoredSubreddit(**igs)
            ignored_subreddits.append(ignored_subreddit)
    print(yaml.dump(ignored_subreddits))
    links:typing.List[Link] = []
    for l in config_data['links']:
        link = Link(**l)
        links.append(link)
    print(yaml.dump(links))
    print("---")
    print()

    return ReddHarvestConfig(global_config, redditors, subreddits, ignored_redditors, ignored_subreddits, links)