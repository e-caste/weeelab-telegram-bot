import os  # system library needed to read the environment variables


def __unpack_wol(wol):
    wol = wol.split('|')
    result = {}
    for machine in wol:
        machine = machine.split(':', 1)
        result[machine[0]] = machine[1]
    return result


# get environment variables
OC_URL = os.environ.get('OC_URL')  # url of the OwnCloud server
OC_USER = os.environ.get('OC_USER')  # OwnCloud username
OC_PWD = os.environ.get('OC_PWD')  # OwnCloud password
# path of the log file to read in OwnCloud (/folder/file.txt)
LOG_PATH = os.environ.get('LOG_PATH')
TOLAB_PATH = os.environ.get('TOLAB_PATH')
# base path
LOG_BASE = os.environ.get('LOG_BASE')
# path of the file to store bot users in OwnCloud (/folder/file.txt)
USER_BOT_PATH = os.environ.get('USER_BOT_PATH')
TOKEN_BOT = os.environ.get('TOKEN_BOT')  # Telegram token for the bot API
TARALLO = os.environ.get('TARALLO')  # tarallo URL
TARALLO_TOKEN = os.environ.get('TARALLO_TOKEN')  # tarallo token

LDAP_SERVER = os.environ.get('LDAP_SERVER')  # ldap.example.com
LDAP_USER = os.environ.get('LDAP_USER')  # cn=whatever,ou=whatever
LDAP_PASS = os.environ.get('LDAP_PASS')  # foo
LDAP_SUFFIX = os.environ.get('LDAP_SUFFIX')  # dc=weeeopen,dc=it
LDAP_TREE_PEOPLE = os.environ.get('LDAP_TREE_PEOPLE')  # ou=People,dc=weeeopen,dc=it
LDAP_TREE_INVITES = os.environ.get('LDAP_TREE_INVITES')  # ou=Invites,dc=weeeopen,dc=it
LDAP_ADMIN_GROUPS = os.environ.get('LDAP_ADMIN_GROUPS')  # ou=Group,dc=weeeopen,dc=it|ou=OtherGroup,dc=weeeopen,dc=it
if LDAP_ADMIN_GROUPS is not None:
    LDAP_ADMIN_GROUPS = LDAP_ADMIN_GROUPS.split('|')

INVITE_LINK = os.environ.get('INVITE_LINK')  # https://example.com/register.php?invite= (invite code will be appended, no spaces in invite code)

SSH_USER = os.environ.get('SSH_USER')  # foo
SSH_HOST_IP = os.environ.get('SSH_HOST_IP')  # 10.20.30.40
SSH_KEY_PATH = os.environ.get('SSH_KEY_PATH')  # /home/whatever/ssh_key

WOL_MACHINES = os.environ.get('WOL_MACHINES')  # machine:00:0a:0b:0c:0d:0e|other:10:2a:3b:4c:5d:6e
if WOL_MACHINES is not None:
    WOL_MACHINES = __unpack_wol(WOL_MACHINES)
WOL_LOGOUT = os.environ.get('WOL_LOGOUT')  # 00:0a:0b:0c:0d:0e

MAX_WORK_DONE = int(os.environ.get('MAX_WORK_DONE'))  # 2000

