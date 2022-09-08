# Software License Agreement (BSD License)
#
# Copyright (c) 2019, PickNik Consulting.
# Copyright (c) 2020, Open Source Robotics Foundation, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""A rosbag abstraction with functionality required by rqt_bag."""

from collections import namedtuple
import os
import pathlib
import sqlite3

from rclpy.clock import Clock, ClockType
from rclpy.duration import Duration
from rclpy import logging
from rclpy.serialization import deserialize_message
from rclpy.time import Time
import rosbag2_py
from rosidl_runtime_py.utilities import get_message
import yaml

WRITE_ONLY_MSG = "open for writing only, returning None"


class Rosbag2:

    def __init__(self, bag_path, recording=False, topics={},
                 serialization_format='cdr', storage_id='sqlite3'):
        self.bag_path = bag_path
        self.reader = None
        self._logger = logging.get_logger('rqt_bag.Rosbag2')

        if recording:
            # TODO(emersonknapp)
            pass
        else:
            self.reader = rosbag2_py.SequentialReader()
            self.reader.open(
                rosbag2_py.StorageOptions(uri=bag_path), rosbag2_py.ConverterOptions())
            self.metadata = self.reader.get_metadata()
            self.db_name = os.path.join(self.bag_path, self.metadata.relative_file_paths[0])
            self.topic_metadata_map = {
                t_info.topic_metadata.name: t_info.topic_metadata
                for t_info in self.metadata.topics_with_message_count
            }

    def size(self):
        """Get the size of the rosbag."""
        return self.metadata.bag_size

    def get_earliest_timestamp(self):
        """Get the timestamp of the earliest message in the bag."""
        self._logger.info("GET START")
        return self.metadata.starting_time

    def get_latest_timestamp(self):
        """Get the timestamp of the most recent message in the bag."""
        self._logger.info("GET END")
        end = self.metadata.starting_time + self.metadata.duration
        print("ITS A ", end)
        return self.metadata.starting_time + self.metadata.duration

    def get_topics(self):
        """Get all of the topics used in this bag."""
        return sorted(self.topic_metadata_map.keys())

    def get_topic_type(self, topic):
        """Get the topic type for a given topic name."""
        if topic not in self.topic_metadata_map:
            return None
        return self.topic_metadata_map[topic].type

    def get_topic_metadata(self, topic):
        """Get the full metadata for a given topic name."""
        if topic not in self.topic_metadata_map:
            return None
        return self.topic_metadata_map[topic]

    def get_topics_by_type(self):
        """Return a map of topic data types to a list of topics publishing that type."""
        topics_by_type = {}
        for name, topic in self.topic_metadata_map.items():
            topics_by_type.setdefault(topic.type, []).append(name)
        return topics_by_type

    def get_entry(self, timestamp, topic=None):
        """Get the (serialized) entry for a specific timestamp.

        Returns the entry that is closest in time (<=) to the provided timestamp.
        """
        if not self.reader:
            self._logger.warn("get_entry - " + WRITE_ONLY_MSG)
            return None
        self._logger.info("GET ENTRY")
        sql_query = 'timestamp<={} ORDER BY messages.timestamp ' \
                    'DESC LIMIT 1;'.format(timestamp.nanoseconds)
        result = self._execute_sql_query(sql_query, topic)
        return result[0] if result else None

    def get_entry_after(self, timestamp, topic=None):
        """Get the next entry after a given timestamp."""
        if not self.reader:
            self._logger.warn("get_entry_after - " + WRITE_ONLY_MSG)
            return None
        self._logger.info("GET ENTRY AFTER")
        sql_query = 'timestamp>{} ORDER BY messages.timestamp ' \
                    'LIMIT 1;'.format(timestamp.nanoseconds)
        result = self._execute_sql_query(sql_query, topic)
        return result[0] if result else None

    def get_entries_in_range(self, t_start, t_end, topic=None):
        if not self.reader:
            self._logger.warn("get_entries_in_range - " + WRITE_ONLY_MSG)
            return None
        """Get a list of all of the entries within a given range of timestamps (inclusive)."""
        self._logger.info("GET ENTRIES IN RANGE")
        sql_query = 'timestamp>={} AND timestamp<={} ' \
                    'ORDER BY messages.timestamp;'.format(t_start.nanoseconds, t_end.nanoseconds)
        return self._execute_sql_query(sql_query, topic)

    def deserialize_entry(self, entry):
        """Deserialize a bag entry into its corresponding ROS message."""
        msg_type_name = self.get_topic_type(entry.topic)
        msg_type = get_message(msg_type_name)
        ros_message = deserialize_message(entry.data, msg_type)
        return (ros_message, msg_type_name, entry.topic)

    def _execute_sql_query(self, sql_query, topic):
        Entry = namedtuple('Entry', ['topic', 'data', 'timestamp'])
        base_query = 'SELECT topics.name, data, timestamp FROM messages ' \
                     'JOIN topics ON messages.topic_id = topics.id WHERE '

        # If there was a topic requested, make sure it is in this bag
        if topic is not None:
            if topic not in self.topic_metadata_map:
                return []
            base_query += 'topics.name="{}"AND '.format(topic)

        with sqlite3.connect(self.db_name) as db:
            cursor = db.cursor()
            entries = cursor.execute(base_query + sql_query).fetchall()
            cursor.close()
            return [Entry(*entry) for entry in entries]
