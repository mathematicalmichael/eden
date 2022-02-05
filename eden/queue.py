import os
import time
import json
from .log_utils import Colors
import warnings

"""
redis stuff so that different eden replicas can stay in sync
"""
from redis import Redis


class QueueData(object):
    """
    Simple way to keep a track of the tasks done on multiple threads.


    """

    def __init__(self, redis_port: int, redis_host: str, queue_name: str, redis_db=0):

        """
        to wipe all redis stuff, use:
        $ redis-cli flushall
        """

        self.redis = Redis(host=redis_host, port=str(redis_port), db=redis_db)

        self.queue = []  ## used to find position on the queue

        self.name_mapping = {
            "PENDING": "queued",
            "STARTED": "running",
            "SUCCESS": "complete",
            "FAILURE": "failed",
            "REVOKED": "revoked",
        }

        self.queue_name = queue_name

    def get_queue(self):
        tokens_in_queue = []

        queue_stuff = self.redis.lrange(self.queue_name, 0, -1)

        if queue_stuff is not None:

            for stuff in queue_stuff:
                stuff = self.decode_response_bytes(stuff)
                token_standing_in_queue = stuff["headers"]["id"]
                tokens_in_queue.append(token_standing_in_queue)

        return tokens_in_queue

    def get_queue_length(self):
        length = self.redis.llen(self.queue_name)
        return length

    def check_if_token_in_queue(self, token):
        tokens_in_queue = self.get_queue()

        if token in tokens_in_queue:
            return True
        else:
            return False

    def get_from_redis(self, token):
        full_token = "celery-task-meta-" + token
        response_bytes = self.redis.get(full_token)  ##.execute()[0]
        return response_bytes

    def decode_response_bytes(self, response_bytes):
        dict_str = response_bytes.decode("UTF-8")
        dict_from_str = json.loads(dict_str)
        return dict_from_str

    def get_results(self, token):

        response_bytes = self.get_from_redis(token=token)
        result = self.decode_response_bytes(response_bytes=response_bytes)["result"]
        return result

    def check_if_token_in_unacked(self, token):
        tokens_in_unacked = []

        unacked_stuff = self.redis.hgetall("unacked")

        if unacked_stuff is not None:

            keys = unacked_stuff.keys()
            for k in keys:

                token_standing_in_queue = json.loads(unacked_stuff[k].decode("utf-8"))[
                    0
                ]["headers"]["root_id"]

                tokens_in_unacked.append(token_standing_in_queue)

        if token in tokens_in_unacked:
            return True
        else:
            return False

    def get_status(self, token):

        """
        note: a VERY common source of latency generated by the execution
        of slow commands is the use of the KEYS command in production environments.
        KEYS (or self.redis.keys()), as documented in the Redis documentation, should only be used for
        debugging purposes.

        source: https://redis.io/topics/latency
        """

        in_queue = self.check_if_token_in_queue(token=token)

        if in_queue == True:
            """
            The job is in queue
            """
            status_to_return = {
                "status": "queued",
            }

            queue_pos = self.get_queue_position(token=token)
            status_to_return["queue_position"] = queue_pos

        else:
            """
            The job is either complete or running or revoked,
            these can be found on the redis keys
            """

            response_bytes = self.get_from_redis(token=token)

            if response_bytes is not None:

                status = self.decode_response_bytes(response_bytes=response_bytes)[
                    "status"
                ]
                status = self.name_mapping[status]

                status_to_return = {
                    "status": status,
                }

            elif self.check_if_token_in_unacked(token=token):
                """
                check if job is in key 'unacked'
                'unacked' generally stores the jobs which are just about to start
                """

                status_to_return = {
                    "status": "starting",
                }

            else:
                status_to_return = {
                    "status": "invalid token",
                }

        return status_to_return

    def __getitem__(self, token):
        return self.get_status(token=token)

    def get_queue_position(self, token):
        try:
            all_tokens = self.get_queue()
            pos = len(all_tokens) - all_tokens.index(
                token
            )  ## reversing the index, and queue starts at 1, not 0
        except:
            pos = None
            raise Exception(f"token: {token} not found in {self.get_queue()}")
        return pos
