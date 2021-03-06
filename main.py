import boto3
import logging
import os
import pprint
from everett.manager import ConfigManager
from everett.manager import ConfigOSEnv

from driver import TeamDrive

logger = logging.getLogger(__name__)

logging.basicConfig(
   level=logging.INFO,
   format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)

"""
Group driver configuration
* Environment variables used
CIS_DYNAMODB_PERSON_TABLE
"""

# Users must be a member of these groups to participate in the gsuite pilot.
WHITELIST = ['mozilliansorg_cis_whitelist']


def get_config():
    return ConfigManager(
        [
            ConfigOSEnv()
        ]
)


class CISTable(object):
    def __init__(self, table_name):
        self.boto_session = boto3.session.Session()
        self.table_name = table_name
        self.table = None

    def connect(self):
        resource = self.boto_session.resource('dynamodb')
        self.table = resource.Table(self.table_name)
        return self.table

    @property
    def all(self):
        if self.table is None:
            self.connect()
        return self.table.scan().get('Items')


class People(object):
    def __init__(self):
        self.config = get_config()
        self.table_name = self.config('dynamodb_person_table', namespace='cis')
        self.table = self.table = CISTable(self.table_name)

    def grouplist(self):
        """Returns a list of dicts of for each group id, email"""
        self.master_grouplist = self._extract_groups()
        for record in self.table.all:
            self._add_record_to_groups(record)
        return self.master_grouplist

    def _add_record_to_groups(self, user_record):
        for group in user_record['groups']:
            group_idx = self._locate_group_index(group)
            self.master_grouplist[group_idx]['members'].append(user_record)

    def _locate_group_index(self, group_name):
        for group in self.master_grouplist:
            if group_name == group['group']:
                return self.master_grouplist.index(group)

    def _extract_groups(self):
        groups = []
        for record in self.table.all:
            for group in record.get('groups'):
                proposed_group = {
                    'group': group,
                    'members': []
                }
                if proposed_group not in groups:
                    groups.append(proposed_group)
                    logger.info('Group {g} added to group masterlist.'.format(g=group))

                else:
                    logger.info('Group {g} already in grouplist passing on adding DUP!'.format(g=group))

        return groups

    def build_email_list(self, group_dict):
        memberships = []
        for member in group_dict['members']:
            for email in member['emails']:
                if email['value'].split('@')[1] == 'mozilla.com':
                    memberships.append(email['value'])
                elif email['name'] == 'Google Provider':
                    memberships.append(email['value'])
                else:
                    pass
        return memberships


def handle(event=None, context={}):
    logger.info('Initializing connector.')
    people = People()

    for group in people.grouplist():
        if group.get('group') in WHITELIST:
            community_drive_driver = TeamDrive("{}_{}".format(os.getenv('environment'), group.get('group')))
            logger.info('Group :{} in gsuite pilot initiating sync.'.format(group.get('group')))
            community_drive_driver.find_or_create()
            work_plan = community_drive_driver.reconcile_members(people.build_email_list(group))
            community_drive_driver.execute_proposal(work_plan)
        else:
            logger.info('Group :{} not whitelisted for team drive testing.'.format(group.get('group')))
