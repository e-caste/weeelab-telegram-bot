from time import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import ldap
from ldap.filter import escape_filter_chars


class LdapConnection:
    def __init__(self, server: str, bind_dn: str, password: str):
        self.bind_dn = bind_dn
        self.password = password
        self.server = server

    def __enter__(self):
        print("Connecting to LDAP")
        self.conn = ldap.initialize(f"ldap://{self.server}:389")
        self.conn.protocol_version = ldap.VERSION3
        self.conn.start_tls_s()
        self.conn.simple_bind_s(self.bind_dn, self.password)
        if self.conn is None:
            raise LdapConnectionError
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("Disconnecting from LDAP")
        self.conn.unbind_s()


class LdapConnectionError(BaseException):
    pass


class DuplicateEntryError(BaseException):
    pass


class AccountLockedError(BaseException):
    pass


class AccountNotFoundError(BaseException):
    pass


class AccountNotCompletedError(BaseException):
    def __init__(self, invite_code: str, *args):
        super().__init__(*args)
        self.invite_code = invite_code


class Users:
    def __init__(self, admin_groups: List[str], tree: str, invite_tree: str):
        self.__users: Dict[int, User] = {}
        self.admin_groups = admin_groups
        self.tree = tree
        self.invite_tree = invite_tree

    def get(self, tgid, nickname: Optional[str], conn: LdapConnection):
        if not isinstance(tgid, int):
            raise IndexError(f"{tgid} is not an int")

        user = None
        # Try to get cached user
        if tgid in self.__users:
            user = self.__users[tgid]
            if not user.need_update():
                return user

        with conn as c:
            # Got it but it's stale?
            if user is not None:
                try:
                    if user.need_update():
                        user.update(c, self.admin_groups, True, nickname)
                except (AccountNotFoundError, AccountLockedError, DuplicateEntryError):
                    del self.__users[tgid]
                    user = None

            # Deleted stale user or didn't get it?
            if user is None:
                user = User.search(tgid, nickname, self.admin_groups, c, self.tree, self.invite_tree)
                self.__users[tgid] = user

        return user

    def update_invite(self, invite_code: str, tgid: int, nickname: Optional[str], conn: LdapConnection):
        invite_code_escaped = escape_filter_chars(invite_code)
        with conn as c:
            result = c.search_s(self.invite_tree, ldap.SCOPE_SUBTREE, f"(inviteCode={invite_code_escaped})", ())

            if len(result) == 0:
                raise AccountNotFoundError()
            if len(result) > 1:
                raise DuplicateEntryError(f"Invite code {invite_code} associated to {len(result)} invites")

            dn = result[0][0]
            del result

            modlist = [(ldap.MOD_REPLACE, 'telegramid', str(tgid).encode('UTF-8'))]
            if nickname is None:
                modlist.append((ldap.MOD_DELETE, 'telegramnickname', None))
            else:
                modlist.append((ldap.MOD_REPLACE, 'telegramnickname', nickname.encode('UTF-8')))
            c.modify_s(dn, modlist)

    def delete_cache(self) -> int:
        busted = len(self.__users)
        self.__users = {}
        return busted


@dataclass
class Person:
    uid: str
    cn: str
    isadmin: bool
    nickname: Optional[str]
    tgid: Optional[int]


class People:
    def __init__(self, admin_groups: List[str], tree: str):
        self.__people = {}
        self.last_update = 0
        self.tree = tree
        self.admin_groups = admin_groups

    def get(self, uid: str, conn: LdapConnection) -> Optional[Person]:
        if time() - self.last_update > 3600:
            with conn as c:
                print("Sync people from LDAP")
                self.__sync(c)
        uid = uid.lower()
        if uid in self.__people:
            return self.__people[uid]
        else:
            return None

    def delete_cache(self) -> int:
        busted = len(self.__people)
        self.__people = {}
        self.last_update = 0
        return busted

    def __sync(self, conn):
        result = conn.search_s(self.tree, ldap.SCOPE_SUBTREE, f"(objectClass=weeeOpenPerson)", (
            'uid',
            'cn',
            'memberof',
            'telegramnickname',
            'telegramid'
        ))

        for dn, attributes in result:
            person = Person(
                attributes['uid'][0].decode(),
                attributes['cn'][0].decode(),
                User.is_admin(self.admin_groups, attributes),
                attributes['telegramnickname'][0].decode() if 'telegramnickname' in attributes else None,
                int(attributes['telegramid'][0].decode()) if 'telegramid' in attributes else None,
            )
            self.__people[person.uid.lower()] = person

        self.last_update = time()

# noinspection PyAttributeOutsideInit
@dataclass
class User:
    dn: str
    tgid: int
    uid: str
    cn: str
    givenname: str
    surname: str
    isadmin: bool
    nickname: Optional[str]

    def __post_init__(self):
        self.__set_update_time()

    def __set_update_time(self):
        self.last_update = time()

    def need_update(self):
        return time() - self.last_update > 3600

    def update(self, conn, admin_groups: List[str], also_nickname: bool, nickname: Optional[str] = None):
        """
        Update user (if cached result is old)

        :param conn: LDAP Connection
        :param admin_groups: Users that belong to these groups are considered admins
        :param also_nickname: Also update the nickname, if false the nickname parameter is ignored
        :param nickname: New nickname, will be updated if needed
        :return: attributes, dn
        """
        print(f"Update {self.tgid} ({self.dn})")
        result = conn.read_s(self.dn, None, (
            'uid',
            'cn',
            'givenname',
            'sn',
            'memberof',
            'telegramnickname',
            'telegramid',
            'nsaccountlock'
        ))
        if len(result) == 0:
            raise AccountNotFoundError()
        if len(result) > 1:
            raise DuplicateEntryError(f"DN {self.dn} associated to {len(result)} entries (how!?)")

        dn, attributes = User.__extract_the_only_result(result)
        del result

        if 'nsaccountlock' in attributes:
            raise AccountLockedError()

        # self.tgid = int(attributes['tgid'][0].decode())
        self.uid = attributes['uid'][0].decode()
        self.cn = attributes['cn'][0].decode()
        self.givenname = attributes['givenname'][0].decode()
        self.surname = attributes['surname'][0].decode()
        self.isadmin = User.is_admin(admin_groups, attributes)
        if also_nickname:
            if User.__get_stored_nickname(attributes) != nickname:
                User.__update_nickname(dn, nickname, conn)
        self.__set_update_time()

    @staticmethod
    def search(tgid: int, tgnick: Optional[str], admin_groups, conn, tree: str, invite_tree: str):
        """
        Get User from Telegram ID. Or nickname as a fallback, Also update nickname and ID if needed.

        :param conn: LDAP Connection
        :param invite_tree: Invites tree DN
        :param tgid: Telegram ID
        :param tgnick: Telegram nickname
        :param admin_groups: Users that belong to these groups are considered admins
        :param tree: Users tree DN
        :return: attributes, dn
        """
        print(f"Search {tgid}")
        tgid = int(tgid)  # Safety measure
        try:
            attributes, dn = User.__search_by_tgid(conn, invite_tree, tgid, tree)
        except AccountNotFoundError as e:
            if tgnick is None:
                raise e
            else:
                attributes, dn = User.__search_by_nickname(conn, invite_tree, tgnick, tgid, tree)

        if 'nsaccountlock' in attributes:
            raise AccountLockedError()

        isadmin = User.is_admin(admin_groups, attributes)
        nickname = User.__get_stored_nickname(attributes)

        if nickname != tgnick:
            User.__update_nickname(dn, tgnick, conn)
        # self.__set_update_time() done in __post_init___
        return User(dn, tgid, attributes['uid'][0].decode(), attributes['cn'][0].decode(), attributes['givenname'][0].decode(), attributes['sn'][0].decode(), isadmin, tgnick)

    @staticmethod
    def __search_by_tgid(conn, invite_tree, tgid, tree) -> Tuple[Dict, str]:
        """
        Get attributes from a Telegram ID

        :param conn: LDAP Connection
        :param invite_tree: Invites tree DN
        :param tgid: Telegram ID
        :param tree: Users tree DN
        :return: attributes, dn
        """
        result = conn.search_s(tree, ldap.SCOPE_SUBTREE, f"(&(objectClass=weeeOpenPerson)(telegramId={tgid}))", (
            'uid',
            'cn',
            'givenname',
            'sn',
            'memberof',
            'telegramnickname',
            'telegramid',
            'nsaccountlock'
        ))
        if len(result) == 0:
            # TODO: this part can be removed, once every old user has signed up to the SSO
            invite = User.__get_invite_from_tgid(tgid, invite_tree, conn)
            if invite is None:
                raise AccountNotFoundError()
            else:
                raise AccountNotCompletedError(invite)
        if len(result) > 1:
            raise DuplicateEntryError(f"Telegram ID {tgid} associated to {len(result)} entries")
        dn, attributes = User.__extract_the_only_result(result)
        del result
        return attributes, dn

    @staticmethod
    def __search_by_nickname(conn, invite_tree, tgnick: str, tgid: int, tree) -> Tuple[Dict, str]:
        """
        Search a user by nickname IF Telegram ID is not set.
        If found, update their Telegram ID, search again by ID and return the usual attributes.

        :param conn: LDAP Connection
        :param invite_tree: Invites tree DN
        :param tgnick: Telegram nickname
        :param tgid: Telegram ID
        :param tree: Users tree DN
        :return: attributes, dn
        """
        print(f"Search {tgnick}")
        tgnick = ldap.filter.escape_filter_chars(tgnick)
        result = conn.search_s(tree, ldap.SCOPE_SUBTREE, f"(&(objectClass=weeeOpenPerson)(!(telegramId=*))(telegramNickname={tgnick}))", ())
        if len(result) == 0:
            raise AccountNotFoundError()
        if len(result) > 1:
            raise DuplicateEntryError(f"Telegram nickname {tgnick} associated to {len(result)} entries")

        dn = result[0][0]
        User.__update_id(dn, tgid, conn)

        return User.__search_by_tgid(conn, invite_tree, tgid, tree)

    @staticmethod
    def __get_invite_from_tgid(tgid: int, invite_tree: str, conn):
        result = conn.search_s(invite_tree, ldap.SCOPE_SUBTREE, f"(&(inviteCode=*)(telegramId={tgid}))", ('*',))
        if len(result) == 0:
            return None
        if len(result) > 1:
            raise DuplicateEntryError(f"Telegram ID {tgid} associated to {len(result)} invites")
        dn, attributes = User.__extract_the_only_result(result)
        del result
        return attributes['inviteCode'][0].decode()

    @staticmethod
    def __get_stored_nickname(attributes):
        if 'telegramnickname' in attributes:
            nickname = attributes['telegramnickname'][0].decode()
        else:
            nickname = None
        return nickname

    @staticmethod
    def is_admin(admin_groups, attributes):
        if 'memberof' not in attributes:
            return False
        for group in attributes['memberof']:
            if group.decode() in admin_groups:
                return True
        return False

    @staticmethod
    def __extract_the_only_result(result):
        tup = result.pop()
        dn = tup[0]
        attributes = tup[1]
        return dn, attributes

    @staticmethod
    def __update_nickname(dn: str, new_nickname: Optional[str], conn):
        if new_nickname is None:
            conn.modify_s(dn, [
                (ldap.MOD_DELETE, 'telegramNickname', None)
            ])
        else:
            conn.modify_s(dn, [
                (ldap.MOD_REPLACE, 'telegramNickname', new_nickname.encode('UTF-8'))
            ])

    @staticmethod
    def __update_id(dn: str, new_id: int, conn):
        conn.modify_s(dn, [
            (ldap.MOD_REPLACE, 'telegramId', str(new_id).encode('UTF-8'))
        ])
