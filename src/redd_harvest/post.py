from datetime import datetime
import typing

import praw

class Post():
    def __init__(self, submission: praw.reddit.models.Submission):
        self.submission:praw.reddit.models.Submission = submission
        self.id:str = submission.id
        self.title:str = submission.title
        self.author:str = 'unknown'
        try:
            if submission.author is not None and submission.author.name is not None:
                self.author:str = submission.author.name.strip()
        except:
            print('...massive trouble getting post author info... continuing anyways')
        self.subreddit_name:str = submission.subreddit.display_name.strip()
        self.url:str = submission.url.strip()
        self.selftext:str = submission.selftext
        self.created:datetime = datetime.fromtimestamp(submission.created_utc)
        self.over_18:bool = submission.over_18
        self.post_raw:typing.Dict[str, typing.Any] = vars(submission)